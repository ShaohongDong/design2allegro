"use strict";
const pageSize = 60;
const collator = new Intl.Collator("zh-CN", { numeric: true });
const view = {
  part: null,
  net: null,
  pin: null,
  side: "left",
  left: { page: 0, sort: "num", reverse: false },
  right: { page: 0, sort: "reference", reverse: false },
};
const selected = new Set();
let selectionSide = null;
const history = [];
const filterIds = [
  "part-search",
  "module-filter",
  "assembly-filter",
  "part-status",
  "net-search",
  "net-status",
  "left-search",
  "left-status",
  "right-search",
  "right-status",
];
const searchIndex = new Map();
let parts = [],
  nets = [];
function modulePath(part) {
  return part.hierarchy.slice(0, -1).join("/");
}
function partOf(pin) {
  return pkg.parts[pin.ref];
}
function pinValue(pin, field) {
  if (field === "module") return modulePath(partOf(pin)) || "顶层";
  if (field === "assembly")
    return partOf(pin).assembly === "dnp" ? "DNP" : "已装配";
  if (field === "status") return entry(pin.key).status;
  if (field === "net") return pin.nc ? "NC" : pin.net;
  return pin[field] ?? "";
}
function initializeIndex() {
  parts = Object.values(pkg.parts).sort((a, b) =>
    collator.compare(a.reference, b.reference),
  );
  nets = Object.values(pkg.nets).sort((a, b) =>
    collator.compare(a.name, b.name),
  );
  for (const p of Object.values(pkg.pins))
    searchIndex.set(
      p.key,
      [
        p.reference,
        p.num,
        p.name,
        p.type_name,
        p.nc ? "NC" : p.net,
        partOf(p).path,
        partOf(p).assembly,
      ]
        .join(" ")
        .toLowerCase(),
    );
  for (const p of parts)
    searchIndex.set(
      p.key,
      [
        p.reference,
        p.device,
        p.path,
        p.footprint,
        ...Object.values(p.properties),
        ...p.pins.map((id) => searchIndex.get(pkg.pins[id].key)),
      ]
        .join(" ")
        .toLowerCase(),
    );
  for (const n of nets)
    searchIndex.set(
      n.key,
      [
        n.name,
        n.allegro_name,
        ...n.aliases,
        ...n.pins.map((id) => searchIndex.get(pkg.pins[id].key)),
      ]
        .join(" ")
        .toLowerCase(),
    );
  for (const path of [...new Set(parts.map(modulePath))].sort(
    collator.compare,
  )) {
    const option = node("option", path || "顶层");
    option.value = path;
    $("module-filter").append(option);
  }
}
function matches(x, query, status) {
  return (
    (!query || searchIndex.get(x.key).includes(query)) &&
    (status === "all" || entry(x.key).status === status)
  );
}
function pickerRows(kind) {
  const query = $(kind + "-search")
      .value.trim()
      .toLowerCase(),
    status = $(kind + "-status").value;
  return (kind === "part" ? parts : nets).filter(
    (x) =>
      matches(x, query, status) &&
      (kind !== "part" ||
        (($("module-filter").value === "all" ||
          modulePath(x) === $("module-filter").value) &&
          ($("assembly-filter").value === "all" ||
            x.assembly === $("assembly-filter").value))),
  );
}
function pinRows(side, applyStatus = true) {
  const owner = side === "left" ? pkg.parts[view.part] : pkg.nets[view.net];
  const query = $(side + "-search")
    .value.trim()
    .toLowerCase();
  const status = applyStatus ? $(side + "-status").value : "all";
  return (owner?.pins || [])
    .map((id) => pkg.pins[id])
    .filter((p) => matches(p, query, status))
    .sort(
      (a, b) =>
        (view[side].reverse ? -1 : 1) *
        (collator.compare(
          pinValue(a, view[side].sort),
          pinValue(b, view[side].sort),
        ) || collator.compare(a.id, b.id)),
    );
}
function remember() {
  history.push({
    view: structuredClone(view),
    currentKey,
    filters: Object.fromEntries(filterIds.map((id) => [id, $(id).value])),
    scroll: [
      $("left-scroll").scrollTop,
      $("left-scroll").scrollLeft,
      $("right-scroll").scrollTop,
      $("right-scroll").scrollLeft,
    ],
  });
  if (history.length > 100) history.shift();
  $("back").disabled = false;
}
function clearSelection() {
  selected.clear();
  selectionSide = null;
}
function resetPinFilter(side) {
  $(side + "-search").value = "";
  $(side + "-status").value = "all";
  view[side].page = 0;
}
function revealPin(side, id) {
  let index = pinRows(side).findIndex((p) => p.id === id);
  if (index < 0) {
    resetPinFilter(side);
    index = pinRows(side).findIndex((p) => p.id === id);
  }
  view[side].page = Math.max(0, Math.floor(index / pageSize));
}
function navigate(key, side = "left") {
  if (!object(key)) return;
  remember();
  clearSelection();
  $("navigation-message").textContent = "";
  const x = object(key),
    kind = key.split(":")[0];
  if (kind === "part") {
    view.part = x.id;
    view.pin = null;
    view.net = null;
    resetPinFilter("left");
    resetPinFilter("right");
  } else if (kind === "net") {
    view.net = x.name;
    resetPinFilter("right");
    if (view.pin && pkg.pins[view.pin].net !== x.name) view.pin = null;
  } else {
    if (view.part !== x.ref) {
      view.part = x.ref;
      resetPinFilter("left");
    }
    if (view.net !== (x.nc ? null : x.net)) {
      view.net = x.nc ? null : x.net;
      resetPinFilter("right");
    }
    view.pin = x.id;
    revealPin("left", x.id);
    if (!x.nc) revealPin("right", x.id);
  }
  view.side = side;
  currentKey = key;
  renderTables();
  renderReview();
  for (const s of ["left", "right"])
    $(s + "-table")
      .querySelector("tr.active")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
}
function renderPicker(kind) {
  const picker = $(kind + "-picker"),
    items = pickerRows(kind);
  const current = kind === "part" ? pkg.parts[view.part] : pkg.nets[view.net];
  picker.replaceChildren();
  const blank = node(
    "option",
    items.length
      ? `选择${kind === "part" ? "元件" : "网络"} · ${items.length} 个结果`
      : "没有匹配的对象",
  );
  blank.value = "";
  picker.append(blank);
  if (current && !items.includes(current)) {
    const o = node(
      "option",
      `当前定位（筛选外）：${kind === "part" ? current.reference : current.name}`,
    );
    o.value = current.key;
    picker.append(o);
  }
  for (const x of items) {
    const o = node(
      "option",
      kind === "part" ? `${x.reference} · ${x.device} · ${x.path}` : x.name,
    );
    o.value = x.key;
    picker.append(o);
  }
  picker.value = current?.key || "";
}
const columns = {
  left: [
    ["num", "焊盘"],
    ["name", "逻辑名称"],
    ["type_name", "类型"],
    ["net", "网络 / NC"],
    ["status", "状态"],
  ],
  right: [
    ["reference", "位号"],
    ["module", "模块"],
    ["num", "焊盘"],
    ["name", "逻辑名称"],
    ["type_name", "类型"],
    ["assembly", "装配"],
    ["status", "状态"],
  ],
};
function renderTable(side) {
  const all = pinRows(side),
    state = view[side];
  state.page = Math.max(
    0,
    Math.min(state.page, Math.ceil(all.length / pageSize) - 1),
  );
  const visible = all.slice(state.page * pageSize, (state.page + 1) * pageSize);
  const table = $(side + "-table"),
    head = table.querySelector("thead"),
    body = table.querySelector("tbody");
  const header = node("tr");
  header.append(node("th", "选择"));
  for (const [field, title] of columns[side]) {
    const th = node("th");
    th.scope = "col";
    if (state.sort === field)
      th.setAttribute("aria-sort", state.reverse ? "descending" : "ascending");
    th.append(
      button(
        title + (state.sort === field ? (state.reverse ? " ↓" : " ↑") : ""),
        () => {
          remember();
          state.reverse = state.sort === field ? !state.reverse : false;
          state.sort = field;
          state.page = 0;
          clearSelection();
          renderTables();
        },
      ),
    );
    header.append(th);
  }
  head.replaceChildren(header);
  body.replaceChildren();
  for (const pin of visible) {
    const row = node("tr");
    row.dataset.key = pin.key;
    row.tabIndex = 0;
    row.classList.toggle("active", view.pin === pin.id);
    row.classList.toggle(
      "selected",
      selectionSide === side && selected.has(pin.key),
    );
    row.setAttribute("aria-label", `${pin.reference}.${pin.num} ${pin.name}`);
    const td = node("td"),
      cb = node("input");
    cb.type = "checkbox";
    cb.checked = selectionSide === side && selected.has(pin.key);
    cb.setAttribute("aria-label", `选择 ${pin.reference}.${pin.num}`);
    cb.onclick = (e) => e.stopPropagation();
    cb.onchange = () => {
      if (selectionSide !== side) clearSelection();
      selectionSide = side;
      cb.checked ? selected.add(pin.key) : selected.delete(pin.key);
      renderTables();
    };
    td.append(cb);
    row.append(td);
    for (const [field] of columns[side]) {
      const cell = node("td");
      if (field === "status") cell.append(badge(entry(pin.key).status));
      else cell.textContent = pinValue(pin, field);
      row.append(cell);
    }
    row.onclick = () => navigate(pin.key, side);
    row.onkeydown = (e) => {
      if (e.target === row && ["Enter", " "].includes(e.key)) {
        e.preventDefault();
        navigate(pin.key, side);
      }
    };
    body.append(row);
  }
  if (!visible.length) {
    const row = node("tr"),
      cell = node(
        "td",
        side === "left" ? "没有匹配的引脚" : "没有匹配的端点",
        "empty",
      );
    cell.colSpan = columns[side].length + 1;
    row.append(cell);
    body.append(row);
  }
  const total =
    (side === "left" ? pkg.parts[view.part] : pkg.nets[view.net])?.pins
      .length || 0;
  $(side + "-count").textContent = `当前 ${all.length} / 总数 ${total}`;
  $(side + "-page").textContent =
    `${all.length ? state.page + 1 : 0} / ${Math.ceil(all.length / pageSize)}`;
  $(side + "-previous").disabled = state.page === 0;
  $(side + "-next").disabled = (state.page + 1) * pageSize >= all.length;
  $(side + "-select").disabled = !visible.length;
}
function renderTables() {
  renderPicker("part");
  renderPicker("net");
  const part = pkg.parts[view.part],
    net = pkg.nets[view.net];
  $("part-title").textContent = part
    ? `${part.reference} · ${part.assembly === "dnp" ? "DNP · " : ""}${part.device}`
    : "尚未选择元件";
  $("net-title").textContent =
    net?.name ||
    (view.pin && pkg.pins[view.pin].nc ? "NC · 明确不连接" : "尚未选择网络");
  for (const id of ["review-part", "part-details"]) $(id).disabled = !part;
  for (const id of ["review-net", "net-details"]) $(id).disabled = !net;
  $("right-empty").textContent =
    !net && view.pin && pkg.pins[view.pin].nc
      ? "此引脚明确不连接，没有网络端点。"
      : "";
  renderTable("left");
  renderTable("right");
  $("selection-count").textContent = selected.size
    ? `${selectionSide === "left" ? "左侧" : "右侧"}已选 ${selected.size} 个引脚`
    : "未选择引脚";
  $("batch-apply").disabled = !selected.size;
  $("batch-apply").textContent = selected.size
    ? `标记选中的 ${selected.size} 个引脚`
    : "标记选中引脚";
}
function bindTables() {
  for (const id of filterIds) {
    const apply = () => {
      clearSelection();
      view.left.page = 0;
      view.right.page = 0;
      renderTables();
    };
    $(id).addEventListener(
      $(id).tagName === "INPUT" ? "input" : "change",
      apply,
    );
  }
  for (const kind of ["part", "net"])
    $(kind + "-picker").onchange = (e) => {
      if (e.target.value)
        navigate(e.target.value, kind === "part" ? "left" : "right");
    };
  for (const side of ["left", "right"]) {
    for (const [name, delta] of [
      ["previous", -1],
      ["next", 1],
    ])
      $(side + "-" + name).onclick = () => {
        remember();
        view[side].page += delta;
        renderTables();
        $(side + "-scroll").scrollTop = 0;
      };
    $(side + "-select").onclick = () => {
      if (selectionSide !== side) clearSelection();
      selectionSide = side;
      pinRows(side)
        .slice(view[side].page * pageSize, (view[side].page + 1) * pageSize)
        .forEach((p) => selected.add(p.key));
      renderTables();
    };
  }
  $("clear-selection").onclick = () => {
    clearSelection();
    renderTables();
  };
  $("batch-apply").onclick = () => {
    for (const key of [...selected])
      pending[key] = { ...pending[key], status: $("batch-status").value };
    clearSelection();
    refreshProgress();
    renderTables();
    renderReview();
    flush();
  };
  $("back").onclick = () => {
    const prev = history.pop();
    if (!prev) return;
    Object.assign(view, prev.view);
    currentKey = prev.currentKey;
    for (const [id, value] of Object.entries(prev.filters)) $(id).value = value;
    clearSelection();
    renderTables();
    renderReview();
    [
      $("left-scroll").scrollTop,
      $("left-scroll").scrollLeft,
      $("right-scroll").scrollTop,
      $("right-scroll").scrollLeft,
    ] = prev.scroll;
    $("back").disabled = !history.length;
    $("navigation-message").textContent = "";
  };
}
