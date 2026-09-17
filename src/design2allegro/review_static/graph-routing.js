"use strict";
const ReviewRouting = (() => {
  const EPS = 0.001;
  class Index {
    constructor(items = []) {
      this.cells = new Map();
      this.items = [];
      items.forEach((r) => this.add(r));
    }
    add(r) {
      this.items.push(r);
      for (let x = Math.floor(r.x1 / 128); x <= Math.floor(r.x2 / 128); x++)
        for (let y = Math.floor(r.y1 / 128); y <= Math.floor(r.y2 / 128); y++) {
          const key = x + "," + y;
          if (!this.cells.has(key)) this.cells.set(key, []);
          this.cells.get(key).push(r);
        }
    }
    query(box) {
      const found = new Set();
      for (let x = Math.floor(box.x1 / 128); x <= Math.floor(box.x2 / 128); x++)
        for (
          let y = Math.floor(box.y1 / 128);
          y <= Math.floor(box.y2 / 128);
          y++
        )
          for (const r of this.cells.get(x + "," + y) || []) found.add(r);
      return [...found];
    }
  }
  const overlaps = (a, b) =>
    a.x1 < b.x2 - EPS &&
    a.x2 > b.x1 + EPS &&
    a.y1 < b.y2 - EPS &&
    a.y2 > b.y1 + EPS;
  const segmentBox = (a, b) => ({
    x1: Math.min(a.x, b.x),
    x2: Math.max(a.x, b.x),
    y1: Math.min(a.y, b.y),
    y2: Math.max(a.y, b.y),
  });
  function hits(a, b, r) {
    if (Math.abs(a.x - b.x) < EPS)
      return (
        a.x > r.x1 + EPS &&
        a.x < r.x2 - EPS &&
        Math.max(a.y, b.y) > r.y1 + EPS &&
        Math.min(a.y, b.y) < r.y2 - EPS
      );
    return (
      a.y > r.y1 + EPS &&
      a.y < r.y2 - EPS &&
      Math.max(a.x, b.x) > r.x1 + EPS &&
      Math.min(a.x, b.x) < r.x2 - EPS
    );
  }
  function collinear(a, b, s) {
    const r = segmentBox(a, b);
    return (
      (Math.abs(a.y - b.y) < EPS &&
        Math.abs(s.a.y - s.b.y) < EPS &&
        Math.abs(a.y - s.a.y) < EPS &&
        Math.min(r.x2, s.x2) - Math.max(r.x1, s.x1) > EPS) ||
      (Math.abs(a.x - b.x) < EPS &&
        Math.abs(s.a.x - s.b.x) < EPS &&
        Math.abs(a.x - s.a.x) < EPS &&
        Math.min(r.y2, s.y2) - Math.max(r.y1, s.y1) > EPS)
    );
  }
  function clear(a, b, index, wires, net, skip = null) {
    if (Math.abs(a.x - b.x) > EPS && Math.abs(a.y - b.y) > EPS) return false;
    const box = segmentBox(a, b);
    if (index.query(box).some((r) => r.id !== skip && hits(a, b, r)))
      return false;
    return !wires.query(box).some((s) => s.net !== net && collinear(a, b, s));
  }
  class Heap {
    constructor() {
      this.q = [];
    }
    push(n) {
      const q = this.q;
      let i = q.length;
      q.push(n);
      while (i) {
        const p = (i - 1) >> 1;
        if (q[p].f <= n.f) break;
        q[i] = q[p];
        i = p;
      }
      q[i] = n;
    }
    pop() {
      const q = this.q,
        out = q[0],
        n = q.pop();
      if (q.length) {
        let i = 0;
        while (i * 2 + 1 < q.length) {
          let c = i * 2 + 1;
          if (c + 1 < q.length && q[c + 1].f < q[c].f) c++;
          if (n.f <= q[c].f) break;
          q[i] = q[c];
          i = c;
        }
        q[i] = n;
      }
      return out;
    }
  }
  // Lazy coordinate visibility grid: only explored vertices are allocated.
  function search(start, end, index, wires, net) {
    const xs = new Set([start.x, end.x]),
      ys = new Set([start.y, end.y]);
    for (const r of index.items) {
      xs.add(r.x1);
      xs.add(r.x2);
      ys.add(r.y1);
      ys.add(r.y2);
    }
    for (const s of wires.items)
      if (s.net !== net) {
        if (s.a.x === s.b.x) {
          xs.add(s.a.x - 4);
          xs.add(s.a.x + 4);
        } else {
          ys.add(s.a.y - 4);
          ys.add(s.a.y + 4);
        }
      }
    let xx = [...xs].sort((a, b) => a - b),
      yy = [...ys].sort((a, b) => a - b);
    xx = [xx[0] - 20, ...xx, xx.at(-1) + 20];
    yy = [yy[0] - 20, ...yy, yy.at(-1) + 20];
    const sx = xx.indexOf(start.x),
      sy = yy.indexOf(start.y),
      tx = xx.indexOf(end.x),
      ty = yy.indexOf(end.y);
    const heap = new Heap(),
      best = new Map();
    const initial = { x: sx, y: sy, dir: 0, g: 0, f: 0, prev: null };
    heap.push(initial);
    let count = 0;
    while (heap.q.length && count++ < 60000) {
      const n = heap.pop(),
        key = n.x + "," + n.y + "," + n.dir;
      if (best.has(key) && best.get(key) < n.g) continue;
      if (n.x === tx && n.y === ty) {
        const pts = [];
        for (let p = n; p; p = p.prev) pts.push({ x: xx[p.x], y: yy[p.y] });
        return ReviewGeometry.simplify(pts.reverse());
      }
      for (const [dx, dy, dir] of [
        [1, 0, 1],
        [-1, 0, 1],
        [0, 1, 2],
        [0, -1, 2],
      ]) {
        const x = n.x + dx,
          y = n.y + dy;
        if (x < 0 || y < 0 || x >= xx.length || y >= yy.length) continue;
        const a = { x: xx[n.x], y: yy[n.y] },
          b = { x: xx[x], y: yy[y] };
        if (!clear(a, b, index, wires, net)) continue;
        const g =
            n.g +
            Math.abs(a.x - b.x) +
            Math.abs(a.y - b.y) +
            (n.dir && n.dir !== dir ? 12 : 0),
          k = x + "," + y + "," + dir;
        if (best.has(k) && best.get(k) <= g) continue;
        best.set(k, g);
        heap.push({
          x,
          y,
          dir,
          g,
          f: g + Math.abs(b.x - end.x) + Math.abs(b.y - end.y),
          prev: n,
        });
      }
    }
    throw new Error("无法找到满足间距要求的线路");
  }
  function route(edges, boxes) {
    const obstacles = new Index(boxes),
      wires = new Index(),
      result = [];
    for (const e of edges) {
      let points = e.points;
      const legal = points
        .slice(1)
        .every((b, i) =>
          clear(
            points[i],
            b,
            obstacles,
            wires,
            e.net,
            i === 0 ? e.source : i === points.length - 2 ? e.target : null,
          ),
        );
      if (!legal) {
        const middle = search(
          points[1],
          points.at(-2),
          obstacles,
          wires,
          e.net,
        );
        points = [points[0], ...middle, points.at(-1)];
      }
      // Keep port escape points for independent validation, simplify for rendering only.
      for (let i = 1; i < points.length; i++)
        if (
          !clear(
            points[i - 1],
            points[i],
            obstacles,
            wires,
            e.net,
            i === 1 ? e.source : i === points.length - 1 ? e.target : null,
          )
        )
          throw new Error("线路避障校验失败");
      const escapeStart = points[1],
        escapeEnd = points.at(-2);
      const validationPoints = points;
      points = ReviewGeometry.simplify(points);
      result.push({ ...e, points, escapeStart, escapeEnd, validationPoints });
      for (let i = 1; i < points.length; i++)
        wires.add({
          ...segmentBox(points[i - 1], points[i]),
          a: points[i - 1],
          b: points[i],
          net: e.net,
        });
    }
    return { edges: result, obstacles, wires };
  }
  function labels(edges, obstacles, wires) {
    const labels = [];
    for (const e of edges) {
      if (!e.label) continue;
      const segments = e.points
        .slice(1)
        .map((b, i) => ({
          a: e.points[i],
          b,
          length: Math.abs(b.x - e.points[i].x) + Math.abs(b.y - e.points[i].y),
        }))
        .sort((a, b) => b.length - a.length);
      let placed = null;
      for (const { a, b } of segments) {
        for (const t of [0.5, 0.25, 0.75])
          for (const side of [-1, 1]) {
            if (placed) break;
            const p = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
            if (a.y === b.y) p.y += side * (e.text.height / 2 + 10);
            else p.x += side * (e.text.width / 2 + 10);
            const r = ReviewGeometry.rect(
              p.x,
              p.y,
              e.text.width + 8,
              e.text.height + 8,
            );
            if (
              obstacles.query(r).some((o) => overlaps(r, o)) ||
              wires.query(r).some((w) => hits(w.a, w.b, r))
            )
              continue;
            placed = {
              data: {
                id: "label:" + e.id,
                objectKey: e.net,
                netKey: e.net,
                label: e.label,
                width: e.text.width,
                height: e.text.height,
              },
              position: p,
              classes: "wire-label",
              selectable: false,
              grabbable: false,
            };
            obstacles.add({ ...r, id: placed.data.id });
          }
        if (placed) break;
      }
      if (!placed) throw new Error("网络文字缺少无重叠位置");
      labels.push(placed);
    }
    return labels;
  }
  function metrics(edges, boxes, labels) {
    const rs = [
      ...boxes,
      ...labels.map((n) =>
        ReviewGeometry.rect(
          n.position.x,
          n.position.y,
          n.data.width,
          n.data.height,
        ),
      ),
    ];
    let length = 0,
      bends = 0,
      crossings = 0,
      overlap = 0;
    const index = new Index();
    for (const e of edges) {
      bends += Math.max(0, e.points.length - 2);
      for (let i = 1; i < e.points.length; i++) {
        const a = e.points[i - 1],
          b = e.points[i],
          box = segmentBox(a, b);
        length += Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
        rs.push(box);
        for (const s of index.query(box))
          if (s.net !== e.net) {
            if (collinear(a, b, s)) overlap++;
            else if (
              (a.x === b.x) !== (s.a.x === s.b.x) &&
              (a.x === b.x
                ? a.x > s.x1 + EPS &&
                  a.x < s.x2 - EPS &&
                  s.a.y > box.y1 + EPS &&
                  s.a.y < box.y2 - EPS
                : s.a.x > box.x1 + EPS &&
                  s.a.x < box.x2 - EPS &&
                  a.y > s.y1 + EPS &&
                  a.y < s.y2 - EPS)
            )
              crossings++;
          }
        index.add({ ...box, a, b, net: e.net });
      }
    }
    const box = ReviewGeometry.union(rs),
      area = (box.x2 - box.x1) * (box.y2 - box.y1);
    return {
      area,
      width: box.x2 - box.x1,
      height: box.y2 - box.y1,
      wireLength: length,
      bends,
      crossings,
      foreignOverlap: overlap,
      occupancy: area
        ? boxes.reduce((s, r) => s + (r.x2 - r.x1) * (r.y2 - r.y1), 0) / area
        : 0,
    };
  }
  function audit(edges, boxes, labels) {
    const obstacles = new Index(),
      wires = new Index();
    let boxOverlaps = 0,
      obstacleViolations = 0;
    for (const box of [
      ...boxes,
      ...labels.map((n) => ({
        id: n.data.id,
        ...ReviewGeometry.rect(
          n.position.x,
          n.position.y,
          n.data.width + 8,
          n.data.height + 8,
        ),
      })),
    ]) {
      boxOverlaps += obstacles
        .query(box)
        .filter((r) => overlaps(r, box)).length;
      obstacles.add(box);
    }
    for (const e of edges) {
      const points = e.validationPoints;
      if (
        !points ||
        points.some((p) => !Number.isFinite(p.x) || !Number.isFinite(p.y))
      )
        throw new Error("无效线路坐标");
      for (let i = 1; i < points.length; i++)
        if (
          !clear(
            points[i - 1],
            points[i],
            obstacles,
            wires,
            e.net,
            i === 1 ? e.source : i === points.length - 1 ? e.target : null,
          )
        )
          obstacleViolations++;
    }
    return { boxOverlaps, obstacleViolations };
  }
  return { Index, rectOverlap: overlaps, hits, route, labels, metrics, audit };
})();
