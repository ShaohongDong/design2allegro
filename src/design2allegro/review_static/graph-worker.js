"use strict";
importScripts("/vendor/elk-api.js", "/graph-geometry.js", "/graph-routing.js");
const engine = new ELK({ workerUrl: "/vendor/elk-worker.min.js" });
const G = ReviewGeometry,
  R = ReviewRouting;
function escapeChoices(node, box, point = node.position) {
  const side = node.data.bodyId ? node.data.side : null;
  const sides = side
    ? [side]
    : node.data.layoutKind === "fixed"
      ? ["W", "E"]
      : ["W", "E", "N", "S"];
  return sides
    .map((side) => ({
      side,
      point: {
        x: side === "W" ? box.x1 : side === "E" ? box.x2 : point.x,
        y: side === "N" ? box.y1 : side === "S" ? box.y2 : point.y,
      },
    }))
    .filter(
      (candidate) =>
        !(node.data.escapeObstacles || []).some((obstacle) =>
          R.hits(point, candidate.point, G.move(obstacle, node.position)),
        ),
    );
}
function layoutBetter(a, b) {
  for (const key of [
    "bends",
    "alignmentDeviation",
    "crossings",
    "wireLength",
    "area",
  ])
    if (Math.abs((a[key] || 0) - (b[key] || 0)) > 0.01)
      return (a[key] || 0) < (b[key] || 0);
  return false;
}
function layoutLimits(scene) {
  return (
    scene.optimizationLimits || {
      area: scene.metrics.area * 1.1,
      wireLength: scene.metrics.wireLength * 1.1,
      crossings: scene.metrics.crossings,
    }
  );
}
function rejectLayout(metrics, reference, limits) {
  return metrics.area > limits.area + 0.01
    ? "area"
    : metrics.wireLength > limits.wireLength + 0.01
      ? "length"
      : metrics.crossings > reference.crossings
        ? "crossings"
        : metrics.foreignOverlap
          ? "overlap"
          : !layoutBetter(metrics, reference)
            ? "noImprovement"
            : null;
}
function pack(scenes, aspect) {
  const ordered = scenes
    .map((s, i) => ({
      i,
      w: s.bounds.x2 - s.bounds.x1 + 20,
      h: s.bounds.y2 - s.bounds.y1 + 20,
    }))
    .sort((a, b) => b.w * b.h - a.w * a.h || a.i - b.i);
  const area = ordered.reduce((s, r) => s + r.w * r.h, 0),
    maxWidth = Math.max(1, ...ordered.map((r) => r.w));
  let best = null;
  for (const factor of [0.8, 1, 1.25]) {
    const width = Math.max(maxWidth, Math.sqrt(area * aspect * factor));
    const free = [{ x: 0, y: 0, w: width, h: Infinity }],
      positions = new Map();
    let maxX = 0,
      maxY = 0;
    for (const r of ordered) {
      let chosen = -1;
      for (let i = 0; i < free.length; i++)
        if (
          free[i].w >= r.w &&
          free[i].h >= r.h &&
          (chosen < 0 ||
            free[i].y < free[chosen].y ||
            (free[i].y === free[chosen].y && free[i].w < free[chosen].w))
        )
          chosen = i;
      const f = free.splice(chosen, 1)[0];
      positions.set(r.i, { x: f.x, y: f.y });
      if (f.w > r.w + 0.01)
        free.push({ x: f.x + r.w, y: f.y, w: f.w - r.w, h: r.h });
      if (f.h > r.h + 0.01)
        free.push({ x: f.x, y: f.y + r.h, w: f.w, h: f.h - r.h });
      maxX = Math.max(maxX, f.x + r.w);
      maxY = Math.max(maxY, f.y + r.h);
    }
    const score =
      maxX * maxY * (1 + 0.1 * Math.abs(Math.log(maxX / maxY / aspect)));
    if (!best || score < best.score) best = { positions, score };
  }
  return best.positions;
}
async function candidate(
  ids,
  es,
  byId,
  terminals,
  depths,
  direction,
  mixed,
  cache,
) {
  const models = new Map(ids.map((id) => [id, structuredClone(byId.get(id))]));
  const localTerminals = new Map();
  for (const [id, t] of terminals)
    if (models.has(t.bodyId)) localTerminals.set(id, { data: { ...t } });
  for (const n of models.values())
    if (n.data.variants) {
      let variant = n.data.variants[direction === "RIGHT" ? 0 : 1];
      if (mixed)
        variant = n.data.variants.reduce((a, b) =>
          (b.box.x2 - b.box.x1) * (b.box.y2 - b.box.y1) <
          (a.box.x2 - a.box.x1) * (a.box.y2 - a.box.y1)
            ? b
            : a,
        );
      G.applyVariant(n, variant, localTerminals);
    }
  const index = new Map(ids.map((id, i) => [id, "" + i]));
  const ports = new Map();
  const moduleNets = new Map();
  for (const [id, n] of models)
    if (n.classes === "module") {
      const nets = [
        ...new Set(
          es
            .filter((e) => e.data.source === id || e.data.target === id)
            .map((e) => e.data.netKey),
        ),
      ].sort();
      moduleNets.set(id, nets);
      n.data.height = Math.max(n.data.height, nets.length * 16 + 24);
      n.data.box = G.rect(0, 0, n.data.width, n.data.height);
    }
  const children = ids.map((id) => {
    const d = models.get(id).data,
      b = d.box,
      width = b.x2 - b.x1 + 16,
      height = b.y2 - b.y1 + 16;
    const sides = d.variants
      ? d.angle % 180
        ? ["N", "S"]
        : ["W", "E"]
      : escapeChoices(
          { data: d, position: { x: 0, y: 0 } },
          { x1: b.x1 - 8, y1: b.y1 - 8, x2: b.x2 + 8, y2: b.y2 + 8 },
        ).map((c) => c.side);
    const ps = sides.flatMap((side) =>
      (moduleNets.get(id) || [null]).map((net, i) => {
        const suffix = net === null ? "" : String(i);
        const p = {
          id: index.get(id) + ":" + side + suffix,
          x: side === "W" ? 0 : side === "E" ? width : 8 - b.x1,
          y:
            net !== null
              ? 20 + i * 16
              : side === "N"
                ? 0
                : side === "S"
                  ? height
                  : 8 - b.y1,
          width: 0,
          height: 0,
          layoutOptions: {
            "elk.port.side": { W: "WEST", E: "EAST", N: "NORTH", S: "SOUTH" }[
              side
            ],
          },
        };
        ports.set(id + ":" + side + suffix, p);
        return p;
      }),
    );
    return {
      id: index.get(id),
      width,
      height,
      layoutOptions: { "elk.portConstraints": "FIXED_POS" },
      ports: ps,
    };
  });
  const oriented = es.map((e, i) => {
    const reversed = depths.get(e.data.source) > depths.get(e.data.target);
    const src = reversed ? e.data.target : e.data.source,
      dst = reversed ? e.data.source : e.data.target;
    const sourcePin = localTerminals.get(
        reversed ? e.data.originalTarget : e.data.originalSource,
      )?.data,
      targetPin = localTerminals.get(
        reversed ? e.data.originalSource : e.data.originalTarget,
      )?.data;
    const selectSide = (id, preferred) =>
      [preferred, "W", "E", "S", "N"].find((side) =>
        ports.has(id + ":" + side + (moduleNets.has(id) ? "0" : "")),
      );
    const from =
        (sourcePin?.side || selectSide(src, direction === "DOWN" ? "S" : "E")) +
        (moduleNets.has(src) ? moduleNets.get(src).indexOf(e.data.netKey) : ""),
      to =
        (targetPin?.side || selectSide(dst, direction === "DOWN" ? "N" : "W")) +
        (moduleNets.has(dst) ? moduleNets.get(dst).indexOf(e.data.netKey) : "");
    return {
      id: "e" + i,
      sources: [index.get(src) + ":" + from],
      targets: [index.get(dst) + ":" + to],
      reversed,
      src,
      dst,
      from,
      to,
    };
  });
  const elkEdges = oriented.map(({ id, sources, targets }, i) => ({
    id,
    sources,
    targets,
    ...(es[i].data.label
      ? {
          labels: [
            {
              id: "label" + i,
              // ELK needs a nonempty label; actual text is rendered separately.
              text: "net",
              width: es[i].data.text.width + 16,
              height: es[i].data.text.height + 20,
            },
          ],
        }
      : {}),
  }));
  const cacheKey = JSON.stringify([children, elkEdges, direction]);
  let layout = cache.get(cacheKey);
  if (!layout) {
    layout = await engine.layout({
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": direction,
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": "20",
        "elk.layered.spacing.nodeNodeBetweenLayers": "40",
        "elk.padding": "[top=12,left=12,bottom=12,right=12]",
        "elk.randomSeed": "1",
      },
      children,
      edges: elkEdges,
    });
    cache.set(cacheKey, layout);
  }
  const nodes = [],
    centers = new Map(),
    boxes = [];
  for (const n of layout.children) {
    const id = ids[Number(n.id)],
      d = models.get(id).data;
    const p = { x: n.x + 8 - d.box.x1, y: n.y + 8 - d.box.y1 };
    centers.set(id, p);
    nodes.push({ id, position: p, data: d });
    boxes.push({ id, x1: n.x, y1: n.y, x2: n.x + n.width, y2: n.y + n.height });
  }
  for (const t of localTerminals.values()) {
    const p = centers.get(t.data.bodyId);
    nodes.push({
      id: t.data.id,
      position: { x: p.x + t.data.offsetX, y: p.y + t.data.offsetY },
      data: t.data,
    });
  }
  const routes = (layout.edges || []).map((e) => {
    const number = Number(e.id.slice(1)),
      original = es[number],
      o = oriented[number],
      section = e.sections?.[0];
    if (!section) throw new Error("线路缺少布局结果");
    let points = [
      section.startPoint,
      ...(section.bendPoints || []),
      section.endPoint,
    ];
    if (o.reversed) points.reverse();
    const offsets = {};
    for (const [id, pin, front] of [
      [original.data.source, original.data.originalSource, true],
      [original.data.target, original.data.originalTarget, false],
    ]) {
      const p = centers.get(id),
        t = localTerminals.get(pin)?.data,
        anchor = { x: p.x + (t?.offsetX || 0), y: p.y + (t?.offsetY || 0) };
      if (moduleNets.has(id)) {
        const portName = front !== o.reversed ? o.from : o.to;
        const port = ports.get(id + ":" + portName),
          box = models.get(id).data.box;
        const offset = {
          x: portName[0] === "W" ? box.x1 : box.x2,
          y: port.y - 8 + box.y1,
        };
        offsets[front ? "sourceOffset" : "targetOffset"] = offset;
        anchor.x = p.x + offset.x;
        anchor.y = p.y + offset.y;
      }
      if (front) points.unshift(anchor);
      else points.push(anchor);
    }
    return {
      id: original.data.id,
      ...offsets,
      sourcePin: original.data.originalSource,
      targetPin: original.data.originalTarget,
      source: original.data.source,
      target: original.data.target,
      net: original.data.netKey,
      label: original.data.label,
      text: original.data.text,
      points,
    };
  });
  const routed = R.route(routes, boxes),
    labels = R.labels(routed.edges, routed.obstacles, routed.wires);
  const allBoxes = [
    ...boxes,
    ...labels.map((n) =>
      G.rect(n.position.x, n.position.y, n.data.width + 8, n.data.height + 8),
    ),
    ...routed.edges.flatMap((e) => e.points.map((p) => G.rect(p.x, p.y, 0, 0))),
  ];
  const bounds = G.union(allBoxes),
    metrics = R.metrics(routed.edges, boxes, labels);
  return { nodes, edges: routed.edges, labels, boxes, bounds, metrics };
}
// Deterministic sweep compaction. Reject any pass whose routes cannot be validated.
function compact(scene, axis) {
  const other = axis === "x" ? "y" : "x",
    lo = axis + "1",
    hi = axis + "2";
  const boxes = scene.boxes
    .map((b) => ({ ...b }))
    .sort((a, b) => a[lo] - b[lo] || a.id.localeCompare(b.id));
  const shifts = new Map(),
    placed = [];
  for (const box of boxes) {
    let lower = 0;
    for (const prev of placed)
      if (
        prev[other + "1"] < box[other + "2"] + 12 &&
        prev[other + "2"] > box[other + "1"] - 12
      )
        lower = Math.max(lower, prev[hi] + 20);
    const delta = Math.min(0, lower - box[lo]);
    box[lo] += delta;
    box[hi] += delta;
    shifts.set(box.id, {
      x: axis === "x" ? delta : 0,
      y: axis === "y" ? delta : 0,
    });
    placed.push(box);
  }
  const shift = (p, id) => ({
    x: p.x + shifts.get(id).x,
    y: p.y + shifts.get(id).y,
  });
  const nodes = scene.nodes.map((n) => ({
    ...n,
    position: shift(n.position, n.data.bodyId || n.id),
  }));
  const input = scene.edges.map((e) => ({
    ...e,
    points: [
      shift(e.points[0], e.source),
      shift(e.escapeStart, e.source),
      ...e.points.slice(1, -1),
      shift(e.escapeEnd, e.target),
      shift(e.points.at(-1), e.target),
    ],
  }));
  const routed = R.route(input, boxes),
    labels = R.labels(routed.edges, routed.obstacles, routed.wires);
  const bounds = G.union([
    ...boxes,
    ...labels.map((n) =>
      G.rect(n.position.x, n.position.y, n.data.width + 8, n.data.height + 8),
    ),
    ...routed.edges.flatMap((e) => e.points.map((p) => G.rect(p.x, p.y, 0, 0))),
  ]);
  return {
    nodes,
    edges: routed.edges,
    labels,
    boxes,
    bounds,
    metrics: R.metrics(routed.edges, boxes, labels),
  };
}
// Search individual body orientations and nearby free positions using routed cost.
function detourBodies(scene) {
  const scores = new Map(
    scene.nodes.filter((n) => n.data.variants).map((n) => [n.id, 0]),
  );
  for (const e of scene.edges) {
    const length = e.points
      .slice(1)
      .reduce(
        (sum, p, i) =>
          sum + Math.abs(p.x - e.points[i].x) + Math.abs(p.y - e.points[i].y),
        0,
      );
    const detour =
      length -
      Math.abs(e.points[0].x - e.points.at(-1).x) -
      Math.abs(e.points[0].y - e.points.at(-1).y) +
      12 * Math.max(0, e.points.length - 2);
    for (const id of new Set([e.source, e.target]))
      if (scores.has(id)) scores.set(id, scores.get(id) + detour);
  }
  return [...scores]
    .map(([id, score]) => ({ id, score }))
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
}
function optimizeLocal(scene, budget, options = {}) {
  scene.optimizationLimits = layoutLimits(scene);
  const previous = scene.localOptimization;
  const ceiling = scene.optimizationLimits.area;
  const before = scene.metrics;
  const stats = {
    rotations: 0,
    moves: 0,
    candidates: 0,
    accepted: 0,
    ...previous,
    rejected: {
      collision: 0,
      area: 0,
      bends: 0,
      overlap: 0,
      noImprovement: 0,
      audit: 0,
      routing: 0,
      length: 0,
      crossings: 0,
      ...previous?.rejected,
    },
  };
  for (
    let round = 0;
    round < (options.rounds ?? 2) && budget.remaining;
    round++
  ) {
    let changed = false;
    const bodies = options.id ? [{ id: options.id }] : detourBodies(scene);
    for (const { id } of bodies) {
      if (!budget.remaining) break;
      const body = scene.nodes.find((n) => n.id === id);
      const affected = scene.edges.filter(
        (e) => e.source === id || e.target === id,
      );
      if (!affected.length) continue;
      const others = scene.boxes.filter((b) => b.id !== id);
      const candidates = [];
      for (const variant of body.data.variants) {
        const b = variant.box;
        const proposals = [body.position];
        for (const e of affected) {
          const front = e.source === id;
          const pin = front ? e.sourcePin : e.targetPin;
          const i = body.data.pins.findIndex((p) => "pin:" + p === pin);
          if (i < 0) continue;
          const offset = variant.positions[i],
            q = front ? e.points.at(-1) : e.points[0];
          const sx = Math.sign(offset.x),
            sy = Math.sign(offset.y);
          const neighbor = others.find(
            (o) => o.id === (front ? e.target : e.source),
          );
          if (neighbor)
            proposals.push({
              x:
                sx > 0
                  ? neighbor.x1 - b.x2 - 16
                  : sx < 0
                    ? neighbor.x2 - b.x1 + 16
                    : q.x,
              y:
                sy > 0
                  ? neighbor.y1 - b.y2 - 16
                  : sy < 0
                    ? neighbor.y2 - b.y1 + 16
                    : q.y,
            });
          proposals.push(
            { x: q.x - offset.x - sx * 48, y: q.y - offset.y - sy * 48 },
            { x: body.position.x, y: q.y - offset.y },
            { x: q.x - offset.x, y: body.position.y },
          );
          // Project the active pin onto nearby segments of its network trunk.
          for (const trunk of scene.edges
            .filter((t) => t.net === e.net && t.id !== e.id)
            .slice(0, 4)) {
            const anchor = {
              x: body.position.x + offset.x,
              y: body.position.y + offset.y,
            };
            const projected = trunk.points.slice(1).map((end, i) => {
              const start = trunk.points[i];
              return {
                x: Math.max(
                  Math.min(start.x, end.x),
                  Math.min(anchor.x, Math.max(start.x, end.x)),
                ),
                y: Math.max(
                  Math.min(start.y, end.y),
                  Math.min(anchor.y, Math.max(start.y, end.y)),
                ),
              };
            });
            const distance = (p) =>
              Math.abs(p.x - anchor.x) + Math.abs(p.y - anchor.y);
            const p = projected.sort((a, b) => distance(a) - distance(b))[0];
            proposals.push({
              x: p.x - offset.x - sx * 48,
              y: p.y - offset.y - sy * 48,
            });
          }
        }
        // If alignment hits a neighbor, also try the nearest free boundary.
        for (const p of proposals.slice(0, 9)) {
          const box = {
            x1: p.x + b.x1 - 8,
            y1: p.y + b.y1 - 8,
            x2: p.x + b.x2 + 8,
            y2: p.y + b.y2 + 8,
          };
          const obstacle = others.find((o) => R.rectOverlap(box, o));
          if (obstacle)
            proposals.push(
              { x: obstacle.x1 - b.x2 - 16, y: p.y },
              { x: obstacle.x2 - b.x1 + 16, y: p.y },
              { x: p.x, y: obstacle.y1 - b.y2 - 16 },
              { x: p.x, y: obstacle.y2 - b.y1 + 16 },
            );
        }
        const angleCandidates = [];
        const seen = new Set();
        for (const raw of proposals) {
          const p =
            raw === body.position
              ? { ...raw }
              : {
                  x: Math.round(raw.x / 8) * 8,
                  y: Math.round(raw.y / 8) * 8,
                };
          const key = p.x + ":" + p.y;
          if (seen.has(key)) continue;
          seen.add(key);
          const box = {
            id,
            x1: p.x + b.x1 - 8,
            y1: p.y + b.y1 - 8,
            x2: p.x + b.x2 + 8,
            y2: p.y + b.y2 + 8,
          };
          if (others.some((o) => R.rectOverlap(box, o))) {
            stats.rejected.collision++;
            continue;
          }
          let score = 0;
          for (const e of affected) {
            const front = e.source === id,
              pin = front ? e.sourcePin : e.targetPin;
            const i = body.data.pins.findIndex((v) => "pin:" + v === pin);
            const off = variant.positions[i],
              q = front ? e.points.at(-1) : e.points[0];
            const a = { x: p.x + off.x, y: p.y + off.y };
            const escape = {
              x: off.x < 0 ? box.x1 : off.x > 0 ? box.x2 : a.x,
              y: off.y < 0 ? box.y1 : off.y > 0 ? box.y2 : a.y,
            };
            score +=
              Math.abs(a.x - escape.x) +
              Math.abs(a.y - escape.y) +
              Math.abs(q.x - escape.x) +
              Math.abs(q.y - escape.y);
          }
          angleCandidates.push({ variant, p, box, score });
        }
        const stationary = angleCandidates.find(
          (c) => c.p.x === body.position.x && c.p.y === body.position.y,
        );
        if (stationary && variant.angle !== body.data.angle)
          candidates.push({ ...stationary, stationary: true });
        const mobile = angleCandidates
          .filter((c) => c.p.x !== body.position.x || c.p.y !== body.position.y)
          .sort(
            (a, b) => a.score - b.score || a.p.x - b.p.x || a.p.y - b.p.y,
          )[0];
        if (mobile) candidates.push(mobile);
      }
      candidates.sort(
        (a, b) =>
          Number(!!b.stationary) - Number(!!a.stationary) ||
          a.score - b.score ||
          a.variant.angle - b.variant.angle ||
          a.p.x - b.p.x ||
          a.p.y - b.p.y,
      );
      let best = scene;
      const finalists = candidates.slice(0, 8);
      for (const c of finalists) {
        if (!budget.remaining) break;
        budget.remaining--;
        stats.candidates++;
        try {
          const nodes = scene.nodes.map((n) =>
            n.id === id || n.data.bodyId === id
              ? { ...n, data: { ...n.data }, position: { ...n.position } }
              : n,
          );
          const map = new Map(nodes.map((n) => [n.id, n])),
            moved = map.get(id);
          moved.position = c.p;
          G.applyVariant(moved, c.variant, map);
          for (const pin of moved.data.pins) {
            const t = map.get("pin:" + pin);
            t.position = {
              x: c.p.x + t.data.offsetX,
              y: c.p.y + t.data.offsetY,
            };
          }
          const boxes = [...others, c.box];
          const input = scene.edges.map((e) => {
            if (e.source !== id && e.target !== id)
              return { ...e, points: e.validationPoints };
            const endpoints = [
              [e.sourcePin, e.source, e.sourceOffset, true],
              [e.targetPin, e.target, e.targetOffset, false],
            ].map(([pin, owner, offset, front]) => {
              const n = map.get(pin),
                p = {
                  x: n.position.x + (offset?.x || 0),
                  y: n.position.y + (offset?.y || 0),
                };
              if (owner !== id)
                return { p, s: front ? e.escapeStart : e.escapeEnd };
              const side = n.data.side;
              return {
                p,
                s: {
                  x: side === "W" ? c.box.x1 : side === "E" ? c.box.x2 : p.x,
                  y: side === "N" ? c.box.y1 : side === "S" ? c.box.y2 : p.y,
                },
              };
            });
            const [a, b] = endpoints;
            return {
              ...e,
              points: [a.p, a.s, { x: a.s.x, y: b.s.y }, b.s, b.p],
            };
          });
          const routed = R.route(input, boxes, { preferBends: true }),
            labels = R.labels(routed.edges, routed.obstacles, routed.wires);
          const metrics = R.metrics(routed.edges, boxes, labels);
          const reason = rejectLayout(
            metrics,
            best.metrics,
            scene.optimizationLimits,
          );
          if (reason) {
            stats.rejected[reason]++;
            continue;
          }
          const audit = R.audit(routed.edges, boxes, labels);
          if (audit.boxOverlaps || audit.obstacleViolations) {
            stats.rejected.audit++;
            continue;
          }
          const bounds = G.union([
            ...boxes,
            ...labels.map((n) =>
              G.rect(
                n.position.x,
                n.position.y,
                n.data.width + 8,
                n.data.height + 8,
              ),
            ),
            ...routed.edges.flatMap((e) =>
              e.points.map((p) => G.rect(p.x, p.y, 0, 0)),
            ),
          ]);
          best = {
            ...scene,
            nodes,
            edges: routed.edges,
            labels,
            boxes,
            bounds,
            metrics,
          };
        } catch (e) {
          stats.rejected.routing++;
          /* A failed candidate leaves the accepted scene intact. */
        }
      }
      if (best !== scene) {
        stats.accepted++;
        const moved = best.nodes.find((n) => n.id === id);
        if (moved.data.angle !== body.data.angle) stats.rotations++;
        if (
          moved.position.x !== body.position.x ||
          moved.position.y !== body.position.y
        )
          stats.moves++;
        scene = best;
        changed = true;
      }
    }
    if (!changed) break;
  }
  scene.localOptimization = {
    ...stats,
    areaCeiling: ceiling,
    wireLengthCeiling: scene.optimizationLimits.wireLength,
    beforeArea: previous?.beforeArea ?? before.area,
    afterArea: scene.metrics.area,
    beforeWireLength: previous?.beforeWireLength ?? before.wireLength,
    afterWireLength: scene.metrics.wireLength,
    beforeBends: previous?.beforeBends ?? before.bends,
    afterBends: scene.metrics.bends,
    budgetExhausted: budget.remaining === 0,
  };
  return scene;
}

function optimizeScenes(scenes, budget) {
  scenes.forEach((scene, i) => {
    scenes[i] = optimizeLocal(scene, budget, { rounds: 0 });
  });
  for (let round = 0; round < 2 && budget.remaining; round++) {
    const ordered = scenes
      .flatMap((s, index) => detourBodies(s).map((b) => ({ ...b, index })))
      .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    let changed = false;
    for (const { index, id } of ordered) {
      if (!budget.remaining) break;
      const before = scenes[index];
      scenes[index] = optimizeLocal(before, budget, { id, rounds: 1 });
      changed ||= before !== scenes[index];
    }
    if (!changed) break;
  }
  scenes.forEach((scene) => {
    scene.localOptimization.budgetExhausted = budget.remaining === 0;
  });
}

// A candidate owns all its moved nodes. Failed routing cannot mutate the scene.
function jointCandidate(scene, shifts, portNodes) {
  const nodes = scene.nodes.map((n) => {
    const delta = shifts.get(n.data.bodyId || n.id) || { x: 0, y: 0 };
    return {
      ...n,
      data: { ...n.data },
      position: { x: n.position.x + delta.x, y: n.position.y + delta.y },
    };
  });
  const map = new Map(nodes.map((n) => [n.id, n]));
  const boxes = scene.boxes.map((b) => ({
    ...b,
    ...G.move(b, shifts.get(b.id) || { x: 0, y: 0 }),
  }));
  const boxMap = new Map(boxes.map((b) => [b.id, b]));
  const index = new R.Index();
  for (const box of boxes) {
    if (index.query(box).some((b) => R.rectOverlap(b, box)))
      throw new Error("collision");
    index.add(box);
  }
  const input = scene.edges.map((e) => {
    if (!portNodes.has(e.source) && !portNodes.has(e.target))
      return { ...e, points: e.validationPoints };
    const endpoints = [
      [e.sourcePin, e.source, e.sourceOffset, true],
      [e.targetPin, e.target, e.targetOffset, false],
    ].map(([pin, owner, offset, front]) => {
      const node = map.get(pin),
        p = {
          x: node.position.x + (offset?.x || 0),
          y: node.position.y + (offset?.y || 0),
        };
      const delta = shifts.get(owner) || { x: 0, y: 0 };
      const old = front ? e.escapeStart : e.escapeEnd;
      // Module ports keep their separate per-net offsets and original side.
      const choices =
        node.data.layoutKind === "fixed" && !node.data.bodyId
          ? [{ point: { x: old.x + delta.x, y: old.y + delta.y } }]
          : escapeChoices(node, boxMap.get(owner), p);
      return { p, choices };
    });
    const [a, b] = endpoints;
    const pairs = a.choices
      .flatMap((s) =>
        b.choices.map((t) => {
          const points = [
            a.p,
            s.point,
            { x: s.point.x, y: t.point.y },
            t.point,
            b.p,
          ];
          const score = R.metrics(
            [{ ...e, points: G.simplify(points) }],
            [],
            [],
          );
          return { points, score };
        }),
      )
      .sort(
        (a, b) =>
          a.score.bends - b.score.bends ||
          a.score.wireLength - b.score.wireLength,
      );
    let best;
    for (const pair of pairs.slice(0, 3)) {
      try {
        const routed = R.route([{ ...e, points: pair.points }], boxes, {
          preferBends: true,
        }).edges[0];
        const score = R.metrics([routed], [], []);
        if (!best || layoutBetter(score, best.score))
          best = { edge: routed, score };
      } catch (_) {
        /* Try another geometrically legal escape. */
      }
    }
    if (!best) throw new Error("routing");
    return { ...best.edge, points: best.edge.validationPoints };
  });
  const routed = R.route(input, boxes, { preferBends: true });
  const labels = R.labels(routed.edges, routed.obstacles, routed.wires);
  const metrics = R.metrics(routed.edges, boxes, labels);
  const audit = R.audit(routed.edges, boxes, labels);
  if (audit.obstacleViolations || audit.boxOverlaps) throw new Error("audit");
  const bounds = G.union([
    ...boxes,
    ...labels.map((n) =>
      G.rect(n.position.x, n.position.y, n.data.width + 8, n.data.height + 8),
    ),
    ...routed.edges.flatMap((e) => e.points.map((p) => G.rect(p.x, p.y, 0, 0))),
  ]);
  return {
    ...scene,
    nodes,
    boxes,
    edges: routed.edges,
    labels,
    metrics,
    bounds,
  };
}
function jointGroups(scene) {
  const movable = new Set(
    scene.nodes
      .filter(
        (n) =>
          !n.data.bodyId &&
          (n.data.variants || ["pin", "net"].includes(n.data.layoutKind)),
      )
      .map((n) => n.id),
  );
  const adjacent = new Map([...movable].map((id) => [id, []]));
  for (const e of scene.edges) {
    adjacent.get(e.source)?.push({ id: e.target, edge: e });
    adjacent.get(e.target)?.push({ id: e.source, edge: e });
  }
  return [...movable]
    .map((id) => {
      const ids = [id];
      // A two-hop neighborhood includes the endpoints behind a net junction.
      for (let i = 0; i < Math.min(2, ids.length) && ids.length < 6; i++)
        for (const neighbor of adjacent.get(ids[i]) || [])
          if (
            movable.has(neighbor.id) &&
            !ids.includes(neighbor.id) &&
            ids.length < 6
          )
            ids.push(neighbor.id);
      const edges = scene.edges.filter(
        (e) => ids.includes(e.source) || ids.includes(e.target),
      );
      const m = R.metrics(edges, [], []);
      return { id, ids, score: m.bends * 100 + m.alignmentDeviation };
    })
    .filter((g) => g.score > 0)
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
}
function jointProposals(scene, group) {
  const byId = new Map(scene.nodes.map((n) => [n.id, n]));
  const boxes = new Map(scene.boxes.map((b) => [b.id, b]));
  const anchor = (id) => {
    const e = scene.edges.find(
      (e) =>
        (e.source === id && group.ids.includes(e.target)) ||
        (e.target === id && group.ids.includes(e.source)),
    );
    return e
      ? e.source === id
        ? e.points[0]
        : e.points.at(-1)
      : byId.get(id).position;
  };
  const proposals = [new Map()];
  for (const axis of ["y", "x"]) {
    const other = axis === "x" ? "y" : "x";
    const coordinates = group.ids
      .map((id) => anchor(id)[axis])
      .sort((a, b) => a - b);
    const targets = [
      anchor(group.id)[axis],
      coordinates[Math.floor(coordinates.length / 2)],
    ];
    for (const target of new Set(targets)) {
      const shifts = new Map(
        group.ids.map((id) => [
          id,
          { x: 0, y: 0, [axis]: target - anchor(id)[axis] },
        ]),
      );
      proposals.push(shifts);
      // Spread along the trunk only when simultaneous alignment would overlap.
      const spread = new Map([...shifts].map(([id, d]) => [id, { ...d }]));
      const ordered = [...group.ids].sort(
        (a, b) => anchor(a)[other] - anchor(b)[other] || a.localeCompare(b),
      );
      let last = -Infinity;
      for (const id of ordered) {
        const box = boxes.get(id),
          delta = spread.get(id);
        delta[other] = Math.max(0, last + 16 - box[other + "1"]);
        last = box[other + "2"] + delta[other];
      }
      proposals.push(spread);
    }
    for (const e of scene.edges
      .filter((e) => e.source === group.id || e.target === group.id)
      .slice(0, 4)) {
      const p = e.source === group.id ? e.points[0] : e.points.at(-1);
      const q = e.source === group.id ? e.points.at(-1) : e.points[0];
      proposals.push(
        new Map([[group.id, { x: 0, y: 0, [axis]: q[axis] - p[axis] }]]),
      );
    }
  }
  const seen = new Set();
  return proposals.filter((shifts) => {
    const key = JSON.stringify(
      [...shifts]
        .filter(([, d]) => d.x || d.y)
        .sort(([a], [b]) => a.localeCompare(b)),
    );
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
function optimizeJoint(scenes, budget) {
  scenes.forEach((scene) => {
    scene.optimizationLimits = layoutLimits(scene);
    scene.jointOptimization = {
      candidates: 0,
      accepted: 0,
      movedNodes: 0,
      maxMovedTogether: 0,
      exitChanges: 0,
      beforeBends: scene.metrics.bends,
      beforeAlignment: scene.metrics.alignmentDeviation,
      beforeWireLength: scene.metrics.wireLength,
      rejected: {},
      limits: { ...scene.optimizationLimits },
    };
  });
  for (let round = 0; round < 2 && budget.remaining; round++) {
    const groups = scenes
      .flatMap((scene, index) =>
        jointGroups(scene).map((group) => ({ ...group, index })),
      )
      .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
    let changed = false;
    for (const group of groups) {
      if (!budget.remaining) break;
      const scene = scenes[group.index],
        stats = scene.jointOptimization;
      let best = scene;
      for (const shifts of jointProposals(scene, group)) {
        if (!budget.remaining) break;
        budget.remaining--;
        stats.candidates++;
        try {
          const candidate = jointCandidate(scene, shifts, new Set(group.ids));
          const reason = rejectLayout(
            candidate.metrics,
            best.metrics,
            scene.optimizationLimits,
          );
          if (reason) {
            stats.rejected[reason] = (stats.rejected[reason] || 0) + 1;
            continue;
          }
          best = candidate;
        } catch (error) {
          const reason = ["collision", "audit"].includes(error.message)
            ? error.message
            : "routing";
          stats.rejected[reason] = (stats.rejected[reason] || 0) + 1;
        }
      }
      if (best !== scene) {
        stats.accepted++;
        const old = new Map(scene.nodes.map((n) => [n.id, n]));
        const movedTogether = best.nodes.filter(
          (n) =>
            !n.data.bodyId &&
            (n.position.x !== old.get(n.id).position.x ||
              n.position.y !== old.get(n.id).position.y),
        ).length;
        stats.movedNodes += movedTogether;
        stats.maxMovedTogether = Math.max(
          stats.maxMovedTogether,
          movedTogether,
        );
        const direction = (p, q) => (Math.abs(p.x - q.x) < 0.001 ? "y" : "x");
        best.edges.forEach((e, i) => {
          const previous = scene.edges[i];
          stats.exitChanges += Number(
            direction(e.points[0], e.escapeStart) !==
              direction(previous.points[0], previous.escapeStart),
          );
          stats.exitChanges += Number(
            direction(e.points.at(-1), e.escapeEnd) !==
              direction(previous.points.at(-1), previous.escapeEnd),
          );
        });
        scenes[group.index] = best;
        changed = true;
      }
    }
    if (!changed) break;
  }
  scenes.forEach((scene) =>
    Object.assign(scene.jointOptimization, {
      afterBends: scene.metrics.bends,
      afterAlignment: scene.metrics.alignmentDeviation,
      afterWireLength: scene.metrics.wireLength,
      budgetExhausted: budget.remaining === 0,
    }),
  );
}

self.onmessage = async ({ data }) => {
  const started = performance.now();
  try {
    if (data.mode === "route") {
      const boxes = data.nodes
        .filter((n) => !n.data.bodyId && !n.classes.includes("wire-label"))
        .map((n) => ({ id: n.data.id, ...G.move(n.data.box, n.position) }));
      const expanded = boxes.map((r) => ({
        ...r,
        x1: r.x1 - 8,
        x2: r.x2 + 8,
        y1: r.y1 - 8,
        y2: r.y2 + 8,
      }));
      const collisionIndex = new R.Index();
      for (const box of expanded) {
        if (
          collisionIndex.query(box).some((other) => R.rectOverlap(box, other))
        )
          throw new Error("移动后元件或文字重叠");
        collisionIndex.add(box);
      }
      const byId = new Map(data.nodes.map((n) => [n.data.id, n]));
      const routes = data.edges.map((e) => {
        const endpoint = (id, offset) => {
          const n = byId.get(id);
          return {
            ...n,
            position: {
              x: n.position.x + (offset?.x || 0),
              y: n.position.y + (offset?.y || 0),
            },
          };
        };
        const a = endpoint(e.data.source, e.data.sourceOffset),
          b = endpoint(e.data.target, e.data.targetOffset);
        const escape = (n, other) => {
          const owner = byId.get(n.data.bodyId || n.data.id),
            box = expanded.find((r) => r.id === owner.data.id),
            p = n.position;
          const side = n.data.side || (other.position.x >= p.x ? "E" : "W");
          return {
            x: side === "W" ? box.x1 : side === "E" ? box.x2 : p.x,
            y: side === "N" ? box.y1 : side === "S" ? box.y2 : p.y,
          };
        };
        const s = escape(a, b),
          t = escape(b, a);
        return {
          id: e.data.id,
          sourceOffset: e.data.sourceOffset,
          targetOffset: e.data.targetOffset,
          net: e.data.netKey,
          source: a.data.bodyId || a.data.id,
          target: b.data.bodyId || b.data.id,
          label: e.data.label,
          text: e.data.text,
          points:
            e.data.validationPoints &&
            Math.abs(e.data.validationPoints[0].x - a.position.x) < 0.001 &&
            Math.abs(e.data.validationPoints[0].y - a.position.y) < 0.001 &&
            Math.abs(e.data.validationPoints.at(-1).x - b.position.x) < 0.001 &&
            Math.abs(e.data.validationPoints.at(-1).y - b.position.y) < 0.001
              ? e.data.validationPoints
              : [a.position, s, { x: s.x, y: t.y }, t, b.position],
        };
      });
      const routed = R.route(routes, expanded),
        labels = R.labels(routed.edges, routed.obstacles, routed.wires);
      const quality = R.audit(routed.edges, expanded, labels);
      if (quality.obstacleViolations || quality.boxOverlaps)
        throw new Error("移动布线质量检查失败");
      self.postMessage({
        edges: routed.edges,
        labels,
        metrics: {
          ...R.metrics(routed.edges, expanded, labels),
          ...quality,
          routingMs: performance.now() - started,
        },
      });
      return;
    }
    const terminals = new Map(
      data.nodes.filter((n) => n.data.bodyId).map((n) => [n.data.id, n.data]),
    );
    const byId = new Map(
      data.nodes.filter((n) => !n.data.bodyId).map((n) => [n.data.id, n]),
    );
    const edges = data.edges.map((e) => ({
      ...e,
      data: {
        ...e.data,
        originalSource: e.data.source,
        originalTarget: e.data.target,
        source: terminals.get(e.data.source)?.bodyId || e.data.source,
        target: terminals.get(e.data.target)?.bodyId || e.data.target,
      },
    }));
    const adjacency = new Map([...byId.keys()].map((id) => [id, []]));
    for (const e of edges) {
      adjacency.get(e.data.source).push(e);
      adjacency.get(e.data.target).push(e);
    }
    const visited = new Set(),
      scenes = [],
      cache = new Map();
    const order = [...byId.keys()].sort();
    const root = terminals.get(data.root)?.bodyId || data.root;
    if (byId.has(root)) order.unshift(root);
    let failures = 0;
    const candidateMetrics = [];
    const localBudget = { remaining: 512 };
    for (const seed of order) {
      if (visited.has(seed)) continue;
      visited.add(seed);
      const ids = [seed],
        es = new Map(),
        depths = new Map([[seed, 0]]);
      for (let i = 0; i < ids.length; i++)
        for (const e of adjacency.get(ids[i])) {
          es.set(e.data.id, e);
          const other =
            e.data.source === ids[i] ? e.data.target : e.data.source;
          if (!visited.has(other)) {
            visited.add(other);
            ids.push(other);
            depths.set(other, depths.get(ids[i]) + 1);
          }
        }
      let best = null,
        lastError;
      for (const [direction, mixed] of [
        ["RIGHT", false],
        ["DOWN", false],
        ["RIGHT", true],
        ["DOWN", true],
      ]) {
        // Repeated tiny blocks need no extra orientation search.
        if (
          best &&
          (ids.length < 3 ||
            (!ids.some((id) => byId.get(id).data.variants) && mixed))
        )
          continue;
        try {
          const c = await candidate(
            ids,
            [...es.values()],
            byId,
            terminals,
            depths,
            direction,
            mixed,
            cache,
          );
          if (ids.length > 3)
            candidateMetrics.push({
              count: ids.length,
              direction,
              mixed,
              ...c.metrics,
            });
          if (
            !best ||
            c.metrics.area < best.metrics.area * 0.9 ||
            (c.metrics.area <= best.metrics.area * 1.1 &&
              c.metrics.wireLength < best.metrics.wireLength)
          )
            best = c;
        } catch (e) {
          lastError = e;
          if (ids.length > 3)
            candidateMetrics.push({
              count: ids.length,
              direction,
              mixed,
              error: e.message,
            });
          failures++;
        }
      }
      if (!best) throw lastError;
      if (ids.length >= 3 && ids.length <= 32)
        for (const axis of ["x", "y"]) {
          try {
            const c = compact(best, axis);
            if (
              c.metrics.area < best.metrics.area &&
              c.metrics.wireLength <= best.metrics.wireLength
            )
              best = c;
          } catch (e) {
            failures++;
          }
        }
      scenes.push(best);
    }
    optimizeScenes(scenes, localBudget);
    const jointBudget = { remaining: 256 };
    optimizeJoint(scenes, jointBudget);
    const packingStart = performance.now(),
      packed = pack(
        scenes,
        (data.viewport?.width || 800) / (data.viewport?.height || 600),
      );
    const nodes = [],
      resultEdges = [],
      labels = [],
      boxes = [];
    scenes.forEach((s, i) => {
      const p = packed.get(i),
        shift = { x: p.x - s.bounds.x1, y: p.y - s.bounds.y1 };
      const translate = (p) => ({ x: p.x + shift.x, y: p.y + shift.y });
      nodes.push(
        ...s.nodes.map((n) => ({ ...n, position: translate(n.position) })),
      );
      resultEdges.push(
        ...s.edges.map((e) => ({
          ...e,
          points: e.points.map(translate),
          validationPoints: e.validationPoints.map(translate),
          escapeStart: translate(e.escapeStart),
          escapeEnd: translate(e.escapeEnd),
        })),
      );
      labels.push(
        ...s.labels.map((n) => ({ ...n, position: translate(n.position) })),
      );
      boxes.push(...s.boxes.map((r) => ({ ...r, ...G.move(r, shift) })));
    });
    const packingMs = performance.now() - packingStart;
    const computed = new Map(nodes.map((n) => [n.id, n.data]));
    const positions = new Map(nodes.map((n) => [n.id, n.position])),
      originalEdges = new Map(data.edges.map((e) => [e.data.id, e.data]));
    let endpointViolations = 0;
    for (const e of resultEdges) {
      const original = originalEdges.get(e.id);
      for (const [id, offset, point] of [
        [original.source, e.sourceOffset, e.points[0]],
        [original.target, e.targetOffset, e.points.at(-1)],
      ]) {
        const p = positions.get(id);
        if (
          !p ||
          Math.abs(p.x + (offset?.x || 0) - point.x) > 0.1 ||
          Math.abs(p.y + (offset?.y || 0) - point.y) > 0.1
        )
          endpointViolations++;
      }
    }
    const metrics = {
      ...R.metrics(resultEdges, boxes, labels),
      ...R.audit(resultEdges, boxes, labels),
      endpointViolations,
    };
    if (
      metrics.obstacleViolations ||
      metrics.boxOverlaps ||
      metrics.foreignOverlap ||
      endpointViolations
    )
      throw new Error("最终布局质量检查失败");
    self.postMessage({
      nodes,
      edges: resultEdges,
      labels,
      modelNodes: data.nodes.map((n) => ({
        ...n,
        data: computed.get(n.data.id),
      })),
      metrics: {
        ...metrics,
        layout: "elk-pin-layered",
        layoutMs: performance.now() - started,
        packingMs,
        nodes: nodes.length,
        edges: resultEdges.length,
        components: scenes.length,
        rejectedCandidates: failures,
        candidateMetrics,
        localOptimization: scenes.map((s) => s.localOptimization),
        jointOptimization: scenes.map((s) => s.jointOptimization),
        jointBudget: {
          limit: 256,
          remaining: jointBudget.remaining,
          exhausted: jointBudget.remaining === 0,
        },
        localBudget: {
          limit: 512,
          remaining: localBudget.remaining,
          exhausted: localBudget.remaining === 0,
        },
      },
    });
  } catch (e) {
    self.postMessage({ error: e.message });
  }
};
