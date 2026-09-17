"use strict";
// Pure presentation model. No inferred electrical connections are written to the package.
const ReviewGraphModel = (() => {
  function nameRole(name) {
    const base = name.split("/").pop().toUpperCase();
    if (/^(?:GND|AGND|DGND|PGND|SGND)$/.test(base)) return "ground";
    if (
      /^(?:(?:VCC|VDD|VDDA|VDDD|AVDD|DVDD|VBAT|VBUS|VIN|VOUT)\d*|[+-]?\d+V\d*)$/.test(
        base,
      )
    )
      return "power";
    return null;
  }
  function classify(net, overrides) {
    if (["signal", "power", "ground"].includes(overrides[net.name]))
      return { role: overrides[net.name], reason: "用户显示设置" };
    const explicit = net.electrical?.role;
    if (explicit)
      return {
        role: ["power", "ground"].includes(explicit) ? explicit : "signal",
        reason: `电气声明：${explicit}`,
      };
    const roles = new Set(
      [net.name, ...(net.aliases || [])].map(nameRole).filter(Boolean),
    );
    if (roles.size > 1)
      return { role: "signal", reason: "网名与别名识别冲突，按普通信号显示" };
    return {
      role: [...roles][0] || "signal",
      reason: roles.size ? "常见网名规则" : "未匹配电源／地规则",
    };
  }

  function exits(pkg, id, choices) {
    const pin = pkg.pins[id],
      part = pkg.parts[pin.ref];
    if (pin.nc) return [];
    if (
      !(part.assembly === "fitted" && part.pins.length === 2) &&
      !choices[id]?.length
    )
      return [];
    const candidates = part.pins.filter(
      (other) => other !== id && !pkg.pins[other].nc,
    );
    if (part.assembly === "fitted" && part.pins.length === 2) return candidates;
    return candidates.filter((other) => (choices[id] || []).includes(other));
  }
  function transitionId(a, b) {
    return "cross:" + JSON.stringify([a, b].sort());
  }
  function trace(pkg, root, choices, overrides) {
    const pins = new Set(),
      nets = new Set(),
      transitions = new Map();
    const queue = root && pkg.pins[root] ? [root] : [];
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      if (pins.has(id)) continue;
      pins.add(id);
      const pin = pkg.pins[id];
      if (pin.nc) continue;
      const net = pkg.nets[pin.net];
      if (classify(net, overrides).role !== "signal") continue;
      if (!nets.has(net.name)) {
        nets.add(net.name);
        queue.push(...net.pins);
      }
      for (const other of exits(pkg, id, choices)) {
        transitions.set(transitionId(id, other), [id, other]);
        queue.push(other);
      }
    }
    return { pins, nets, transitions };
  }
  function topology(pkg, options = {}) {
    const {
      overrides = {},
      choices = {},
      root = null,
      onlyTrace = false,
      visible = null,
      collapsed = new Set(),
    } = options;
    const chain = trace(pkg, root, choices, overrides);
    const nodes = [],
      edges = [],
      represented = new Map(),
      modules = new Map();
    const moduleOf = (part) =>
      part.hierarchy.length > 1 ? part.hierarchy[0] : "";
    for (const pin of Object.values(pkg.pins)) {
      if (
        (visible && !visible.has(pin.id)) ||
        (onlyTrace && !chain.pins.has(pin.id))
      )
        continue;
      const part = pkg.parts[pin.ref],
        group = moduleOf(part);
      const id = collapsed.has(group) ? "module:" + group : pin.key;
      represented.set(pin.id, id);
      if (collapsed.has(group)) {
        if (!modules.has(id)) {
          const n = {
            data: { id, group, label: group, width: 210, height: 64, pins: [] },
            classes: "module",
          };
          modules.set(id, n);
          nodes.push(n);
        }
        modules.get(id).data.pins.push(pin.id);
        continue;
      }
      const role = pin.nc ? "nc" : classify(pkg.nets[pin.net], overrides).role;
      const suffix = pin.nc
        ? " × NC"
        : role === "signal"
          ? ""
          : ` ${role === "ground" ? "⏚" : "↑"} ${pin.net}`;
      const lines = [
        `${pin.reference}.${pin.num} · ${pin.name}`,
        `${group || "顶层"}${part.assembly === "dnp" ? " · DNP" : ""}${suffix}`,
      ];
      nodes.push({
        data: {
          id,
          key: pin.key,
          objectKey: pin.key,
          pinId: pin.id,
          partKey: part.key,
          category: part.category || "generic",
          anchorY: 10,
          group,
          netKey: pin.nc ? null : "net:" + pin.net,
          role,
          label: lines.join("\n"),
          width: Math.max(210, ...lines.map((s) => [...s].length * 12 + 84)),
          height: 86,
        },
        classes: "pin " + role + (part.assembly === "dnp" ? " dnp" : ""),
      });
    }
    for (const n of modules.values())
      n.data.label += `\n${n.data.pins.length} 个引脚 · 点击展开`;
    const addEdge = (id, source, target, data, classes) => {
      if (source !== target)
        edges.push({ data: { id, source, target, ...data }, classes });
    };
    for (const net of Object.values(pkg.nets)) {
      if (classify(net, overrides).role !== "signal") continue;
      const pins = net.pins.filter((id) => represented.has(id));
      if (!pins.length) continue;
      const netKey = net.key;
      const label =
        net.name +
        (pins.length !== net.pins.length
          ? ` (${pins.length}/${net.pins.length})`
          : "");
      if (
        pins.length === 2 &&
        represented.get(pins[0]) !== represented.get(pins[1])
      ) {
        addEdge(
          "wire:" + JSON.stringify([net.name]),
          represented.get(pins[0]),
          represented.get(pins[1]),
          { netKey, objectKey: netKey, label, pins },
          "wire",
        );
      } else {
        nodes.push({
          data: {
            id: netKey,
            objectKey: netKey,
            netKey,
            label,
            width: Math.max(100, [...label].length * 12 + 24),
            height: 48,
            anchorY: 0,
          },
          classes: "net",
        });
        for (const id of pins)
          addEdge(
            "wire:" + JSON.stringify([net.name, id]),
            represented.get(id),
            netKey,
            { netKey, objectKey: netKey, label: "", pins: [id] },
            "wire",
          );
      }
    }
    const crosses = new Map(chain.transitions);
    if (!onlyTrace) {
      for (const pin of Object.values(pkg.pins))
        for (const other of exits(pkg, pin.id, choices))
          crosses.set(transitionId(pin.id, other), [pin.id, other]);
    }
    for (const [id, [a, b]] of crosses) {
      if (!represented.has(a) || !represented.has(b)) continue;
      addEdge(
        id,
        represented.get(a),
        represented.get(b),
        { label: "追踪跨越", pins: [a, b], partKey: "part:" + pkg.pins[a].ref },
        "transition",
      );
    }
    return { nodes, edges, chain };
  }
  // Union collinear runs first: a shared trunk must have one geometric identity.
  // Coordinates are quantized to 0.001 canvas units to absorb layout round-off.
  function junctions(wires, anchors = []) {
    const q = (value) => Math.round(value * 1000);
    const excluded = new Map(),
      groups = new Map(),
      result = [];
    for (const a of anchors) {
      if (!excluded.has(a.netKey)) excluded.set(a.netKey, new Set());
      excluded.get(a.netKey).add(`${q(a.x)},${q(a.y)}`);
    }
    for (const wire of wires) {
      if (!wire.netKey) continue;
      if (!groups.has(wire.netKey))
        groups.set(wire.netKey, { h: new Map(), v: new Map() });
      const g = groups.get(wire.netKey),
        points = wire.points || [];
      for (let i = 1; i < points.length; i++) {
        const a = { x: q(points[i - 1].x), y: q(points[i - 1].y) },
          b = { x: q(points[i].x), y: q(points[i].y) };
        if (a.x === b.x && a.y === b.y) continue;
        const horizontal = a.y === b.y;
        if (!horizontal && a.x !== b.x) continue;
        const lines = horizontal ? g.h : g.v,
          fixed = horizontal ? a.y : a.x;
        const lo = horizontal ? Math.min(a.x, b.x) : Math.min(a.y, b.y);
        const hi = horizontal ? Math.max(a.x, b.x) : Math.max(a.y, b.y);
        if (!lines.has(fixed)) lines.set(fixed, []);
        lines.get(fixed).push([lo, hi]);
      }
    }
    const merge = (lines) => {
      const merged = [];
      for (const [fixed, intervals] of lines) {
        intervals.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
        let current = null;
        for (const [lo, hi] of intervals) {
          if (current && lo <= current.hi)
            current.hi = Math.max(current.hi, hi);
          else {
            current = { fixed, lo, hi };
            merged.push(current);
          }
        }
      }
      return merged;
    };
    for (const [netKey, g] of groups) {
      const hs = merge(g.h),
        vs = merge(g.v);
      if (!hs.length || !vs.length) continue;
      let minX = Infinity,
        maxX = -Infinity,
        minY = Infinity,
        maxY = -Infinity;
      for (const h of hs) {
        minX = Math.min(minX, h.lo);
        maxX = Math.max(maxX, h.hi);
        minY = Math.min(minY, h.fixed);
        maxY = Math.max(maxY, h.fixed);
      }
      for (const v of vs) {
        minX = Math.min(minX, v.fixed);
        maxX = Math.max(maxX, v.fixed);
        minY = Math.min(minY, v.lo);
        maxY = Math.max(maxY, v.hi);
      }
      const cell = Math.max(
        32000,
        Math.ceil(
          Math.sqrt(((maxX - minX) * (maxY - minY)) / (hs.length + vs.length)),
        ),
      );
      const grid = new Map(),
        found = new Set();
      for (let i = 0; i < vs.length; i++) {
        const v = vs[i],
          x = Math.floor(v.fixed / cell);
        for (
          let y = Math.floor(v.lo / cell);
          y <= Math.floor(v.hi / cell);
          y++
        ) {
          const key = `${x},${y}`;
          if (!grid.has(key)) grid.set(key, []);
          grid.get(key).push(i);
        }
      }
      for (const h of hs) {
        const y = Math.floor(h.fixed / cell);
        for (
          let x = Math.floor(h.lo / cell);
          x <= Math.floor(h.hi / cell);
          x++
        ) {
          for (const i of grid.get(`${x},${y}`) || []) {
            const v = vs[i];
            if (
              v.fixed < h.lo ||
              v.fixed > h.hi ||
              h.fixed < v.lo ||
              h.fixed > v.hi
            )
              continue;
            const directions =
              Number(v.fixed > h.lo) +
              Number(v.fixed < h.hi) +
              Number(h.fixed > v.lo) +
              Number(h.fixed < v.hi);
            const key = `${v.fixed},${h.fixed}`;
            if (
              directions < 3 ||
              found.has(key) ||
              excluded.get(netKey)?.has(key)
            )
              continue;
            found.add(key);
            result.push({ netKey, x: v.fixed / 1000, y: h.fixed / 1000 });
          }
        }
      }
    }
    return result.sort(
      (a, b) => a.netKey.localeCompare(b.netKey) || a.x - b.x || a.y - b.y,
    );
  }
  return { classify, exits, trace, topology, transitionId, junctions };
})();
