/* 知览前端：列表 / 分类 / 渲染 / 导入 / 外观设置 */
const $ = (s) => document.querySelector(s);
const listEl = $("#list"), tocEl = $("#toc"), stageEl = $("#stage");
let current = null;
let currentDoc = null;     // 当前打开的知识点数据
let settings = null;
let saveTimer = null;
let groups = { categories: [], untagged: 0, total: 0 };
let group = "";            // "" 全部 | "-" 未分类 | 分类 id
let editing = null;        // 正在重命名的分类 id
let confirmDel = null;     // 等待二次确认的分类 id

const PRESETS = ["#5aa2f0", "#4bbf8a", "#e0883c", "#c56cf0", "#ef6a8a", "#2ec4b6", "#f2c14e", "#9aa5b1"];

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = "";
    try { msg = (await r.text()).trim(); } catch (e) { /* 无响应体 */ }
    throw new Error(msg || (r.status + " " + url));
  }
  return r.json();
}
function post(url, body) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}
function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
}
function groupName(id) {
  const c = groups.categories.find((x) => x.id === id);
  return c ? c.name : "未分类";
}

/* ---------- 分类 ---------- */
async function loadGroups() {
  groups = await api("/api/categories");
  if (group && group !== "-" && !groups.categories.some((c) => c.id === group)) group = "";
  renderGroups();
}

function renderGroups() {
  const bar = $("#groupbar");
  const chip = (id, name, n, extra) =>
    '<button class="grp' + (group === id ? " on" : "") + (extra || "") + '" data-g="' + id + '">' +
    esc(name) + " <i>" + n + "</i>" +
    (id && id !== "-"
      ? '<span class="ops"><b data-act="rename" title="重命名">✎</b><b data-act="del" title="删除分类">✕</b></span>'
      : "") +
    "</button>";

  let html = chip("", "全部", groups.total) + chip("-", "未分类", groups.untagged);
  for (const c of groups.categories) html += chip(c.id, c.name, c.count);
  bar.innerHTML = html;

  bar.querySelectorAll(".grp").forEach((el) => {
    el.onclick = (e) => {
      const act = e.target.dataset.act;
      const id = el.dataset.g;
      if (act === "rename") return startRename(id);
      if (act === "del") return delGroup(id, el);
      selectGroup(id);
    };
  });
}

function selectGroup(id) {
  group = id;
  current = null;
  confirmDel = null;
  renderGroups();
  loadList($("#search").value);
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_import_target(id && id !== "-" ? id : null);
  }
}

function startRename(id) {
  editing = id;
  $("#groupform").hidden = false;
  $("#groupname").value = groupName(id);
  $("#groupname").focus();
  $("#groupname").select();
}

async function delGroup(id, el) {
  if (confirmDel !== id) {
    confirmDel = id;
    el.classList.add("confirm");
    el.querySelector('[data-act="del"]').textContent = "确认";
    setTimeout(() => { confirmDel = null; renderGroups(); }, 3000);
    return;
  }
  await post("/api/categories/" + id + "/delete");
  confirmDel = null;
  toast("已删除分类，其中的知识点退回未分类");
  await loadGroups();
  loadList($("#search").value);
}

function wireGroupForm() {
  const form = $("#groupform"), input = $("#groupname");
  const close = () => { form.hidden = true; editing = null; input.value = ""; };
  $("#add-group").onclick = () => {
    editing = null;
    form.hidden = false;
    input.value = "";
    input.focus();
  };
  $("#group-cancel").onclick = close;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const name = input.value.trim();
    const wasEdit = editing;
    close();
    if (!name) return;
    try {
      if (wasEdit) {
        await post("/api/categories/" + wasEdit + "/rename", { name });
        toast("分类已重命名");
      } else {
        const cat = await post("/api/categories", { name });
        toast("已创建分类「" + cat.name + "」");
        if (cat && cat.id) { await loadGroups(); return selectGroup(cat.id); }
      }
      await loadGroups();
      loadList($("#search").value);
    } catch (err) {
      toast("分类名称无效或已存在");
    }
  };
}

/* ---------- 外观 ---------- */
function applySettings(s) {
  const b = document.body;
  b.dataset.mode = s.mode;
  b.dataset.font = s.fontFamily;
  b.dataset.density = s.density;
  b.dataset.toc = s.showToc ? "on" : "off";
  const root = document.documentElement.style;
  root.setProperty("--accent", s.accent);
  root.setProperty("--fs", s.fontScale + "px");
  root.setProperty("--lh", s.lineHeight);
  root.setProperty("--measure", s.contentWidth + "px");
  root.setProperty("--side-w", s.sideWidth + "px");
  $("#hljs-theme").href = s.codeTheme === "light" ? "/static/atom-one-light.css" : "/static/atom-one-dark.css";
  $("#mode-cycle").textContent = { dark: "深色", light: "浅色", sepia: "护眼" }[s.mode];
  syncControls(s);
}

function syncControls(s) {
  document.querySelectorAll(".seg").forEach((seg) => {
    const key = seg.dataset.key;
    seg.querySelectorAll("button").forEach((btn) => btn.classList.toggle("on", btn.dataset.val === String(s[key])));
  });
  $("#accent").value = s.accent;
  $("#fontScale").value = s.fontScale;
  $("#lineHeight").value = s.lineHeight;
  $("#contentWidth").value = s.contentWidth;
  $("#sideWidth").value = s.sideWidth;
  $("#showToc").checked = !!s.showToc;
  $("#fontScaleVal").textContent = s.fontScale + " px";
  $("#lineHeightVal").textContent = Number(s.lineHeight).toFixed(2);
  $("#contentWidthVal").textContent = s.contentWidth + " px";
  $("#sideWidthVal").textContent = s.sideWidth + " px";
  $("#fontFamilyVal").textContent = { sans: "无衬线", serif: "衬线", mono: "等宽" }[s.fontFamily];
  $("#densityVal").textContent = { comfortable: "宽松", compact: "紧凑" }[s.density];
  document.querySelectorAll(".swatch").forEach((el) => el.classList.toggle("on", el.dataset.color === s.accent));
}

function update(patch, rerender) {
  settings = Object.assign(settings, patch);
  applySettings(settings);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }).catch(() => {});
  }, 320);
  if (rerender && current) openEntry(current, true);
}

function buildSwatches() {
  $("#swatches").innerHTML = PRESETS
    .map((c) => '<button class="swatch" data-color="' + c + '" style="background:' + c + '" title="' + c + '"></button>')
    .join("");
  document.querySelectorAll(".swatch").forEach((el) => {
    el.onclick = () => update({ accent: el.dataset.color }, true);
  });
}

function openSheet(open) {
  $("#settings").hidden = !open;
  if (open) refreshMaintenance();
}

function wireSettings() {
  document.querySelectorAll(".seg").forEach((seg) => {
    seg.querySelectorAll("button").forEach((btn) => {
      btn.onclick = () => {
        const key = seg.dataset.key;
        const affectsRender = key === "mode" || key === "codeTheme" || key === "density" || key === "fontFamily";
        update({ [key]: btn.dataset.val }, affectsRender);
      };
    });
  });
  const bind = (id, key, parse, affectsRender) => {
    $(id).addEventListener("input", (e) => update({ [key]: parse(e.target.value) }, affectsRender));
  };
  bind("#accent", "accent", (v) => v, true);
  bind("#fontScale", "fontScale", Number, false);
  bind("#lineHeight", "lineHeight", Number, false);
  bind("#contentWidth", "contentWidth", Number, false);
  bind("#sideWidth", "sideWidth", Number, false);
  $("#showToc").addEventListener("change", (e) => update({ showToc: e.target.checked }));
  $("#reset-settings").onclick = () => update({
    mode: "dark", accent: "#5aa2f0", fontFamily: "sans", density: "comfortable",
    codeTheme: "dark", showToc: true, fontScale: 16, lineHeight: 1.75,
    contentWidth: 860, sideWidth: 288,
  }, true);
  $("#open-settings").onclick = () => openSheet(true);
  $("#close-settings").onclick = () => openSheet(false);
  $("#settings").addEventListener("click", (e) => { if (e.target.id === "settings") openSheet(false); });
  const order = ["dark", "light", "sepia"];
  $("#mode-cycle").onclick = () => update({ mode: order[(order.indexOf(settings.mode) + 1) % 3] }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      openSheet(false);
      if (!$("#groupform").hidden) { $("#groupform").hidden = true; editing = null; }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === ",") { e.preventDefault(); openSheet(true); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") { e.preventDefault(); $("#search").focus(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") {
      e.preventDefault();
      if (editingId) return;                 // 编辑原文时不劫持
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.import_files(group && group !== "-" ? group : null);
      } else {
        toast("导入需要在桌面窗口中操作");
      }
    }
  });
}

/* ---------- 存储清理 ---------- */
function fmtSize(n) {
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

async function refreshMaintenance() {
  try {
    const r = await api("/api/maintenance");
    $("#cleanup-info").textContent = r.files
      ? "可清理 " + r.files + " 个文件（" + fmtSize(r.bytes) + "）。现存知识点的历史备份会保留。"
      : "没有可清理的文件。现存知识点的历史备份会一直保留。";
  } catch (e) { /* 统计失败不影响设置面板使用 */ }
}

function wireMaintenance() {
  const btn = $("#cleanup");
  let armed = false;
  const reset = () => { armed = false; btn.textContent = "清理孤儿备份与图片"; };
  btn.onclick = async () => {
    if (!armed) {
      armed = true;
      btn.textContent = "再点一次确认清理";
      setTimeout(reset, 3000);
      return;
    }
    reset();
    try {
      const r = await post("/api/maintenance/cleanup");
      toast("已清理 " + r.removed + " 个文件，释放 " + fmtSize(r.freed));
    } catch (err) {
      toast("清理失败：" + err.message);
    }
    refreshMaintenance();
  };
}

/* ---------- 自定义显示名 ---------- */
function openRenameBar() {
  if (!current || !currentDoc) return;
  const bar = $("#renamebar");
  bar.hidden = false;
  $("#rename-input").value = currentDoc.alias || "";
  $("#rename-file").checked = false;
  $("#rename-hint").textContent = "文件原标题：" + currentDoc.title + "　|　当前文件：" + (currentDoc.source_name || "");
  $("#rename-input").focus();
  $("#rename-input").select();
}

async function applyRename(alias, alsoFile) {
  if (!current) return;
  try {
    if (alsoFile && alias) {
      const f = await post("/api/entries/" + current + "/file", { name: alias });
      currentDoc = Object.assign(currentDoc || {}, f);
    }
    const r = await post("/api/entries/" + current + "/rename", { alias });
    currentDoc = Object.assign(currentDoc || {}, r);
    $("#renamebar").hidden = true;
    toast(alias ? "显示名已改为「" + alias + "」" + (alsoFile ? "，文件也已重命名" : "") : "已恢复使用文件里的标题");
    await openEntry(current, true);
    loadList($("#search").value);
  } catch (err) {
    $("#rename-hint").textContent = "✕ " + err.message;
    toast(err.message);
  }
}

function wireRename() {
  $("#rename").onclick = openRenameBar;
  $("#rename-cancel").onclick = () => { $("#renamebar").hidden = true; };
  $("#rename-clear").onclick = () => applyRename("", false);
  $("#renamebar").onsubmit = (e) => {
    e.preventDefault();
    applyRename($("#rename-input").value.trim(), $("#rename-file").checked);
  };
}

/* ---------- 右键菜单 ---------- */
let menuId = null;

function hideMenu() {
  $("#menu").hidden = true;
  menuId = null;
}

function showMenu(x, y, id) {
  menuId = id;
  const m = $("#menu");
  m.hidden = false;
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.min(x, innerWidth - w - 8) + "px";
  m.style.top = Math.min(y, innerHeight - h - 8) + "px";
}

function wireMenu() {
  listEl.addEventListener("contextmenu", (e) => {
    const item = e.target.closest(".item");
    if (!item || !item.dataset.id) return;
    e.preventDefault();
    showMenu(e.clientX, e.clientY, item.dataset.id);
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#menu")) hideMenu(); });
  window.addEventListener("blur", hideMenu);
  document.addEventListener("scroll", hideMenu, true);
  const menuEl = $("#menu");
  if (menuEl) menuEl.addEventListener("click", async (e) => {
    const act = e.target.dataset.act;
    if (!act || !menuId) return;
    const id = menuId;
    hideMenu();
    if (act === "open") return openEntry(id);
    if (act === "source") return openSource(id);
    if (act === "reveal") return reveal(id);
    if (act === "rename") { await openEntry(id); return openRenameBar(); }
    if (act === "delete") return removeEntry(id);
  });
}

async function reveal(id) {
  if (!(window.pywebview && window.pywebview.api)) return toast("仅桌面版支持定位文件");
  if (!(await window.pywebview.api.reveal_in_folder(id))) toast("原始文件已移动或删除");
}

async function removeEntry(id) {
  await post("/api/entries/" + id + "/delete");
  toast("已从知识库移除（原文件保留）");
  if (id === current) {
    current = null;
    $("#doc").hidden = true;
    $("#empty").hidden = false;
    tocEl.innerHTML = "";
  }
  if (id === editingId) closeEditor(true);
  await loadGroups();
  loadList($("#search").value);
}

/* ---------- 原文查看 / 编辑 ---------- */
let editingId = null;
let dirty = false;
let discardArmed = false;
let staleDoc = false;      // 编辑器里保存过当前打开的知识点

function setDirty(v) {
  dirty = v;
  $("#editor").classList.toggle("dirty", v);
  $("#ed-status").textContent = v ? "未保存的修改" : "";
}

async function openSource(id) {
  editingId = id;                  // 先占位，迟到的响应据此判断是否已被切走
  let d;
  try {
    d = await api("/api/entries/" + id + "/source");
  } catch (err) {
    if (editingId === id) editingId = null;
    throw err;
  }
  if (editingId !== id) return;
  $("#empty").hidden = true;
  $("#doc").hidden = true;
  $("#editor").hidden = false;
  $("#ed-name").textContent = d.source_name || "原文";
  $("#ed-path").textContent = d.in_library
    ? d.path + "　（原件已不在原位置，正在编辑库内副本）"
    : d.path;
  $("#ed-text").value = d.content;
  setDirty(false);
  document.title = "编辑 · " + d.source_name;
  $("#ed-text").focus();
}

function closeEditor(force) {
  if (dirty && !force) {
    if (!discardArmed) {
      discardArmed = true;
      $("#ed-status").textContent = "有未保存修改，再点一次放弃";
      setTimeout(() => { discardArmed = false; if (dirty) setDirty(true); }, 3000);
      return;
    }
  }
  $("#editor").hidden = true;
  editingId = null;
  discardArmed = false;
  setDirty(false);
  if (staleDoc && current) {
    staleDoc = false;
    openEntry(current, true);
    return;
  }
  if (current) {
    $("#doc").hidden = false;
  } else {
    $("#empty").hidden = false;
  }
}

async function saveSource() {
  if (!editingId) return;
  const r = await post("/api/entries/" + editingId + "/source", { content: $("#ed-text").value });
  setDirty(false);
  discardArmed = false;
  toast("已保存" + (r.backup ? "，旧版本已备份" : ""));
  if (editingId === current) staleDoc = true;   // 关闭编辑器后再刷新阅读视图
  await loadGroups();
  loadList($("#search").value);
}

function wireEditor() {
  const ta = $("#ed-text");
  $("#doc-src").onclick = () => current && openSource(current);
  ta.addEventListener("input", () => { discardArmed = false; setDirty(true); });
  $("#ed-save").onclick = saveSource;
  $("#ed-cancel").onclick = () => closeEditor(false);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (editingId) saveSource();
    }
    if (e.key === "Escape" && editingId) {
      e.preventDefault();
      closeEditor(false);
    }
  });
  /* 列对齐：Tab 缩进而非跳出编辑器 */
  ta.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const s = ta.selectionStart, t = ta.selectionEnd, v = ta.value;
    ta.value = v.slice(0, s) + "    " + v.slice(t);
    ta.selectionStart = ta.selectionEnd = s + 4;
    setDirty(true);
  });
}

/* ---------- 列表与渲染 ---------- */
let listSeq = 0;

function highlight(text, q) {
  const safe = esc(text);
  const needle = q.trim();
  if (!needle) return safe;
  const pattern = esc(needle).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  try {
    return safe.replace(new RegExp(pattern, "ig"), (m) => "<mark>" + m + "</mark>");
  } catch (e) {
    return safe;
  }
}

async function loadList(q = "") {
  const seq = ++listSeq;
  const url = "/api/entries?q=" + encodeURIComponent(q) + "&category=" + encodeURIComponent(group);
  const { items, total } = await api(url);
  if (seq !== listSeq) return;      // 连续输入时，旧响应不能覆盖新结果
  $("#count").textContent = total;
  $("#dropzone").style.display = total ? "none" : "";
  listEl.innerHTML = items.length
    ? ""
    : '<div class="item"><div class="g">' + (q ? "没有匹配的知识点" : "该分类下还没有知识点") + "</div></div>";
  const frag = document.createDocumentFragment();
  for (const it of items) {
    const d = document.createElement("div");
    d.className = "item" + (current === it.id ? " on" : "");
    d.dataset.id = it.id;
    const meta = (it.tags || []).map((t) => "<b>#" + highlight(t, q) + "</b>").join(" ");
    const badge = !group && it.category ? '<b class="cat">' + esc(groupName(it.category)) + "</b> " : "";
    d.innerHTML =
      '<div class="t">' + highlight(it.display || it.title, q) + "</div>" +
      '<div class="g">' + badge + (meta ? meta + " · " : "") + esc(it.source_name) +
      (it.alias && it.alias !== it.title ? ' <i class="alias">自定义名</i>' : "") + "</div>";
    d.onclick = () => openEntry(it.id);
    frag.appendChild(d);
  }
  listEl.appendChild(frag);
  if (items.length && !current) openEntry(items[0].id);
  else if (!items.length) {
    $("#doc").hidden = true;
    $("#empty").hidden = false;
    tocEl.innerHTML = "";
  }
}

async function openEntry(id, keepScroll) {
  if (editingId) { $("#editor").hidden = true; editingId = null; setDirty(false); }
  staleDoc = false;
  const restore = keepScroll ? stageEl.scrollTop : 0;
  $("#renamebar").hidden = true;
  current = id;
  document.querySelectorAll(".item").forEach((e) => e.classList.toggle("on", e.dataset.id === id));
  const d = await api("/api/entries/" + id);
  if (id !== current) return;      // 请求期间用户已切到别的条目，丢弃迟到结果
  $("#empty").hidden = true;
  $("#doc").hidden = false;
  currentDoc = d;
  document.title = "知览 · " + (d.display || d.title);
  const aliasEl = $("#doc-name");
  aliasEl.hidden = !(d.alias && d.alias !== d.title);
  if (!aliasEl.hidden) aliasEl.textContent = d.alias;
  $("#doc-tags").innerHTML = (d.tags || []).map((t) => '<span class="chip">#' + esc(t) + "</span>").join("");
  $("#doc-src").textContent = d.source_name || "";
  $("#doc-src").title = "点击查看 / 编辑 Markdown 原文";
  $("#body").innerHTML = d.html;

  const sel = $("#cat-select");
  sel.innerHTML = '<option value="">未分类</option>' +
    groups.categories
      .map((c) => '<option value="' + c.id + '">' + esc(c.name) + "</option>")
      .join("");
  sel.value = d.category || "";
  sel.onchange = async () => {
    await post("/api/entries/" + current + "/category", { category: sel.value || null });
    toast(sel.value ? "已移动到「" + groupName(sel.value) + "」" : "已移出分类");
    await loadGroups();
    loadList($("#search").value);
  };

  tocEl.innerHTML = d.toc
    .map((t) => '<li><a class="l' + t.level + '" href="#' + t.id + '" data-id="' + t.id + '">' + esc(t.text) + "</a></li>")
    .join("");
  tocEl.querySelectorAll("a").forEach((a) => {
    a.onclick = (e) => {
      e.preventDefault();
      const el = document.getElementById(a.dataset.id);
      if (el) stageEl.scrollTo({ top: el.offsetTop - 20, behavior: "smooth" });
    };
  });

  await enrich();
  stageEl.scrollTop = restore;
  markToc();
}

/* KaTeX 等脚本用 defer 加载，需等 load 事件后才可用 */
const scriptsReady = new Promise((res) => {
  if (document.readyState === "complete") res();
  else window.addEventListener("load", res, { once: true });
});

/* mermaid.min.js 有 3.2 MB，静态引入会卡住 WebView2 的渲染主线程，
   连带 fetch 和 load 事件一起挂起。改成真正用到图表时才加载。 */
function ensureMermaid(w) {
  if (w.mermaid) return Promise.resolve(w.mermaid);
  if (!w.__mermaidLoading) {
    w.__mermaidLoading = new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = "/static/mermaid.min.js";
      s.onload = () => (w.mermaid ? res(w.mermaid) : rej(new Error("mermaid 未就绪")));
      s.onerror = () => rej(new Error("mermaid 加载失败"));
      document.head.appendChild(s);
    }).catch((e) => { console.error(e); return null; });
  }
  return w.__mermaidLoading;
}

async function enrich() {
  await scriptsReady;
  const w = window;
  const graphs = document.querySelectorAll("#body .mermaid");
  if (graphs.length) {
    const mermaid = await ensureMermaid(w);
    if (mermaid) {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "loose",
        theme: settings && settings.mode === "light" ? "default" : "dark",
      });
      try { await mermaid.run({ nodes: Array.from(graphs) }); } catch (e) { console.error(e); }
    }
  }
  w.hljs && document.querySelectorAll("#body pre code").forEach((el) => w.hljs.highlightElement(el));
  if (w.renderMathInElement) {
    w.renderMathInElement($("#body"), {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false },
      ],
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      throwOnError: false,
    });
  }
}

function markToc() {
  const heads = Array.from(document.querySelectorAll("#body h1,#body h2,#body h3,#body h4"));
  const top = stageEl.scrollTop;
  let active = heads[0];
  for (const h of heads) if (h.offsetTop - 40 <= top) active = h;
  tocEl.querySelectorAll("a").forEach((a) => a.classList.toggle("on", active && a.dataset.id === active.id));
}

/* ---------- 导入 / 移除 / 定位文件 ---------- */
$("#import").onclick = async () => {
  if (window.pywebview && window.pywebview.api) {
    await window.pywebview.api.import_files(group && group !== "-" ? group : null);
  } else {
    toast("导入需要在桌面窗口中操作");
  }
};
$("#new-entry").onclick = async () => {
  try {
    const cat = group && group !== "-" ? group : null;
    const d = await post("/api/entries", { title: "未命名知识点", category: cat });
    $("#search").value = "";
    current = d.id;
    await loadGroups();
    await loadList("");
    await openSource(d.id);
    toast("已新建空白知识点，编辑后按 Ctrl+S 保存");
  } catch (err) {
    toast("新建失败：" + err.message);
  }
};
$("#reveal").onclick = () => current && reveal(current);
$("#del").onclick = () => current && removeEntry(current);

let timer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(timer);
  timer = setTimeout(() => { current = null; loadList(e.target.value); }, 180);
});
stageEl.addEventListener("scroll", () => { clearTimeout(stageEl._t); stageEl._t = setTimeout(markToc, 60); });

/* 拖放高亮（真实导入由外壳的原生事件完成） */
["dragenter", "dragover"].forEach((t) =>
  document.addEventListener(t, (e) => { e.preventDefault(); document.body.classList.add("dropping"); })
);
["dragleave", "drop"].forEach((t) =>
  document.addEventListener(t, (e) => { e.preventDefault(); document.body.classList.remove("dropping"); })
);

window.refreshLibrary = async () => {
  await loadGroups();
  loadList($("#search").value);
};

/* 外部打开：右键菜单或命令行传进来的 .md，导入后由前端取走并展示 */
let pendingTimer = null;

async function takePending() {
  if (dirty) return null;                 // 正在编辑时先不动，等保存后再取，避免丢掉改动
  try {
    const { id } = await api("/api/pending");
    return id || null;
  } catch (e) {
    return null;
  }
}

async function checkPending() {
  const id = await takePending();
  if (id) openFromOutside(id);
}

async function openFromOutside(id) {
  current = id;
  await loadGroups();
  await loadList($("#search").value);
  await openEntry(id);
  toast("已加入知识库并打开");
}

function startPendingWatch() {
  if (pendingTimer) return;
  pendingTimer = true;
  // 长轮询：请求挂在服务端，来文件就立刻返回。比定时器可靠——
  // 窗口被遮挡时 Chromium 会把 setInterval 节流到分钟级，网络请求不受影响。
  (async function watchLoop() {
    for (;;) {
      try {
        const { id } = await api("/api/wait");
        if (id) await openFromOutside(id);
      } catch (e) {
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  })();
  // 切回窗口时补一次，避免断线期间漏掉
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) checkPending();
  });
  window.addEventListener("focus", checkPending);
  window.__pendingNow = checkPending;   // 服务端若能把 JS 叫起来，也可以用这个
}

async function boot() {
  try {
    settings = await api("/api/settings");
  } catch (e) {
    settings = {
      mode: "dark", accent: "#5aa2f0", fontFamily: "sans", density: "comfortable",
      codeTheme: "dark", showToc: true, fontScale: 16, lineHeight: 1.75,
      contentWidth: 860, sideWidth: 288,
    };
  }
  buildSwatches();
  applySettings(settings);
  wireSettings();
  wireMaintenance();
  wireGroupForm();
  wireMenu();
  wireEditor();
  wireRename();
  const first = await takePending();
  if (first) current = first;           // 先占位，避免 loadList 自动打开第一条
  await loadGroups();
  loadList();
  if (first) openEntry(first);
  startPendingWatch();
}

function fail(err) {
  // 初始化失败时别静默白屏：至少把原因显示出来
  console.error(err);
  const t = $("#toast");
  if (t) {
    t.textContent = "界面初始化失败：" + (err && err.message ? err.message : err);
    t.hidden = false;
  }
}

/* 等 load 之后再发请求：pywebview 在导航完成时注入 JS 桥，
   过早发出的 fetch 会卡在注入过程中收不到响应 */
function startApp() {
  boot().catch(fail);
}

if (document.readyState === "complete") startApp();
else window.addEventListener("load", startApp, { once: true });
