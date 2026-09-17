"use strict";
// Presentation only: identities and connectivity always come from the frozen package.
const ReviewGraphModel = (() => {
  const icons = {
    resistor:
      '<path d="M2 20h9m26 0h9"/><rect x="11" y="13" width="26" height="14"/>',
    inductor:
      '<path d="M2 24h6c0-18 8-18 8 0 0-18 8-18 8 0 0-18 8-18 8 0 0-18 8-18 8 0h6"/>',
    capacitor: '<path d="M2 20h18m0-12v24m8-24v24m0-12h18"/>',
    diode: '<path d="M2 20h10m22 0h12M12 10v20l20-10zM34 9v22"/>',
    led: '<path d="M2 24h10m22 0h12M12 14v20l20-10zM34 13v22M27 10l7-7m-5 0h5v5m4 4l7-7m-5 0h5v5"/>',
    crystal:
      '<path d="M2 20h11m22 0h11M13 9v22m22-22v22"/><rect x="18" y="8" width="12" height="24"/>',
    transistor:
      '<circle cx="25" cy="20" r="16"/><path d="M2 20h16m0-10v20m0-13L36 5M18 23l18 12"/>',
    ferrite: '<path d="M2 20h44m-30-8l16 0-4 16H12z"/>',
    connector:
      '<rect x="10" y="3" width="28" height="34"/><path d="M3 10h14m-14 10h14M3 30h14"/><circle cx="26" cy="10" r="2"/><circle cx="26" cy="20" r="2"/><circle cx="26" cy="30" r="2"/>',
    ic: '<rect x="12" y="8" width="24" height="24"/><path d="M4 12h8M4 20h8M4 28h8m24-16h8m-8 8h8m-8 8h8M18 2v6m12-6v6M18 32v6m12-6v6"/>',
    regulator:
      '<rect x="10" y="9" width="28" height="23"/><path d="M2 20h8m28 0h8M24 32v7M17 20h14m-7-6v12"/>',
    switch:
      '<path d="M2 27h10m24 0h10M12 27L33 10"/><circle cx="12" cy="27" r="2"/><circle cx="36" cy="27" r="2"/>',
    jumper:
      '<path d="M2 27h10m24 0h10M12 22V10h24v12"/><circle cx="12" cy="27" r="3"/><circle cx="36" cy="27" r="3"/>',
    testpoint: '<circle cx="24" cy="12" r="7"/><path d="M24 19v19"/>',
    generic:
      '<path d="M12 4h24l10 16-10 16H12L2 20z"/><path d="M19 15a5 5 0 0 1 10 0c0 4-5 3-5 8m0 4v1"/>',
    power: '<path d="M24 20V3m-7 7 7-7 7 7"/>',
    nc: '<path d="M12 8l24 24m0-24L12 32"/>',
    ground: '<path d="M24 24v8m-13 0h26m-21 6h16m-11 6h6"/>',
  };
  const images = new Map();
  function image(kind, rotation = 0) {
    const key = kind === "ground" ? `${kind}:${rotation}` : kind;
    if (images.has(key)) return images.get(key);
    const height = kind === "ground" ? 48 : 40;
    const transform =
      kind === "ground" ? ` transform="rotate(${rotation} 24 24)"` : "";
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="${height}" viewBox="0 0 48 ${height}"><g${transform} fill="none" stroke="#34577c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${icons[kind] || icons.generic}</g></svg>`;
    const uri = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    // Cache the four common directions, without accumulating arbitrary angles.
    if (kind !== "ground" || rotation % 90 === 0) images.set(key, uri);
    return uri;
  }
  function groundAppearance(source, anchor, side = 1) {
    let dx = anchor.x - source.x,
      dy = anchor.y - source.y;
    if (Math.hypot(dx, dy) < 1e-6) {
      dx = side < 0 ? -1 : 1;
      dy = 0;
    }
    const rotation =
      ((((Math.atan2(dy, dx) * 180) / Math.PI - 90) % 360) + 360) % 360;
    return { rotation, image: image("ground", rotation) };
  }
  function geometry(part, pins) {
    const sorted = part.pins
      .map((id) => pins[id])
      .sort(
        (a, b) =>
          a.num.localeCompare(b.num, "en", { numeric: true }) ||
          a.id.localeCompare(b.id),
      );
    const half = Math.ceil(sorted.length / 2);
    const labelWidth = Math.max(
      0,
      ...sorted.map(
        (p) => [...`${p.num} · ${p.name}${p.nc ? " NC" : ""}`].length * 7,
      ),
    );
    const width = Math.max(150, 72 + 2 * labelWidth);
    const height = Math.max(64, half * 48 + 24);
    return {
      width,
      height,
      image: image(part.category),
      pins: sorted.map((pin, i) => {
        const side = i < half ? -1 : 1;
        const row = i < half ? i : i - half;
        const count = i < half ? half : sorted.length - half;
        return {
          pin,
          side,
          dx: side * (width / 2 + 20),
          dy: (row - (count - 1) / 2) * 48,
        };
      }),
    };
  }
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
  return {
    image,
    geometry,
    groundAppearance,
    classify,
    categories: Object.keys(icons).filter(
      (k) => !["generic", "power", "ground", "nc"].includes(k),
    ),
  };
})();
