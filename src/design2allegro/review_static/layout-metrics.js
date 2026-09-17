import { polarityBox } from "./layout-geometry.js";
/* Runtime routing geometry: no calls to either routing implementation. */
const eps = 0.1;
function key(p) {
  return `${Math.round(p.x * 100) / 100},${Math.round(p.y * 100) / 100}`;
}
export function mergedSegments(wires) {
  const groups = new Map();
  for (const w of wires)
    for (let i = 1; i < w.points.length; i++) {
      const a = w.points[i - 1],
        b = w.points[i],
        horizontal = Math.abs(a.y - b.y) < eps;
      if (Math.abs(a.x - b.x) < eps && Math.abs(a.y - b.y) < eps) continue;
      if (!horizontal && Math.abs(a.x - b.x) > eps) continue;
      const fixed = horizontal ? a.y : a.x,
        k = JSON.stringify([w.net, horizontal, Math.round(fixed * 100) / 100]);
      if (!groups.has(k))
        groups.set(k, { net: w.net, horizontal, fixed, ranges: [] });
      groups
        .get(k)
        .ranges.push([
          Math.min(horizontal ? a.x : a.y, horizontal ? b.x : b.y),
          Math.max(horizontal ? a.x : a.y, horizontal ? b.x : b.y),
        ]);
    }
  const result = [];
  for (const g of groups.values()) {
    const ranges = [];
    for (const r of g.ranges.sort((a, b) => a[0] - b[0])) {
      if (ranges.length && r[0] <= ranges.at(-1)[1] + eps)
        ranges.at(-1)[1] = Math.max(r[1], ranges.at(-1)[1]);
      else ranges.push([...r]);
    }
    for (const [lo, hi] of ranges)
      result.push({
        net: g.net,
        a: g.horizontal ? { x: lo, y: g.fixed } : { x: g.fixed, y: lo },
        b: g.horizontal ? { x: hi, y: g.fixed } : { x: g.fixed, y: hi },
      });
  }
  return result;
}
function hit(a, b, r) {
  let lo = 0,
    hi = 1;
  for (const [axis, min, max] of [
    ["x", "x1", "x2"],
    ["y", "y1", "y2"],
  ]) {
    const d = b[axis] - a[axis];
    if (Math.abs(d) < eps) {
      if (!(a[axis] > r[min] + eps && a[axis] < r[max] - eps)) return false;
    } else {
      const t1 = (r[min] + eps - a[axis]) / d,
        t2 = (r[max] - eps - a[axis]) / d;
      lo = Math.max(lo, Math.min(t1, t2));
      hi = Math.min(hi, Math.max(t1, t2));
    }
  }
  return lo < hi;
}
export function measure(scene) {
  const byId = new Map(scene.nodes.map((n) => [n.id, n])),
    segments = mergedSegments(scene.wires);
  const failures = [],
    crossings = new Set(),
    shared = new Set(),
    penetrations = new Set(),
    endpointErrors = [];
  const obstacles = [];
  for (const n of scene.nodes) {
    const polarity = polarityBox(n);
    if (polarity) obstacles.push({ ...polarity, id: n.id + ":polarity" });
    if (n.classes.includes("part") || n.classes.includes("module"))
      obstacles.push({
        id: n.id,
        x1: n.x - n.width / 2,
        y1: n.y - n.height / 2,
        x2: n.x + n.width / 2,
        y2: n.y + n.height / 2,
      });
    if (
      n.labelBox &&
      (n.compactLabel ||
        (!n.classes.includes("pin") && !n.classes.includes("port")))
    )
      obstacles.push({ id: n.id + ":label", ...n.labelBox });
  }
  let missingEndpoints = 0,
    disconnectedNets = 0;
  for (const [net, expected] of Object.entries(scene.expected || {})) {
    const adj = new Map();
    for (const w of scene.wires.filter((w) => w.net === net)) {
      if (!adj.has(w.source)) adj.set(w.source, []);
      if (!adj.has(w.target)) adj.set(w.target, []);
      adj.get(w.source).push(w.target);
      adj.get(w.target).push(w.source);
    }
    missingEndpoints += expected.filter((id) => !adj.has(id)).length;
    // Repeated power/ground symbols connect electrically by canonical net ID.
    // Only join symbols that actually have a wire; never hide a missing lead.
    const labels = scene.nodes.filter(
      (n) =>
        n.classes.includes("rail") && n.data?.netKey === net && adj.has(n.id),
    );
    for (const label of labels.slice(1)) {
      adj.get(labels[0].id).push(label.id);
      adj.get(label.id).push(labels[0].id);
    }
    const seen = new Set(),
      queue = expected.length ? [expected[0]] : [];
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      if (seen.has(id)) continue;
      seen.add(id);
      queue.push(...(adj.get(id) || []).filter((n) => !seen.has(n)));
    }
    if (expected.some((id) => !seen.has(id))) disconnectedNets++;
  }
  let bends = 0;
  const corners = new Set();
  for (const w of scene.wires) {
    const a = byId.get(w.source),
      b = byId.get(w.target),
      ps = w.points;
    if (
      !ps.length ||
      Math.hypot(ps[0].x - a.x, ps[0].y - a.y) > 0.1 ||
      Math.hypot(ps.at(-1).x - b.x, ps.at(-1).y - b.y) > 0.1
    )
      endpointErrors.push(w.id);
    for (let i = 1; i < ps.length; i++)
      if (
        Math.abs(ps[i].x - ps[i - 1].x) > 0.1 &&
        Math.abs(ps[i].y - ps[i - 1].y) > 0.1
      )
        failures.push(w.id);
    for (let i = 1; i < ps.length - 1; i++) {
      const p = ps[i - 1],
        q = ps[i],
        r = ps[i + 1];
      if (
        (Math.abs(p.x - q.x) < eps && Math.abs(q.y - r.y) < eps) ||
        (Math.abs(p.y - q.y) < eps && Math.abs(q.x - r.x) < eps)
      )
        corners.add(w.net + "|" + key(q));
    }
  }
  // A synthetic junction must not hide a bend by splitting one elbow into
  // two connectors. Count turns across degree-two branch endpoints as well.
  for (const n of scene.nodes.filter((n) => n.classes.includes("branch"))) {
    const incident = scene.wires.filter(
      (w) => w.source === n.id || w.target === n.id,
    );
    if (incident.length !== 2) continue;
    const axes = new Set();
    for (const w of incident) {
      const ps = w.source === n.id ? w.points : [...w.points].reverse();
      const p = ps.find((p) => Math.hypot(p.x - n.x, p.y - n.y) > 0.1);
      if (p) axes.add(Math.abs(p.x - n.x) < eps ? "v" : "h");
    }
    if (axes.size === 2) corners.add(n.data.netKey + "|" + key(n));
  }
  bends = corners.size;
  let length = 0;
  for (let i = 0; i < segments.length; i++) {
    const { a, b, net } = segments[i];
    length += Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
    for (const r of obstacles)
      if (hit(a, b, r)) penetrations.add(net + "|" + r.id);
    for (const t of segments.slice(i + 1)) {
      if (t.net === net) continue;
      const c = t.a,
        d = t.b,
        nets = [net, t.net].sort().join("|"),
        h = Math.abs(a.y - b.y) < eps,
        h2 = Math.abs(c.y - d.y) < eps;
      if (h === h2) {
        if (
          (h &&
            Math.abs(a.y - c.y) < eps &&
            Math.min(b.x, d.x) - Math.max(a.x, c.x) > eps) ||
          (!h &&
            Math.abs(a.x - c.x) < eps &&
            Math.min(b.y, d.y) - Math.max(a.y, c.y) > eps)
        )
          shared.add(nets + "|" + key(a) + "|" + key(c));
      } else {
        const v = h ? t : segments[i],
          hor = h ? segments[i] : t;
        if (
          v.a.x > hor.a.x + eps &&
          v.a.x < hor.b.x - eps &&
          hor.a.y > v.a.y + eps &&
          hor.a.y < v.b.y - eps
        )
          crossings.add(nets + "|" + key({ x: v.a.x, y: hor.a.y }));
      }
    }
  }
  const bodies = scene.nodes.filter(
    (n) => n.classes.includes("part") || n.classes.includes("module"),
  );
  let overlaps = 0;
  for (let i = 0; i < bodies.length; i++)
    for (const b of bodies.slice(i + 1)) {
      const a = bodies[i];
      if (
        Math.abs(a.x - b.x) < (a.width + b.width) / 2 - eps &&
        Math.abs(a.y - b.y) < (a.height + b.height) / 2 - eps
      )
        overlaps++;
    }
  const points = [
    ...obstacles.flatMap((r) => [
      { x: r.x1, y: r.y1 },
      { x: r.x2, y: r.y2 },
    ]),
    ...segments.flatMap((s) => [s.a, s.b]),
  ];
  const bounds = {
    x1: Math.min(...points.map((p) => p.x)),
    y1: Math.min(...points.map((p) => p.y)),
    x2: Math.max(...points.map((p) => p.x)),
    y2: Math.max(...points.map((p) => p.y)),
  };
  return {
    crossings: crossings.size,
    length,
    bends,
    area: (bounds.x2 - bounds.x1) * (bounds.y2 - bounds.y1),
    missingEndpoints,
    disconnectedNets,
    failedRoutes: scene.wires.filter((w) => w.failed).length,
    overlaps,
    penetrations: penetrations.size,
    shared: shared.size,
    nonOrthogonal: new Set(failures).size,
    endpointErrors: endpointErrors.length,
    bounds,
    details: {
      penetrations: [...penetrations],
      shared: [...shared],
      failures: [...new Set(failures)],
      endpointErrors,
    },
  };
}
export function usable(m) {
  return [
    "overlaps",
    "penetrations",
    "shared",
    "nonOrthogonal",
    "endpointErrors",
    "missingEndpoints",
    "disconnectedNets",
    "failedRoutes",
  ].every((k) => m[k] === 0);
}
