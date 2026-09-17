import { polarityBox } from "./layout-geometry.js";
/* Native orthogonal routing with explicit physical-pin escape constraints. */
export const directions = {
  W: { x: -1, y: 0 },
  E: { x: 1, y: 0 },
  N: { x: 0, y: -1 },
  S: { x: 0, y: 1 },
};
export function simplify(ps) {
  const out = [];
  for (const p of ps) {
    if (out.length && Math.hypot(p.x - out.at(-1).x, p.y - out.at(-1).y) < 0.01)
      continue;
    while (out.length > 1) {
      const a = out.at(-2),
        b = out.at(-1);
      if (
        (Math.abs(a.x - b.x) < 0.01 && Math.abs(b.x - p.x) < 0.01) ||
        (Math.abs(a.y - b.y) < 0.01 && Math.abs(b.y - p.y) < 0.01)
      )
        out.pop();
      else break;
    }
    if (
      !out.length ||
      Math.hypot(p.x - out.at(-1).x, p.y - out.at(-1).y) > 0.01
    )
      out.push({ x: p.x, y: p.y });
  }
  return out;
}
function point(A, p) {
  return new A.Point(p.x, p.y);
}
export function rectOf(n, pad = 0) {
  return {
    x1: n.x - n.width / 2 - pad,
    y1: n.y - n.height / 2 - pad,
    x2: n.x + n.width / 2 + pad,
    y2: n.y + n.height / 2 + pad,
  };
}
function rectangle(A, r) {
  const a = new A.Point(r.x1, r.y1),
    b = new A.Point(r.x2, r.y2),
    poly = new A.Rectangle(a, b);
  A.destroy(a);
  A.destroy(b);
  return poly;
}
function shape(A, router, r) {
  const poly = rectangle(A, r),
    s = new A.ShapeRef(router, poly);
  A.destroy(poly);
  return s;
}
export function sceneObstacles(scene) {
  const result = [];
  for (const n of scene.nodes) {
    const polarity = polarityBox(n);
    if (polarity)
      result.push({ ...polarity, id: n.id + ":polarity", owner: n.id });
    if (n.classes.includes("part") || n.classes.includes("module"))
      result.push({ ...rectOf(n), id: n.id, owner: n.id });
    // Keep text separate from a symbol's connection point. Its own incoming
    // connector must not be allowed to run through the whole text rectangle.
    if (
      n.labelBox &&
      (n.compactLabel ||
        (!n.classes.includes("pin") && !n.classes.includes("port")))
    )
      result.push({
        ...n.labelBox,
        id: n.id + ":label",
        owner: n.data.owner || n.id,
      });
    if (n.classes.includes("rail")) {
      // Reserve the outward half of the symbol, leaving its anchor accessible.
      const d = directions[n.direction || "E"];
      const r = rectOf(n);
      const gap = 2;
      if (d.x > 0) r.x1 = n.x + gap;
      else if (d.x < 0) r.x2 = n.x - gap;
      else if (d.y > 0) r.y1 = n.y + gap;
      else r.y2 = n.y - gap;
      result.push({ ...r, id: n.id + ":symbol", owner: n.data.owner });
    }
  }
  return result;
}
export function normalizeTerminals(scene) {
  for (const n of scene.nodes.filter(
    (n) => n.classes.includes("net") && n.labelBox,
  )) {
    const b = n.labelBox,
      w = b.w ?? b.x2 - b.x1,
      h = b.h ?? b.y2 - b.y1;
    const extra = n.labelOffset || 0;
    const vertical = n.direction === "N" || n.direction === "S";
    n.labelBox = vertical
      ? {
          x1: n.x + 24 + extra,
          x2: n.x + 24 + extra + w,
          y1: n.y - h / 2,
          y2: n.y + h / 2,
          w,
          h,
        }
      : {
          x1: n.x - w / 2,
          x2: n.x + w / 2,
          y1: n.y + 16 + extra,
          y2: n.y + 16 + extra + h,
          w,
          h,
        };
  }
  return scene;
}
export function nativePathValid(ps, a, b) {
  return (
    ps.length >= 2 &&
    Math.hypot(ps[0].x - a.x, ps[0].y - a.y) <= 0.1 &&
    Math.hypot(ps.at(-1).x - b.x, ps.at(-1).y - b.y) <= 0.1 &&
    ps.every(
      (p, i) =>
        !i ||
        Math.abs(p.x - ps[i - 1].x) <= 0.1 ||
        Math.abs(p.y - ps[i - 1].y) <= 0.1,
    )
  );
}
export class SceneRouter {
  constructor(A, scene, options = {}) {
    const allowed = new Set([
      "segmentPenalty",
      "crossingPenalty",
      "fixedSharedPathPenalty",
      "shapeBufferDistance",
      "idealNudgingDistance",
      "reverseDirectionPenalty",
    ]);
    for (const [name, value] of Object.entries(options))
      if (
        !allowed.has(name) ||
        !Number.isFinite(value) ||
        value < 0 ||
        value > 100000
      )
        throw new Error("Invalid routing option " + name);
    this.A = A;
    this.scene = normalizeTerminals(scene);
    this.router = new A.Router(A.OrthogonalRouting);
    this.endpoints = new Map();
    this.refs = [];
    this.connectors = [];
    this.nodes = new Map(scene.nodes.map((n) => [n.id, n]));
    this.shapes = new Map();
    const r = this.router;
    for (const [name, value] of Object.entries({
      segmentPenalty: 1000,
      crossingPenalty: 200,
      fixedSharedPathPenalty: 100,
      shapeBufferDistance: 14,
      idealNudgingDistance: 12,
      reverseDirectionPenalty: 100,
      ...options,
    }))
      r.setRoutingParameter(A[name], value);
    for (const name of [
      "nudgeOrthogonalTouchingColinearSegments",
      "penaliseOrthogonalSharedPathsAtConnEnds",
    ])
      r.setRoutingOption(A[name], true);
    r.setRoutingOption(A.nudgeOrthogonalSegmentsConnectedToShapes, false);
    // Topology remains application-owned. Never let native code create/delete
    // junctions that this binding cannot enumerate reliably.
    r.setRoutingOption(
      A.improveHyperedgeRoutesMovingAddingAndDeletingJunctions,
      false,
    );
    r.setRoutingOption(A.improveHyperedgeRoutesMovingJunctions, false);
    r.setRoutingOption(A.nudgeSharedPathsWithCommonEndPoint, false);
    for (const obstacle of sceneObstacles(scene)) {
      const s = shape(A, r, obstacle);
      this.shapes.set(obstacle.id, { s, obstacle });
    }
    const ends = new Map();
    for (const n of scene.nodes) {
      if (n.classes.includes("pin") || n.classes.includes("port")) {
        const d = directions[n.direction || (n.data.side < 0 ? "W" : "E")];
        const escape = { x: n.x + d.x * 28, y: n.y + d.y * 28 };
        // A narrow shape reserves the escape stub and gives libavoid a real,
        // direction-constrained pin at its outward end.
        const box = {
          x1: Math.min(n.x, escape.x) - (d.x ? 0 : 1),
          x2: Math.max(n.x, escape.x) + (d.x ? 0 : 1),
          y1: Math.min(n.y, escape.y) - (d.y ? 0 : 1),
          y2: Math.max(n.y, escape.y) + (d.y ? 0 : 1),
        };
        const s = shape(A, r, box),
          flag =
            d.x < 0
              ? A.ConnDirLeft
              : d.x > 0
                ? A.ConnDirRight
                : d.y < 0
                  ? A.ConnDirUp
                  : A.ConnDirDown;
        const pin = new A.ShapeConnectionPin(
          s,
          1,
          escape.x - box.x1,
          escape.y - box.y1,
          false,
          0,
          flag,
        );
        pin.setExclusive(false);
        this.shapes.set(n.id + ":stub", {
          s,
          obstacle: { ...box, id: n.id + ":stub", owner: n.data.owner },
        });
        this.endpoints.set(n.id, escape);
        const end = new A.ConnEnd(s, 1);
        ends.set(n.id, end);
        this.refs.push(end);
      } else if (
        n.classes.includes("net") ||
        n.classes.includes("rail") ||
        n.classes.includes("branch")
      ) {
        let target = { x: n.x, y: n.y };
        this.endpoints.set(n.id, target);
        const p = point(A, target),
          end = new A.ConnEnd(p);
        A.destroy(p);
        ends.set(n.id, end);
        this.refs.push(end);
      }
    }
    for (const w of [...scene.wires].sort(
      (a, b) => a.net.localeCompare(b.net) || a.id.localeCompare(b.id),
    )) {
      if (!ends.has(w.source) || !ends.has(w.target))
        throw new Error("Missing connector endpoint " + w.id);
      const conn = new A.ConnRef(r, ends.get(w.source), ends.get(w.target));
      conn.setRoutingType(A.ConnType_Orthogonal);
      conn.setHateCrossings(true);
      this.connectors.push({ conn, wire: w });
    }
  }
  compute() {
    this.router.processTransaction();
    const wires = this.connectors.map(({ conn, wire }) => {
      const path = conn.displayRoute(),
        ps = [];
      for (let i = 0; i < path.size(); i++) {
        const p = path.get_ps(i);
        ps.push({ x: p.x, y: p.y });
      }
      const a = this.nodes.get(wire.source),
        b = this.nodes.get(wire.target);
      return {
        ...wire,
        failed: !nativePathValid(
          ps,
          this.endpoints.get(a.id) || a,
          this.endpoints.get(b.id) || b,
        ),
        points: simplify([
          { x: a.x, y: a.y },
          ...(this.endpoints.has(a.id) ? [this.endpoints.get(a.id)] : []),
          ...ps,
          ...(this.endpoints.has(b.id) ? [this.endpoints.get(b.id)] : []),
          { x: b.x, y: b.y },
        ]),
      };
    });
    return {
      ...this.scene,
      wires,
    };
  }
  dispose() {
    if (!this.router) return;
    // Router owns connectors, shapes and shape pins. ConnEnd values are owned
    // here; destroy the router before the copied endpoint values.
    this.A.destroy(this.router);
    this.router = null;
    for (const ref of this.refs) this.A.destroy(ref);
    this.refs = [];
    this.connectors = [];
    this.shapes.clear();
  }
}
