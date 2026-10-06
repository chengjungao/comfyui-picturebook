/* 绘本工坊 · 界面逻辑
   原生 JS，不依赖任何框架与 CDN —— 断网也能用。 */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const state = { project: null, config: null, images: [], poll: null, lastRunning: false };

/* ---------------- 工具 ---------------- */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show " + kind;
  clearTimeout(t._tm);
  t._tm = setTimeout(() => { t.className = ""; }, 3200);
}

function log(text) {
  const box = $("#log");
  const line = document.createElement("div");
  line.textContent = text;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

async function api(path, body) {
  const opt = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) };
  let res;
  try {
    res = await fetch(path, opt);
  } catch (e) {
    toast("连不上本地服务，窗口是不是被关了？", "err");
    throw e;
  }
  const data = await res.json().catch(() => ({ error: "返回内容看不懂" }));
  if (data && data.ok === false && data.error) toast(data.error, "err");
  return data;
}

/* ---------------- 步骤切换 ---------------- */

function goto(step) {
  $$(".steps button").forEach(b => b.classList.toggle("active", b.dataset.step === step));
  $$(".panel").forEach(p => p.classList.toggle("active", p.id === "step-" + step));
  // 切步骤回到顶部：分镜页很长，不回顶的话换步后停在半空，看不到标题
  const scroller = document.querySelector("main");
  if (scroller) scroller.scrollTop = 0;
  // 出图要跑几分钟，中途刷新很常见，所以把当前步写进地址栏，
  // 刷新后能回到原处，也能直接分享这一步的链接。
  if (location.hash.slice(1) !== step) location.hash = step;
  if (step === "story") autoGrowAll($("#step-story"));
  if (step === "draw") { renderKey(); renderThumbs(); }
  if (step === "book") renderBookThumbs();
}

$$(".steps button").forEach(b => b.onclick = () => goto(b.dataset.step));
$$("[data-goto]").forEach(b => b.onclick = () => goto(b.dataset.goto));
window.addEventListener("hashchange", () => goto(location.hash.slice(1) || "env"));

/* ---------------- 环境 ---------------- */

async function checkHealth() {
  const h = $("#health");
  h.className = "health";
  $("#healthText").textContent = "正在检查 ComfyUI…";
  const r = await api("/api/health");
  const info = r.info || {};
  if (r.ok) {
    h.className = "health " + ((r.warnings || []).length ? "warn" : "ok");
    $("#healthText").textContent =
      [info.device || "ComfyUI 已连接",
       info.vram_free_gb != null ? "空闲 " + info.vram_free_gb + "GB" : null]
      .filter(Boolean).join(" · ");
  } else {
    h.className = "health err";
    $("#healthText").textContent = "ComfyUI 连不上 · 点这里重试";
  }
  renderEnv(r);
  return r;
}

function renderEnv(r) {
  const box = $("#envReport");
  const info = r.info || {};
  const items = [];
  const add = (cls, mark, text) =>
    items.push(`<div class="item ${cls}"><span class="mark">${mark}</span><span>${text}</span></div>`);

  if (!r.ok) {
    add("err", "✗", "连不上 ComfyUI。<code>" + esc(r.errors && r.errors[0] || "") + "</code>");
    add("warn", "!", "请先启动 ComfyUI（便携版双击 <code>run_nvidia_gpu.bat</code>），再点右上角重试。");
  } else {
    add("ok", "✓", "ComfyUI 已连接：" + esc(info.comfyui_version || "?") +
      "（Python " + esc(info.python || "?") + "）");
    if (info.device) {
      add("ok", "✓", "显卡：<b>" + esc(info.device) + "</b>，显存 " +
        (info.vram_total_gb || "?") + " GB，空闲 " + (info.vram_free_gb || "?") + " GB");
    }
    add("ok", "✓", "队列：执行中 " + (info.queue_running || 0) +
      " / 等待 " + (info.queue_pending || 0));
    (r.warnings || []).forEach(w => add("warn", "!", esc(w)));
  }
  box.innerHTML = '<div class="report">' + items.join("") + "</div>";
}

async function loadModels() {
  const r = await api("/api/models");
  if (!r.ok) return;
  if (r.has_qwen_nodes === false) {
    toast("ComfyUI 里没有 Qwen-Image 的节点，工作流跑不起来", "err");
  }
  const fill = (sel, list, current, manual) => {
    const el = $(sel);
    el.innerHTML = "";
    const opts = list.slice();
    if (current && !opts.includes(current)) opts.unshift(current);
    opts.forEach(n => {
      const o = document.createElement("option");
      o.value = n; o.textContent = n;
      el.appendChild(o);
    });
    if (current) el.value = current;
    $(manual).placeholder = list.length
      ? "可以手填（现在 ComfyUI 认识 " + list.length + " 个）"
      : "ComfyUI 里这一类一个都没有";
  };
  fill("#cfgUnet", r.unet || [], state.config.models.unet, "#cfgUnetManual");
  fill("#cfgClip", r.clip || [], state.config.models.clip, "#cfgClipManual");
  fill("#cfgVae", r.vae || [], state.config.models.vae, "#cfgVaeManual");
}

function fillConfig() {
  const c = state.config;
  $("#cfgUrl").value = c.comfy_url;
  $("#cfgW").value = c.generate.width;
  $("#cfgH").value = c.generate.height;
  $("#cfgSteps").value = c.generate.steps;
  $("#cfgSeed").value = c.generate.base_seed;
  $("#cfgBrowser").value = c.browser_path || "";
  $("#cfgUnetManual").value = c.models.unet;
  $("#cfgClipManual").value = c.models.clip;
  $("#cfgVaeManual").value = c.models.vae;
}

async function saveConfig() {
  const pick = (sel, manual) => ($(manual).value.trim() || $(sel).value || "");
  const c = JSON.parse(JSON.stringify(state.config));
  c.comfy_url = $("#cfgUrl").value.trim() || c.comfy_url;
  c.generate.width = parseInt($("#cfgW").value, 10) || c.generate.width;
  c.generate.height = parseInt($("#cfgH").value, 10) || c.generate.height;
  c.generate.steps = parseInt($("#cfgSteps").value, 10) || c.generate.steps;
  c.generate.base_seed = parseInt($("#cfgSeed").value, 10) || c.generate.base_seed;
  c.browser_path = $("#cfgBrowser").value.trim();
  c.models.unet = pick("#cfgUnet", "#cfgUnetManual");
  c.models.clip = pick("#cfgClip", "#cfgClipManual");
  c.models.vae = pick("#cfgVae", "#cfgVaeManual");
  const r = await api("/api/config", { config: c });
  if (r.ok) {
    state.config = r.config;
    $("#cfgSaved").textContent = "已保存 " + new Date().toLocaleTimeString();
    toast("设置已保存", "ok");
    checkHealth();
  }
}

/* ---------------- 分镜 ---------------- */

const KIND_LABEL = { cover: "封面", page: "内页", back: "封底" };

function renderStory() {
  const p = state.project;
  if (!p) return;
  $("#pjTitle").value = p.title || "";
  $("#pjByline").value = p.byline || "";
  $("#pjPrefix").value = (p.style || {}).prefix || "";
  $("#pjSuffix").value = (p.style || {}).suffix || "";
  $("#pjColophon").value = (p.colophon || []).join("\n");

  const tb = $("#pagesTable tbody");
  tb.innerHTML = p.pages.map((pg, i) => {
    const kindOpts = Object.keys(KIND_LABEL).map(k =>
      `<option value="${k}"${pg.kind === k ? " selected" : ""}>${KIND_LABEL[k]}</option>`).join("");
    return `<tr>
      <td class="idx">${i + 1}</td>
      <td><select data-i="${i}" data-k="kind">${kindOpts}</select></td>
      <td><input type="text" data-i="${i}" data-k="id" value="${esc(pg.id)}"></td>
      <td><textarea data-i="${i}" data-k="scene" rows="3">${esc(pg.scene)}</textarea></td>
      <td>${textCell(pg, i)}</td>
      <td class="thumbcell">${thumbCell(pg)}</td>
    </tr>`;
  }).join("");

  const s = { page: 0, cover: 0, back: 0, words: 0 };
  p.pages.forEach(x => {
    s[x.kind] = (s[x.kind] || 0) + 1;
    (x.text || []).forEach(t => { s.words += (t || "").replace(/\s/g, "").length; });
  });
  $("#storyStats").textContent =
    `共 ${p.pages.length} 页（封面 ${s.cover} · 内页 ${s.page} · 封底 ${s.back}），正文约 ${s.words} 字`;
  autoGrowAll(tb);
}

function textCell(pg, i) {
  if (pg.kind === "cover") {
    return `<input type="text" data-i="${i}" data-k="title" value="${esc(pg.title)}"
              placeholder="书名" style="margin-bottom:4px">
            <input type="text" data-i="${i}" data-k="subtitle" value="${esc(pg.subtitle)}"
              placeholder="副标题（可留空）">`;
  }
  return `<textarea data-i="${i}" data-k="text" rows="3"
            placeholder="每行一句">${esc((pg.text || []).join("\n"))}</textarea>`;
}

function thumbCell(pg) {
  const f = pg.id + ".png";
  const has = state.images.includes(f);
  return (has ? `<img src="/img/${encodeURIComponent(f)}?t=${Date.now()}" alt="">` : `<span class="none">未出图</span>`)
    + `<div class="act"><button data-redraw="${esc(pg.id)}" title="只重画这一页">重画</button></div>`;
}

function syncProjectFromForm() {
  const p = state.project;
  p.title = $("#pjTitle").value;
  p.byline = $("#pjByline").value;
  p.style.prefix = $("#pjPrefix").value;
  p.style.suffix = $("#pjSuffix").value;
  p.colophon = $("#pjColophon").value.split("\n").filter(x => x.trim() !== "");
  return p;
}

async function saveProject(silent) {
  const r = await api("/api/project", { project: syncProjectFromForm() });
  if (!r.ok) return;
  state.issues = r.issues || [];
  renderIssues();
  if (!silent) {
    const errs = (r.issues || []).filter(x => x[0] === "error").length;
    toast(errs ? `已保存，但有 ${errs} 个问题要处理` : "分镜已保存", errs ? "" : "ok");
  }
}

function renderIssues() {
  const box = $("#issues");
  const list = state.issues || [];
  if (!list.length) {
    box.innerHTML = '<div class="i pass">校验通过，可以出图了。</div>';
    return;
  }
  box.innerHTML = list.map(([lvl, msg]) =>
    `<div class="i ${lvl === "error" ? "error" : "warn"}">${lvl === "error" ? "必须改" : "建议"}：${esc(msg)}</div>`
  ).join("");
}

/* 画面描述往往比三行还长，让输入框自己撑高。
   不撑的话得在单元格里滚动，看不到全貌，很容易写着写着就重复了。 */
function autoGrow(el) {
  if (!el || el.tagName !== "TEXTAREA") return;
  el.style.height = "auto";
  el.style.height = Math.max(el.scrollHeight, 54) + "px";
}

function autoGrowAll(root) {
  $$("textarea", root || document).forEach(autoGrow);
}

/* 表格编辑：事件委托，避免每次输入都重渲染（会丢焦点） */
$("#pagesTable tbody").addEventListener("input", e => {
  const el = e.target;
  autoGrow(el);
  const i = el.dataset.i;
  if (i == null) return;
  const k = el.dataset.k;
  const pg = state.project.pages[+i];
  if (k === "text") pg.text = el.value.split("\n").map(s => s.trim()).filter(s => s !== "");
  else pg[k] = el.value;
});

$("#pagesTable tbody").addEventListener("change", e => {
  const el = e.target;
  if (el.dataset.k !== "kind") return;
  state.project.pages[+el.dataset.i].kind = el.value;
  renderStory();   // 类型变了，单元格结构也要换
});

$("#pagesTable tbody").addEventListener("click", async e => {
  const id = e.target.dataset && e.target.dataset.redraw;
  if (!id) return;
  e.target.disabled = true;
  const r = await api("/api/one", { id });
  toast(r.msg || r.error || "");
  e.target.disabled = false;
  if (r.ok) { state.lastRunning = true; startPolling(); }
});

$("#btnAddPage").onclick = () => {
  const pages = state.project.pages;
  const backIdx = pages.findIndex(p => p.kind === "back");
  const n = pages.filter(p => p.kind === "page").length + 1;
  const np = { id: String(n).padStart(2, "0") + "-page", kind: "page", scene: "", text: [""] };
  if (backIdx >= 0) pages.splice(backIdx, 0, np); else pages.push(np);
  renderStory();
};

$("#btnSavePj").onclick = () => saveProject(false);

/* ---------------- 出图 ---------------- */

function renderKey() {
  const p = state.project;
  const ta = $("#keyPrompt");
  if (!ta.value) ta.value = (p.style && p.style.key_prompt) || "";
  const f = state.images.includes("char_sheet.png");
  $("#keyStatus").textContent = f ? "已有定妆照" : "还没有定妆照";
  $("#keyPreview").innerHTML = f
    ? `<img src="/img/char_sheet.png?t=${Date.now()}" alt="定妆照">`
    : "";
  $("#keyHint").textContent = f ? "满意就去下面批量出图；不满意可以重出。" : "";
}

function renderThumbs() {
  const p = state.project;
  if (!p) return;
  const box = $("#thumbs");
  const jobs = (state.progress && state.progress.jobs) || {};
  box.innerHTML = p.pages.map(pg => {
    const f = pg.id + ".png";
    const has = state.images.includes(f);
    const st = jobs[pg.id];
    let cls = "", tag = "";
    if (st) {
      cls = st.status;
      tag = { queued: "排队中", running: "生成中", done: "✓ 完成", failed: "✗ 失败" }[st.status] || st.status;
    } else if (has) { cls = "done"; tag = "✓ 已有"; }
    return `<figure class="${cls}">
      ${has ? `<img src="/img/${encodeURIComponent(f)}?t=${Date.now()}" alt="">`
            : `<img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" style="height:80px;background:#F3EEE4">`}
      <figcaption><span class="tag">${tag || "待出图"}</span><span>${esc(pg.id)}</span></figcaption>
    </figure>`;
  }).join("");
}

async function startKey() {
  const prompt = $("#keyPrompt").value.trim();
  await saveProject(true);
  const r = await api("/api/key", { prompt });
  toast(r.msg || r.error || "");
  if (r.ok) { state.lastRunning = true; startPolling(); }
}

$("#btnKey").onclick = startKey;

$("#keyFile").onchange = e => {
  const file = e.target.files[0];
  if (!file) return;
  const fr = new FileReader();
  fr.onload = async () => {
    const r = await api("/api/import-key", { data: fr.result });
    toast(r.msg || r.error || "");
    if (r.ok) { await refresh(); renderKey(); }
  };
  fr.readAsDataURL(file);
};

$("#btnPages").onclick = async () => {
  await saveProject(true);
  const r = await api("/api/pages", {});
  toast(r.msg || r.error || "");
  if (r.ok) { state.lastRunning = true; startPolling(); }
};

$("#btnCancel").onclick = async () => {
  const r = await api("/api/cancel", {});
  toast(r.msg || "");
};

/* ---------------- 进度轮询 ---------------- */

function startPolling() {
  if (state.poll) return;
  state.poll = setInterval(tick, 1500);
  tick();
}

async function tick() {
  const p = await api("/api/progress");
  state.progress = p;
  if (!p) return;

  const running = p.running;
  $("#btnCancel").disabled = !running;
  $("#btnKey").disabled = running;
  $("#btnPages").disabled = running;

  let pct = 0;
  if (p.total) pct = Math.round(100 * Math.min(p.done, p.total) / p.total);
  else if (running) pct = 8;
  $("#progBar").style.width = (running || p.done ? pct : 0) + "%";

  const parts = [];
  if (running) parts.push(p.msg || "处理中…");
  if (p.elapsed) parts.push("已用 " + p.elapsed + " 秒");
  if (p.queue && (p.queue.running || p.queue.pending))
    parts.push("队列 执行" + p.queue.running + " / 等待" + p.queue.pending);
  if (p.total) parts.push(`进度 ${Math.min(p.done, p.total)}/${p.total}`);
  $("#progText").textContent = parts.length ? parts.join(" · ") : "还没有开始";

  const box = $("#log");
  const want = (p.log || []).length;
  if (box.childElementCount !== want) {
    box.innerHTML = "";
    (p.log || []).forEach(t => log(t));
  }

  if (state.lastRunning && !running) {
    // 刚跑完，刷新一次图片列表
    state.lastRunning = false;
    await refresh();
    toast("这一轮结束了", "ok");
  }
  renderThumbs();
}

/* ---------------- 成书 ---------------- */

function renderBookThumbs() {
  const p = state.project;
  if (!p) return;
  $("#bookThumbs").innerHTML = p.pages.map(pg => {
    const f = pg.id + ".png";
    const has = state.images.includes(f);
    return `<figure>${has
      ? `<img src="/img/${encodeURIComponent(f)}?t=${Date.now()}" alt="">`
      : `<img src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" style="height:110px;background:#F3EEE4">`}
      <figcaption><span class="tag">${has ? "✓" : "缺"}</span><span>${esc(pg.id)}</span></figcaption></figure>`;
  }).join("");
}

$("#btnBuild").onclick = async () => {
  await saveProject(true);
  const r = await api("/api/build", {});
  if (r.ok) {
    $("#bookInfo").textContent =
      `排版完成：共 ${r.info.pages} 页（内页 ${r.info.inner} 页），` +
      `开本 ${r.info.size}，插图高 ${r.info.art_h}mm、文字带 ${r.info.band_h}mm。`;
    toast("排版完成", "ok");
  }
};

$("#btnPreview").onclick = () => window.open("/book", "_blank");

$("#btnPdf").onclick = async () => {
  $("#bookInfo").textContent = "正在导出 PDF…";
  const r = await api("/api/pdf", {});
  if (r.ok) {
    $("#bookInfo").textContent =
      `PDF 已生成：${r.path}（${r.size_mb} MB，共 ${r.pages} 页）。` +
      `可以去工程文件夹里取。`;
    toast("PDF 生成好了", "ok");
  } else {
    $("#bookInfo").textContent = r.error || "导出失败";
  }
};

$("#btnFolder").onclick = async () => {
  const r = await api("/api/open", { what: "folder" });
  if (!r.ok && r.error) toast(r.error, "err");
};

$("#btnClearLog").onclick = () => { $("#log").innerHTML = ""; };

$("#btnSaveCfg").onclick = saveConfig;
$("#health").onclick = () => { checkHealth(); loadModels(); };

/* ---------------- 启动 ---------------- */

async function refresh() {
  const s = await api("/api/state");
  if (!s.ok) return;
  state.project = s.project;
  state.config = s.config;
  state.images = s.images || [];
  state.issues = s.issues || [];
  state.hasKey = s.has_key;
  renderStory();
  renderIssues();
  renderKey();
  renderThumbs();
  renderBookThumbs();
  if (!$("#cfgSaved").textContent) fillConfig();
  if (s.pdf) $("#bookInfo").textContent = `已有 PDF：${s.pdf.path}（${s.pdf.size_mb} MB）`;
}

(async function boot() {
  log("界面已加载，正在读取工程…");
  await refresh();
  fillConfig();
  checkHealth();
  loadModels();
  goto(location.hash.slice(1) || "env");
})();
