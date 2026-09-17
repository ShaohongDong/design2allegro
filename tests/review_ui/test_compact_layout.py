"""Measured geometry and routing quality, independent of layout implementation."""

import pytest
from playwright.sync_api import expect
from test_browser import browser  # noqa: F401
from test_pin_graph import graph_page  # noqa: F401


def test_rendered_text_and_symbols_do_not_overlap(graph_page):
    page, _ = graph_page
    assert page.locator("#layout-warning").inner_text() == ""
    assert page.evaluate('cy.nodes(".pin").length') > 0
    page.evaluate("()=>{cy.zoom(1);updateDetailLevel()}")
    errors = page.evaluate("""()=>{
      const boxes=[],labels=[];
      for(const n of cy.nodes().not('.junction')){
        if(n.data('label')){
          const b=n.boundingBox({includeNodes:false,includeLabels:true,includeOverlays:false});
          labels.push({...b,id:n.id()});
        }
        if(!n.data('image'))continue;
        const svg=new DOMParser().parseFromString(decodeURIComponent(n.data('image').split(',')[1]),'image/svg+xml').documentElement;
        document.body.appendChild(svg);
        const b=svg.getBBox(),p=n.position();
        boxes.push({id:n.id(),x1:p.x-n.width()/2+b.x,y1:p.y-n.height()/2+b.y,x2:p.x-n.width()/2+b.x+b.width,y2:p.y-n.height()/2+b.y+b.height});
        svg.remove();
      }
      const overlap=(a,b)=>a.x1<b.x2-.5&&a.x2>b.x1+.5&&a.y1<b.y2-.5&&a.y2>b.y1+.5;
      const errors=[];
      for(let i=0;i<labels.length;i++){
        for(let j=i+1;j<labels.length;j++)if(overlap(labels[i],labels[j]))errors.push(['text',labels[i].id,labels[j].id]);
        for(const b of boxes)if(overlap(labels[i],b))errors.push(['symbol',labels[i].id,b.id]);
      }
      for(const e of cy.edges('.wire')){
        const points=e.data('routePoints');
        for(let i=1;i<points.length;i++){
          const a=points[i-1],b=points[i];
          for(const r of labels){
            if(a.x===b.x ? a.x>r.x1&&a.x<r.x2&&Math.max(a.y,b.y)>r.y1&&Math.min(a.y,b.y)<r.y2
              : a.y>r.y1&&a.y<r.y2&&Math.max(a.x,b.x)>r.x1&&Math.min(a.x,b.x)<r.x2)errors.push(['wire',e.id(),r.id]);
          }
        }
      }
      return errors;
    }""")
    assert errors == []
    assert page.evaluate("graphMetrics.foreignOverlap") == 0


def test_sparse_router_avoids_obstacles_and_foreign_overlap(graph_page):
    page, _ = graph_page
    page.add_script_tag(url="/graph-routing.js")
    result = page.evaluate("""()=>{
      const boxes=[{id:'obstacle',x1:40,y1:-20,x2:60,y2:20}];
      const edges=[{id:'A',source:'s',target:'t',net:'A',points:[{x:-10,y:0},{x:0,y:0},{x:100,y:0},{x:110,y:0}]},
        {id:'B',source:'s2',target:'t2',net:'B',points:[{x:-10,y:30},{x:0,y:30},{x:0,y:0},{x:100,y:0},{x:100,y:30},{x:110,y:30}]}];
      const routed=ReviewRouting.route(edges,boxes).edges;
      return {routes:routed,metrics:ReviewRouting.metrics(routed,boxes,[])};
    }""")
    assert result["metrics"]["foreignOverlap"] == 0
    for edge in result["routes"]:
        for a, b in zip(edge["points"], edge["points"][1:]):
            assert a["x"] == b["x"] or a["y"] == b["y"]
            if a["x"] == b["x"]:
                assert not (
                    40 < a["x"] < 60
                    and max(a["y"], b["y"]) > -20
                    and min(a["y"], b["y"]) < 20
                )
            else:
                assert not (
                    -20 < a["y"] < 20
                    and max(a["x"], b["x"]) > 40
                    and min(a["x"], b["x"]) < 60
                )


def test_drag_validates_drop_and_rolls_back_overlap(graph_page):
    page, _ = graph_page
    assert page.locator("#layout-warning").inner_text() == ""
    before = page.evaluate("""()=>{
      const n=cy.nodes('.pin.nc').first();window.dragTestId=n.id();
      const before={...n.position()},box=cy.elements().boundingBox();
      n.emit('grab');n.position({x:box.x2+200,y:before.y});n.emit('free');
      return before;
    }""")
    expect(page.locator("#layout-warning")).to_have_text("", timeout=10000)
    accepted = page.evaluate("({...cy.getElementById(dragTestId).position()})")
    assert accepted["x"] > before["x"]
    page.evaluate("""()=>{
      const n=cy.getElementById(dragTestId),other=cy.nodes('.pin.nc').filter(x=>x.id()!==n.id()).first();
      n.emit('grab');n.position({...other.position()});n.emit('free');
    }""")
    expect(page.locator("#layout-warning")).to_contain_text("移动已撤回", timeout=10000)
    assert page.evaluate("({...cy.getElementById(dragTestId).position()})") == accepted


def test_vertical_ports_keep_identity_and_move_together(graph_page):
    page, server = graph_page
    # Evaluate the alternative geometry explicitly; candidate choice may vary by fixture.
    assert page.evaluate("""()=>{
      const m=ReviewGeometry.prepare(ReviewGraphModel.topology(pkg),measureGraphText);
      const byId=new Map(m.nodes.map(n=>[n.data.id,n]));
      const body=byId.get('body:part:resistor');
      ReviewGeometry.applyVariant(body,body.data.variants[1],byId);
      return body.data.pins.every((id,i)=>{
        const p=byId.get('pin:'+id).data;
        return p.pinId===id&&p.offsetX===0&&p.offsetY===(i?62:-62)&&p.side===(i?'S':'N')&&p.netKey==='net:'+pkg.pins[id].net;
      });
    }""")
    assert sorted(page.evaluate('cy.nodes(".pin").map(n=>n.data("pinId"))')) == sorted(
        server.package["pins"]
    )


def test_long_labels_preserved_and_resize_does_not_relayout(graph_page):
    page, _ = graph_page
    before = page.evaluate(
        "cy.nodes().map(n=>({id:n.id(),position:{...n.position()}}))"
    )
    page.set_viewport_size({"width": 1920, "height": 1080})
    assert (
        page.evaluate("cy.nodes().map(n=>({id:n.id(),position:{...n.position()}}))")
        == before
    )
    assert page.evaluate("""()=>{
      const m=ReviewGraphModel.topology(pkg),n=m.nodes.find(n=>n.data.pinId);
      const text='long_module_name/'.repeat(12)+'实际完整逻辑引脚';n.data.label=text;
      ReviewGeometry.prepare(m,measureGraphText);
      return n.data.sourceLabel===text && n.data.label.replaceAll('\\n','')===text && n.data.text.width<=240 && n.data.text.height>40;
    }""")


def test_empty_filtered_graph_has_finite_metrics(graph_page):
    page, _ = graph_page
    page.evaluate(
        "()=>runGraphCalculation(ReviewGraphModel.topology(pkg,{visible:new Set()}))"
    )
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.locator("#layout-warning").inner_text() == ""
    assert page.evaluate('cy.nodes(".pin").length') == 0
    assert page.evaluate(
        "[graphMetrics.area,graphMetrics.occupancy,graphMetrics.wireLength].every(x=>x===0)"
    )
    page.evaluate("buildGraph()")
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate('cy.nodes(".pin").length') > 0


def test_four_rotations_preserve_pin_identity_and_svg_endpoints(graph_page):
    page, _ = graph_page
    assert page.evaluate("""()=>{
      const m=ReviewGeometry.prepare(ReviewGraphModel.topology(pkg),measureGraphText);
      const byId=new Map(m.nodes.map(n=>[n.data.id,n]));
      for(const body of m.nodes.filter(n=>n.data.variants)){
        const identity=body.data.pins.map(id=>({...byId.get('pin:'+id).data}));
        if(body.data.variants.length!==4)return false;
        for(const v of body.data.variants){
          ReviewGeometry.applyVariant(body,v,byId);
          const uri=ReviewSymbols.image({...body.data,category:body.data.symbolCategory,body:true});
          const svg=new DOMParser().parseFromString(decodeURIComponent(uri.split(',')[1]),'image/svg+xml').documentElement;
          const transform=svg.querySelector('[data-role="component"]').transform.baseVal.consolidate().matrix;
          for(let i=0;i<2;i++){
            const p=byId.get('pin:'+body.data.pins[i]).data, old=identity[i];
            const radians=v.angle*Math.PI/180, x=(i?1:-1)*body.data.halfSpan;
            const rendered=new DOMPoint(body.data.width/2+x,body.data.height/2).matrixTransform(transform);
            if(Math.abs(rendered.x-body.data.width/2-p.offsetX)>.001||Math.abs(rendered.y-body.data.height/2-p.offsetY)>.001)return false;
            if(p.pinId!==old.pinId||p.netKey!==old.netKey||p.nc!==old.nc||
               Math.abs(p.offsetX-x*Math.cos(radians))>.001||Math.abs(p.offsetY-x*Math.sin(radians))>.001)return false;
            if(p.groundOffsetX && (p.side!=='N'||p.width/2<Math.abs(p.groundOffsetX)+12))return false;
          }
        }
      }
      return true;
    }""")


@pytest.mark.parametrize("target", [{"x": 500, "y": 0}, {"x": 0, "y": 400}])
def test_local_rotation_shortens_shunt_branch_and_respects_area(graph_page, target):
    page, _ = graph_page
    # Exercise the real worker optimizer with controlled initial geometry, rather
    # than relying on ELK to reproduce a particular bad starting layout.
    from pathlib import Path

    worker = (
        Path(__file__).resolve().parents[2]
        / "src/design2allegro/review_static/graph-worker.js"
    ).read_text()
    worker = worker.split("self.onmessage = async")[0] + """
self.onmessage=({data})=>{
  try {
    const routed=R.route(data.edges,data.boxes);
    const scene={...data,edges:routed.edges,labels:[],metrics:R.metrics(routed.edges,data.boxes,[])};
    scene.bounds=G.union(data.boxes);
    const result=optimizeLocal(scene,{remaining:256});
    self.postMessage({...result,audit:R.audit(result.edges,result.boxes,result.labels)});
  }catch(e){self.postMessage({error:e.message})}
};
"""
    page.route(
        "**/graph-worker.js",
        lambda route: route.fulfill(body=worker, content_type="application/javascript"),
    )
    result = page.evaluate(
        """async target=>{
      const m=ReviewGeometry.prepare(ReviewGraphModel.topology(pkg),measureGraphText);
      const map=new Map(m.nodes.map(n=>[n.data.id,n]));
      const body=map.get('body:part:capacitor');
      ReviewGeometry.applyVariant(body,body.data.variants[0],map);
      const terminals=body.data.pins.map(id=>map.get('pin:'+id));
      const nodes=[{id:body.data.id,data:body.data,position:{x:0,y:0}},
        ...terminals.map(n=>({id:n.data.id,data:n.data,position:{x:n.data.offsetX,y:n.data.offsetY}})),
        {id:'sink',data:{id:'sink',box:ReviewGeometry.rect(0,0,20,20)},position:target}];
      const b=body.data.box;
      const boxes=[{id:body.data.id,x1:b.x1-8,y1:b.y1-8,x2:b.x2+8,y2:b.y2+8},
        {id:'sink',...ReviewGeometry.move(ReviewGeometry.rect(0,0,36,36),target)}];
      const a=nodes[1].position,s={x:b.x1-8,y:0},t=target.x?{x:target.x-18,y:target.y}:{x:target.x,y:target.y-18};
      const edges=[{id:'branch',source:body.data.id,target:'sink',sourcePin:nodes[1].id,targetPin:'sink',net:'signal',label:'',
        points:target.x?[a,s,{x:s.x,y:-180},{x:t.x,y:-180},t,target]:[a,s,{x:s.x,y:t.y},t,target]}];
      return await new Promise(resolve=>{const w=new Worker('/graph-worker.js');w.onmessage=e=>{w.terminate();resolve(e.data)};w.postMessage({nodes,boxes,edges});});
    }""",
        target,
    )
    assert "error" not in result
    stats = result["localOptimization"]
    assert stats["afterWireLength"] < stats["beforeWireLength"]
    assert stats["afterBends"] <= stats["beforeBends"]
    assert stats["afterArea"] <= stats["beforeArea"] * 1.1
    assert stats["candidates"] <= 6
    body = next(n for n in result["nodes"] if n["data"].get("variants"))
    assert body["data"]["angle"] in (90, 180, 270)
    assert result["audit"] == {"boxOverlaps": 0, "obstacleViolations": 0}
