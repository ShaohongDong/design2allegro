"use strict";
const $ = (id) => document.getElementById(id);
const statusNames = { pending: "待审", approved: "通过", issue: "有问题" };
let pkg,
  record,
  cy,
  currentKey = null,
  tab = "parts",
  page = 0;
let selected = new Set(),
  collapsed = new Set(),
  manuallyHidden = new Set(),
  focusKeys = null;
let pending = {},
  inFlight = {},
  saving = null,
  blocked = false,
  saveTimer,
  previewRecord = null,
  previewRevision = null;
let rows = [],
  syncing = false;
const pageSize = 60;
function node(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function button(text, fn, cls = "link") {
  const b = node("button", text, cls);
  b.type = "button";
  b.onclick = fn;
  return b;
}
function message(text) {
  $("error").textContent = text;
  $("error").hidden = !text;
}
function saveMessage(text, cls = "") {
  $("save-state").textContent = text;
  $("save-state").className = "save-state " + cls;
  $("retry").hidden = !blocked;
}
async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Review-Token": pkg?.token || "",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const err = new Error(data.error || "请求失败");
    err.status = response.status;
    throw err;
  }
  return data;
}
function entry(key) {
  return {
    ...{ status: "pending", note: "" },
    ...record.entries[key],
    ...inFlight[key],
    ...pending[key],
  };
}
function object(key) {
  const i = key.indexOf(":");
  const kind = key.slice(0, i);
  return { part: pkg.parts, pin: pkg.pins, net: pkg.nets }[kind]?.[
    key.slice(i + 1)
  ];
}
function badge(status) {
  return node("span", statusNames[status] || status, "status " + status);
}
function queueChange(key, patch) {
  pending[key] = { ...pending[key], ...patch };
  clearTimeout(saveTimer);
  if (!blocked) saveMessage("有修改，正在保存…", "pending");
  refreshProgress();
  renderList();
  styleGraph();
  saveTimer = setTimeout(flush, 450);
}
async function flush() {
  clearTimeout(saveTimer);
  if (saving) {
    await saving;
    if (!blocked && Object.keys(pending).length) return flush();
    return !blocked;
  }
  if (blocked) return false;
  if (!Object.keys(pending).length) return true;
  const changes = pending;
  pending = {};
  inFlight = changes;
  saveMessage("正在保存…", "pending");
  saving = (async () => {
    try {
      record = await api("/api/review", "PATCH", {
        revision: record.revision,
        changes,
      });
      message("");
      saveMessage("已保存 · 修订 " + record.revision);
    } catch (err) {
      for (const [key, value] of Object.entries(changes))
        pending[key] = { ...value, ...pending[key] };
      blocked = true;
      message(
        err.status === 409
          ? "其他页面已更新记录。本地修改仍保留；可导出本地草稿，或刷新记录后重新编辑。"
          : "保存失败，本地修改仍保留：" + err.message,
      );
      saveMessage("未保存，请重试", "failed");
    }
  })();
  await saving;
  saving = null;
  inFlight = {};
  refreshProgress();
  renderList();
  styleGraph();
  const time = $("note-time");
  if (time && currentKey)
    time.textContent = pending[currentKey]
      ? "本地修改尚未保存"
      : record.entries[currentKey]?.updated_at
        ? "更新于 " +
          new Date(record.entries[currentKey].updated_at).toLocaleString()
        : "尚无人工记录";
  if (!blocked && Object.keys(pending).length) return flush();
  return !blocked;
}
function refreshProgress() {
  const totals = { pending: 0, approved: 0, issue: 0 };
  for (const key of Object.keys(pkg.objects)) totals[entry(key).status]++;
  $("progress").textContent =
    `人工审查（含引脚）  待审 ${totals.pending}  /  通过 ${totals.approved}  /  有问题 ${totals.issue}`;
}
function partText(p) {
  return [
    p.reference,
    p.id,
    p.path,
    p.device,
    p.footprint,
    ...Object.values(p.properties),
    ...p.pins.flatMap((k) => {
      const x = pkg.pins[k];
      return [
        x.name,
        x.num,
        x.reference + "." + x.num,
        x.reference + "." + x.name,
        x.net || "NC",
      ];
    }),
  ]
    .join(" ")
    .toLowerCase();
}
function netText(n) {
  return [
    n.name,
    n.allegro_name,
    ...n.aliases,
    ...n.pins.flatMap((k) => {
      const p = pkg.pins[k];
      return [
        p.name,
        p.reference,
        p.reference + "." + p.num,
        pkg.parts[p.ref].path,
      ];
    }),
  ]
    .join(" ")
    .toLowerCase();
}
let searchable = new Map();
function filteredRows() {
  const q = $("search").value.trim().toLowerCase(),
    status = $("status-filter").value,
    assembly = $("assembly-filter").value;
  if (tab === "diagnostics")
    return pkg.diagnostics.filter(
      (d) =>
        ($("diagnostic-filter").value === "all" || d.status !== "PASS") &&
        (!q ||
          [d.rule, d.object, d.message, ...d.targets.map((k) => pkg.objects[k])]
            .join(" ")
            .toLowerCase()
            .includes(q)),
    );
  const all = Object.values(tab === "parts" ? pkg.parts : pkg.nets);
  return all.filter(
    (x) =>
      (!q || searchable.get(x.key).includes(q)) &&
      (status === "all" || entry(x.key).status === status) &&
      (assembly === "all" ||
        (tab === "parts"
          ? x.assembly === assembly
          : x.pins.some(
              (k) => pkg.parts[pkg.pins[k].ref].assembly === assembly,
            ))),
  );
}
function renderList() {
  rows = filteredRows();
  page = Math.max(0, Math.min(page, Math.ceil(rows.length / pageSize) - 1));
  const visible = rows.slice(page * pageSize, (page + 1) * pageSize);
  $("object-list").replaceChildren();
  $("list-count").textContent = rows.length + " 个结果";
  $("status-filter").hidden = tab === "diagnostics";
  $("assembly-filter").hidden = tab === "diagnostics";
  $("diagnostic-filter").hidden = tab !== "diagnostics";
  $("select-page").hidden = tab === "diagnostics";
  for (const x of visible) {
    const row = node(
      "div",
      undefined,
      "object-row" + (x.key === currentKey ? " selected" : ""),
    );
    row.dataset.key = x.key || "diagnostic:" + x.index;
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    if (x.key) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selected.has(x.key);
      cb.setAttribute("aria-label", "选择 " + pkg.objects[x.key]);
      cb.onclick = (e) => e.stopPropagation();
      cb.onchange = () => {
        cb.checked ? selected.add(x.key) : selected.delete(x.key);
        syncSelection();
      };
      row.append(cb);
    }
    const main = node("div", undefined, "object-main"),
      top = node("div", undefined, "object-top");
    top.append(
      node(
        "strong",
        tab === "parts" ? x.reference : tab === "nets" ? x.name : x.rule,
      ),
    );
    if (x.key) top.append(badge(entry(x.key).status));
    else
      top.append(
        node(
          "span",
          {
            PASS: "通过",
            FAIL: "失败",
            UNKNOWN: "未知",
            NOT_APPLICABLE: "不适用",
            WAIVED: "已豁免",
          }[x.status] || x.status,
          "status " +
            (x.status === "PASS"
              ? "approved"
              : ["FAIL", "UNKNOWN"].includes(x.status)
                ? "issue"
                : "pending"),
        ),
      );
    main.append(
      top,
      node(
        "div",
        tab === "parts"
          ? `${x.properties.mpn || x.value || x.device} · ${x.footprint}`
          : tab === "nets"
            ? `${x.pins.length} 个端点 · ${x.allegro_name}`
            : `${x.severity} · ${x.message}`,
        "object-sub",
      ),
    );
    if (tab === "parts")
      main.append(
        node(
          "div",
          x.path + (x.assembly === "dnp" ? " · DNP" : ""),
          "object-sub",
        ),
      );
    row.append(main);
    const activate = () => (x.key ? selectObject(x.key) : showDiagnostic(x));
    row.onclick = activate;
    row.onkeydown = (e) => {
      if (e.target === row && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        activate();
      }
    };
    $("object-list").append(row);
  }
  if (!visible.length)
    $("object-list").append(node("p", "没有匹配的对象", "nothing"));
  $("page-number").textContent =
    `${rows.length ? page + 1 : 0} / ${Math.ceil(rows.length / pageSize)}`;
  $("previous").disabled = page === 0;
  $("next").disabled = (page + 1) * pageSize >= rows.length;
  updateSelectionCount();
}
function updateSelectionCount() {
  $("selection-count").textContent = `已选 ${selected.size} 个对象`;
  $("selection-count").title = [...selected]
    .map((k) => pkg.objects[k])
    .join("\n");
  $("batch-apply").disabled = !selected.size;
}
function syncSelection() {
  syncing = true;
  cy?.nodes().forEach((n) => (n.data("key") ? n.selectify() : n.unselectify()));
  cy?.nodes().forEach((n) =>
    selected.has(n.data("key")) ? n.select() : n.unselect(),
  );
  syncing = false;
  updateSelectionCount();
}
function section(title) {
  return node("div", title, "section-title");
}
function fields(values) {
  const dl = node("dl");
  for (const [name, value] of values) {
    dl.append(
      node("dt", name),
      node(
        "dd",
        typeof value === "object"
          ? JSON.stringify(value)
          : String(value ?? "—"),
      ),
    );
  }
  return dl;
}
function endpoint(pin) {
  const e = node("div", undefined, "endpoint");
  e.append(
    button(`${pin.reference}.${pin.num} · ${pin.name}`, () =>
      selectObject(pin.key),
    ),
    badge(entry(pin.key).status),
  );
  if (pin.nc) e.append(node("small", "NC · 明确不连接"));
  else e.append(button(pin.net, () => selectObject("net:" + pin.net)));
  return e;
}
function showReview(key) {
  const e = node("div");
  e.append(section("人工审查"));
  const select = node("select");
  select.id = "review-status";
  select.setAttribute("aria-label", "审查状态");
  for (const [value, label] of Object.entries(statusNames)) {
    const option = node("option", label);
    option.value = value;
    select.append(option);
  }
  select.value = entry(key).status;
  select.onchange = () => queueChange(key, { status: select.value });
  const label = node("label", "审查批注 · 自动保存", "note-label");
  label.htmlFor = "note";
  const note = node("textarea");
  note.id = "note";
  note.maxLength = 20000;
  note.value = entry(key).note;
  note.placeholder = "记录检查依据、发现的问题或待确认事项…";
  note.oninput = () => queueChange(key, { note: note.value });
  const time = node(
    "div",
    record.entries[key]?.updated_at
      ? "更新于 " + new Date(record.entries[key].updated_at).toLocaleString()
      : "尚无人工记录",
    "note-time",
  );
  time.id = "note-time";
  e.append(select, label, note, time);
  return e;
}
function relatedKeys(key) {
  const x = object(key),
    keys = new Set([key]);
  if (key.startsWith("part:"))
    for (const id of x.pins) {
      keys.add("pin:" + id);
      const p = pkg.pins[id];
      if (!p.nc) keys.add("net:" + p.net);
    }
  if (key.startsWith("net:"))
    for (const id of x.pins) {
      keys.add("pin:" + id);
      keys.add("part:" + pkg.pins[id].ref);
    }
  if (key.startsWith("pin:")) {
    keys.add("part:" + x.ref);
    if (!x.nc) keys.add("net:" + x.net);
  }
  return keys;
}
function renderDetail() {
  if (!currentKey) return;
  const x = object(currentKey),
    detail = $("detail");
  detail.replaceChildren();
  detail.append(
    node("h1", pkg.objects[currentKey], "detail-title"),
    node("div", x.path || x.id || x.name, "detail-path"),
    showReview(currentKey),
  );
  if (currentKey.startsWith("part:")) {
    detail.append(
      section("器件信息"),
      fields([
        ["功能路径", x.path],
        ["器件型号", x.device],
        ["类别", x.category],
        ["装配", x.assembly],
        ["封装", x.footprint],
        ["稳定 ID", x.id],
      ]),
    );
    detail.append(section("规格与额定条件"));
    const dl = node("dl");
    for (const [name, value] of Object.entries(x.properties)) {
      const dd = node("dd", String(value), "property-value");
      const normalized = x.normalized_properties[name];
      if (normalized && typeof normalized === "object")
        dd.append(
          node("small", `SI: ${normalized.value} · ${normalized.dimension}`),
        );
      dl.append(node("dt", name), dd);
    }
    detail.append(dl, section(`引脚与焊盘 · ${x.pins.length}`));
    for (const id of [...x.pins].sort((a, b) =>
      pkg.pins[a].num.localeCompare(pkg.pins[b].num, undefined, {
        numeric: true,
      }),
    ))
      detail.append(endpoint(pkg.pins[id]));
    detail.append(
      section("来源"),
      node(
        "pre",
        JSON.stringify(
          { library: x.library_source, design: x.source },
          null,
          2,
        ),
      ),
    );
  } else if (currentKey.startsWith("net:")) {
    detail.append(
      section("网络信息"),
      fields([
        ["设计网络名", x.name],
        ["Allegro 名称", x.allegro_name],
        ["别名", x.aliases.join(", ")],
        ["端点数量", x.pins.length],
      ]),
    );
    detail.append(railControl(x), section("全部网络端点"));
    for (const id of x.pins) detail.append(endpoint(pkg.pins[id]));
    if (Object.keys(x.electrical || {}).length)
      detail.append(
        section("电气声明"),
        node("pre", JSON.stringify(x.electrical, null, 2)),
      );
  } else {
    detail.append(
      section("引脚映射"),
      fields([
        ["逻辑引脚", x.name],
        ["物理焊盘", x.num],
        ["引脚类型", x.type_name || x.func],
        ["稳定 ID", x.id],
      ]),
    );
    detail.append(
      button("查看元件 " + x.reference, () => selectObject("part:" + x.ref)),
      endpoint(x),
    );
  }
  const keys = relatedKeys(currentKey),
    ds = pkg.diagnostics.filter((d) => d.targets.some((k) => keys.has(k)));
  detail.append(section(`关联检查 · ${ds.length}`));
  for (const d of ds)
    detail.append(
      button(
        `${d.severity} · ${d.rule} · ${d.status}`,
        () => showDiagnostic(d),
        "detail-check" + (d.status === "PASS" ? " pass" : ""),
      ),
    );
  if (!ds.length) detail.append(node("p", "无关联检查结果", "note-time"));
}
function showDiagnostic(d) {
  currentKey = null;
  $("detail").replaceChildren(
    node("h1", d.rule, "detail-title"),
    node("div", d.severity + " · " + d.status, "detail-path"),
    node("p", d.message),
    section("关联对象"),
  );
  for (const key of d.targets)
    $("detail").append(button(pkg.objects[key], () => selectObject(key)));
  $("detail").append(
    section("检查证据"),
    node("pre", JSON.stringify(d.evidence, null, 2)),
    section("来源"),
    node("pre", JSON.stringify(d.source || [], null, 2)),
  );
  cy.elements().removeClass("highlight faded");
  let found = cy.collection();
  for (const key of d.targets) found = found.add(graphElementsFor(key));
  if (found.length) {
    found.add(found.connectedEdges()).addClass("highlight");
    cy.fit(found.add(found.edges().connectedNodes()), 65);
  }
}
function applyFilters() {
  page = 0;
  renderList();
  buildGraph();
}
function download(data, name) {
  const a = node("a");
  a.href = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function bindUI() {
  document.querySelectorAll("[data-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        tab = b.dataset.tab;
        page = 0;
        document
          .querySelectorAll("[data-tab]")
          .forEach((x) => x.classList.toggle("active", x === b));
        renderList();
        buildGraph(false);
      }),
  );
  let searchTimer;
  $("search").oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 150);
  };
  for (const id of ["status-filter", "assembly-filter", "diagnostic-filter"])
    $(id).onchange = applyFilters;
  $("previous").onclick = () => {
    page--;
    renderList();
  };
  $("next").onclick = () => {
    page++;
    renderList();
  };
  $("select-page").onclick = () => {
    rows
      .slice(page * pageSize, (page + 1) * pageSize)
      .forEach((x) => x.key && selected.add(x.key));
    syncSelection();
    renderList();
  };
  $("clear-selection").onclick = () => {
    selected.clear();
    syncSelection();
    renderList();
  };
  $("batch-apply").onclick = () => {
    for (const key of selected)
      queueChange(key, { status: $("batch-status").value });
    if (currentKey) renderDetail();
    flush();
  };
  $("fit").onclick = () => cy.fit(undefined, 45);
  $("layout").onclick = runLayout;
  $("labels").onchange = styleGraph;
  $("collapse").onclick = () => {
    collapsed = new Set(Object.values(pkg.parts).map(moduleOf).filter(Boolean));
    buildGraph();
  };
  $("restore").onclick = () => {
    collapsed.clear();
    manuallyHidden.clear();
    focusKeys = null;
    $("search").value = "";
    $("status-filter").value = "all";
    $("assembly-filter").value = "all";
    renderList();
    buildGraph();
  };
  $("hide-selected").onclick = () => {
    for (const key of selected) manuallyHidden.add(graphIdFor(key));
    buildGraph();
  };
  $("focus").onclick = () => {
    const keys = selected.size ? [...selected] : currentKey ? [currentKey] : [];
    if (!keys.length) return;
    focusKeys = new Set();
    for (const key of keys) {
      const related = relatedKeys(key);
      for (const k of [...related]) {
        if (k.startsWith("net:"))
          for (const endpointKey of relatedKeys(k)) related.add(endpointKey);
      }
      for (const k of related) focusKeys.add(ownerKey(k));
    }
    buildGraph();
  };
  $("retry").onclick = () => {
    blocked = false;
    flush();
  };
  $("reload").onclick = async () => {
    clearTimeout(saveTimer);
    if (saving) await saving;
    if (
      Object.keys(pending).length &&
      !confirm("丢弃本地尚未保存的修改，重新载入审查记录？")
    )
      return;
    try {
      record = await api("/api/review");
      pending = {};
      blocked = false;
      message("");
      saveMessage("已载入 · 修订 " + record.revision);
      refreshProgress();
      renderList();
      renderDetail();
      styleGraph();
    } catch (e) {
      message(e.message);
    }
  };
  $("export").onclick = async () => {
    try {
      const saved = await flush();
      if (saved) {
        download(await api("/api/review/export"), "review.json");
      } else {
        const draft = structuredClone(record);
        for (const [key, patch] of Object.entries(pending))
          draft.entries[key] = {
            status: "pending",
            note: "",
            ...draft.entries[key],
            ...patch,
            updated_at: new Date().toISOString(),
          };
        download(draft, "review-unsaved-draft.json");
        message("已导出含本地未保存修改的草稿。服务器记录未被覆盖。");
      }
    } catch (e) {
      message("导出失败：" + e.message);
    }
  };
  $("import").onclick = () => $("import-file").click();
  $("import-file").onchange = async () => {
    const file = $("import-file").files[0];
    $("import-file").value = "";
    if (!file) return;
    try {
      if (!(await flush())) throw new Error("请先处理尚未保存的修改");
      if (file.size > 8 * 1024 * 1024) throw new Error("记录文件超过 8 MiB");
      const data = JSON.parse(await file.text());
      const preview = await api("/api/review/import/preview", "POST", {
        revision: record.revision,
        record: data,
      });
      previewRecord = data;
      previewRevision = preview.revision;
      $("import-summary").textContent =
        `将导入 ${preview.total} 条记录，改变 ${preview.changed.length} 个对象，清除 ${preview.removed.length} 条现有记录。`;
      $("import-preview").replaceChildren(
        ...preview.changed.slice(0, 200).map((key) => {
          const item = node("details");
          item.append(
            node(
              "summary",
              `${pkg.objects[key]} · ${statusNames[record.entries[key]?.status || "pending"]} → ${statusNames[data.entries[key]?.status || "pending"]}${preview.removed.includes(key) ? "（清除记录）" : ""}`,
            ),
          );
          item.append(
            node(
              "pre",
              "当前批注：\n" +
                (record.entries[key]?.note || "（空）") +
                "\n\n导入批注：\n" +
                (data.entries[key]?.note || "（空）"),
            ),
          );
          return item;
        }),
      );
      if (preview.changed.length > 200)
        $("import-preview").append(
          node("p", "仅预览前 200 个变化；确认将应用全部变化。"),
        );
      $("import-dialog").showModal();
    } catch (e) {
      message("无法导入：" + e.message);
    }
  };
  $("cancel-import").onclick = () => $("import-dialog").close();
  $("confirm-import").onclick = async () => {
    try {
      record = await api("/api/review/import", "POST", {
        revision: previewRevision,
        record: previewRecord,
      });
      $("import-dialog").close();
      message("");
      saveMessage("导入已保存 · 修订 " + record.revision);
      refreshProgress();
      renderList();
      renderDetail();
      styleGraph();
    } catch (e) {
      $("import-dialog").close();
      message("导入未保存：" + e.message);
    }
  };
  window.addEventListener("beforeunload", (e) => {
    if (saving || Object.keys(pending).length) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}
async function start() {
  try {
    pkg = await api("/api/package");
    record = await api("/api/review");
    for (const p of Object.values(pkg.parts))
      searchable.set(p.key, partText(p));
    for (const n of Object.values(pkg.nets)) searchable.set(n.key, netText(n));
    $("board-name").textContent = pkg.name;
    document.title = pkg.name + " · 网表审查";
    $("inventory").textContent =
      `${pkg.statistics.parts} 元件  /  ${pkg.statistics.pins} 引脚  /  ${pkg.statistics.nets} 网络`;
    $("version-label").textContent = "版本指纹 " + pkg.fingerprint.slice(0, 12);
    bindUI();
    initGraph();
    renderList();
    refreshProgress();
    saveMessage("已载入 · 修订 " + record.revision);
  } catch (e) {
    message("无法载入审查工具：" + e.message);
    saveMessage("载入失败", "failed");
  }
}
start();
