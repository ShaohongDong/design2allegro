import { AvoidLib } from "/vendor/libavoid.js";
import "/vendor/elk-api.js";
import {
  moduleScene,
  layoutScene,
  optimizePorts,
  shift,
  updateLabels,
} from "./layout-layout.js";
import { compactPassives } from "./layout-geometry.js";
import { SceneRouter } from "./layout-routing.js";
import { measure, usable } from "./layout-metrics.js";
import { search, sceneKey } from "./layout-search.js";
const ready = AvoidLib.load("/vendor/libavoid.wasm");
const engine = new self.ELK({ workerUrl: "/vendor/elk-worker.min.js" });
function boundsOf(scene) {
  let x1 = Infinity,
    y1 = Infinity,
    x2 = -Infinity,
    y2 = -Infinity;
  for (const n of scene.nodes) {
    x1 = Math.min(x1, n.x - n.width / 2, n.labelBox?.x1 ?? Infinity);
    x2 = Math.max(x2, n.x + n.width / 2, n.labelBox?.x2 ?? -Infinity);
    y1 = Math.min(y1, n.y - n.height / 2, n.labelBox?.y1 ?? Infinity);
    y2 = Math.max(y2, n.y + n.height / 2, n.labelBox?.y2 ?? -Infinity);
  }
  for (const w of scene.wires)
    for (const p of w.points || []) {
      x1 = Math.min(x1, p.x);
      x2 = Math.max(x2, p.x);
      y1 = Math.min(y1, p.y);
      y2 = Math.max(y2, p.y);
    }
  return { x1, y1, x2, y2 };
}
function components(scene) {
  const roots = scene.nodes.filter((n) => !n.data.owner),
    byId = new Map(scene.nodes.map((n) => [n.id, n])),
    parents = new Map(roots.map((n) => [n.id, n.id]));
  const find = (id) => {
    let p = id;
    while (parents.get(p) !== p) p = parents.get(p);
    return p;
  };
  for (const w of scene.wires) {
    const a = byId.get(w.source),
      b = byId.get(w.target),
      x = find(a.data.owner || a.id),
      y = find(b.data.owner || b.id);
    parents.set(x, y);
  }
  const groups = new Map();
  for (const n of scene.nodes) {
    const root = find(n.data.owner || n.id);
    if (!groups.has(root))
      groups.set(root, { ...scene, nodes: [], wires: [], expected: {} });
    groups.get(root).nodes.push(n);
  }
  for (const w of scene.wires) {
    const n = byId.get(w.source),
      g = groups.get(find(n.data.owner || n.id));
    g.wires.push(w);
    g.expected[w.net] ||= [];
    for (const id of [w.source, w.target])
      if (
        !byId.get(id).classes.includes("branch") &&
        !g.expected[w.net].includes(id)
      )
        g.expected[w.net].push(id);
  }
  return [...groups.values()];
}
function pack(scenes, position) {
  const items = scenes.map((scene) => ({
    scene: {
      ...scene,
      nodes: structuredClone(scene.nodes),
      wires: structuredClone(scene.wires),
    },
    bounds: boundsOf(scene),
  }));
  const width =
    Math.sqrt(
      items.reduce(
        (s, { bounds: b }) => s + (b.x2 - b.x1 + 120) * (b.y2 - b.y1 + 120),
        0,
      ),
    ) * 1.25;
  let x = 0,
    y = 0,
    row = 0;
  const nodes = [],
    wires = [],
    frames = [];
  for (const { scene, bounds: b } of items) {
    const w = b.x2 - b.x1 + 96,
      h = b.y2 - b.y1 + 96;
    if (position && x && x + w > width) {
      x = 0;
      y += row + 100;
      row = 0;
    }
    const dx = position ? x + 48 - b.x1 : 0,
      dy = position ? y + 48 - b.y1 : 0;
    for (const n of scene.nodes) shift(n, dx, dy);
    for (const e of scene.wires)
      for (const p of e.points) {
        p.x += dx;
        p.y += dy;
      }
    nodes.push(...scene.nodes);
    wires.push(...scene.wires);
    frames.push({
      group: scene.group,
      x1: b.x1 + dx - 32,
      y1: b.y1 + dy - 32,
      x2: b.x2 + dx + 32,
      y2: b.y2 + dy + 32,
    });
    if (position) {
      x += w + 100;
      row = Math.max(row, h);
    }
  }
  const conflicts = new Set(),
    bodies = nodes.filter(
      (n) => n.classes.includes("part") || n.classes.includes("module"),
    );
  for (let i = 0; i < bodies.length; i++)
    for (let j = i + 1; j < bodies.length; j++) {
      const a = bodies[i],
        b = bodies[j];
      if (
        Math.abs(a.x - b.x) < (a.width + b.width) / 2 - 0.1 &&
        Math.abs(a.y - b.y) < (a.height + b.height) / 2 - 0.1
      ) {
        conflicts.add(a.id);
        conflicts.add(b.id);
      }
    }
  return { nodes, wires, frames, conflicts: [...conflicts] };
}
self.onmessage = async ({ data }) => {
  const send = (phase, result) =>
    self.postMessage({ generation: data.generation, phase, result });
  try {
    await ready;
    const A = AvoidLib.getInstance(),
      input = data.input.scene;
    const route = (scene) => {
      const r = new SceneRouter(A, scene);
      try {
        const out = r.compute(),
          metrics = measure(out);
        const badNets = new Set();
        for (const detail of [
          ...metrics.details.shared,
          ...metrics.details.penetrations,
        ])
          for (const net of Object.keys(out.expected))
            if (detail.includes(net + "|")) badNets.add(net);
        for (const w of out.wires) if (badNets.has(w.net)) w.failed = true;
        out.routingKey = sceneKey(out);
        return out;
      } finally {
        r.dispose();
      }
    };
    const groups = [
      ...new Set(
        input.nodes.filter((n) => !n.data.owner).map((n) => n.data.group || ""),
      ),
    ].sort();
    const scenes = [];
    for (const group of groups) {
      let scene = moduleScene(input, group);
      if (!scene.nodes.length) continue;
      if (data.input.layout) {
        let index = 0;
        for (const root of scene.nodes
          .filter((n) => !n.data.owner)
          .sort((a, b) => a.id.localeCompare(b.id))) {
          const dx = index++ * 600 - root.x,
            dy = -root.y;
          for (const n of scene.nodes)
            if (n.id === root.id || n.data.owner === root.id) shift(n, dx, dy);
        }
      }
      scene = compactPassives(scene);
      updateLabels(scene);
      if (data.input.layout) {
        const chunks = [];
        for (let chunk of components(scene)) {
          chunk = await layoutScene(
            compactPassives(optimizePorts(chunk)),
            engine,
          );
          chunks.push(route(chunk));
        }
        const merged = pack(chunks, true);
        scene = { ...scene, nodes: merged.nodes, wires: merged.wires };
      } else scene = route(scene);
      scenes.push(scene);
    }
    send("preview", pack(scenes, data.input.layout));
    if (!data.input.layout) {
      send("complete", null);
      return;
    }
    const started = performance.now();
    let count = 0;
    for (let i = 0; i < scenes.length && count < 64; i++) {
      const budgetMs =
        (10000 - (performance.now() - started)) / (scenes.length - i);
      if (budgetMs <= 0) break;
      const base = scenes[i];
      if (base.nodes.length > 2000) continue;
      let lastBest = 0;
      const out = await search(base, {
        route,
        engine,
        seeds: [base],
        compactSymbols: true,
        budgetMs,
        maxCandidates: Math.max(
          1,
          Math.floor((64 - count) / (scenes.length - i)),
        ),
        onProgress: (p) => {
          if (p.best && p.best.id !== lastBest && usable(p.best.metrics)) {
            lastBest = p.best.id;
            scenes[i] = p.best.scene;
            send("progress", pack(scenes, true));
          }
        },
      });
      count += out.count;
      if (out.best) scenes[i] = out.best.scene;
    }
    send("complete", null);
  } catch (e) {
    self.postMessage({
      generation: data.generation,
      error: String(e.message || e),
    });
  }
};
