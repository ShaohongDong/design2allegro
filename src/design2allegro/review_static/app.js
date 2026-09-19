"use strict";
const $ = (id) => document.getElementById(id);
const statusNames = { pending: "待审", approved: "通过", issue: "有问题" };
let pkg,
  record,
  currentKey = null,
  checksPage = 0;
function refreshProgress() {
  $("progress").replaceChildren();
  for (const [kind, title] of [
    ["part", "元件"],
    ["net", "网络"],
    ["pin", "引脚"],
  ]) {
    const totals = { pending: 0, approved: 0, issue: 0 };
    for (const key of Object.keys(pkg.objects))
      if (key.startsWith(kind + ":")) totals[entry(key).status]++;
    $("progress").append(
      node(
        "span",
        `${title}　待审 ${totals.pending} · 通过 ${totals.approved} · 有问题 ${totals.issue}`,
      ),
    );
  }
}
function renderReview() {
  const has = !!currentKey;
  for (const id of ["review-status", "note", "current-details", "next-pending"])
    $(id).disabled = !has;
  $("review-target").textContent = has
    ? `当前审核${{ part: "元件", net: "网络", pin: "引脚" }[currentKey.split(":")[0]]}：${pkg.objects[currentKey]}`
    : "请选择审核对象";
  $("review-status").value = has ? entry(currentKey).status : "pending";
  $("note").value = has ? entry(currentKey).note : "";
  $("note-time").textContent =
    has && (pending[currentKey] || inFlight[currentKey])
      ? "本地修改尚未保存"
      : has && record.entries[currentKey]?.updated_at
        ? "更新于 " +
          new Date(record.entries[currentKey].updated_at).toLocaleString()
        : "尚无人工记录";
}
function reviewOwner(kind) {
  const owner = kind === "part" ? pkg.parts[view.part] : pkg.nets[view.net];
  if (!owner) return;
  remember();
  currentKey = owner.key;
  renderReview();
}
function nextPending() {
  const kind = currentKey.split(":")[0];
  // Status changes may remove the current object from the filtered list. Find its
  // position using the same order with status filtering temporarily disabled.
  const id = kind === "pin" ? view.side + "-status" : kind + "-status";
  const status = $(id).value;
  $(id).value = "all";
  const ordered = kind === "pin" ? pinRows(view.side) : pickerRows(kind);
  $(id).value = status;
  const index = ordered.findIndex((x) => x.key === currentKey);
  if (index < 0) {
    $("navigation-message").textContent =
      "当前对象不在筛选结果中，请先选择列表中的对象。";
    return;
  }
  const candidates = kind === "pin" ? pinRows(view.side) : pickerRows(kind);
  const allowed = new Set(candidates.map((x) => x.key));
  const next = ordered
    .slice(index + 1)
    .find((x) => allowed.has(x.key) && entry(x.key).status === "pending");
  if (next) navigate(next.key, view.side);
  else $("navigation-message").textContent = "当前列表已无下一待审项。";
}
function fields(values) {
  const dl = node("dl");
  for (const [name, value] of values)
    dl.append(
      node("dt", name),
      node(
        "dd",
        typeof value === "object"
          ? JSON.stringify(value)
          : String(value ?? "—"),
      ),
    );
  return dl;
}
function section(title) {
  return node("h3", title, "section-title");
}
function relatedKeys(key) {
  const x = object(key),
    keys = new Set([key]);
  if (key.startsWith("part:"))
    for (const id of x.pins) {
      const p = pkg.pins[id];
      keys.add(p.key);
      if (!p.nc) keys.add("net:" + p.net);
    }
  if (key.startsWith("net:"))
    for (const id of x.pins) {
      const p = pkg.pins[id];
      keys.add(p.key);
      keys.add("part:" + p.ref);
    }
  if (key.startsWith("pin:")) {
    keys.add("part:" + x.ref);
    if (!x.nc) keys.add("net:" + x.net);
  }
  return keys;
}
function detailLink(key) {
  return button(pkg.objects[key], () => {
    $("detail-dialog").close();
    $("checks-dialog").close();
    navigate(key);
  });
}
function openDetail(key) {
  const x = object(key),
    detail = $("detail");
  detail.replaceChildren(
    node("h2", pkg.objects[key]),
    badge(entry(key).status),
  );
  if (key.startsWith("part:")) {
    detail.append(
      section("器件信息"),
      fields([
        ["功能路径", x.path],
        ["器件型号", x.device],
        ["类别", x.category],
        ["装配", x.assembly],
        ["封装", x.footprint],
        ["引脚数", x.pins.length],
        ["稳定 ID", x.id],
      ]),
      section("规格与额定条件"),
      fields(Object.entries(x.properties)),
      section("归一化规格"),
      fields(Object.entries(x.normalized_properties)),
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
  } else if (key.startsWith("net:")) {
    detail.append(
      section("网络信息"),
      fields([
        ["设计网络名", x.name],
        ["Allegro 名称", x.allegro_name],
        ["别名", x.aliases.join(", ")],
        ["端点数量", x.pins.length],
      ]),
      section("电气声明"),
      node("pre", JSON.stringify(x.electrical || {}, null, 2)),
    );
  } else {
    detail.append(
      section("引脚映射"),
      fields([
        ["逻辑引脚", x.name],
        ["物理焊盘", x.num],
        ["引脚类型", x.type_name],
        ["稳定 ID", x.id],
      ]),
      section("所属元件"),
      detailLink("part:" + x.ref),
      section("网络"),
    );
    detail.append(
      x.nc ? node("p", "NC · 明确不连接") : detailLink("net:" + x.net),
    );
  }
  if (entry(key).note)
    detail.append(section("当前批注"), node("pre", entry(key).note));
  const keys = relatedKeys(key),
    diagnostics = pkg.diagnostics.filter((d) =>
      d.targets.some((k) => keys.has(k)),
    );
  detail.append(section(`关联检查 · ${diagnostics.length}`));
  for (const d of diagnostics)
    detail.append(
      button(
        `${d.severity} · ${d.rule} · ${d.status}`,
        () => showDiagnostic(d),
        "check-row",
      ),
    );
  if (!diagnostics.length) detail.append(node("p", "无关联检查结果"));
  if (!$("detail-dialog").open) $("detail-dialog").showModal();
}
function showDiagnostic(d) {
  $("checks-dialog").close();
  const detail = $("detail");
  detail.replaceChildren(
    node("h2", d.rule),
    node("p", `${d.severity} · ${d.status}`),
    node("p", d.message),
    section("关联对象"),
  );
  for (const key of d.targets) detail.append(detailLink(key));
  detail.append(
    section("检查证据"),
    node("pre", JSON.stringify(d.evidence, null, 2)),
    section("来源"),
    node("pre", JSON.stringify(d.source || [], null, 2)),
  );
  if (!$("detail-dialog").open) $("detail-dialog").showModal();
}
function renderChecks() {
  const q = $("check-search").value.trim().toLowerCase();
  const ds = pkg.diagnostics.filter(
    (d) =>
      ($("diagnostic-filter").value === "all" || d.status !== "PASS") &&
      (!q || JSON.stringify(d).toLowerCase().includes(q)),
  );
  checksPage = Math.max(
    0,
    Math.min(checksPage, Math.ceil(ds.length / pageSize) - 1),
  );
  $("checks-list").replaceChildren(
    ...ds
      .slice(checksPage * pageSize, (checksPage + 1) * pageSize)
      .map((d) =>
        button(
          `${d.status} · ${d.severity} · ${d.rule} — ${d.message}`,
          () => showDiagnostic(d),
          "check-row",
        ),
      ),
  );
  if (!ds.length)
    $("checks-list").append(node("p", "没有匹配的检查结果", "empty"));
  $("checks-page").textContent =
    `${ds.length ? checksPage + 1 : 0} / ${Math.ceil(ds.length / pageSize)} · ${ds.length} 项`;
  $("checks-previous").disabled = checksPage === 0;
  $("checks-next").disabled = (checksPage + 1) * pageSize >= ds.length;
}
function bindUI() {
  for (const id of [
    "part-status",
    "net-status",
    "left-status",
    "right-status",
  ]) {
    for (const [value, label] of [
      ["all", "全部审核状态"],
      ...Object.entries(statusNames),
    ]) {
      const o = node("option", label);
      o.value = value;
      $(id).append(o);
    }
  }
  bindTables();
  bindRecords();
  $("review-status").onchange = () => {
    if (currentKey)
      queueChange(currentKey, { status: $("review-status").value });
  };
  $("note").oninput = () => {
    if (currentKey) queueChange(currentKey, { note: $("note").value });
  };
  $("review-part").onclick = () => reviewOwner("part");
  $("review-net").onclick = () => reviewOwner("net");
  $("part-details").onclick = () => openDetail(pkg.parts[view.part].key);
  $("net-details").onclick = () => openDetail(pkg.nets[view.net].key);
  $("current-details").onclick = () => openDetail(currentKey);
  $("close-detail").onclick = () => $("detail-dialog").close();
  $("next-pending").onclick = nextPending;
  $("diagnostics").onclick = () => {
    renderChecks();
    $("checks-dialog").showModal();
  };
  $("close-checks").onclick = () => $("checks-dialog").close();
  $("check-search").oninput = () => {
    checksPage = 0;
    renderChecks();
  };
  $("diagnostic-filter").onchange = () => {
    checksPage = 0;
    renderChecks();
  };
  $("checks-previous").onclick = () => {
    checksPage--;
    renderChecks();
  };
  $("checks-next").onclick = () => {
    checksPage++;
    renderChecks();
  };
}
async function start() {
  try {
    pkg = await api("/api/package");
    record = await api("/api/review");
    bindUI();
    initializeIndex();
    $("board-name").textContent = pkg.name;
    document.title = pkg.name + " · 网表审查";
    $("inventory").textContent =
      `${pkg.statistics.parts} 元件 / ${pkg.statistics.pins} 引脚 / ${pkg.statistics.nets} 网络`;
    $("version-label").textContent = "版本指纹 " + pkg.fingerprint.slice(0, 12);
    if (parts.length) {
      view.part = parts[0].id;
      currentKey = parts[0].key;
    }
    renderTables();
    renderReview();
    refreshProgress();
    saveMessage("已载入 · 修订 " + record.revision);
  } catch (e) {
    message("无法载入审查工具：" + e.message);
    saveMessage("载入失败", "failed");
  }
}
start();
