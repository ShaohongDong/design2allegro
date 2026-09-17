"use strict";
let railOverrides = Object.create(null),
  railStorageKey;
let graphPositioning = false;
let dragSnapshot = null,
  dragWorker = null,
  dragTimer = null;
let junctionFrame = null;
const dirtyJunctionNets = new Set();
let graphWorker = null,
  graphWorkerTimer = null,
  layoutGeneration = 0;
let graphFocusAfterLayout = null,
  selectionFrame = null;
let traceRoot = null,
  traceChoices = Object.create(null),
  traceOnly = false;
let currentChain = { pins: new Set(), nets: new Set(), transitions: new Map() };
const graphMetrics = {};
function loadRailSettings() {
  railStorageKey =
    "design2allegro.display:" + JSON.stringify([pkg.board_id, pkg.fingerprint]);
  try {
    const value = JSON.parse(localStorage.getItem(railStorageKey) || "{}");
    if (value && typeof value === "object" && !Array.isArray(value))
      for (const [key, role] of Object.entries(value))
        if (
          ["signal", "power", "ground"].includes(role) &&
          Object.hasOwn(pkg.nets, key)
        )
          railOverrides[key] = role;
  } catch {
    $("display-warning").textContent = "无法读取显示设置；本次会话仍可调整。";
  }
}
function railControl(net) {
  const wrap = node("div", undefined, "rail-control");
  const label = node("label", "网络显示方式");
  label.htmlFor = "net-display-role";
  const select = node("select");
  select.id = "net-display-role";
  for (const [value, text] of [
    ["auto", "自动识别"],
    ["signal", "普通信号"],
    ["power", "电源符号"],
    ["ground", "地符号"],
  ]) {
    const option = node("option", text);
    option.value = value;
    select.append(option);
  }
  select.value = railOverrides[net.name] || "auto";
  select.onchange = () => {
    if (select.value === "auto") delete railOverrides[net.name];
    else railOverrides[net.name] = select.value;
    try {
      localStorage.setItem(railStorageKey, JSON.stringify(railOverrides));
      $("display-warning").textContent = "";
    } catch {
      $("display-warning").textContent = "显示设置未持久化；仅本次会话生效。";
    }
    buildGraph(false);
    renderDetail();
    highlightObject(net.key);
  };
  wrap.append(
    label,
    select,
    node("small", ReviewGraphModel.classify(net, railOverrides).reason),
  );
  return wrap;
}
function moduleOf(part) {
  return part.hierarchy.length > 1 ? part.hierarchy[0] : null;
}
function graphIdFor(key) {
  return key;
}
function ownerKey(key) {
  return key;
}
function graphElementsFor(key) {
  return cy
    .elements()
    .filter(
      (e) =>
        e.id() === key ||
        e.data("key") === key ||
        e.data("objectKey") === key ||
        e.data("partKey") === key ||
        e.data("netKey") === key,
    );
}
function paintChain() {
  cy.elements().removeClass("chain faded highlight");
  if (!traceRoot) {
    updateDetailLevel();
    return;
  }
  cy.elements().addClass("faded");
  cy.elements()
    .filter((e) =>
      e.hasClass("component")
        ? e.data("pins").some((id) => currentChain.pins.has(id))
        : e.hasClass("module")
          ? e.data("pins").some((id) => currentChain.pins.has(id))
          : e.hasClass("pin")
            ? currentChain.pins.has(e.data("pinId"))
            : currentChain.nets.has((e.data("netKey") || "").slice(4)),
    )
    .removeClass("faded")
    .addClass("chain");
  updateDetailLevel();
}
function highlightObject(key) {
  paintChain();
  const area = graphElementsFor(key);
  area.removeClass("faded").addClass("highlight");
  if (area.length) {
    const bounds = area.add(area.edges().connectedNodes());
    cy.fit(bounds, 65);
    if (cy.zoom() > 1.25) {
      cy.zoom(1.25);
      cy.center(bounds);
    }
  }
  updateDetailLevel();
}
function selectObject(key) {
  if (!object(key)) return;
  currentKey = key;
  const pins = key.startsWith("pin:") ? [object(key).id] : object(key).pins;
  let changed =
    focusKeys !== null ||
    !!$("search").value ||
    $("status-filter").value !== "all" ||
    $("assembly-filter").value !== "all";
  if (traceOnly && pins.some((id) => !currentChain.pins.has(id))) {
    traceOnly = false;
    changed = true;
  }
  for (const id of pins) {
    const p = pkg.pins[id],
      group = moduleOf(pkg.parts[p.ref]);
    for (const k of [p.key, "part:" + p.ref, "net:" + p.net, "module:" + group])
      if (manuallyHidden.delete(k)) changed = true;
    if (collapsed.delete(group)) changed = true;
  }
  focusKeys = null;
  $("search").value = "";
  $("status-filter").value = "all";
  $("assembly-filter").value = "all";
  if (changed || !graphElementsFor(key).length) {
    graphFocusAfterLayout = key;
    buildGraph();
  } else highlightObject(key);
  renderList();
  renderDetail();
}
function traceControls(pin) {
  const wrap = node("div", undefined, "trace-controls");
  wrap.append(
    section("连接链追踪"),
    button("从此追踪", () => {
      traceRoot = pin.id;
      traceChoices = Object.create(null);
      traceOnly = false;
      graphFocusAfterLayout = pin.key;
      buildGraph();
      renderDetail();
    }),
  );
  const part = pkg.parts[pin.ref];
  if (!traceRoot || !currentChain.pins.has(pin.id)) return wrap;
  if (
    pin.nc ||
    ReviewGraphModel.classify(pkg.nets[pin.net], railOverrides).role !==
      "signal"
  ) {
    wrap.append(
      node(
        "p",
        pin.nc
          ? "NC：追踪在此停止。"
          : "电源／地：追踪在此停止，可在网络详情调整显示方式。",
      ),
    );
    return wrap;
  }
  if (part.pins.length === 2 && part.assembly === "fitted") {
    wrap.append(
      node("p", "已装配两脚器件自动跨越；仅表示拓扑追踪，不表示导通。"),
    );
    return wrap;
  }
  wrap.append(
    node("p", "选择此到达引脚的传播出口；高亮表示追踪范围，不表示导通。"),
  );
  const search = node("input");
  search.type = "search";
  search.placeholder = "查找出口引脚或网络";
  search.setAttribute("aria-label", "查找传播引脚");
  const list = node("div", undefined, "trace-exits");
  const draft = new Set(traceChoices[pin.id] || []);
  for (const id of [...part.pins].sort((a, b) =>
    pkg.pins[a].num.localeCompare(pkg.pins[b].num, "en", { numeric: true }),
  )) {
    if (id === pin.id) continue;
    const other = pkg.pins[id],
      label = node("label");
    const cb = node("input");
    cb.type = "checkbox";
    cb.value = id;
    cb.disabled = other.nc;
    cb.checked = draft.has(id);
    cb.onchange = () => (cb.checked ? draft.add(id) : draft.delete(id));
    label.append(
      cb,
      node(
        "span",
        `${other.num} · ${other.name} · ${other.nc ? "NC" : other.net}`,
      ),
    );
    list.append(label);
  }
  search.oninput = () => {
    for (const label of list.children)
      label.hidden = !label.textContent
        .toLowerCase()
        .includes(search.value.trim().toLowerCase());
  };
  const apply = button("应用传播引脚", () => {
    traceChoices[pin.id] = [...draft];
    buildGraph();
    renderDetail();
  });
  apply.id = "apply-trace-exits";
  wrap.append(search, list, apply);
  return wrap;
}
const graphStyles = [
  {
    selector: "node",
    style: {
      shape: "round-rectangle",
      width: "data(width)",
      height: "data(height)",
      label: "data(label)",
      "text-wrap": "wrap",
      "text-valign": "center",
      "font-family": "system-ui",
      "font-size": 12,
      color: "#253e64",
      "background-color": "#fff",
      "border-color": "#809bb7",
      "border-width": 1.5,
    },
  },
  {
    selector: ".net",
    style: {
      shape: "round-rectangle",
      "background-color": "#e0edf7",
      "font-size": 11,
    },
  },
  {
    selector: ".module",
    style: { "background-color": "#e5edfa", "border-style": "dashed" },
  },
  { selector: ".dnp", style: { "border-style": "dashed" } },
  { selector: ".ground, .power", style: { "background-color": "#eef5ed" } },
  {
    selector: ".nc",
    style: { "background-color": "#f1f2f5", "border-color": "#a4acb8" },
  },
  {
    selector: "edge",
    style: {
      width: 1.5,
      "line-color": "#819ab5",
      "curve-style": "taxi",
      "taxi-direction": "horizontal",
      "source-endpoint": "outside-to-node",
      "target-endpoint": "outside-to-node",
      "font-size": 11,
      "text-background-color": "#fff",
      "text-background-opacity": 0.95,
      "text-background-padding": 3,
    },
  },
  { selector: ".approved", style: { "border-color": "#258363" } },
  {
    selector: ".issue",
    style: { "border-color": "#bf4848", "border-width": 3 },
  },
  { selector: ".faded", style: { opacity: 0.17 } },
  {
    selector: ".chain",
    style: { "border-color": "#296fc1", "line-color": "#296fc1", width: 2 },
  },
  {
    selector: "node.chain",
    style: { width: "data(width)", "border-width": 2.5 },
  },
  {
    selector: ".highlight",
    style: {
      "border-color": "#dc8c22",
      "line-color": "#dc8c22",
      "border-width": 3,
    },
  },
  {
    selector: "node:selected",
    style: { "background-color": "#d9e8ff", "border-width": 3 },
  },
  {
    selector: ".pin, .net, .component",
    style: {
      "background-opacity": 0,
      "border-width": 0,
      "background-image": "data(image)",
      "background-width": "100%",
      "background-height": "100%",
      "background-fit": "contain",
      "text-margin-y": "data(labelY)",
      "text-margin-x": "data(labelX)",
      "font-size": 12,
      "text-background-opacity": 0,
    },
  },
  {
    selector: ".net",
    style: { "font-size": 11 },
  },
  {
    selector: ".component",
    style: { "z-index": 0 },
  },
  { selector: ".terminal", style: { "z-index": 2 } },
  { selector: ".pin.dnp", style: { color: "#778493" } },
  {
    selector: ".wire-label",
    style: {
      "background-opacity": 0,
      "border-width": 0,
      "font-size": 11,
      "text-margin-x": 0,
      "text-margin-y": 0,
    },
  },
  { selector: ".wire-label.hidden-label", style: { label: "" } },
  { selector: ".compact", style: { label: "" } },
  {
    selector: ".junction",
    style: {
      shape: "ellipse",
      width: 7,
      height: 7,
      label: "",
      "border-width": 0,
      "background-color": "#819ab5",
      "z-index": 5,
    },
  },
  { selector: ".junction.chain", style: { "background-color": "#296fc1" } },
  { selector: ".junction.highlight", style: { "background-color": "#dc8c22" } },
];
function visiblePins() {
  const filtered =
    $("search").value.trim() ||
    $("status-filter").value !== "all" ||
    $("assembly-filter").value !== "all";
  const allowed = new Set();
  if (filtered)
    for (const row of filteredRows()) {
      for (const key of row.key ? [row.key] : row.targets) {
        const x = object(key);
        for (const id of key.startsWith("pin:") ? [x.id] : x.pins)
          allowed.add(id);
      }
    }
  return new Set(
    Object.values(pkg.pins)
      .filter(
        (p) =>
          (!filtered || allowed.has(p.id)) &&
          ![
            p.key,
            "part:" + p.ref,
            "net:" + p.net,
            "module:" + moduleOf(pkg.parts[p.ref]),
          ].some((k) => manuallyHidden.has(k)) &&
          (!focusKeys ||
            [p.key, "part:" + p.ref, "net:" + p.net].some((k) =>
              focusKeys.has(k),
            )),
      )
      .map((p) => p.id),
  );
}
function refreshSymbols() {
  cy.nodes(".pin, .net, .component").forEach((n) => {
    const image = ReviewSymbols.image({
      category: n.data("symbolCategory") || n.data("category"),
      terminal: n.hasClass("terminal"),
      body: n.hasClass("component"),
      halfSpan: n.data("halfSpan"),
      angle: n.data("angle") || 0,
      width: n.data("width"),
      height: n.data("height"),
      anchorY: n.data("anchorY"),
      status: n.hasClass("component")
        ? entry(n.data("partKey")).status
        : n.data("key")
          ? entry(n.data("key")).status
          : "pending",
      dnp: n.hasClass("dnp"),
      nc: n.hasClass("nc"),
      ground: n.hasClass("ground"),
      groundOffsetX: n.data("groundOffsetX") || 0,
      net: n.hasClass("net"),
      emphasis: n.hasClass("highlight")
        ? "highlight"
        : n.selected()
          ? "selected"
          : n.hasClass("chain")
            ? "chain"
            : "",
    });
    if (n.data("image") !== image) n.data("image", image);
  });
}
function updateDetailLevel() {
  cy.batch(() => {
    cy.elements().toggleClass("compact", cy.zoom() < 0.55);
    cy.elements(".highlight, .chain, :selected, .module").removeClass(
      "compact",
    );
    refreshSymbols();
  });
}
function styleGraph() {
  if (!cy) return;
  cy.batch(() => {
    cy.nodes(".pin").forEach((n) => {
      n.removeClass("approved issue pending").addClass(
        entry(n.data("key")).status,
      );
    });
    cy.nodes(".wire-label").toggleClass("hidden-label", !$("labels").checked);
  });
  updateDetailLevel();
}
function updateTraceSummary() {
  $("trace-only").disabled = !traceRoot;
  $("trace-only").textContent = traceOnly ? "返回全板" : "仅看连接链";
  $("trace-clear").disabled = !traceRoot;
  $("trace-summary").textContent = traceRoot
    ? `起点 ${pkg.objects["pin:" + traceRoot]} · ${currentChain.pins.size} 个引脚 · ${currentChain.nets.size} 个信号网络`
    : "选择引脚后可追踪连接链";
}
function buildGraph() {
  cancelDragRouting();
  if (junctionFrame !== null) cancelAnimationFrame(junctionFrame);
  junctionFrame = null;
  dirtyJunctionNets.clear();
  cancelGraphCalculation();
  const model = ReviewGraphModel.topology(pkg, {
    overrides: railOverrides,
    choices: traceChoices,
    root: traceRoot,
    onlyTrace: traceOnly,
    visible: visiblePins(),
    collapsed,
  });
  currentChain = model.chain;
  updateTraceSummary();
  runGraphCalculation(model);
}
function cancelGraphCalculation() {
  layoutGeneration++;
  graphWorker?.terminate();
  graphWorker = null;
  clearTimeout(graphWorkerTimer);
  $("graph-loading").hidden = true;
  $("cancel-layout").hidden = true;
}
function applyWirePath(edge, points) {
  const a = edge.source().position(),
    b = edge.target().position();
  const vx = b.x - a.x,
    vy = b.y - a.y,
    len2 = vx * vx + vy * vy;
  edge.data("routePoints", points);
  const endpoint = (p, n) =>
    `${p.x - n.position("x")}px ${p.y - n.position("y")}px`;
  edge.style({
    "source-endpoint": endpoint(points[0], edge.source()),
    "target-endpoint": endpoint(points[points.length - 1], edge.target()),
  });
  if (len2 < 0.01) return;
  const bends = points.slice(1, -1);
  if (!bends.length) {
    edge.style("curve-style", "straight");
    return;
  }
  edge.style({
    "curve-style": "segments",
    "edge-distances": "node-position",
    "segment-weights": bends.map(
      (p) => ((p.x - a.x) * vx + (p.y - a.y) * vy) / len2,
    ),
    "segment-distances": bends.map(
      (p) => (vx * (p.y - a.y) - vy * (p.x - a.x)) / Math.sqrt(len2),
    ),
  });
}
function refreshJunctions(netKeys = null) {
  const started = performance.now();
  const wires = [],
    states = new Map(),
    anchors = [];
  cy.edges(".wire").forEach((e) => {
    const netKey = e.data("netKey");
    if (netKeys && !netKeys.has(netKey)) return;
    wires.push({ netKey, points: e.data("routePoints") });
    if (!states.has(netKey)) states.set(netKey, new Set());
    for (const cls of ["faded", "chain", "highlight"])
      if (e.hasClass(cls)) states.get(netKey).add(cls);
  });
  cy.nodes(".pin, .net").forEach((n) => {
    const netKey = n.data("netKey");
    if (netKey && (!netKeys || netKeys.has(netKey)))
      anchors.push({
        netKey,
        x: n.position("x"),
        y: n.position("y") + n.data("anchorY"),
      });
  });
  const dots = ReviewGraphModel.junctions(wires, anchors);
  cy.batch(() => {
    cy.nodes(".junction")
      .filter((n) => !netKeys || netKeys.has(n.data("netKey")))
      .remove();
    cy.add(
      dots.map((p) => ({
        data: {
          id: "junction:" + JSON.stringify([p.netKey, p.x, p.y]),
          netKey: p.netKey,
          objectKey: p.netKey,
          label: "",
          width: 7,
          height: 7,
        },
        position: { x: p.x, y: p.y },
        classes: ["junction", ...(states.get(p.netKey) || [])].join(" "),
        selectable: false,
        grabbable: false,
      })),
    );
  });
  graphMetrics.junctions = cy.nodes(".junction").length;
  graphMetrics.junctionMs = performance.now() - started;
}
function scheduleJunctions(netKeys) {
  for (const key of netKeys) if (key) dirtyJunctionNets.add(key);
  if (!dirtyJunctionNets.size || junctionFrame !== null) return;
  junctionFrame = requestAnimationFrame(() => {
    junctionFrame = null;
    const changed = new Set(dirtyJunctionNets);
    dirtyJunctionNets.clear();
    refreshJunctions(changed);
  });
}
function measureGraphText(label, size) {
  const cache = (measureGraphText.cache ||= new Map()),
    key = size + "\0" + label;
  if (cache.has(key)) return cache.get(key);
  const canvas = (measureGraphText.canvas ||= document.createElement("canvas"));
  const context = canvas.getContext("2d");
  context.font = `${size}px system-ui`;
  const result = {
    width:
      Math.ceil(
        Math.max(
          0,
          ...label.split("\n").map((line) => context.measureText(line).width),
        ),
      ) + 4,
    height: label.split("\n").length * size * 1.2 + 4,
  };
  if (cache.size >= 50000) cache.clear();
  cache.set(key, result);
  return result;
}
function runGraphCalculation(model) {
  ReviewGeometry.prepare(model, measureGraphText);
  const generation = layoutGeneration;
  $("graph-loading").hidden = false;
  $("cancel-layout").hidden = false;
  $("layout-warning").textContent = "";
  const fail = (text) => {
    if (generation !== layoutGeneration) return;
    cancelGraphCalculation();
    $("layout-warning").textContent = text;
  };
  try {
    graphWorker = new Worker("/graph-worker.js");
    graphWorker.onerror = () => fail("布局失败，已保留画面；可重新布局重试。");
    graphWorkerTimer = setTimeout(
      () => fail("布局超时，已保留画面；可重新布局重试。"),
      60000,
    );
    graphWorker.onmessage = ({ data }) => {
      if (generation !== layoutGeneration) return;
      if (data.error) {
        fail("布局失败：" + data.error);
        return;
      }
      cancelGraphCalculation();
      const elements = [
        ...data.modelNodes,
        ...model.edges,
        ...(data.labels || []),
      ];
      graphPositioning = true;
      cy.batch(() => {
        cy.elements().remove();
        cy.add(elements);
        for (const n of data.nodes)
          cy.getElementById(n.id).position(n.position);
        for (const e of data.edges) {
          const edge = cy.getElementById(e.id);
          edge.data({
            sourceOffset: e.sourceOffset,
            targetOffset: e.targetOffset,
            validationPoints: e.validationPoints,
          });
          applyWirePath(edge, e.points);
        }
      });
      graphPositioning = false;
      Object.assign(graphMetrics, data.metrics);
      refreshJunctions();
      const pinCount = model.nodes.filter((n) =>
        n.classes.split(" ").includes("pin"),
      ).length;
      const foldedCount = model.nodes
        .filter((n) => n.classes === "module")
        .reduce((sum, n) => sum + n.data.pins.length, 0);
      $("graph-count").textContent =
        `${pinCount} 个可见引脚 · ${foldedCount} 个折叠引脚 · ${pkg.statistics.pins - pinCount - foldedCount} 个隐藏引脚`;
      syncSelection();
      styleGraph();
      paintChain();
      cy.fit(undefined, 45);
      if (graphFocusAfterLayout) {
        highlightObject(graphFocusAfterLayout);
        graphFocusAfterLayout = null;
      }
    };
    graphWorker.postMessage({
      viewport: { width: cy.width(), height: cy.height() },
      nodes: model.nodes,
      edges: model.edges,
      root: traceRoot ? "pin:" + traceRoot : null,
    });
  } catch (e) {
    fail("布局失败：" + e.message);
  }
}
function restoreDrag() {
  if (!dragSnapshot) return;
  graphPositioning = true;
  cy.batch(() => {
    for (const n of dragSnapshot.nodes)
      cy.getElementById(n.id).position(n.position);
    for (const e of dragSnapshot.edges)
      applyWirePath(cy.getElementById(e.id), e.points);
  });
  graphPositioning = false;
  refreshJunctions();
  dragSnapshot = null;
}
function cancelDragRouting() {
  if (dragWorker) {
    dragWorker.terminate();
    dragWorker = null;
    clearTimeout(dragTimer);
    restoreDrag();
  }
}
function finishDragRouting() {
  if (!dragSnapshot) return;
  const worker = (dragWorker = new Worker("/graph-worker.js"));
  const fail = (message) => {
    if (dragWorker !== worker) return;
    cancelDragRouting();
    $("layout-warning").textContent = "移动已撤回：" + message;
  };
  worker.onerror = () => fail("重新布线失败");
  dragTimer = setTimeout(() => fail("重新布线超时"), 5000);
  $("layout-warning").textContent = "正在检查移动位置并重新布线…";
  worker.onmessage = ({ data }) => {
    if (dragWorker !== worker) return;
    if (data.error) {
      fail(data.error);
      return;
    }
    worker.terminate();
    dragWorker = null;
    clearTimeout(dragTimer);
    dragSnapshot = null;
    cy.batch(() => {
      cy.nodes(".wire-label").remove();
      cy.add(data.labels);
      for (const e of data.edges) {
        const edge = cy.getElementById(e.id);
        edge.data("validationPoints", e.validationPoints);
        applyWirePath(edge, e.points);
      }
    });
    Object.assign(graphMetrics, data.metrics);
    refreshJunctions();
    styleGraph();
    paintChain();
    $("layout-warning").textContent = "";
  };
  worker.postMessage({
    mode: "route",
    nodes: cy
      .nodes()
      .not(".junction, .wire-label")
      .map((n) => ({
        data: n.data(),
        classes: n.classes().join(" "),
        position: { ...n.position() },
      })),
    edges: cy.edges().map((e) => ({ data: e.data() })),
  });
}
function runLayout() {
  buildGraph();
}
function initGraph() {
  loadRailSettings();
  // One vertical wheel event is one step, independent of device delta magnitude.
  // Capture prevents Cytoscape's native exponential wheel handler running too.
  $("graph").addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!event.deltaY || !cy.zoomingEnabled() || !cy.userZoomingEnabled())
        return;
      const bounds = $("graph").getBoundingClientRect();
      const level = Math.max(
        cy.minZoom(),
        Math.min(cy.maxZoom(), cy.zoom() * (event.deltaY < 0 ? 1.15 : 0.85)),
      );
      cy.zoom({
        level,
        renderedPosition: {
          x: event.clientX - bounds.left,
          y: event.clientY - bounds.top,
        },
      });
      cy.emit("scrollzoom");
    },
    { capture: true, passive: false },
  );
  cy = cytoscape({
    container: $("graph"),
    elements: [],
    style: graphStyles,
    minZoom: 0.005,
    maxZoom: 3,
    boxSelectionEnabled: true,
    selectionType: "additive",
    layout: { name: "preset" },
  });
  $("cancel-layout").onclick = () => {
    cancelGraphCalculation();
    $("layout-warning").textContent = "已取消布局，保留当前画面。";
  };
  $("trace-only").onclick = () => {
    traceOnly = !traceOnly;
    buildGraph();
  };
  $("trace-clear").onclick = () => {
    traceRoot = null;
    traceChoices = Object.create(null);
    traceOnly = false;
    buildGraph();
    if (currentKey) renderDetail();
  };
  cy.on("tap", "node", ({ target: n }) => {
    if (n.hasClass("module")) {
      collapsed.delete(n.data("group"));
      buildGraph();
    } else if (n.data("objectKey")) selectObject(n.data("objectKey"));
  });
  cy.on("tap", "edge", ({ target: e }) => {
    if (e.data("objectKey")) selectObject(e.data("objectKey"));
    else if (e.data("partKey")) selectObject(e.data("partKey"));
  });
  cy.on("grab", "node", () => {
    cancelGraphCalculation();
    cancelDragRouting();
    dragSnapshot = {
      nodes: cy
        .nodes()
        .not(".junction")
        .map((n) => ({ id: n.id(), position: { ...n.position() } })),
      edges: cy
        .edges()
        .map((e) => ({ id: e.id(), points: e.data("routePoints") })),
    };
  });
  cy.on("free", "node", finishDragRouting);
  cy.on("position", "node", ({ target: n }) => {
    if (graphPositioning || n.hasClass("junction")) return;
    let moved = n;
    const body = n.data("bodyId")
      ? cy.getElementById(n.data("bodyId"))
      : n.hasClass("component")
        ? n
        : null;
    if (body) {
      const center = {
        x: n.position("x") - (n.data("offsetX") || 0),
        y: n.position("y") - (n.data("offsetY") || 0),
      };
      const terminals = cy
        .nodes(".terminal")
        .filter((t) => t.data("bodyId") === body.id());
      graphPositioning = true;
      body.position(center);
      terminals.forEach((t) =>
        t.position({
          x: center.x + t.data("offsetX"),
          y: center.y + (t.data("offsetY") || 0),
        }),
      );
      graphPositioning = false;
      moved = body.union(terminals);
    }
    moved.connectedEdges().forEach((e) => {
      const endpoint = (n, other) =>
        n.data("anchorY") !== undefined
          ? { x: n.position("x"), y: n.position("y") + n.data("anchorY") }
          : {
              x:
                n.position("x") +
                ((other.position("x") >= n.position("x") ? 1 : -1) *
                  n.width()) /
                  2,
              y: n.position("y"),
            };
      const a = endpoint(e.source(), e.target()),
        b = endpoint(e.target(), e.source());
      const mid = (a.x + b.x) / 2;
      applyWirePath(e, [a, { x: mid, y: a.y }, { x: mid, y: b.y }, b]);
    });
    scheduleJunctions(
      moved.connectedEdges(".wire").map((e) => e.data("netKey")),
    );
  });
  cy.on("zoom", updateDetailLevel);
  cy.on("select unselect", "node", (ev) => {
    if (syncing || !ev.target.data("key")) return;
    ev.type === "select"
      ? selected.add(ev.target.data("key"))
      : selected.delete(ev.target.data("key"));
    if (selectionFrame === null)
      selectionFrame = requestAnimationFrame(() => {
        selectionFrame = null;
        syncSelection();
        renderList();
        updateDetailLevel();
      });
  });
  buildGraph();
}
