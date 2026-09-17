/* Shared symbol, anchor and label geometry for known two-terminal passives. */
const kinds = new Set(["resistor", "capacitor", "inductor"]);
const dirs = ["W", "N", "E", "S"];
function turn(x, y, rotation) {
  return rotation === 90
    ? { x: -y, y: x }
    : rotation === 180
      ? { x: -x, y: -y }
      : rotation === 270
        ? { x: y, y: -x }
        : { x, y };
}
export function translate(n, dx, dy) {
  n.x += dx;
  n.y += dy;
  for (const key of ["box", "labelBox"])
    if (n[key]) {
      n[key].x1 += dx;
      n[key].x2 += dx;
      n[key].y1 += dy;
      n[key].y2 += dy;
    }
}
export function passiveSpec(part, pins) {
  if (
    !part ||
    !kinds.has(part.category) ||
    pins.length !== 2 ||
    part.pins?.length !== 2
  )
    return null;
  const polarized =
    part.properties?.polarized === true || part.electrical?.polarized === true;
  const positive = pins.find(
    (p) =>
      p.electrical?.polarity === "positive" ||
      ["+", "POS", "POSITIVE"].includes(p.name?.toUpperCase()),
  );
  // Never infer capacitor polarity from pin number alone.
  if (part.category === "capacitor" && polarized && !positive) return null;
  return { kind: part.category, positive: polarized ? positive?.id : null };
}
export function refreshPassive(scene, owner) {
  if (!owner.symbol) return;
  const pins = owner.symbol.pinIds.map((id) =>
    scene.nodes.find((n) => n.id === id),
  );
  const rotation = owner.rotation || 0,
    vertical = rotation % 180 !== 0;
  owner.width = vertical ? 24 : 36;
  owner.height = vertical ? 36 : 24;
  for (const [i, p] of pins.entries()) {
    const q = turn(i ? 36 : -36, 0, rotation),
      side = dirs[(i * 2 + rotation / 90) % 4];
    translate(p, owner.x + q.x - p.x, owner.y + q.y - p.y);
    p.direction = side;
    Object.assign(p.data, { dx: q.x, dy: q.y });
    const label = turn(i ? 29 : -29, -14, rotation);
    const text = scene.pkg.pins[p.id.slice(4)]?.num || p.data.label;
    const pw = String(text).length * 6;
    p.compactLabel = true;
    p.labelBox = {
      x1: owner.x + label.x - pw / 2,
      x2: owner.x + label.x + pw / 2,
      y1: owner.y + label.y - 10,
      y2: owner.y + label.y,
      w: pw,
      h: 10,
    };
    for (const w of scene.wires.filter((w) => w.source === p.id)) {
      const n = scene.nodes.find((n) => n.id === w.target);
      if (n?.data.owner !== owner.id || n.classes.includes("pin")) continue;
      const d = turn(i ? 1 : -1, 0, rotation);
      translate(n, p.x + d.x * 65 - n.x, p.y + d.y * 65 - n.y);
      n.direction = side;
      Object.assign(n.data, { dx: n.x - owner.x, dy: n.y - owner.y });
    }
  }
  const lines = String(owner.data.label || "").split("\n");
  const w = Math.max(...lines.map((s) => [...s].length * 6.5), 1),
    h = lines.length * 14;
  owner.labelBox = vertical
    ? {
        x1: owner.x + 26,
        x2: owner.x + 26 + w,
        y1: owner.y - h / 2,
        y2: owner.y + h / 2,
        w,
        h,
      }
    : {
        x1: owner.x - w / 2,
        x2: owner.x + w / 2,
        y1: owner.y - 30 - h,
        y2: owner.y - 30,
        w,
        h,
      };
}
export function compactPassives(scene) {
  for (const owner of scene.nodes.filter((n) => n.classes.includes("part"))) {
    const part = scene.pkg.parts?.[owner.id.slice(5)];
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
    const spec = passiveSpec(
      part,
      pins.map((n) => scene.pkg.pins[n.id.slice(4)]),
    );
    if (!spec) continue;
    if (owner.rotation === undefined)
      owner.rotation = Math.max(0, dirs.indexOf(pins[0].direction)) * 90;
    owner.symbol = { ...spec, pinIds: pins.map((n) => n.id) };
    refreshPassive(scene, owner);
  }
  return scene;
}
export function symbolPath(symbol) {
  if (symbol.kind === "resistor") return "M-36 0H-18M18 0H36M-18 -7H18V7H-18Z";
  if (symbol.kind === "capacitor") return "M-36 0H-6M-6 -12V12M6 -12V12M6 0H36";
  return "M-36 0H-18C-18 -16 -9 -16 -9 0C-9 -16 0 -16 0 0C0 -16 9 -16 9 0C9 -16 18 -16 18 0H36";
}

export function polarityBox(n) {
  if (!n.symbol?.positive) return null;
  const first = n.symbol.pinIds[0] === "pin:" + n.symbol.positive,
    x = first ? -17 : 10;
  const ps = [
    [x, -26],
    [x + 9, -26],
    [x, -16],
    [x + 9, -16],
  ].map(([x, y]) => turn(x, y, n.rotation || 0));
  return {
    x1: n.x + Math.min(...ps.map((p) => p.x)),
    x2: n.x + Math.max(...ps.map((p) => p.x)),
    y1: n.y + Math.min(...ps.map((p) => p.y)),
    y2: n.y + Math.max(...ps.map((p) => p.y)),
  };
}
