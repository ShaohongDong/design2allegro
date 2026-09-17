"use strict";
let graphCoarse = [],
  railOverrides = Object.create(null),
  railStorageKey;
let graphPositioning = false,
  layoutGeneration = 0,
  graphFocusAfterLayout = null;
let selectionFrame = null;
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
  if (key.startsWith("pin:")) {
    const mod = moduleOf(pkg.parts[object(key).ref]);
    return collapsed.has(mod) ? "module:" + mod : key;
  }
  if (key.startsWith("part:")) {
    const mod = moduleOf(object(key));
    return collapsed.has(mod) ? "module:" + mod : key;
  }
  return key;
}
function ownerKey(key) {
  return key.startsWith("pin:")
    ? graphIdFor("part:" + object(key).ref)
    : graphIdFor(key);
}
function graphElementsFor(key) {
  const id = graphIdFor(key);
  return cy
    .elements()
    .filter(
      (e) =>
        e.id() === id ||
        e.data("key") === key ||
        e.data("owner") === id ||
        e.data("netKey") === key,
    );
}
function highlightObject(key) {
  if (!$("graph-loading").hidden) {
    graphFocusAfterLayout = key;
    return;
  }
  let area = graphElementsFor(key);
  if (key.startsWith("pin:")) {
    area = area.add(cy.getElementById(ownerKey(key)));
    const pin = object(key);
    if (!pin.nc) area = area.add(graphElementsFor("net:" + pin.net));
  } else if (key.startsWith("part:")) {
    area = area.add(area.connectedEdges());
  }
  area = area.add(area.edges().connectedNodes());
  cy.elements().removeClass("highlight faded");
  if (area.length) {
    cy.elements().addClass("faded");
    area.removeClass("faded").addClass("highlight");
    const ownerIds = new Set(
      area
        .nodes()
        .map((n) => n.data("owner"))
        .filter(Boolean),
    );
    const fitArea = area.add(cy.nodes().filter((n) => ownerIds.has(n.id())));
    updateDetailLevel();
    cy.fit(fitArea, 65);
  }
}
function selectObject(key) {
  if (!object(key)) return;
  currentKey = key;
  // Reveal all endpoints when cross-probing a net, including symbol-only rails.
  for (const related of relatedKeys(key)) {
    if (related.startsWith("part:")) {
      const mod = moduleOf(object(related));
      collapsed.delete(mod);
      manuallyHidden.delete("module:" + mod);
    }
    manuallyHidden.delete(related);
  }
  manuallyHidden.delete(ownerKey(key));
  focusKeys = null;
  $("search").value = "";
  $("status-filter").value = "all";
  $("assembly-filter").value = "all";
  buildGraph(false);
  renderList();
  renderDetail();
  highlightObject(key);
}
const graphStyles = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      "font-family": "system-ui",
      "font-size": 11,
      color: "#253e64",
      "background-color": "#fff",
      "border-color": "#6e8fc5",
      "border-width": 1.5,
    },
  },
  {
    selector: ".part, .module",
    style: {
      shape: "round-rectangle",
      width: "data(width)",
      height: "data(height)",
      "text-valign": "top",
      "text-margin-y": -10,
      "text-wrap": "wrap",
      "text-max-width": 260,
      "background-image": "data(image)",
      "background-width": 40,
      "background-height": 34,
      "background-fit": "none",
    },
  },
  {
    selector: ".module",
    style: {
      "background-color": "#e5edfa",
      "border-style": "dashed",
      "font-weight": "bold",
    },
  },
  {
    selector: ".pin, .port",
    style: {
      width: 5,
      height: 5,
      "background-color": "#34577c",
      "border-width": 0,
      "font-size": 10,
      "text-valign": "center",
    },
  },
  {
    selector: ".pin.left, .port.left",
    style: { "text-halign": "right", "text-margin-x": 26 },
  },
  {
    selector: ".pin.right, .port.right",
    style: { "text-halign": "left", "text-margin-x": -26 },
  },
  {
    selector: ".nc",
    style: {
      width: 9,
      height: 9,
      "background-opacity": 0,
      "background-image": ReviewGraphModel.image("nc"),
      "background-fit": "contain",
      label: "data(label)",
      "border-width": 0,
    },
  },
  {
    selector: ".rail",
    style: {
      width: 32,
      height: 32,
      "border-width": 0,
      "background-opacity": 0,
      "background-image": "data(image)",
      "background-fit": "contain",
      "text-valign": "bottom",
      "text-margin-y": 3,
      "font-size": 10,
      "text-background-color": "#f8fafd",
      "text-background-opacity": 1,
    },
  },
  {
    selector: ".net",
    style: {
      width: 6,
      height: 6,
      "background-color": "#35a5a3",
      "border-width": 0,
      "text-valign": "bottom",
      "text-margin-y": 5,
      "font-size": 10,
    },
  },
  { selector: ".terminal", style: { width: 2, height: 2 } },
  {
    selector: ".dnp",
    style: {
      "border-style": "dashed",
      "background-color": "#f1edf6",
      "border-color": "#9987b6",
    },
  },
  {
    selector: "node.approved",
    style: { "border-color": "#219979", "border-width": 3 },
  },
  {
    selector: "node.issue",
    style: { "border-color": "#d76442", "border-width": 3 },
  },
  {
    selector: "edge",
    style: {
      width: 1.3,
      "line-color": "#a6b7cd",
      "curve-style": "segments",
      "segment-weights": [0.3, 0.7],
      "segment-distances": [0, 0],
      "source-endpoint": "0 0",
      "target-endpoint": "0 0",
      "font-size": 9,
      color: "#56708c",
      "text-background-color": "#f8fafd",
      "text-background-opacity": 1,
      "text-background-padding": 2,
    },
  },
  {
    selector: ".lead",
    style: {
      "curve-style": "straight",
      "source-endpoint": "data(anchor)",
      "line-color": "#34577c",
      events: "no",
    },
  },
  { selector: "edge.labels", style: { label: "data(label)" } },
  { selector: ".faded", style: { opacity: 0.18 } },
  {
    selector: ".highlight",
    style: { opacity: 1, "line-color": "#4174d6", "z-index": 5 },
  },
  {
    selector: "node.highlight",
    style: { "border-color": "#245ddb", "border-width": 2 },
  },
  {
    selector: "node:selected",
    style: {
      "overlay-color": "#245ddb",
      "overlay-opacity": 0.12,
      "overlay-padding": 5,
      "border-width": 3,
    },
  },
  { selector: ".rail, .nc", style: { "border-width": 0 } },
  { selector: ".rail.approved", style: { color: "#219979" } },
  { selector: ".rail.issue", style: { color: "#d76442" } },
  { selector: ".compact", style: { "font-size": 0 } },
];
function allowedObjects() {
  if (
    !$("search").value.trim() &&
    $("status-filter").value === "all" &&
    $("assembly-filter").value === "all"
  )
    return null;
  const allowed = new Set();
  for (const x of filteredRows())
    for (const key of x.key ? relatedKeys(x.key) : x.targets)
      allowed.add(ownerKey(key));
  return allowed;
}
function buildGraph(layout = true) {
  graphFocusAfterLayout = null;
  cy.stop(true);
  const started = performance.now();
  const oldPositions = new Map(
    cy.nodes().map((n) => [n.id(), { ...n.position() }]),
  );
  const elements = [],
    bodies = new Map(),
    pinEnds = new Map(),
    modules = new Map();
  const allowed = allowedObjects();
  const visible = (key) =>
    !manuallyHidden.has(key) &&
    (!allowed || allowed.has(key)) &&
    (!focusKeys || focusKeys.has(key));
  let shownParts = 0,
    shownNets = 0;
  graphCoarse = [];
  const addBody = (id, data, classes) => {
    const el = { data: { id, ...data }, classes };
    elements.push(el);
    bodies.set(id, el);
    graphCoarse.push({
      data: { id, width: data.width + 220, height: data.height + 110 },
      position: oldPositions.get(id),
    });
  };
  const addPin = (id, owner, label, dx, dy, side, key, classes, pins) => {
    elements.push({
      data: { id, key, owner, label, dx, dy, side, pins },
      classes: classes + (side < 0 ? " left" : " right"),
      grabbable: false,
    });
    elements.push({
      data: {
        id: "lead:" + id,
        source: owner,
        target: id,
        owner,
        anchor: `${(side * bodies.get(owner).data.width) / 2} ${dy}`,
      },
      classes: "lead",
      selectable: false,
    });
  };
  for (const part of Object.values(pkg.parts)) {
    const id = graphIdFor(part.key);
    if (manuallyHidden.has(part.key) || !visible(id)) continue;
    shownParts++;
    if (id.startsWith("module:")) {
      if (!modules.has(id)) modules.set(id, []);
      modules.get(id).push(part);
      continue;
    }
    const g = ReviewGraphModel.geometry(part, pkg.pins);
    addBody(
      id,
      {
        key: part.key,
        label:
          part.reference +
          (part.assembly === "dnp" ? " · DNP" : "") +
          "\n" +
          (part.value || part.device || part.category),
        width: g.width,
        height: g.height,
        image: g.image,
      },
      "part " + part.assembly,
    );
    for (const { pin, dx, dy, side } of g.pins) {
      if (manuallyHidden.has(pin.key)) continue;
      addPin(
        pin.key,
        id,
        `${pin.num} · ${pin.name}${pin.nc ? " NC" : ""}`,
        dx,
        dy,
        side,
        pin.key,
        "pin" + (pin.nc ? " nc" : ""),
        [pin.id],
      );
      pinEnds.set(pin.id, {
        id: pin.key,
        owner: id,
        dx,
        dy,
        side,
        pins: [pin.id],
      });
    }
  }
  for (const [id, parts] of modules) {
    const groups = new Map();
    for (const part of parts)
      for (const pinId of part.pins) {
        const pin = pkg.pins[pinId];
        if (pin.nc) continue;
        if (!groups.has(pin.net)) groups.set(pin.net, []);
        groups.get(pin.net).push(pinId);
      }
    const width = Math.max(
      220,
      72 +
        14 * Math.max(0, ...[...groups.keys()].map((s) => [...s].length + 6)),
    );
    const height = Math.max(70, Math.ceil(groups.size / 2) * 48 + 24);
    addBody(
      id,
      {
        label: id.slice(7) + " · " + parts.length,
        members: parts.map((p) => p.key),
        width,
        height,
        image: ReviewGraphModel.image("ic"),
      },
      "module",
    );
    let i = 0;
    const half = Math.ceil(groups.size / 2);
    for (const [net, pins] of [...groups].sort(([a], [b]) =>
      a.localeCompare(b),
    )) {
      const side = i < half ? -1 : 1,
        row = i < half ? i : i - half;
      const dx = side * (width / 2 + 20),
        dy = (row - ((i < half ? half : groups.size - half) - 1) / 2) * 48;
      const portId = "port:" + JSON.stringify([id, net]);
      addPin(
        portId,
        id,
        `${net} · ${pins.length}`,
        dx,
        dy,
        side,
        "net:" + net,
        "port",
        pins,
      );
      for (const pin of pins)
        pinEnds.set(pin, { id: portId, owner: id, dx, dy, side, pins });
      i++;
    }
  }
  const addWire = (net, source, target, pins, cls = "wire") => {
    elements.push({
      data: {
        id: "wire:" + JSON.stringify([net.key, source, target]),
        source,
        target,
        netKey: net.key,
        pins,
        label: net.name,
      },
      classes: cls,
      selectable: false,
    });
  };
  for (const net of Object.values(pkg.nets)) {
    if (!visible(net.key)) continue;
    const ends = [
      ...new Map(
        net.pins
          .filter((p) => pinEnds.has(p))
          .map((p) => [pinEnds.get(p).id, pinEnds.get(p)]),
      ).values(),
    ];
    if (!ends.length) continue;
    shownNets++;
    const role = ReviewGraphModel.classify(net, railOverrides).role;
    if (role !== "signal") {
      for (const end of ends) {
        const id = "rail:" + JSON.stringify([net.key, end.id]);
        elements.push({
          data: {
            id,
            key: net.key,
            netKey: net.key,
            owner: end.owner,
            dx: end.dx + end.side * 65,
            dy: end.dy,
            label: net.name,
            ...(role === "ground"
              ? ReviewGraphModel.groundAppearance(
                  { x: 0, y: 0 },
                  { x: end.side, y: 0 },
                  end.side,
                )
              : { image: ReviewGraphModel.image(role) }),
            role,
          },
          classes: "rail " + role,
          grabbable: false,
        });
        addWire(net, end.id, id, end.pins, "rail-wire");
      }
    } else if (ends.length === 2 && net.pins.length === 2) {
      addWire(net, ends[0].id, ends[1].id, net.pins);
    } else {
      const id = net.key;
      const terminal = ends.length === 1;
      const end = ends[0];
      const attachment = terminal
        ? { owner: end.owner, dx: end.dx + end.side * 65, dy: end.dy }
        : {};
      const visiblePins = ends.flatMap((e) => e.pins).length;
      elements.push({
        data: {
          id,
          key: net.key,
          netKey: net.key,
          label:
            net.name +
            (visiblePins < net.pins.length
              ? ` · ${visiblePins}/${net.pins.length} 端点`
              : ""),
          ...attachment,
        },
        classes: "net" + (terminal ? " terminal" : " junction"),
        grabbable: !terminal,
      });
      if (!terminal)
        graphCoarse.push({
          data: { id, width: 60, height: 50 },
          position: oldPositions.get(id),
        });
      for (const end of ends) addWire(net, end.id, id, end.pins);
    }
    if (role === "signal") {
      if (ends.length === 2 && net.pins.length === 2) {
        if (ends[0].owner !== ends[1].owner)
          graphCoarse.push({
            data: {
              id: "coarse:" + net.key,
              source: ends[0].owner,
              target: ends[1].owner,
            },
          });
      } else if (ends.length > 1)
        for (const owner of new Set(ends.map((e) => e.owner)))
          graphCoarse.push({
            data: {
              id: "coarse:" + JSON.stringify([net.key, owner]),
              source: owner,
              target: net.key,
            },
          });
    }
  }
  syncing = true;
  graphPositioning = true;
  cy.batch(() => {
    cy.elements().remove();
    cy.add(elements);
    cy.nodes().forEach((n) => {
      if (oldPositions.has(n.id())) n.position(oldPositions.get(n.id()));
    });
    graphPositioning = false;
    positionAttachments();
  });
  syncing = false;
  styleGraph();
  syncSelection();
  $("graph-count").textContent =
    `${shownParts}/${Object.keys(pkg.parts).length} 元件 · ${shownNets}/${Object.keys(pkg.nets).length} 网络 · ${cy.nodes(".pin").length} 引脚 · ${collapsed.size} 个模块折叠 · 隐藏 ${Object.keys(pkg.parts).length + Object.keys(pkg.nets).length - shownParts - shownNets} 个对象`;
  graphMetrics.buildMs = performance.now() - started;
  if (
    layout ||
    graphCoarse.some((e) => !e.data.source && !oldPositions.has(e.data.id))
  )
    runLayout();
  else updateDetailLevel();
}
function routeWire(edge) {
  const a = edge.source().position(),
    b = edge.target().position();
  const sa = edge.source().data("side") || 0,
    sb = edge.target().data("side") || 0;
  if (edge.hasClass("rail-wire") && edge.target().data("role") === "ground") {
    const appearance = ReviewGraphModel.groundAppearance(a, b, sa);
    if (edge.target().data("image") !== appearance.image)
      edge.target().data(appearance);
  }
  const vx = b.x - a.x,
    vy = b.y - a.y,
    len2 = vx * vx + vy * vy;
  if (len2 < 1) return;
  let points = [];
  if (!edge.hasClass("rail-wire")) {
    const first = { x: a.x + sa * 28, y: a.y };
    const last = { x: b.x + sb * 28, y: b.y };
    const backFacing = (sa && sa * vx <= 0) || (sb && sb * vx >= 0);
    const sameOwner =
      edge.source().data("owner") &&
      edge.source().data("owner") === edge.target().data("owner");
    if (sameOwner && sa === sb) {
      const x = sa < 0 ? Math.min(first.x, last.x) : Math.max(first.x, last.x);
      points = [
        { x, y: a.y },
        { x, y: b.y },
      ];
    } else if (backFacing || sameOwner) {
      const owners = [edge.source(), edge.target()]
        .map((n) => cy.getElementById(n.data("owner")))
        .filter((n) => n.length);
      const y =
        Math.min(
          a.y,
          b.y,
          ...owners.map((n) => n.position("y") - n.height() / 2),
        ) - 55;
      points = [first, { x: first.x, y }, { x: last.x, y }, last];
    } else {
      const x = (first.x + last.x) / 2;
      points = [first, { x, y: a.y }, { x, y: b.y }, last];
    }
    // Duplicate/end-point segment positions can make the canvas path undefined.
    points = points.filter(
      (p, i) =>
        Math.hypot(p.x - a.x, p.y - a.y) > 0.1 &&
        Math.hypot(p.x - b.x, p.y - b.y) > 0.1 &&
        (!i || Math.hypot(p.x - points[i - 1].x, p.y - points[i - 1].y) > 0.1),
    );
  }
  if (!points.length) {
    edge.style("curve-style", "straight");
    return;
  }
  edge.style({
    "curve-style": "segments",
    "edge-distances": "node-position",
    "segment-weights": points.map(
      (p) => ((p.x - a.x) * vx + (p.y - a.y) * vy) / len2,
    ),
    "segment-distances": points.map(
      (p) => (vx * (p.y - a.y) - vy * (p.x - a.x)) / Math.sqrt(len2),
    ),
  });
}
function positionAttachments(owner) {
  if (graphPositioning) return;
  graphPositioning = true;
  cy.batch(() => {
    const attached = cy
      .nodes()
      .filter((n) => n.data("owner") && (!owner || n.data("owner") === owner));
    attached.forEach((n) => {
      const p = cy.getElementById(n.data("owner")).position();
      n.position({ x: p.x + n.data("dx"), y: p.y + n.data("dy") });
    });
    (owner ? attached.connectedEdges() : cy.edges())
      .not(".lead")
      .forEach(routeWire);
  });
  graphPositioning = false;
}
function updateDetailLevel() {
  cy.batch(() => {
    cy.nodes(".pin, .port, .rail, .net").toggleClass(
      "compact",
      cy.zoom() < 0.55,
    );
    cy.nodes(".highlight, :selected").removeClass("compact");
  });
}
function styleGraph() {
  if (!cy) return;
  cy.batch(() => {
    cy.nodes().forEach((n) => {
      n.removeClass("approved issue");
      if (n.data("key")) n.addClass(entry(n.data("key")).status);
    });
    cy.edges(".wire").toggleClass("labels", $("labels").checked);
  });
  updateDetailLevel();
}
function runLayout() {
  const generation = ++layoutGeneration;
  $("graph-loading").hidden = false;
  requestAnimationFrame(() => {
    if (generation !== layoutGeneration) return;
    const started = performance.now();
    const coarse = cytoscape({
      headless: true,
      styleEnabled: true,
      elements: graphCoarse,
      style: [
        {
          selector: "node",
          style: { width: "data(width)", height: "data(height)" },
        },
      ],
      layout: { name: "preset" },
    });
    try {
      const large = graphCoarse.length > 2000;
      coarse
        .layout(
          large
            ? { name: "grid", avoidOverlap: true, spacingFactor: 1.15 }
            : {
                name: "cose",
                animate: false,
                randomize: false,
                nodeRepulsion: () => 18000,
                idealEdgeLength: () => 180,
                componentSpacing: 140,
                numIter: 400,
              },
        )
        .run();
      graphPositioning = true;
      cy.batch(() =>
        coarse
          .nodes()
          .forEach((n) => cy.getElementById(n.id()).position(n.position())),
      );
      graphPositioning = false;
      positionAttachments();
      cy.fit(undefined, 55);
      graphMetrics.layoutMs = performance.now() - started;
      graphMetrics.layout = large ? "grid" : "cose";
      updateDetailLevel();
    } finally {
      graphPositioning = false;
      coarse.destroy();
      $("graph-loading").hidden = true;
    }
    if (graphFocusAfterLayout) {
      const key = graphFocusAfterLayout;
      graphFocusAfterLayout = null;
      highlightObject(key);
    }
  });
}
function initGraph() {
  loadRailSettings();
  cy = cytoscape({
    container: $("graph"),
    elements: [],
    style: graphStyles,
    minZoom: 0.005,
    maxZoom: 3,
    wheelSensitivity: 1.0,
    boxSelectionEnabled: true,
    selectionType: "additive",
    layout: { name: "preset" },
  });
  cy.on("tap", "node", (ev) => {
    const n = ev.target;
    if (n.hasClass("module")) {
      collapsed.delete(n.id().slice(7));
      buildGraph();
    } else if (n.data("key")) selectObject(n.data("key"));
  });
  cy.on("tap", "edge", (ev) => {
    if (ev.target.data("netKey")) selectObject(ev.target.data("netKey"));
  });
  cy.on("position", ".part, .module", (ev) =>
    positionAttachments(ev.target.id()),
  );
  cy.on("position", ".net", (ev) => {
    if (!graphPositioning) ev.target.connectedEdges().forEach(routeWire);
  });
  cy.on("zoom", updateDetailLevel);
  cy.on("select unselect", "node", (ev) => {
    if (syncing) return;
    const key = ev.target.data("key");
    if (key) {
      ev.type === "select" ? selected.add(key) : selected.delete(key);
      if (selectionFrame === null)
        selectionFrame = requestAnimationFrame(() => {
          selectionFrame = null;
          syncSelection();
          renderList();
          updateDetailLevel();
        });
    }
  });
  buildGraph();
}
