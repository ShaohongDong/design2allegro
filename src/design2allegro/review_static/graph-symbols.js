"use strict";
// Pin badges and two-terminal bodies. Polarity is bound by the model, not guessed.
const ReviewSymbols = (() => {
  const shapes = {
    resistor:
      '<path d="M2 20h8m28 0h8"/><rect x="10" y="13" width="28" height="14" rx="1"/>',
    capacitor: '<path d="M2 20h17m10 0h17M19 7v26M29 7v26"/>',
    inductor:
      '<path d="M2 25h6c0-19 8-19 8 0 0-19 8-19 8 0 0-19 8-19 8 0 0-19 8-19 8 0h6"/>',
    ferrite: '<path d="M2 20h44"/><path d="M17 8h20L30 32H10z"/>',
    crystal:
      '<path d="M2 20h11m22 0h11M13 9v22M35 9v22"/><rect x="18" y="7" width="12" height="26"/>',
    diode: '<path d="M2 20h12m20 0h12M14 9v22l20-11zM34 8v24"/>',
    led: '<path d="M2 26h12m20 0h12M14 16v20l20-10zM34 15v22M25 10l8-8m-5 0h5v5m3 6 8-8m-5 0h5v5"/>',
    transistor:
      '<circle cx="26" cy="20" r="17"/><path d="M2 20h17M19 9v22M19 16 38 5M19 24l19 11"/>',
    ic: '<rect x="12" y="7" width="24" height="26" rx="3"/><path d="M4 12h8M4 20h8M4 28h8M36 12h8M36 20h8M36 28h8M18 2v5M30 2v5M18 33v5M30 33v5"/><circle cx="19" cy="14" r="1.5"/>',
    regulator:
      '<rect x="9" y="8" width="30" height="24" rx="3"/><path d="M2 20h7M39 20h7M24 32v6M15 21h5l3-6 4 10 3-4h4"/>',
    connector:
      '<path d="M8 4h30v32H8zM2 10h16M2 20h16M2 30h16"/><circle cx="27" cy="10" r="2.5"/><circle cx="27" cy="20" r="2.5"/><circle cx="27" cy="30" r="2.5"/>',
    switch:
      '<path d="M2 29h10m24 0h10M13 26 33 10"/><circle cx="12" cy="29" r="2.5"/><circle cx="36" cy="29" r="2.5"/>',
    jumper:
      '<path d="M2 28h10m24 0h10M12 22V9h24v13"/><circle cx="12" cy="28" r="3"/><circle cx="36" cy="28" r="3"/>',
    testpoint:
      '<circle cx="24" cy="16" r="10"/><circle cx="24" cy="16" r="4"/><path d="M24 26v12"/>',
    generic:
      '<path d="M24 3 43 20 24 37 5 20z"/><circle cx="24" cy="20" r="4"/>',
  };
  const colors = {
    resistor: "#477083",
    capacitor: "#477083",
    inductor: "#477083",
    ferrite: "#477083",
    crystal: "#477083",
    diode: "#88613f",
    led: "#88613f",
    transistor: "#88613f",
    ic: "#536bb0",
    regulator: "#347b6a",
    connector: "#78629b",
    switch: "#78629b",
    jumper: "#78629b",
    testpoint: "#347b6a",
    generic: "#718096",
  };
  const cache = new Map();
  function image({
    category = "generic",
    width,
    height,
    anchorY = 0,
    status = "pending",
    dnp = false,
    nc = false,
    ground = false,
    groundOffsetX = 0,
    emphasis = "",
    net = false,
    terminal = false,
    body = false,
    halfSpan = 0,
    angle = 0,
  }) {
    if (!Object.hasOwn(shapes, category)) category = "generic";
    const key = JSON.stringify([
      category,
      width,
      height,
      anchorY,
      status,
      dnp,
      nc,
      ground,
      groundOffsetX,
      emphasis,
      net,
      terminal,
      body,
      halfSpan,
      angle,
    ]);
    if (cache.has(key)) return cache.get(key);
    const x = width / 2,
      y = height / 2 + anchorY;
    const color = dnp ? "#8d98a6" : colors[category];
    const state =
      status === "issue"
        ? "#c34444"
        : status === "approved"
          ? "#268168"
          : net
            ? "#558798"
            : color;
    const halo =
      emphasis === "highlight" ? "#dc8c22" : emphasis ? "#3475bd" : null;
    const glyph =
      net || terminal || body
        ? ""
        : `<g transform="translate(12 6) scale(.8)" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${shapes[category]}</g>`;
    const ring =
      halo && !body
        ? `<circle cx="${x}" cy="${y}" r="12" fill="${halo}" fill-opacity=".12" stroke="${halo}" stroke-width="1.5"/>`
        : "";
    const anchor = body
      ? ""
      : nc
        ? `<path d="M${x - 4} ${y - 4}l8 8m0-8-8 8" stroke="${state}" stroke-width="2"/>`
        : `<circle cx="${x}" cy="${y}" r="${net ? 3.5 : 4}" fill="${state}" stroke="white" stroke-width="1.2"/>`;
    const mark =
      status === "approved"
        ? `<path d="M${x + 9} ${y + 8}l3 3 6-7" fill="none" stroke="${state}" stroke-width="1.8"/>`
        : status === "issue"
          ? `<path d="M${x + 13} ${y + 4}v6m0 3v1" stroke="${state}" stroke-width="2"/>`
          : "";
    // Local termination belongs to the pin, so dragging and filtering cannot
    // separate it from its anchor or introduce another review object.
    const groundSymbol =
      ground && !nc && !net
        ? `<path data-role="ground" d="M${x} ${y}h${groundOffsetX}v24m-12 0h24m-20 5h16m-12 5h8" fill="none" stroke="${halo || state}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`
        : "";
    const bodyShapes = {
      resistor: shapes.resistor,
      capacitor: shapes.capacitor,
      inductor:
        '<path d="M2 20h6c0-19 8-19 8 0 0-19 8-19 8 0 0-19 8-19 8 0 0-19 8-19 8 0h6"/>',
      ferrite: shapes.ferrite,
      crystal: shapes.crystal,
      diode: shapes.diode,
      led: '<path d="M2 20h12m20 0h12M14 9v22l20-11zM34 8v24M24 5l7-7m-5 0h5v5m4 5 7-7m-5 0h5v5"/>',
      switch:
        '<path d="M2 20h10m24 0h10M13 17 33 1"/><circle cx="12" cy="20" r="2.5"/><circle cx="36" cy="20" r="2.5"/>',
      jumper:
        '<path d="M2 20h10m24 0h10M12 17V1h24v16"/><circle cx="12" cy="20" r="3"/><circle cx="36" cy="20" r="3"/>',
    };
    const bodyGlyph = body
      ? `<g data-role="component" transform="rotate(${angle} ${x} ${y})" fill="none" stroke="${halo || state}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M${x - halfSpan} ${y}H${x - 44}M${x + 44} ${y}H${x + halfSpan}"/><g transform="translate(${x - 48} ${y - 40}) scale(2)">${bodyShapes[category] || '<path d="M2 20h8m28 0h8"/><rect x="10" y="9" width="28" height="22"/>'}</g></g>`
      : "";
    const statusMark = body
      ? `<g transform="translate(0 38)">${mark}</g>`
      : mark;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${glyph}${bodyGlyph}${groundSymbol}${ring}${anchor}${statusMark}</svg>`;
    const uri = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    // Avoid retaining unlimited label-width variants across repeated package views.
    if (cache.size >= 2048) cache.clear();
    cache.set(key, uri);
    return uri;
  }
  return { image, categories: Object.keys(shapes) };
})();
