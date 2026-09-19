"use strict";
// Shared, explicit geometry: SVG/hit areas never determine layout envelopes.
const ReviewGeometry = (() => {
  const rect = (x, y, w, h) => ({
    x1: x - w / 2,
    y1: y - h / 2,
    x2: x + w / 2,
    y2: y + h / 2,
  });
  const move = (r, p) => ({
    x1: r.x1 + p.x,
    y1: r.y1 + p.y,
    x2: r.x2 + p.x,
    y2: r.y2 + p.y,
  });
  const union = (rs) =>
    rs.length
      ? {
          x1: Math.min(...rs.map((r) => r.x1)),
          y1: Math.min(...rs.map((r) => r.y1)),
          x2: Math.max(...rs.map((r) => r.x2)),
          y2: Math.max(...rs.map((r) => r.y2)),
        }
      : rect(0, 0, 0, 0);
  function wrap(label, size, measure, limit = 240) {
    return label
      .split("\n")
      .flatMap((line) => {
        if (measure(line, size).width <= limit) return [line];
        const result = [];
        let current = "";
        for (const { segment } of new Intl.Segmenter(undefined, {
          granularity: "grapheme",
        }).segment(line)) {
          if (current && measure(current + segment, size).width > limit) {
            result.push(current);
            current = "";
          }
          current += segment;
        }
        result.push(current);
        return result;
      })
      .join("\n");
  }
  function prepare(model, measure) {
    const byId = new Map(model.nodes.map((n) => [n.data.id, n]));
    for (const n of model.nodes) {
      const d = n.data;
      d.sourceLabel = d.label || "";
      d.label = wrap(d.sourceLabel, n.classes === "net" ? 11 : 12, measure);
      d.text = measure(d.label, n.classes === "net" ? 11 : 12);
      d.labelX = 0;
      d.labelY = -22;
      d.anchorY = 0;
      d.layoutKind =
        n.classes === "net"
          ? "net"
          : n.classes.includes("pin")
            ? "pin"
            : "fixed";
      if (d.bodyId) {
        d.width = 40;
        d.height = 90;
        continue;
      }
      if (n.classes.includes("component")) continue;
      if (n.classes === "module") {
        d.width = d.text.width + 24;
        d.height = d.text.height + 24;
        d.labelY = 0;
        d.box = rect(0, 0, d.width, d.height);
        d.obstacles = [d.box];
      } else {
        d.width = n.classes === "net" ? 20 : 56;
        d.height = n.classes === "net" ? 20 : 90;
        if (n.classes !== "net") d.labelX = d.text.width / 2 + 36;
        else d.labelY = -Math.max(22, d.text.height / 2 + 14);
        d.obstacles = [
          rect(0, 0, d.width, d.height),
          rect(d.labelX, d.labelY, d.text.width, d.text.height),
        ];
        // The icon is above the anchor. Its own escape may bypass the anchor
        // enclosure, but must not pass through the icon or its label.
        d.escapeObstacles = [
          ...(n.classes === "net" ? [] : [rect(4, -23, 44, 36)]),
          rect(d.labelX, d.labelY, d.text.width, d.text.height),
        ];
        d.box = union(d.obstacles);
      }
    }
    for (const n of model.nodes.filter((n) =>
      n.classes.includes("component"),
    )) {
      const d = n.data,
        terminals = d.pins.map((id) => byId.get("pin:" + id));
      d.width = 148;
      d.height = 148;
      d.halfSpan = 62;
      d.variants = [0, 90, 180, 270].map((angle) => {
        const vertical = angle % 180 !== 0;
        const cos = Math.round(Math.cos((angle * Math.PI) / 180));
        const sin = Math.round(Math.sin((angle * Math.PI) / 180));
        const positions = terminals.map((t, i) => ({
          x: cos * (i ? 62 : -62),
          y: sin * (i ? 62 : -62),
        }));
        const labels = terminals.map((t, i) =>
          vertical
            ? {
                x: t.data.text.width / 2 + 56,
                y:
                  Math.sign(positions[i].y) *
                  Math.max(0, t.data.text.height / 2 + 8 - 62),
              }
            : {
                x: Math.sign(positions[i].x) * (t.data.text.width / 2 + 22),
                y: -12 - t.data.text.height / 2,
              },
        );
        const title = vertical
          ? { x: -d.text.width / 2 - 60, y: 0 }
          : {
              x: 0,
              y:
                -Math.max(
                  54,
                  ...terminals.map((t) => t.data.text.height + 20),
                ) -
                d.text.height / 2,
            };
        const obstacles = [
          rect(0, 0, vertical ? 90 : 100, vertical ? 100 : 90),
          rect(title.x, title.y, d.text.width, d.text.height),
        ];
        terminals.forEach((t, i) => {
          const p = positions[i],
            l = labels[i];
          if (t.classes.includes("ground")) {
            const dx = Math.sign(p.x),
              dy = Math.sign(p.y);
            obstacles.push(
              rect(p.x + dx * 17, p.y + dy * 17, dx ? 38 : 28, dy ? 38 : 28),
            );
          }
          obstacles.push(
            rect(p.x, p.y + 10, 36, 66),
            rect(p.x + l.x, p.y + l.y, t.data.text.width, t.data.text.height),
          );
        });
        return {
          angle,
          positions,
          labels,
          title,
          obstacles,
          box: union(obstacles),
        };
      });
      d.box = d.variants[0].box;
    }
    for (const e of model.edges) {
      e.data.sourceLabel = e.data.label || "";
      e.data.label = wrap(e.data.sourceLabel, 11, measure);
      e.data.text = measure(e.data.label, 11);
    }
    return model;
  }
  function applyVariant(body, variant, byId) {
    const d = body.data;
    Object.assign(d, {
      angle: variant.angle,
      labelX: variant.title.x,
      labelY: variant.title.y,
      box: variant.box,
      obstacles: variant.obstacles,
    });
    d.pins.forEach((id, i) => {
      const t = byId.get("pin:" + id).data,
        p = variant.positions[i],
        l = variant.labels[i];
      Object.assign(t, {
        offsetX: p.x,
        offsetY: p.y,
        labelX: l.x,
        labelY: l.y,
        side: p.x < 0 ? "W" : p.x > 0 ? "E" : p.y < 0 ? "N" : "S",
        width: t.role === "ground" && p.x !== 0 ? 80 : 40,
      });
    });
  }
  function simplify(points) {
    const result = [];
    for (const p of points) {
      if (result.length && result.at(-1).x === p.x && result.at(-1).y === p.y)
        continue;
      while (result.length > 1) {
        const a = result.at(-2),
          b = result.at(-1);
        if (!(
          (a.x === b.x && b.x === p.x && (b.y - a.y) * (p.y - b.y) >= 0) ||
          (a.y === b.y && b.y === p.y && (b.x - a.x) * (p.x - b.x) >= 0)
        ))
          break;
        result.pop();
      }
      result.push(p);
    }
    return result;
  }
  return { rect, move, union, prepare, applyVariant, simplify };
})();
