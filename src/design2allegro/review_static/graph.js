const geometryReady = import("/layout-geometry.js");
("use strict");
let railOverrides = Object.create(null),
  railStorageKey;
let graphPositioning = false,
  layoutGeneration = 0,
  graphFocusAfterLayout = null;
let selectionFrame = null;
const graphMetrics = {};
let graphWorker = null,
  graphWorkerTimer = null,
  graphRouteTimer = null;
let graphDragging = false,
  graphNeedsLayout = false;
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
  const viewKey = () =>
    JSON.stringify([
      [...collapsed],
      [...manuallyHidden],
      focusKeys ? [...focusKeys] : null,
      $("search").value,
      $("status-filter").value,
      $("assembly-filter").value,
    ]);
  const previousView = viewKey();
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
  if (previousView !== viewKey() || !graphElementsFor(key).length)
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
  {
    selector: ".region",
    style: {
      shape: "round-rectangle",
      width: "data(width)",
      height: "data(height)",
      "background-color": "#edf3fa",
      "background-opacity": 0.5,
      "border-color": "#c4d3e4",
      "border-style": "dashed",
      "text-valign": "top",
      "text-margin-y": 22,
      "font-size": 16,
      "font-weight": "bold",
      "z-index": -10,
      events: "no",
    },
  },
  {
    selector: ".cross-terminal",
    style: {
      shape: "diamond",
      width: 12,
      height: 12,
      "background-color": "#5679aa",
      "text-halign": "center",
      "text-valign": "top",
      "text-margin-y": -10,
    },
  },
  {
    selector: ".route-junction",
    style: {
      width: 5,
      height: 5,
      "background-color": "#34577c",
      "border-width": 0,
    },
  },
  {
    selector: ".route-pending",
    style: { "line-style": "dashed", "line-color": "#9b9da3" },
  },
  {
    selector: ".route-failed",
    style: { "line-style": "dashed", "line-color": "#c54c42", width: 2 },
  },
  {
    selector: ".layout-conflict",
    style: { "border-color": "#c54c42", "border-width": 3 },
  },
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
  cancelGraphCalculation();
  cy.stop(true);
  const started = performance.now();
  const oldPositions = new Map(
    cy.nodes().map((n) => [n.id(), { ...n.position() }]),
  );
  const oldGeometry = new Map(),
    oldChildren = new Map();
  if (!layout)
    cy.nodes().forEach((n) => {
      const data = {};
      for (const field of [
        "width",
        "height",
        "dx",
        "dy",
        "direction",
        "rotation",
        "symbol",
        "compactLabel",
        "geometryLabel",
      ])
        if (n.data(field) !== undefined) data[field] = n.data(field);
      oldGeometry.set(n.id(), { data, label: n.data("label") });
      if (n.data("owner")) {
        const ids = oldChildren.get(n.data("owner")) || [];
        ids.push(n.id());
        oldChildren.set(n.data("owner"), ids);
      }
    });
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
  const addBody = (id, data, classes) => {
    const el = { data: { id, ...data }, classes };
    elements.push(el);
    bodies.set(id, el);
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
        group: moduleOf(part) || "",
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
        group: id.slice(7),
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
    } else {
      const byGroup = new Map();
      for (const end of ends) {
        const group = bodies.get(end.owner).data.group;
        if (!byGroup.has(group)) byGroup.set(group, []);
        byGroup.get(group).push(end);
      }
      // Use the full inventory, so filtering never turns a cross-module signal
      // into an apparently complete local net.
      const allGroups = new Set(
        net.pins.map((id) => moduleOf(pkg.parts[pkg.pins[id].ref]) || ""),
      );
      const cross = allGroups.size > 1;
      for (const [group, local] of byGroup) {
        if (!cross && local.length === 2 && net.pins.length === 2) {
          addWire(net, local[0].id, local[1].id, net.pins);
          continue;
        }
        const id = cross
          ? "local-net:" + JSON.stringify([net.key, group])
          : net.key;
        const terminal = local.length === 1 && !cross;
        const end = local[0];
        const visiblePins = local.flatMap((e) => e.pins).length;
        const label =
          net.name +
          (cross ? ` ↗ ${allGroups.size - 1} 个其他模块` : "") +
          (visiblePins < net.pins.length
            ? ` · ${visiblePins}/${net.pins.length} 端点`
            : "");
        elements.push({
          data: {
            id,
            key: net.key,
            netKey: net.key,
            group,
            label,
            ...(terminal
              ? { owner: end.owner, dx: end.dx + end.side * 65, dy: end.dy }
              : {}),
          },
          classes:
            "net" +
            (terminal ? " terminal" : cross ? " cross-terminal" : " junction"),
          grabbable: !terminal,
        });
        for (const end of local) addWire(net, end.id, id, end.pins);
      }
    }
  }

  syncing = true;
  const stableOwners = new Set();
  if (!layout) {
    const children = new Map();
    for (const { data } of elements)
      if (!data.source && data.owner) {
        const ids = children.get(data.owner) || [];
        ids.push(data.id);
        children.set(data.owner, ids);
      }
    for (const { data } of elements)
      if (
        !data.source &&
        !data.owner &&
        oldGeometry.has(data.id) &&
        JSON.stringify((children.get(data.id) || []).sort()) ===
          JSON.stringify((oldChildren.get(data.id) || []).sort())
      )
        stableOwners.add(data.id);
  }
  graphPositioning = true;
  cy.batch(() => {
    cy.elements().remove();
    cy.add(elements);
    cy.nodes().forEach((n) => {
      if (oldPositions.has(n.id())) n.position(oldPositions.get(n.id()));
      if (
        stableOwners.has(n.data("owner") || n.id()) &&
        oldGeometry.has(n.id())
      ) {
        const old = oldGeometry.get(n.id()),
          data = { ...old.data };
        if (old.label !== n.data("label")) delete data.geometryLabel;
        n.data(data);
      }
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
    cy
      .nodes(".part, .module, .net")
      .some((n) => !n.data("owner") && !oldPositions.has(n.id()))
  )
    runGraphCalculation(true);
  else {
    updateDetailLevel();
    scheduleGraphRoutes();
  }
}
function applyWirePath(edge, points, failed = false) {
  const a = edge.source().position(),
    b = edge.target().position();
  const vx = b.x - a.x,
    vy = b.y - a.y,
    len2 = vx * vx + vy * vy;
  edge.data("routePoints", points);
  edge.toggleClass("route-failed", failed).removeClass("route-pending");
  const bends = points
    .slice(1, -1)
    .filter(
      (p) =>
        Math.hypot(p.x - a.x, p.y - a.y) > 0.01 &&
        Math.hypot(p.x - b.x, p.y - b.y) > 0.01,
    );
  if (!bends.length || len2 < 0.01) {
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
function routeWire(edge) {
  const a = edge.source().position(),
    b = edge.target().position();
  if (edge.hasClass("rail-wire")) {
    if (edge.target().data("role") === "ground")
      edge
        .target()
        .data(
          ReviewGraphModel.groundAppearance(a, b, edge.source().data("side")),
        );
    applyWirePath(edge, [a, b]);
  } else {
    // Temporary paths are explicitly styled until the worker validates them.
    applyWirePath(edge, [
      a,
      { x: (a.x + b.x) / 2, y: a.y },
      { x: (a.x + b.x) / 2, y: b.y },
      b,
    ]);
  }
  edge.addClass("route-pending");
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
    const zoom = cy.zoom();
    cy.nodes(".region").style("font-size", Math.min(100, 14 / zoom));
    cy.edges(".wire, .rail-wire").style("width", Math.max(1.3, 0.65 / zoom));
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
function cancelGraphCalculation() {
  ++layoutGeneration;
  if (graphWorker) graphWorker.terminate();
  graphWorker = null;
  clearTimeout(graphWorkerTimer);
  clearTimeout(graphRouteTimer);
}
function scheduleGraphRoutes() {
  clearTimeout(graphRouteTimer);
  if (!graphDragging)
    graphRouteTimer = setTimeout(
      () => runGraphCalculation(graphNeedsLayout),
      100,
    );
}
function graphSnapshot(layout) {
  // Measure labels before restoring the zoom-dependent detail level.
  cy.nodes().removeClass("compact");
  const snapshot = {
    layout,
    scene: {
      pkg: { parts: pkg.parts, pins: pkg.pins },
      nodes: cy
        .nodes()
        .filter(
          (n) =>
            !n.hasClass("region") &&
            (!n.hasClass("route-junction") || n.hasClass("branch")),
        )
        .map((n) => ({
          id: n.id(),
          x: n.position("x"),
          y: n.position("y"),
          width: n.width(),
          height: n.height(),
          classes: n.classes(),
          data: { ...n.data() },
          direction: n.data("direction"),
          rotation: n.data("rotation"),
          symbol: n.data("symbol"),
          compactLabel: n.data("compactLabel"),
          labelBox: n.data("geometryLabel")
            ? (() => {
                const b = n.data("geometryLabel"),
                  p = n.position();
                return {
                  x1: p.x + b.x1,
                  x2: p.x + b.x2,
                  y1: p.y + b.y1,
                  y2: p.y + b.y2,
                  w: b.w,
                  h: b.h,
                };
              })()
            : (() => {
                const b = n.boundingBox({
                  includeNodes: false,
                  includeLabels: true,
                  includeOverlays: false,
                  useCache: false,
                });
                return n.data("label") ? { ...b } : null;
              })(),
        })),
      wires: cy.edges(".wire, .rail-wire").map((e) => ({
        id: e.id(),
        net: e.data("netKey"),
        source: e.source().id(),
        target: e.target().id(),
        rail: e.hasClass("rail-wire"),
        pins: e.data("pins") || [],
        points: e.data("routePoints") || [],
        failed: e.hasClass("route-failed"),
      })),
    },
  };
  updateDetailLevel();
  return snapshot;
}

async function applyGraphScene(result) {
  const G = await geometryReady;
  graphPositioning = true;
  cy.batch(() => {
    cy.nodes().removeClass("layout-conflict");
    cy.edges(".wire, .rail-wire").remove();
    cy.nodes(".branch, .region, .route-junction").remove();
    for (const n of result.nodes) {
      let el = cy.getElementById(n.id);
      if (!el.length && n.classes.includes("branch"))
        el = cy.add({
          data: {
            id: n.id,
            key: n.data.netKey,
            netKey: n.data.netKey,
            label: "",
          },
          classes: "branch route-junction",
          grabbable: false,
          selectable: false,
        });
      if (!el.length) continue;
      el.position({ x: n.x, y: n.y });
      el.data({
        ...n.data,
        width: n.width,
        height: n.height,
        direction: n.direction,
        rotation: n.rotation,
        symbol: n.symbol,
        compactLabel: n.compactLabel,
      });
      if (n.labelBox) {
        const b = n.labelBox;
        el.data("geometryLabel", {
          x1: b.x1 - n.x,
          x2: b.x2 - n.x,
          y1: b.y1 - n.y,
          y2: b.y2 - n.y,
          w: b.w,
          h: b.h,
        });
        el.style({
          "text-halign": "center",
          "text-valign": "center",
          "text-margin-x": (b.x1 + b.x2) / 2 - n.x,
          "text-margin-y": (b.y1 + b.y2) / 2 - n.y,
          "text-max-width": Math.max(260, b.w || 0),
        });
      }
      if (n.symbol) {
        const vertical = (n.rotation || 0) % 180 !== 0,
          sw = vertical ? 64 : 80,
          sh = vertical ? 80 : 64;
        const polarity = G.polarityBox(n);
        const plus = polarity
          ? `<path d="M${(polarity.x1 + polarity.x2) / 2 - n.x - 4} ${(polarity.y1 + polarity.y2) / 2 - n.y}h8m-4 -4v8"/>`
          : "";
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${sw}" height="${sh}" viewBox="${-sw / 2} ${-sh / 2} ${sw} ${sh}"><g fill="none" stroke="#34577c" stroke-width="1.5"><path transform="rotate(${n.rotation || 0})" d="${G.symbolPath(n.symbol)}"/>${plus}</g></svg>`;
        el.data(
          "image",
          "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg),
        );
        el.addClass("passive").style({
          "border-width": n.classes.includes("dnp") ? 1.5 : 0,
          "background-opacity": 0,
          "background-width": sw,
          "background-height": sh,
          "background-clip": "none",
        });
      }
      if (n.compactLabel)
        el.data("label", pkg.pins[n.id.slice(4)]?.num || n.data.label);
      if (n.classes.includes("rail") && n.data.role === "ground") {
        const wire = result.wires.find((w) => w.target === n.id);
        const pin = result.nodes.find((p) => p.id === wire?.source);
        if (pin) el.data(ReviewGraphModel.groundAppearance(pin, n));
      }
      if (n.classes.includes("pin") || n.classes.includes("port")) {
        const owner = result.nodes.find((p) => p.id === n.data.owner),
          d = n.direction || (n.data.side < 0 ? "W" : "E");
        el.removeClass("left right top bottom").addClass(
          { W: "left", E: "right", N: "top", S: "bottom" }[d],
        );
        if (!n.compactLabel) {
          el.style({
            "text-halign": d === "W" ? "right" : d === "E" ? "left" : "center",
            "text-valign": "center",
            "text-margin-x": d === "W" ? 26 : d === "E" ? -26 : 0,
            "text-margin-y": d === "N" ? 30 : d === "S" ? -26 : 0,
          });
          el.removeData("geometryLabel");
        }

        const anchor = {
          x:
            d === "W"
              ? -owner.width / 2
              : d === "E"
                ? owner.width / 2
                : n.x - owner.x,
          y:
            d === "N"
              ? -owner.height / 2
              : d === "S"
                ? owner.height / 2
                : n.y - owner.y,
        };
        cy.getElementById("lead:" + n.id).data(
          "anchor",
          `${anchor.x} ${anchor.y}`,
        );
      }
    }
    for (const w of result.wires) {
      if (
        !cy.getElementById(w.source).length ||
        !cy.getElementById(w.target).length
      )
        continue;
      const e = cy.add({
        data: {
          id: w.id,
          source: w.source,
          target: w.target,
          netKey: w.net,
          label: w.net.slice(4),
          pins: w.pins || [],
        },
        classes: w.rail ? "rail-wire" : "wire",
        selectable: false,
      });
      applyWirePath(e, w.points, w.failed);
    }
    for (const id of result.conflicts || [])
      cy.getElementById(id).addClass("layout-conflict");
    result.frames.forEach((f) =>
      cy.add({
        data: {
          id: "region:" + JSON.stringify(f.group),
          label: f.group || "顶层",
          width: f.x2 - f.x1,
          height: f.y2 - f.y1,
        },
        position: { x: (f.x1 + f.x2) / 2, y: (f.y1 + f.y2) / 2 },
        classes: "region",
        selectable: false,
        grabbable: false,
      }),
    );
  });
  graphPositioning = false;
  styleGraph();
  syncSelection();
}
function runGraphCalculation(layout) {
  cancelGraphCalculation();
  graphNeedsLayout = layout;
  const generation = layoutGeneration,
    input = graphSnapshot(layout);
  if (!input.scene.nodes.length) {
    $("graph-loading").hidden = true;
    return;
  }
  $("graph-loading").hidden = false;
  $("graph-loading").textContent = layout ? "正在布局与布线…" : "正在重新布线…";
  $("cancel-layout").hidden = true;
  let preview = false,
    finished = false;
  const finish = () => {
    if (generation !== layoutGeneration) return;
    finished = true;
    graphWorker?.terminate();
    graphWorker = null;
    clearTimeout(graphWorkerTimer);
    $("graph-loading").hidden = true;
    $("cancel-layout").hidden = true;
    if (graphFocusAfterLayout) {
      const key = graphFocusAfterLayout;
      graphFocusAfterLayout = null;
      highlightObject(key);
    }
  };
  const fail = (message) => {
    if (generation !== layoutGeneration) return;
    finish();
    $("layout-warning").textContent = message + "；可点击“重新布局”重试。";
    cy.edges(".route-pending")
      .addClass("route-failed")
      .removeClass("route-pending");
  };
  try {
    graphWorker = new Worker("/graph-worker.js", { type: "module" });
    graphWorker.onerror = (e) =>
      fail("布局计算失败，保留当前画面：" + e.message);
    graphWorkerTimer = setTimeout(
      () => fail("布局计算超时，保留当前画面"),
      60000,
    );
    let apply = Promise.resolve();
    graphWorker.onmessage = ({ data }) => {
      apply = apply
        .then(async () => {
          if (
            finished ||
            data.generation !== layoutGeneration ||
            generation !== layoutGeneration
          )
            return;
          if (data.error) {
            fail("布局计算失败：" + data.error);
            return;
          }
          if (data.phase === "complete" && !data.result) {
            finish();
            return;
          }
          await geometryReady;
          if (finished || generation !== layoutGeneration) return;
          await applyGraphScene(data.result);
          if (generation !== layoutGeneration) return;
          graphNeedsLayout = false;
          graphMetrics.layout = "elk-layered";
          graphMetrics.conflicts = data.result.conflicts?.length || 0;
          graphMetrics.failedRoutes = cy.edges(".route-failed").length;
          $("layout-warning").textContent = [
            graphMetrics.conflicts
              ? `${graphMetrics.conflicts} 个元件重叠`
              : null,
            graphMetrics.failedRoutes
              ? `${graphMetrics.failedRoutes} 条连线未找到可用通道（红色虚线）`
              : null,
          ]
            .filter(Boolean)
            .join("；");
          if (!preview) {
            preview = true;
            $("cancel-layout").hidden = !layout;
            if (layout) cy.fit(undefined, 55);
            clearTimeout(graphWorkerTimer);
            graphWorkerTimer = setTimeout(finish, 10000);
          }
          updateDetailLevel();
          if (data.phase === "complete") finish();
          else $("graph-loading").textContent = "预览已就绪，正在精排…";
        })
        .catch((e) => fail(e.message));
    };
    graphWorker.postMessage({ generation, input });
  } catch (e) {
    fail("无法启动布局计算：" + e.message);
  }
}
function runLayout() {
  buildGraph(true);
}
function initGraph() {
  loadRailSettings();
  $("cancel-layout").onclick = () => {
    cancelGraphCalculation();
    graphNeedsLayout = false;
    $("graph-loading").hidden = true;
    $("cancel-layout").hidden = true;
  };
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
  cy.on("grab", ".part, .module, .net", () => {
    graphDragging = true;
    graphNeedsLayout = false;
    cancelGraphCalculation();
  });
  cy.on("free", ".part, .module, .net", () => {
    graphDragging = false;
    scheduleGraphRoutes();
  });
  cy.on("position", ".part, .module", (ev) => {
    if (graphPositioning) return;
    cancelGraphCalculation();
    positionAttachments(ev.target.id());
    scheduleGraphRoutes();
  });
  cy.on("position", ".net", (ev) => {
    if (!graphPositioning) {
      cancelGraphCalculation();
      ev.target.connectedEdges().forEach(routeWire);
      scheduleGraphRoutes();
    }
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
