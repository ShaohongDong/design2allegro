import { refreshPassive } from "./layout-geometry.js";
import { directions } from "./layout-routing.js";
export function moduleScene(input, group) {
  const ownerGroup = new Map(
    input.nodes
      .filter((n) => !n.data.owner)
      .map((n) => [n.id, n.data.group || ""]),
  );
  const nodes = structuredClone(
    input.nodes.filter((n) => ownerGroup.get(n.data.owner || n.id) === group),
  );
  const ids = new Set(nodes.map((n) => n.id));
  for (const n of nodes)
    n.direction =
      n.direction ||
      (n.classes.includes("pin") || n.classes.includes("port")
        ? n.data.side < 0
          ? "W"
          : "E"
        : n.classes.includes("rail")
          ? n.data.dx < 0
            ? "W"
            : "E"
          : null);
  const wires = structuredClone(
    input.wires.filter((w) => ids.has(w.source) && ids.has(w.target)),
  );
  const expected = {};
  for (const w of wires) {
    if (!expected[w.net]) expected[w.net] = [];
    for (const id of [w.source, w.target])
      if (
        !nodes.find((n) => n.id === id).classes.includes("branch") &&
        !expected[w.net].includes(id)
      )
        expected[w.net].push(id);
  }
  return { group, nodes, wires, expected, pkg: input.pkg };
}
export function shift(n, dx, dy) {
  n.x += dx;
  n.y += dy;
  for (const name of ["box", "labelBox"])
    if (n[name]) {
      n[name].x1 += dx;
      n[name].x2 += dx;
      n[name].y1 += dy;
      n[name].y2 += dy;
    }
}
export function optimizePorts(scene, override = {}) {
  const byId = new Map(scene.nodes.map((n) => [n.id, n])),
    pinsByNet = new Map(),
    railByPin = new Map();
  for (const w of scene.wires) {
    if (w.rail) {
      railByPin.set(w.source, byId.get(w.target));
      continue;
    }
    if (!pinsByNet.has(w.net)) pinsByNet.set(w.net, new Set());
    for (const id of [w.source, w.target])
      if (byId.get(id).data.owner) pinsByNet.get(w.net).add(id);
  }
  const endpoints = new Map();
  for (const w of scene.wires)
    for (const id of [w.source, w.target])
      if (byId.get(id).classes.includes("pin")) endpoints.set(id, w.net);
  for (const owner of scene.nodes.filter((n) => n.classes.includes("part"))) {
    if (override.owner && owner.id !== override.owner) continue;
    const pins = scene.nodes
      .filter((n) => n.data.owner === owner.id && n.classes.includes("pin"))
      .sort(
        (a, b) =>
          String(scene.pkg.pins[a.id.slice(4)]?.num).localeCompare(
            String(scene.pkg.pins[b.id.slice(4)]?.num),
            "en",
            { numeric: true },
          ) || a.id.localeCompare(b.id),
      );
    const desired = new Map();
    for (const pin of pins) {
      const neighbours = [...(pinsByNet.get(endpoints.get(pin.id)) || [])]
        .map((id) => byId.get(id))
        .filter((p) => p.data.owner !== owner.id)
        .map((p) => byId.get(p.data.owner));
      const xs = neighbours.map((n) => n.x),
        ys = neighbours.map((n) => n.y);
      desired.set(pin.id, {
        x: xs.length ? xs.reduce((a, b) => a + b) / xs.length : pin.x,
        y: ys.length ? ys.reduce((a, b) => a + b) / ys.length : pin.y,
      });
    }
    const sides = { W: [], E: [], N: [], S: [] };
    if (pins.length === 2) {
      // Four rotations preserve pin identity and polarity, never mirror it.
      const all = [
        ["W", "E"],
        ["N", "S"],
        ["E", "W"],
        ["S", "N"],
      ];
      let best = all[0],
        cost = Infinity,
        rotation = 0;
      for (let k = 0; k < all.length; k++) {
        let c = 0;
        for (let i = 0; i < 2; i++) {
          const d = directions[all[k][i]],
            p = desired.get(pins[i].id),
            role = railByPin.get(pins[i].id)?.data.role;
          if (role === "ground") c += all[k][i] === "S" ? 0 : 4000;
          else if (role === "power") c += all[k][i] === "N" ? 0 : 2000;
          c +=
            Math.abs(owner.x + d.x * 150 - p.x) +
            Math.abs(owner.y + d.y * 150 - p.y);
        }
        if (c < cost) {
          cost = c;
          best = all[k];
          rotation = k * 90;
        }
      }
      if (override.rotation !== undefined) {
        rotation = override.rotation;
        best = all[rotation / 90];
      }
      owner.rotation = rotation;
      pins.forEach((p, i) => sides[best[i]].push(p));
    } else {
      for (const pin of pins) {
        const meta = scene.pkg.pins[pin.id.slice(4)],
          role = railByPin.get(pin.id)?.data.role,
          p = desired.get(pin.id);
        const side =
          role === "ground"
            ? "S"
            : role === "power"
              ? "N"
              : meta?.type_name === "INPUT"
                ? "W"
                : ["OUTPUT", "OPENCOLL"].includes(meta?.type_name)
                  ? "E"
                  : p.x < owner.x
                    ? "W"
                    : "E";
        sides[side].push(pin);
      }
      for (const [side, ps] of Object.entries(sides))
        ps.sort((a, b) => {
          const axis = ["W", "E"].includes(side) ? "y" : "x";
          return (
            desired.get(a.id)[axis] - desired.get(b.id)[axis] ||
            a.id.localeCompare(b.id, "en", { numeric: true })
          );
        });
    }
    const horizontalLabel = Math.max(
      0,
      ...[...sides.W, ...sides.E].map((p) => [...p.data.label].length * 6),
    );
    const verticalPitch = Math.max(
      60,
      ...[...sides.N, ...sides.S].map((p) => [...p.data.label].length * 6 + 16),
    );
    owner.width = Math.max(
      150,
      horizontalLabel * 2 + 60,
      Math.max(sides.N.length, sides.S.length) * verticalPitch + 24,
    );
    owner.height = Math.max(
      64,
      Math.max(sides.W.length, sides.E.length) * 48 + 24,
      sides.N.length || sides.S.length ? 120 : 64,
    );
    for (const [side, ps] of Object.entries(sides))
      ps.forEach((pin, i) => {
        const d = directions[side],
          offset =
            (i - (ps.length - 1) / 2) *
            (["W", "E"].includes(side) ? 48 : verticalPitch);
        const dx = d.x ? d.x * (owner.width / 2 + 20) : offset,
          dy = d.y ? d.y * (owner.height / 2 + 20) : offset;
        shift(pin, owner.x + dx - pin.x, owner.y + dy - pin.y);
        pin.data.dx = dx;
        pin.data.dy = dy;
        pin.direction = side;
      });
    // Attachments track the actual physical pin, including vertically placed pins.
    for (const w of scene.wires) {
      const pin = byId.get(w.source),
        end = byId.get(w.target);
      if (
        pin?.data.owner !== owner.id ||
        end?.data.owner !== owner.id ||
        end.classes.includes("pin")
      )
        continue;
      const d = directions[pin.direction];
      shift(end, pin.x + d.x * 65 - end.x, pin.y + d.y * 65 - end.y);
      end.direction = pin.direction;
      end.data.dx = end.x - owner.x;
      end.data.dy = end.y - owner.y;
    }
  }
  updateLabels(scene);
  for (const n of scene.nodes) if (n.symbol) refreshPassive(scene, n);
  return scene;
}
export function updateLabels(scene) {
  for (const n of scene.nodes) {
    if (n.symbol) {
      refreshPassive(scene, n);
      continue;
    }
    const w =
        n.labelBox?.w ||
        Math.max(
          1,
          ...String(n.data.label || "")
            .split("\n")
            .map((s) => s.length * 6),
        ),
      h = n.labelBox?.h || 14;
    if (n.classes.includes("part") || n.classes.includes("module")) {
      const north = scene.nodes.some(
        (p) => p.data.owner === n.id && p.direction === "N",
      );
      n.labelBox = {
        x1: north ? n.x + n.width / 2 + 24 : n.x - w / 2,
        x2: north ? n.x + n.width / 2 + 24 + w : n.x + w / 2,
        y1: n.y - n.height / 2 - 10 - h,
        y2: n.y - n.height / 2 - 10,
        w,
        h,
      };
    } else if (n.classes.includes("net"))
      n.labelBox = {
        x1: n.x - w / 2,
        x2: n.x + w / 2,
        y1: n.y - 24 - h,
        y2: n.y - 24,
        w,
        h,
      };
    else if (n.classes.includes("rail")) {
      const top = n.direction === "N";
      if (["W", "E"].includes(n.direction)) {
        const x1 = n.direction === "W" ? n.x - 25 - w : n.x + 25;
        n.labelBox = { x1, x2: x1 + w, y1: n.y - h / 2, y2: n.y + h / 2, w, h };
        continue;
      }
      n.labelBox = {
        x1: n.x - w / 2,
        x2: n.x + w / 2,
        y1: top ? n.y - 25 - h : n.y + 25,
        y2: top ? n.y - 25 : n.y + 25 + h,
        w,
        h,
      };
    }
  }
}
export async function layoutScene(scene, engine) {
  const roots = scene.nodes.filter((n) => !n.data.owner),
    byId = new Map(scene.nodes.map((n) => [n.id, n]));
  const children = [],
    owners = new Map();
  for (const n of roots) {
    const attached = scene.nodes.filter((p) => p.data.owner === n.id);
    let x1 = n.x - n.width / 2 - 28,
      x2 = n.x + n.width / 2 + 28,
      y1 = n.y - n.height / 2 - 28,
      y2 = n.y + n.height / 2 + 28;
    for (const a of [n, ...attached]) {
      x1 = Math.min(x1, a.x - a.width / 2 - 28);
      x2 = Math.max(x2, a.x + a.width / 2 + 28);
      y1 = Math.min(y1, a.y - a.height / 2 - 28);
      y2 = Math.max(y2, a.y + a.height / 2 + 28);
      if (a.labelBox && !a.classes.includes("pin")) {
        x1 = Math.min(x1, a.labelBox.x1 - 16);
        x2 = Math.max(x2, a.labelBox.x2 + 16);
        y1 = Math.min(y1, a.labelBox.y1 - 16);
        y2 = Math.max(y2, a.labelBox.y2 + 16);
      }
    }
    const child = {
      id: n.id,
      width: x2 - x1,
      height: y2 - y1,
      ports: [],
      layoutOptions: { "elk.portConstraints": "FIXED_POS" },
    };
    owners.set(n.id, { n, child, x1, y1, x2, y2 });
    children.push(child);
  }
  const used = new Set();
  function port(id, preferred) {
    const n = byId.get(id),
      owner = owners.get(n.data.owner || id),
      side = n.direction || preferred,
      key = id + "|" + side;
    if (used.has(key)) return key;
    used.add(key);
    const x =
        side === "W" ? 0 : side === "E" ? owner.child.width : n.x - owner.x1,
      y = side === "N" ? 0 : side === "S" ? owner.child.height : n.y - owner.y1;
    owner.child.ports.push({
      id: key,
      x,
      y,
      width: 0,
      height: 0,
      layoutOptions: {
        "elk.port.side": { W: "WEST", E: "EAST", N: "NORTH", S: "SOUTH" }[side],
      },
    });
    return key;
  }
  const edges = scene.wires
    .filter(
      (w) =>
        !w.rail &&
        (byId.get(w.source).data.owner || w.source) !==
          (byId.get(w.target).data.owner || w.target),
    )
    .map((w) => {
      const a = byId.get(w.source),
        b = byId.get(w.target);
      const flip = a.direction === "W" || b.direction === "E";
      return {
        id: w.id,
        sources: [port(flip ? w.target : w.source, "E")],
        targets: [port(flip ? w.source : w.target, "W")],
      };
    });
  const input = {
    id: "root",
    children,
    edges,
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.randomSeed": "1",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.spacing.nodeNode": "60",
      "elk.layered.spacing.nodeNodeBetweenLayers": "80",
      "elk.spacing.edgeEdge": "12",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.padding": "[top=48,left=48,bottom=48,right=48]",
    },
  };
  const laid = await engine.layout(input);
  for (const child of laid.children) {
    const o = owners.get(child.id),
      dx = child.x - o.x1,
      dy = child.y - o.y1;
    for (const n of scene.nodes)
      if (n.id === child.id || n.data.owner === child.id) shift(n, dx, dy);
  }
  return scene;
}
export function makeNetTrees(scene) {
  const nodes = new Map(scene.nodes.map((n) => [n.id, n])),
    nets = new Map();
  for (const w of scene.wires)
    if (!w.rail) {
      if (!nets.has(w.net)) nets.set(w.net, new Set());
      nets.get(w.net).add(w.source);
      nets.get(w.net).add(w.target);
    }
  const wires = scene.wires.filter((w) => w.rail);
  const assignedPins = new Set(wires.flatMap((w) => w.pins || []));
  for (const [net, ids] of [...nets].sort(([a], [b]) => a.localeCompare(b))) {
    const left = [...ids].sort(),
      connected = [left.shift()];
    let index = 0;
    while (left.length) {
      let best = null;
      for (const a of connected)
        for (const b of left) {
          const p = nodes.get(a),
            q = nodes.get(b),
            cost = Math.abs(p.x - q.x) + Math.abs(p.y - q.y);
          if (!best || cost < best.cost) best = { a, b, cost };
        }
      const pins = [
        ...new Set(
          [best.a, best.b].flatMap(
            (id) =>
              nodes.get(id).data.pins ||
              (nodes.get(id).classes.includes("pin") ? [id.slice(4)] : []),
          ),
        ),
      ];
      wires.push({
        id: "tree:" + JSON.stringify([scene.group, net, index++]),
        net,
        source: best.a,
        target: best.b,
        pins: pins.filter((id) => {
          if (assignedPins.has(id)) return false;
          assignedPins.add(id);
          return true;
        }),
        rail: false,
      });
      connected.push(best.b);
      left.splice(left.indexOf(best.b), 1);
    }
  }
  scene.wires = wires;
  return scene;
}
