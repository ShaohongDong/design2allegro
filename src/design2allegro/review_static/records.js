"use strict";
let pending = {},
  inFlight = {},
  saving = null,
  blocked = false,
  saveTimer,
  previewRecord = null,
  previewRevision = null;
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
  if (patch.status !== undefined) renderTables();
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
  renderTables();
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
function download(data, name) {
  const a = node("a");
  a.href = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function bindRecords() {
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
      renderTables();
      renderReview();
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
      renderTables();
      renderReview();
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
