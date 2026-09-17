import { compactPassives } from "./layout-geometry.js";
/* Bounded topology and placement search using actual routed geometry. */
import {
  makeNetTrees,
  layoutScene,
  optimizePorts,
  shift,
  updateLabels,
} from "./layout-layout.js";
import {
  sceneObstacles,
  directions,
  normalizeTerminals,
} from "./layout-routing.js";
import { measure, usable } from "./layout-metrics.js";
const clone = (x) => structuredClone(x);
const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
export function netRanking(scene) {
  return [...new Set(scene.wires.map((w) => w.net))]
    .map((net) => ({
      net,
      bends: measure({
        ...scene,
        wires: scene.wires.filter((w) => w.net === net),
        expected: {},
      }).bends,
    }))
    .sort((a, b) => b.bends - a.bends || a.net.localeCompare(b.net));
}
export function score(base, m) {
  if (!usable(m)) return [Infinity];
  return [
    (4 * m.crossings) / Math.max(1, base.crossings) +
      (2 * m.bends) / Math.max(1, base.bends) +
      m.length / Math.max(1, base.length) +
      m.area / Math.max(1, base.area),
  ];
}
export function better(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (a[i] !== b[i]) return a[i] < b[i];
  }
  return false;
}
function terminals(scene, net) {
  return (scene.expected[net] || [])
    .map((id) => scene.nodes.find((n) => n.id === id))
    .filter((n) => n && !n.classes.includes("rail"));
}
function escape(n) {
  const d = directions[n.direction];
  return d ? { x: n.x + d.x * 28, y: n.y + d.y * 28 } : { x: n.x, y: n.y };
}
// Change edges before placement, then retain them through layout and routing.
export function topology(scene, mode = "mst", onlyNet = null, offset = 0) {
  scene = clone(scene);
  if (mode === "mst" && !onlyNet) return makeNetTrees(scene);
  const nets = onlyNet ? [onlyNet] : Object.keys(scene.expected).sort();
  for (const net of nets) {
    const ends = terminals(scene, net);
    if (ends.length < 3 || scene.wires.some((w) => w.net === net && w.rail))
      continue;
    scene.nodes = scene.nodes.filter(
      (n) => !(n.classes.includes("branch") && n.data.netKey === net),
    );
    scene.wires = scene.wires.filter((w) => w.net !== net);
    const axis = mode === "horizontal" ? "x" : "y",
      cross = axis === "x" ? "y" : "x";
    const sorted = ends.sort(
      (a, b) => escape(a)[axis] - escape(b)[axis] || a.id.localeCompare(b.id),
    );
    const common = median(sorted.map((n) => escape(n)[cross])) + offset;
    let previous;
    for (const [i, n] of sorted.entries()) {
      const id = "branch:" + JSON.stringify([scene.group, net, i]);
      scene.nodes.push({
        id,
        x: axis === "x" ? escape(n).x : common,
        y: axis === "y" ? escape(n).y : common,
        width: 1,
        height: 1,
        classes: ["branch"],
        data: { netKey: net, label: "", group: scene.group },
        trunk: { axis, offset, terminal: n.id },
      });
      const add = (a, b, suffix) =>
        scene.wires.push({
          id: "joint:" + JSON.stringify([scene.group, net, i, suffix]),
          net,
          source: a,
          target: b,
          rail: false,
          pins:
            a === n.id
              ? n.data.pins ||
                (n.classes.includes("pin") ? [n.id.slice(4)] : [])
              : [],
          points: [],
        });
      add(n.id, id, "lead");
      if (previous) add(previous, id, "trunk");
      previous = id;
    }
  }
  return scene;
}
export function alignBranches(scene) {
  const obstacles = sceneObstacles(scene),
    byId = new Map(scene.nodes.map((n) => [n.id, n]));
  const groups = new Map();
  for (const n of scene.nodes.filter((n) => n.trunk)) {
    if (!groups.has(n.data.netKey)) groups.set(n.data.netKey, []);
    groups.get(n.data.netKey).push(n);
  }
  for (const branches of groups.values()) {
    const { axis, offset } = branches[0].trunk,
      cross = axis === "x" ? "y" : "x";
    const ps = branches.map((n) => escape(byId.get(n.trunk.terminal)));
    const center = median(ps.map((p) => p[cross])) + offset;
    const choices = [
      center,
      ...obstacles.flatMap((o) =>
        cross === "x" ? [o.x1 - 24, o.x2 + 24] : [o.y1 - 24, o.y2 + 24],
      ),
    ].sort((a, b) => Math.abs(a - center) - Math.abs(b - center) || a - b);
    const free = (v) =>
      ps.every(
        (p) =>
          !obstacles.some((o) => {
            const x = axis === "x" ? p.x : v,
              y = axis === "y" ? p.y : v;
            return (
              x > o.x1 - 12 && x < o.x2 + 12 && y > o.y1 - 12 && y < o.y2 + 12
            );
          }),
      );
    const common = choices.find(free) ?? center;
    branches.forEach((n, i) =>
      shift(
        n,
        (axis === "x" ? ps[i].x : common) - n.x,
        (axis === "y" ? ps[i].y : common) - n.y,
      ),
    );
  }
  return scene;
}
export function moveOwner(scene, id, dx, dy) {
  for (const n of scene.nodes)
    if (n.id === id || n.data.owner === id) shift(n, dx, dy);
  return alignBranches(scene);
}
function swapPins(scene, a, b) {
  const first = scene.nodes.find((n) => n.id === a),
    second = scene.nodes.find((n) => n.id === b);
  const dx = second.x - first.x,
    dy = second.y - first.y;
  for (const [p, x, y] of [
    [first, dx, dy],
    [second, -dx, -dy],
  ]) {
    shift(p, x, y);
    p.data.dx += x;
    p.data.dy += y;
    for (const w of scene.wires.filter((w) => w.rail && w.source === p.id)) {
      const n = scene.nodes.find((n) => n.id === w.target);
      shift(n, x, y);
      n.data.dx += x;
      n.data.dy += y;
    }
  }
  updateLabels(scene);
  return alignBranches(scene);
}
const objectives = ["bends", "crossings", "length", "area"];
export function retainPareto(archive, candidate) {
  if (!candidate.usable) return archive;
  const dominates = (a, b) =>
    objectives.every((k) => a.metrics[k] <= b.metrics[k]) &&
    objectives.some((k) => a.metrics[k] < b.metrics[k]);
  if (
    archive.some(
      (a) =>
        dominates(a, candidate) ||
        objectives.every((k) => a.metrics[k] === candidate.metrics[k]),
    )
  )
    return archive;
  const pool = [...archive.filter((a) => !dominates(candidate, a)), candidate];
  if (pool.length <= 4) return pool;
  const selected = [];
  for (const key of objectives) {
    const winner = [...pool].sort(
      (a, b) => a.metrics[key] - b.metrics[key] || a.id - b.id,
    )[0];
    if (!selected.includes(winner)) selected.push(winner);
  }
  for (const a of pool.sort((a, b) => a.id - b.id))
    if (selected.length < 4 && !selected.includes(a)) selected.push(a);
  return selected;
}
export function sceneKey(scene, options = {}) {
  return JSON.stringify([
    Object.entries(options).sort(([a], [b]) => a.localeCompare(b)),
    [...scene.nodes]
      .sort((a, b) => a.id.localeCompare(b.id))
      .map((n) => [
        n.id,
        n.x,
        n.y,
        n.width,
        n.height,
        n.direction,
        n.rotation,
        n.labelBox && [
          n.labelBox.x1,
          n.labelBox.y1,
          n.labelBox.x2,
          n.labelBox.y2,
        ],
        n.labelOffset,
        n.symbol?.kind,
        n.symbol?.positive,
        n.symbol?.pinIds,
        n.compactLabel,
      ]),
    [...scene.wires]
      .sort((a, b) => a.id.localeCompare(b.id))
      .map((w) => [w.id, w.net, w.source, w.target]),
  ]);
}
function* neighbors(scene) {
  const ranked = netRanking(scene),
    lists = [[], [], [], []];
  for (const { net } of ranked) {
    for (const mode of ["horizontal", "vertical"])
      for (const offset of [0, -24, 24])
        lists[0].push({
          layout: true,
          make: () => topology(scene, mode, net, offset),
        });
    const owners = [
      ...new Set(
        terminals(scene, net)
          .map((n) => n.data.owner)
          .filter(Boolean),
      ),
    ].sort();
    for (const id of owners) {
      const pins = scene.nodes.filter(
        (n) => n.data.owner === id && n.classes.includes("pin"),
      );
      if (pins.length === 2)
        for (const rotation of [0, 90, 180, 270])
          lists[1].push({
            make: () =>
              alignBranches(
                optimizePorts(clone(scene), { owner: id, rotation }),
              ),
          });
      for (const side of ["W", "E", "N", "S"]) {
        const ps = pins
          .filter((n) => n.direction === side)
          .sort((a, b) => (["W", "E"].includes(side) ? a.y - b.y : a.x - b.x));
        for (let i = 1; i < ps.length; i++)
          lists[2].push({
            make: () => swapPins(clone(scene), ps[i - 1].id, ps[i].id),
          });
      }
      for (const [dx, dy] of [
        [12, 0],
        [-12, 0],
        [0, 12],
        [0, -12],
        [24, 0],
        [-24, 0],
        [0, 24],
        [0, -24],
      ])
        lists[3].push({
          make: () => moveOwner(clone(scene), id, dx, dy),
        });
    }
  }
  for (let i = 0; lists.some((l) => i < l.length); i++)
    for (const list of lists) if (list[i]) yield list[i];
}
// Repairs are based on actual failed paths and shared channels, not all objects.
export function* repairs(scene, metrics) {
  const ids = new Set(metrics.details.failures);
  for (const w of scene.wires) if (w.failed) ids.add(w.id);
  const nets = new Set(
    scene.wires.filter((w) => ids.has(w.id)).map((w) => w.net),
  );
  for (const text of metrics.details.shared)
    for (const net of Object.keys(scene.expected))
      if (text.includes(net + "|")) nets.add(net);
  for (const text of metrics.details.penetrations)
    for (const net of Object.keys(scene.expected))
      if (text.startsWith(net + "|")) nets.add(net);
  for (let step = 1; step <= 4; step++) {
    for (const net of [...nets].sort()) {
      const labels = scene.nodes.filter(
        (n) => n.data.netKey === net && n.labelBox,
      );
      for (const label of labels) {
        const c = clone(scene),
          n = c.nodes.find((n) => n.id === label.id);
        n.labelOffset = step * 12;
        yield { scene: c };
      }
      const owners = [
        ...new Set(
          terminals(scene, net)
            .map((n) => n.data.owner)
            .filter(Boolean),
        ),
      ].sort();
      for (const owner of owners)
        for (const [dx, dy] of [
          [step * 12, 0],
          [0, step * 12],
        ])
          yield {
            scene: moveOwner(clone(scene), owner, dx, dy),
          };
    }
  }
}
export async function search(
  preview,
  {
    route,
    engine,
    onProgress = () => {},
    budgetMs = 10000,
    maxCandidates = 64,
    seeds = [],
    compactSymbols = false,
    routeOptions = {},
    now = () => performance.now(),
  },
) {
  const started = now(),
    seen = new Set(),
    cache = new Map();
  const previewMetrics = measure(preview);
  let reference = usable(previewMetrics) ? previewMetrics : null;
  let archive = [],
    best = null,
    bestScore = [Infinity],
    count = 0,
    attempts = 0;
  const available = () =>
    count < maxCandidates &&
    attempts < maxCandidates * 8 &&
    now() - started < budgetMs;
  async function evaluate(input, layout = false) {
    if (!available()) return null;
    attempts++;
    let scene = clone(input);
    if (compactSymbols) compactPassives(scene);
    normalizeTerminals(scene);
    const preKey =
      sceneKey(scene, routeOptions) + (layout ? "layout" : "fixed");
    if (seen.has(preKey)) {
      return null;
    }
    seen.add(preKey);
    try {
      if (layout) {
        scene = alignBranches(await layoutScene(scene, engine));
        normalizeTerminals(scene);
      }
      const key = sceneKey(scene, routeOptions),
        cached = cache.get(key);
      const routed = cached || route(scene);
      if (!cached) cache.set(key, routed);
      const metrics = measure(routed);
      const record = { id: count, usable: usable(metrics), metrics };
      count++;
      const candidate = { ...record, scene: routed };
      archive = retainPareto(archive, candidate);
      if (usable(metrics) && !reference) reference = metrics;
      const s = reference ? score(reference, metrics) : [Infinity];
      if (better(s, bestScore)) {
        best = candidate;
        bestScore = s;
      }
      onProgress({ count: count, best });
      await new Promise((r) => setTimeout(r, 0));
      return candidate;
    } catch (e) {
      count++;
      return null;
    }
  }

  // Seed routing results are reused only when geometry and effective options match.
  for (const seed of seeds)
    if (seed.routingKey === sceneKey(seed, routeOptions))
      cache.set(seed.routingKey, seed);
  const initial = await evaluate(preview);
  if (initial && !initial.usable) {
    let tried = 0;
    for (const repair of repairs(initial.scene, initial.metrics)) {
      if (!available() || tried++ >= 8 || archive.length) break;
      await evaluate(repair.scene);
    }
  }
  for (const seed of seeds) if (available()) await evaluate(seed);
  for (const mode of ["mst", "horizontal", "vertical"]) {
    if (!available()) break;
    const seed = clone(preview);
    if (compactSymbols) compactPassives(seed);
    await evaluate(topology(optimizePorts(seed), mode), true);
  }
  // A cursor belongs to an immutable archive member. Recompute neighborhoods
  // whenever a new candidate enters; never apply stale pin lists to a new scene.
  const cursors = new Map();
  let turns = 0;
  while (available() && archive.length && turns++ < maxCandidates * 8) {
    let progressed = false;
    for (const parent of [...archive]) {
      if (!available()) break;
      if (!cursors.has(parent.id))
        cursors.set(parent.id, neighbors(parent.scene));
      const next = cursors.get(parent.id).next();
      if (next.done) continue;
      progressed = true;
      const op = next.value;
      await evaluate(op.make(), op.layout);
    }
    if (!progressed) break;
  }
  return { best, count: count };
}
