"""Runtime symbol geometry and native routing regressions."""

from test_browser import browser  # noqa: F401
from test_pin_graph import graph_page  # noqa: F401


def test_geometry_detects_diagonals_obstacles_and_shared_paths(graph_page):
    page, server = graph_page
    origin = server.url.rstrip("/")
    try:
        page.goto(origin + "/layout-metrics.js")
        results = page.evaluate("""async () => {
          const {measure,mergedSegments}=await import('/layout-metrics.js');
          const nodes=[{id:'a',x:0,y:0,classes:[]},{id:'b',x:100,y:0,classes:[]},
            {id:'wall',x:50,y:0,width:20,height:20,classes:['part']}];
          const wire={id:'e',net:'N',source:'a',target:'b',points:[{x:0,y:0},{x:100,y:0}]};
          return {
            obstacle:measure({nodes,wires:[wire]}).penetrations,
            shared:measure({nodes,wires:[wire,{...wire,id:'f',net:'M'}]}).shared,
            diagonal:measure({nodes,wires:[{...wire,points:[{x:0,y:0},{x:100,y:10}]}]}).nonOrthogonal,
            deduplicated:mergedSegments([wire,{...wire,id:'f'}]).length,
            missing:measure({nodes,wires:[wire],expected:{N:['a','b','lost']}}).missingEndpoints
          };
        }""")
        assert results == {
            "obstacle": 1,
            "shared": 1,
            "diagonal": 1,
            "deduplicated": 1,
            "missing": 1,
        }
    finally:
        page.close()


def test_two_pin_rotation_preserves_polarity_and_pin_identity(graph_page):
    page, server = graph_page
    origin = server.url.rstrip("/")
    try:
        page.goto(origin + "/layout-layout.js")
        result = page.evaluate("""async () => {
          const {optimizePorts}=await import('/layout-layout.js');
          const n=(id,x,classes,data)=>({id,x,y:0,width:50,height:50,classes,data,labelBox:null});
          const scene={nodes:[
            n('part:D',0,['part'],{label:'D1'}),
            n('pin:D.K',-45,['pin'],{owner:'part:D',label:'1 K'}),
            n('pin:D.A',45,['pin'],{owner:'part:D',label:'2 A'}),
            n('g',-110,['rail'],{owner:'part:D',role:'ground',label:'GND'}),
            n('v',110,['rail'],{owner:'part:D',role:'power',label:'VDD'})],
            wires:[{source:'pin:D.K',target:'g',rail:true},{source:'pin:D.A',target:'v',rail:true}],
            pkg:{pins:{'D.K':{num:'1'},'D.A':{num:'2'}}}};
          optimizePorts(scene);
          return {rotation:scene.nodes[0].rotation,plans:Object.fromEntries(scene.nodes.filter(n=>n.classes.includes("pin")).map(n=>[n.id,{direction:n.direction,dx:n.data.dx,dy:n.data.dy}])),ids:scene.nodes.map(n=>n.id)};
        }""")
        assert result["rotation"] == 270
        assert result["plans"]["pin:D.K"]["direction"] == "S"
        assert result["plans"]["pin:D.A"]["direction"] == "N"
        assert result["ids"] == ["part:D", "pin:D.K", "pin:D.A", "g", "v"]
    finally:
        page.close()


def test_rail_connectivity_uses_net_identity_and_requires_leads(graph_page):
    page, server = graph_page
    origin = server.url.rstrip("/")
    try:
        page.goto(origin + "/layout-metrics.js")
        result = page.evaluate("""async () => {
          const {measure}=await import('/layout-metrics.js');
          const nodes=['a','b','r1','r2'].map((id,i)=>({id,x:i*30,y:0,width:1,height:1,
            classes:id.startsWith('r')?['rail']:[],data:{netKey:'N',label:'GND'}}));
          const wires=[['a','r1'],['b','r2']].map(([source,target],i)=>({id:String(i),net:'N',source,target,
            points:[nodes.find(n=>n.id===source),nodes.find(n=>n.id===target)]}));
          const scene={nodes,wires,expected:{N:['a','b','r1','r2']}};
          const valid=measure(scene);
          nodes[3].data.netKey='M';
          const wrongNet=measure(scene);
          nodes[3].data.netKey='N';
          const missingLead=measure({...scene,wires:wires.slice(0,1)});
          return [valid.disconnectedNets,wrongNet.disconnectedNets,missingLead.missingEndpoints,missingLead.disconnectedNets];
        }""")
        assert result == [0, 1, 2, 1]
    finally:
        page.close()


def test_split_junction_cannot_hide_an_elbow(graph_page):
    page, server = graph_page
    origin = server.url.rstrip("/")
    try:
        page.goto(origin + "/layout-metrics.js")
        result = page.evaluate("""async () => {
          const {measure}=await import('/layout-metrics.js');
          const nodes=[{id:'a',x:0,y:0,classes:[]},{id:'b',x:50,y:50,classes:[]},
            {id:'j',x:50,y:0,classes:['branch'],data:{netKey:'N'}}];
          const w=(id,source,target,points)=>({id,net:'N',source,target,points});
          return [measure({nodes,wires:[w('whole','a','b',[nodes[0],nodes[2],nodes[1]])]}).bends,
            measure({nodes,wires:[w('first','a','j',[nodes[0],nodes[2]]),w('second','j','b',[nodes[2],nodes[1]])]}).bends];
        }""")
        assert result == [1, 1]
    finally:
        page.close()


def test_native_path_rejects_fallback_diagonal_and_wrong_pin(graph_page):
    page, server = graph_page
    origin = server.url.rstrip("/")
    try:
        page.goto(origin + "/layout-routing.js")
        assert page.evaluate("""async()=>{
          const {nativePathValid}=await import('/layout-routing.js');
          const a={x:37,y:0},b={x:0,y:0};
          return [nativePathValid([a,b],a,b),nativePathValid([{x:51,y:0},{x:0,y:-28}],a,b),
            nativePathValid([{x:51,y:0},b],a,b),nativePathValid([],a,b)];
        }""") == [True, False, False, False]
    finally:
        page.close()


def test_compact_geometry_rotation_polarity_and_fallback(graph_page):
    page, server = graph_page
    origin = server.url.rstrip("/")
    try:
        page.goto(origin + "/layout-geometry.js")
        result = page.evaluate("""async()=>{
          const {compactPassives,passiveSpec}=await import('/layout-geometry.js');
          const ids=['C.1','C.2'],parts={C:{category:'capacitor',pins:ids,properties:{polarized:true}}};
          const pins={'C.1':{id:'C.1',num:'1',name:'+'},'C.2':{id:'C.2',num:'2',name:'-'}};
          const scene={pkg:{parts,pins},wires:[],nodes:[{id:'part:C',x:0,y:0,width:150,height:64,rotation:90,classes:['part'],data:{label:'C1\\n123456789 pF'}},
            ...ids.map(id=>({id:'pin:'+id,x:0,y:0,width:5,height:5,classes:['pin'],data:{owner:'part:C',label:id}}))]};
          compactPassives(scene);const owner=scene.nodes[0],a=scene.nodes[1],b=scene.nodes[2];
          return {positive:owner.symbol.positive,distance:Math.hypot(a.x-b.x,a.y-b.y),sides:[a.direction,b.direction],
            extent:[owner.width,owner.height],labels:owner.labelBox.w>50,
            unknown:passiveSpec({category:'generic',pins:ids},Object.values(pins)),
            array:passiveSpec({category:'resistor',pins:[...ids,'C.3']},Object.values(pins)),
            unmarked:passiveSpec(parts.C,[{name:'1'},{name:'2'}])};
        }""")
        assert result == dict(
            positive="C.1",
            distance=72,
            sides=["N", "S"],
            extent=[24, 36],
            labels=True,
            unknown=None,
            array=None,
            unmarked=None,
        )
    finally:
        page.close()


def test_dense_terminal_rows_route_to_real_pins(graph_page):
    page, server = graph_page
    origin = server.url.rstrip("/")
    try:
        page.goto(origin + "/layout-routing.js")
        result = page.evaluate("""async()=>{
          const {AvoidLib}=await import('/vendor/libavoid.js');await AvoidLib.load('/vendor/libavoid.wasm');
          const {SceneRouter}=await import('/layout-routing.js');const {measure}=await import('/layout-metrics.js');
          const nodes=[{id:'ic',x:120,y:24,width:70,height:100,classes:['part'],data:{}}],wires=[];
          for(let i=0;i<2;i++){
            nodes.push({id:'p'+i,x:65,y:i*48,width:5,height:5,direction:'W',classes:['pin'],data:{owner:'ic'}});
            nodes.push({id:'n'+i,x:0,y:i*48,width:2,height:2,classes:['net'],data:{owner:'ic',netKey:'N'+i},labelBox:{x1:-17,x2:17,y1:i*48+4,y2:i*48+18,w:34,h:14}});
            wires.push({id:'w'+i,net:'N'+i,source:'p'+i,target:'n'+i});
          }
          const r=new SceneRouter(AvoidLib.getInstance(),{nodes,wires});
          try{const s=r.compute(),m=measure(s);return {failed:m.failedRoutes,diagonal:m.nonOrthogonal,penetrations:m.penetrations,starts:s.wires.map(w=>w.points[0].x)};}finally{r.dispose();}
        }""")
        assert result == dict(failed=0, diagonal=0, penetrations=0, starts=[65, 65])
    finally:
        page.close()


def test_cross_module_trees_keep_unique_ids_and_pin_inventory(graph_page):
    page, _ = graph_page
    result = page.evaluate("""async()=>{
      const {topology}=await import('/layout-search.js');
      const scenes=['left','right'].map(group=>{
        const nodes=[0,1,2].map(i=>({id:'pin:'+group+i,x:i*100,y:0,width:5,height:5,
          classes:['pin'],data:{pins:[group+i]},direction:'E'}));
        return {group,nodes,expected:{BUS:nodes.map(n=>n.id)},
          wires:[1,2].map(i=>({id:group+i,net:'BUS',source:nodes[0].id,target:nodes[i].id,points:[]}))};
      });
      return ['mst','horizontal'].map(mode=>{
        const graphs=scenes.map(s=>topology(s,mode));
        const ids=graphs.flatMap(s=>[...s.nodes.map(n=>n.id),...s.wires.map(w=>w.id)]);
        return {unique:new Set(ids).size===ids.length,pins:graphs.flatMap(s=>s.wires.flatMap(w=>w.pins)).sort()};
      });
    }""")
    assert (
        result
        == [
            {
                "unique": True,
                "pins": ["left0", "left1", "left2", "right0", "right1", "right2"],
            }
        ]
        * 2
    )
