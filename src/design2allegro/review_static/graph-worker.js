"use strict";
importScripts("/vendor/elk-api.js");
// All layout work stays in local workers, away from the UI thread.
const engine = new ELK({ workerUrl: "/vendor/elk-worker.min.js" });
self.onmessage = async ({ data }) => {
  const started = performance.now();
  try {
    const byId = new Map(data.nodes.map((n) => [n.data.id, n]));
    const adjacent = new Map(data.nodes.map((n) => [n.data.id, []]));
    for (const e of data.edges) {
      adjacent.get(e.data.source).push(e);
      adjacent.get(e.data.target).push(e);
    }
    const visited = new Set(),
      scenes = [],
      cache = new Map();
    const ordered = [...byId.keys()].sort();
    if (data.root && byId.has(data.root)) ordered.unshift(data.root);
    for (const seed of ordered) {
      if (visited.has(seed)) continue;
      const ids = [seed],
        edges = new Map(),
        depths = new Map([[seed, 0]]);
      visited.add(seed);
      for (let i = 0; i < ids.length; i++)
        for (const edge of adjacent.get(ids[i])) {
          edges.set(edge.data.id, edge);
          const other =
            edge.data.source === ids[i] ? edge.data.target : edge.data.source;
          if (!visited.has(other)) {
            visited.add(other);
            ids.push(other);
            depths.set(other, depths.get(ids[i]) + 1);
          }
        }
      const index = new Map(ids.map((id, i) => [id, String(i)]));
      const children = ids.map((id) => {
        const n = byId.get(id).data,
          localId = index.get(id);
        const child = { id: localId, width: n.width, height: n.height };
        if (n.anchorY !== undefined) {
          child.layoutOptions = { "elk.portConstraints": "FIXED_POS" };
          child.ports = [
            {
              id: localId + ":W",
              x: 0,
              y: n.height / 2 + n.anchorY,
              width: 0,
              height: 0,
              layoutOptions: { "elk.port.side": "WEST" },
            },
            {
              id: localId + ":E",
              x: n.width,
              y: n.height / 2 + n.anchorY,
              width: 0,
              height: 0,
              layoutOptions: { "elk.port.side": "EAST" },
            },
          ];
        }
        return child;
      });
      const es = [...edges.values()];
      const elkEdges = es.map((e, i) => {
        let a = e.data.source,
          b = e.data.target;
        if (depths.get(a) > depths.get(b)) [a, b] = [b, a];
        return {
          id: "e" + i,
          sources: [
            index.get(a) + (byId.get(a).data.anchorY !== undefined ? ":E" : ""),
          ],
          targets: [
            index.get(b) + (byId.get(b).data.anchorY !== undefined ? ":W" : ""),
          ],
        };
      });
      const key = JSON.stringify([children, elkEdges]);
      let result = cache.get(key);
      if (!result) {
        result = await engine.layout({
          id: "root",
          layoutOptions: {
            "elk.algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.edgeRouting": "ORTHOGONAL",
            "elk.spacing.nodeNode": "36",
            "elk.layered.spacing.nodeNodeBetweenLayers": "110",
            "elk.padding": "[top=30,left=30,bottom=30,right=30]",
            "elk.randomSeed": "1",
          },
          children,
          edges: elkEdges,
        });
        cache.set(key, result);
      }
      scenes.push({ ids, es, result });
    }
    const area = scenes.reduce(
      (a, s) => a + (s.result.width + 50) * (s.result.height + 50),
      0,
    );
    const rowWidth = Math.max(800, Math.sqrt(area) * 1.4);
    let x = 0,
      y = 0,
      rowHeight = 0;
    const nodes = [],
      edges = [];
    for (const { ids, es, result } of scenes) {
      if (x && x + result.width > rowWidth) {
        x = 0;
        y += rowHeight + 50;
        rowHeight = 0;
      }
      for (const n of result.children)
        nodes.push({
          id: ids[Number(n.id)],
          position: { x: x + n.x + n.width / 2, y: y + n.y + n.height / 2 },
        });
      const positions = new Map(
        result.children.map((n) => [
          ids[Number(n.id)],
          { x: x + n.x + n.width / 2, y: y + n.y + n.height / 2 },
        ]),
      );
      for (const e of result.edges || []) {
        const original = es[Number(e.id.slice(1))],
          section = e.sections?.[0];
        if (!section) throw new Error("线路缺少布局结果");
        let points = [
          section.startPoint,
          ...(section.bendPoints || []),
          section.endPoint,
        ].map((p) => ({ x: x + p.x, y: y + p.y }));
        if (ids[Number(e.sources[0].split(":")[0])] !== original.data.source)
          points.reverse();
        // Extend the port's escape segment to the visible anchor, inside the
        // otherwise transparent label/symbol envelope. Nothing crosses the label.
        for (const [id, front] of [
          [original.data.source, true],
          [original.data.target, false],
        ]) {
          const n = byId.get(id).data;
          if (n.anchorY !== undefined) {
            const p = positions.get(id),
              anchor = { x: p.x, y: p.y + n.anchorY };
            if (front) points.unshift(anchor);
            else points.push(anchor);
          }
        }
        edges.push({ id: original.data.id, points });
      }
      x += result.width + 50;
      rowHeight = Math.max(rowHeight, result.height);
    }
    self.postMessage({
      nodes,
      edges,
      metrics: {
        layout: "elk-pin-layered",
        layoutMs: performance.now() - started,
        nodes: nodes.length,
        edges: edges.length,
        components: scenes.length,
      },
    });
  } catch (e) {
    self.postMessage({ error: e.message });
  }
};
