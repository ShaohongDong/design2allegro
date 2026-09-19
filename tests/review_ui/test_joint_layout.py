"""Joint alignment uses actual routing and immutable electrical endpoint identities."""

import json
from pathlib import Path

import pytest
from test_browser import browser  # noqa: F401
from test_pin_graph import graph_page  # noqa: F401


@pytest.fixture
def joint_worker(graph_page):
    page, _ = graph_page
    worker = (
        (
            Path(__file__).resolve().parents[2]
            / "src/design2allegro/review_static/graph-worker.js"
        )
        .read_text()
        .split("self.onmessage = async")[0]
        + """
self.onmessage=({data})=>{
  try {
    const routed=R.route(data.scene.edges.map(e=>({...e,points:e.validationPoints||e.points})),data.scene.boxes);
    const scene={...data.scene,edges:routed.edges,labels:[],bounds:G.union(data.scene.boxes),
      metrics:R.metrics(routed.edges,data.scene.boxes,[])};
    const before=structuredClone(scene),scenes=[scene],budget={remaining:data.budget};
    const exits=scene.nodes.filter(n=>n.data.layoutKind==='pin'&&!n.data.bodyId).map(n=>({
      id:n.id,sides:escapeChoices(n,scene.boxes.find(b=>b.id===n.id)).map(c=>c.side)}));
    if(data.fail)R.route=()=>{throw new Error('Injected routing failure')};
    optimizeJoint(scenes,budget);
    const after=scenes[0];
    self.postMessage({before,after,budget,exits,audit:R.audit(after.edges,after.boxes,after.labels)});
  }catch(e){self.postMessage({error:e.message,stack:e.stack})}
};
"""
    )
    page.route(
        "**/graph-worker.js",
        lambda route: route.fulfill(body=worker, content_type="application/javascript"),
    )
    return page


SCENE = """async ({mirror=1,vertical=false,longLabels=false,budget=256,fail=false})=>{
  const pin=(id,label,extra={})=>({data:{id,pinId:id,label,role:'signal',category:'ic',...extra},classes:'pin signal'});
  const model={nodes:[
    {data:{id:'r',label:'R15 resistor\\n1500 ohm',pins:['r1','r2'],symbolCategory:'resistor'},classes:'component'},
    pin('pin:r1','R15.1',{bodyId:'r'}),pin('pin:r2','R15.2',{bodyId:'r'}),
    pin('j','J3 DP'),pin('u','U5 PA12'),pin('q','Q1 E'),
    {data:{id:'net',netKey:'USB_DP',label:'USB_DP'},classes:'net'}],edges:[]};
  if(longLabels)for(const n of model.nodes.filter(n=>['j','net'].includes(n.data.id)))n.data.label+=' long_module_name'.repeat(12);
  ReviewGeometry.prepare(model,measureGraphText);
  const map=new Map(model.nodes.map(n=>[n.data.id,n])),body=map.get('r');
  ReviewGeometry.applyVariant(body,body.data.variants.find(v=>v.angle===((mirror<0?180:0)+(vertical?90:0))),map);
  const positions={r:{x:260*mirror,y:0},j:{x:-180*mirror,y:560},u:{x:200*mirror,y:560},
    q:{x:700*mirror,y:560},net:{x:80*mirror,y:300}};
  if(vertical)for(const [id,p] of Object.entries(positions))positions[id]={x:p.y,y:p.x};
  const nodes=model.nodes.map(n=>({id:n.data.id,data:n.data,position:n.data.bodyId?
    {x:positions.r.x+n.data.offsetX,y:positions.r.y+n.data.offsetY}:positions[n.data.id]}));
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const boxes=nodes.filter(n=>!n.data.bodyId).map(n=>({id:n.id,
    x1:n.position.x+n.data.box.x1-8,y1:n.position.y+n.data.box.y1-8,
    x2:n.position.x+n.data.box.x2+8,y2:n.position.y+n.data.box.y2+8}));
  const edge=(id,sourcePin,targetPin,net)=>{
    const a=byId.get(sourcePin),b=byId.get(targetPin),source=a.data.bodyId||a.id,target=b.data.bodyId||b.id;
    const ba=boxes.find(b=>b.id===source),bb=boxes.find(b=>b.id===target);
    const side=a.data.side||'E';
    const s={x:side==='W'?ba.x1:side==='E'?ba.x2:a.position.x,
      y:side==='N'?ba.y1:side==='S'?ba.y2:a.position.y};
    const t={x:bb.x1,y:b.position.y};
    return {id,source,target,sourcePin,targetPin,net,label:'',
      points:[a.position,s,{x:s.x,y:700},{x:t.x,y:700},t,b.position]};
  };
  const scene={nodes,boxes,edges:[edge('r-net','pin:r1','net','USB_DP'),
    edge('j-net','j','net','USB_DP'),edge('u-net','u','net','USB_DP'),edge('r-q','pin:r2','q','N2')]};
  return await new Promise(resolve=>{const w=new Worker('/graph-worker.js');
    w.onmessage=e=>{w.terminate();resolve(e.data)};w.postMessage({scene,budget,fail});});
}"""


@pytest.mark.parametrize("mirror", [1, -1])
@pytest.mark.parametrize("vertical", [False, True])
def test_joint_alignment_reduces_branch_bends_and_preserves_identity(
    joint_worker, mirror, vertical
):
    result = joint_worker.evaluate(SCENE, {"mirror": mirror, "vertical": vertical})
    assert "error" not in result, result
    before, after = result["before"], result["after"]
    assert after["metrics"]["bends"] < before["metrics"]["bends"]
    assert (
        after["metrics"]["alignmentDeviation"] < before["metrics"]["alignmentDeviation"]
    )
    assert after["metrics"]["wireLength"] <= before["metrics"]["wireLength"] * 1.1
    assert after["metrics"]["area"] <= before["metrics"]["area"] * 1.1
    assert after["metrics"]["crossings"] <= before["metrics"]["crossings"]
    assert result["audit"] == {"boxOverlaps": 0, "obstacleViolations": 0}
    assert after["metrics"]["foreignOverlap"] == 0
    assert after["jointOptimization"]["movedNodes"] >= 2
    assert 1 <= after["jointOptimization"]["maxMovedTogether"] <= 6
    if mirror == -1 and not vertical:
        assert after["jointOptimization"]["maxMovedTogether"] >= 2
    for old, new in zip(before["edges"], after["edges"], strict=True):
        for key in ("id", "source", "target", "sourcePin", "targetPin", "net"):
            assert old[key] == new[key]
        positions = {n["id"]: n["position"] for n in after["nodes"]}
        assert new["points"][0] == positions[new["sourcePin"]]
        assert new["points"][-1] == positions[new["targetPin"]]
    assert all("N" not in e["sides"] and "S" in e["sides"] for e in result["exits"])
    again = joint_worker.evaluate(SCENE, {"mirror": mirror, "vertical": vertical})
    assert again["after"] == after
    artifacts = Path(__file__).resolve().parents[2] / "build/parser/review-ui"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / f"joint-alignment-{mirror}-{vertical}.json").write_text(
        json.dumps(result, indent=2)
    )
    repeated = joint_worker.evaluate(
        """async scene=>await new Promise(resolve=>{
      const w=new Worker('/graph-worker.js');w.onmessage=e=>{w.terminate();resolve(e.data)};
      w.postMessage({scene,budget:256});})""",
        after,
    )
    assert "error" not in repeated, repeated
    assert repeated["after"]["optimizationLimits"] == after["optimizationLimits"]
    assert (
        repeated["after"]["metrics"]["wireLength"]
        <= before["metrics"]["wireLength"] * 1.1
    )
    assert repeated["after"]["metrics"]["area"] <= before["metrics"]["area"] * 1.1


@pytest.mark.parametrize("settings", [{"budget": 0}, {"budget": 3, "fail": True}])
def test_joint_budget_and_routing_failure_preserve_scene(joint_worker, settings):
    result = joint_worker.evaluate(SCENE, settings)
    assert "error" not in result, result
    for key in ("nodes", "edges", "boxes", "metrics"):
        assert result["after"][key] == result["before"][key]
    assert result["budget"]["remaining"] == 0
    assert result["after"]["jointOptimization"]["candidates"] == settings["budget"]


def test_bend_preference_allows_bounded_extra_length(graph_page):
    page, _ = graph_page
    page.add_script_tag(url="/graph-routing.js")
    result = page.evaluate("""()=>{
      const boxes=Array.from({length:4},(_,i)=>({id:'b'+i,x1:100+i*200,x2:120+i*200,
        y1:i%2?-100:-10,y2:i%2?10:100}));
      const edge={id:'wire',source:'s',target:'t',net:'signal',points:[
        {x:-10,y:0},{x:0,y:0},{x:1500,y:0},{x:1510,y:0}]};
      const first=ReviewRouting.route([edge],boxes);
      const after=ReviewRouting.route(first.edges.map(e=>({...e,points:e.validationPoints})),boxes,{preferBends:true});
      const strict=ReviewRouting.route(first.edges.map(e=>({...e,points:e.validationPoints})),boxes);
      return {before:ReviewRouting.metrics(first.edges,boxes,[]),
        after:ReviewRouting.metrics(after.edges,boxes,[]),strict:ReviewRouting.metrics(strict.edges,boxes,[]),
        audit:ReviewRouting.audit(after.edges,boxes,[])};
    }""")
    assert result["before"]["wireLength"] == 1600
    assert result["after"]["wireLength"] == 1720
    assert result["after"]["wireLength"] <= result["before"]["wireLength"] * 1.1
    assert result["before"]["bends"] == 10
    assert result["after"]["bends"] == 4
    assert result["strict"]["wireLength"] <= result["before"]["wireLength"]
    assert result["audit"] == {"boxOverlaps": 0, "obstacleViolations": 0}


def test_long_labels_leave_legal_escape_and_alignment_space(joint_worker):
    result = joint_worker.evaluate(SCENE, {"longLabels": True})
    assert "error" not in result, result
    assert result["audit"] == {"boxOverlaps": 0, "obstacleViolations": 0}
    assert result["after"]["metrics"]["bends"] < result["before"]["metrics"]["bends"]
    assert all("N" not in e["sides"] and "S" in e["sides"] for e in result["exits"])
