const state = {
  page: 1,
  pageSize: 20,
  totalPages: 1,
  total: 0,
  query: "",
  sort: "created_at",
  order: "desc",
  shareTargetId: null,
  eventSource: null,
  refreshTimer: null,
  noteSaveTimer: null,
  noteUpdatedAt: "",
  noteDirty: false,
  noteSaveInFlight: false,
  notePendingSave: false,
};

const $ = (id) => document.getElementById(id);

const elements = {
  loginMask: $("loginMask"),
  loginForm: $("loginForm"),
  passwordInput: $("passwordInput"),
  loginError: $("loginError"),
  statFiles: $("statFiles"),
  statSize: $("statSize"),
  statRecent: $("statRecent"),
  networkBox: $("networkBox"),
  refreshBtn: $("refreshBtn"),
  logoutBtn: $("logoutBtn"),
  dropzone: $("dropzone"),
  pickBtn: $("pickBtn"),
  fileInput: $("fileInput"),
  progressList: $("progressList"),
  searchInput: $("searchInput"),
  sortSelect: $("sortSelect"),
  orderSelect: $("orderSelect"),
  searchBtn: $("searchBtn"),
  fileTableBody: $("fileTableBody"),
  pageInfo: $("pageInfo"),
  prevPageBtn: $("prevPageBtn"),
  nextPageBtn: $("nextPageBtn"),
  shareModalMask: $("shareModalMask"),
  shareHours: $("shareHours"),
  shareMax: $("shareMax"),
  createShareBtn: $("createShareBtn"),
  closeShareBtn: $("closeShareBtn"),
  shareOutput: $("shareOutput"),
  toastWrap: $("toastWrap"),
  noteInput: $("noteInput"),
  noteMeta: $("noteMeta"),
  saveNoteBtn: $("saveNoteBtn"),
  liveBadge: $("liveBadge"),
  liveDot: $("liveDot"),
  liveText: $("liveText"),
};

function toast(message, type = "info") {
  const div = document.createElement("div");
  div.className = type === "error" ? "toast error" : "toast";
  div.textContent = message;
  elements.toastWrap.appendChild(div);
  setTimeout(() => div.remove(), 3600);
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  return `${size.toFixed(size >= 100 ? 0 : size >= 10 ? 1 : 2)} ${units[idx]}`;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function shortHash(value) {
  if (!value) return "-";
  return `${value.slice(0, 8)}...${value.slice(-8)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setLiveState(mode, text) {
  elements.liveBadge.dataset.state = mode;
  elements.liveBadge.textContent = mode === "live" ? "Live" : mode === "offline" ? "Offline" : "Connecting";
  elements.liveDot.dataset.state = mode;
  elements.liveText.textContent = text;
}

function setNoteMeta(text, tone = "") {
  elements.noteMeta.textContent = text;
  elements.noteMeta.dataset.tone = tone;
}

function scheduleRefreshAll() {
  clearTimeout(state.refreshTimer);
  state.refreshTimer = setTimeout(async () => {
    try {
      await refreshAll();
    } catch (err) {
      console.error(err);
    }
  }, 180);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    ...options,
  });

  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const data = isJson ? await res.json() : null;

  if (!res.ok) {
    const msg = data?.error || `${res.status} ${res.statusText}`;
    const err = new Error(msg);
    err.status = res.status;
    err.payload = data;
    throw err;
  }

  return data;
}

async function login(password) {
  await api("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}

async function logout() {
  await api("/api/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

async function loadStats() {
  const stats = await api("/api/stats");
  elements.statFiles.textContent = stats.file_count;
  elements.statSize.textContent = formatBytes(stats.total_size);
  elements.statRecent.textContent = stats.uploaded_24h;
}

async function loadNetwork() {
  const data = await api("/api/network");
  if (!data.urls || data.urls.length === 0) {
    elements.networkBox.innerHTML = `<div class="network-item">未检测到局域网地址，可先使用 http://127.0.0.1:${data.port}</div>`;
    return;
  }

  elements.networkBox.innerHTML = "";
  data.urls.forEach((url) => {
    const item = document.createElement("div");
    item.className = "network-item";
    item.innerHTML = `${url}<button class="button button-secondary" data-copy="${url}">复制</button>`;
    elements.networkBox.appendChild(item);
  });
}

async function loadFiles() {
  const params = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
    query: state.query,
    sort: state.sort,
    order: state.order,
  });
  const data = await api(`/api/files?${params.toString()}`);
  state.total = data.total;
  state.totalPages = data.total_pages;
  renderFiles(data.items || []);
  elements.pageInfo.textContent = `第 ${data.page} / ${data.total_pages} 页，共 ${data.total} 个文件`;
}

function renderFiles(items) {
  if (!items.length) {
    elements.fileTableBody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无文件</td></tr>';
    return;
  }

  elements.fileTableBody.innerHTML = items
    .map((file) => `
      <tr>
        <td class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</td>
        <td>${formatBytes(file.size_bytes)}</td>
        <td><span class="tag">${escapeHtml(file.mime_type || "file")}</span></td>
        <td title="${file.sha256}">${shortHash(file.sha256)}</td>
        <td>${formatDate(file.created_at)}</td>
        <td>${file.downloads}</td>
        <td>
          <div class="file-actions">
            <button class="button button-secondary" data-action="download" data-id="${file.id}">下载</button>
            <button class="button button-ghost" data-action="share" data-id="${file.id}">分享</button>
            <button class="button button-danger" data-action="delete" data-id="${file.id}">删除</button>
          </div>
        </td>
      </tr>`)
    .join("");
}

async function loadNote(force = false) {
  const data = await api("/api/note");
  renderNote(data.note, { force });
}

function renderNote(note, options = {}) {
  if (!note) return;
  const force = Boolean(options.force);
  const remote = Boolean(options.remote);
  const incomingContent = note.content || "";
  const hasLocalDraft = state.noteDirty && elements.noteInput.value !== incomingContent;

  if (!hasLocalDraft || force) {
    elements.noteInput.value = incomingContent;
    state.noteDirty = false;
    state.noteUpdatedAt = note.updated_at || "";
    setNoteMeta(`最近同步 ${formatDate(note.updated_at)} · 来自 ${note.updated_by || "system"}`);
    return;
  }

  if (remote && note.updated_at && note.updated_at !== state.noteUpdatedAt) {
    setNoteMeta("其他设备已更新，当前保留你的本地草稿", "warn");
    toast("共享便签已被其他设备更新", "error");
  }
}

async function saveNote(manual = false) {
  const content = elements.noteInput.value;
  if (!state.noteDirty && !manual) return;
  if (state.noteSaveInFlight) {
    state.notePendingSave = true;
    return;
  }

  state.noteSaveInFlight = true;
  setNoteMeta("正在同步共享便签...");

  try {
    const data = await api("/api/note", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    state.noteDirty = false;
    state.noteUpdatedAt = data.note.updated_at || "";
    renderNote(data.note, { force: true });
    if (manual) {
      toast("共享便签已同步");
    }
  } catch (err) {
    setNoteMeta(`同步失败: ${err.message}`, "error");
    if (manual) {
      toast(`便签同步失败: ${err.message}`, "error");
    }
  } finally {
    state.noteSaveInFlight = false;
    if (state.notePendingSave) {
      state.notePendingSave = false;
      saveNote(false);
    }
  }
}

function scheduleNoteSave() {
  clearTimeout(state.noteSaveTimer);
  state.noteSaveTimer = setTimeout(() => {
    saveNote(false);
  }, 700);
}

function connectRealtime() {
  disconnectRealtime();
  setLiveState("connecting", "实时通道连接中");

  const eventSource = new EventSource("/api/events");
  state.eventSource = eventSource;

  eventSource.onopen = () => {
    setLiveState("live", "实时同步已连接");
  };

  eventSource.addEventListener("connected", () => {
    setLiveState("live", "实时同步已连接");
  });

  eventSource.addEventListener("files_changed", () => {
    scheduleRefreshAll();
  });

  eventSource.addEventListener("note_changed", (event) => {
    try {
      const payload = JSON.parse(event.data || "{}");
      if (payload.note) {
        renderNote(payload.note, { remote: true });
      } else {
        loadNote();
      }
      setLiveState("live", "实时同步已连接");
    } catch (err) {
      console.error(err);
    }
  });

  eventSource.onerror = () => {
    setLiveState("offline", "实时通道重连中");
  };
}

function disconnectRealtime() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  setLiveState("offline", "实时通道未连接");
}

function createProgressItem(name) {
  const id = `p_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  const wrap = document.createElement("div");
  wrap.className = "progress-item";
  wrap.id = id;
  wrap.innerHTML = `
    <div class="progress-head">
      <span title="${escapeHtml(name)}">${escapeHtml(name)}</span>
      <span class="progress-percent">0%</span>
    </div>
    <div class="progress-bar-wrap">
      <div class="progress-bar"></div>
    </div>`;
  elements.progressList.prepend(wrap);
  return {
    set(percent) {
      const p = Math.max(0, Math.min(100, percent));
      wrap.querySelector(".progress-percent").textContent = `${p.toFixed(0)}%`;
      wrap.querySelector(".progress-bar").style.width = `${p}%`;
    },
    done(success, text) {
      const head = wrap.querySelector(".progress-head span:last-child");
      head.textContent = text;
      wrap.style.borderColor = success ? "rgba(52,128,62,.35)" : "rgba(146,33,33,.45)";
      setTimeout(() => wrap.remove(), 6000);
    },
  };
}

function uploadFile(file) {
  return new Promise((resolve, reject) => {
    const progress = createProgressItem(file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/upload?filename=${encodeURIComponent(file.name)}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      progress.set((event.loaded / event.total) * 100);
    };

    xhr.onload = () => {
      let payload = {};
      try {
        payload = JSON.parse(xhr.responseText || "{}");
      } catch {
        payload = {};
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        progress.set(100);
        progress.done(true, "完成");
        resolve(payload);
      } else {
        const msg = payload.error || `上传失败(${xhr.status})`;
        progress.done(false, msg);
        reject(new Error(msg));
      }
    };

    xhr.onerror = () => {
      progress.done(false, "网络错误");
      reject(new Error("网络错误"));
    };

    xhr.send(file);
  });
}

async function uploadFiles(files) {
  if (!files.length) return;

  for (const file of files) {
    try {
      await uploadFile(file);
      toast(`上传成功: ${file.name}`);
    } catch (err) {
      toast(`上传失败: ${err.message}`, "error");
    }
  }

  await refreshAll();
}

async function deleteFile(id) {
  if (!confirm("确认删除这个文件吗？")) return;
  await api(`/api/files/${id}`, { method: "DELETE" });
  toast("文件已删除");
  await refreshAll();
}

function downloadFile(id) {
  window.open(`/api/files/${id}/download`, "_blank");
}

function openShareModal(id) {
  state.shareTargetId = id;
  elements.shareOutput.textContent = "尚未生成";
  elements.shareModalMask.classList.add("show");
}

function closeShareModal() {
  state.shareTargetId = null;
  elements.shareModalMask.classList.remove("show");
}

async function createShare() {
  if (!state.shareTargetId) {
    toast("未选择文件", "error");
    return;
  }

  const expiresHours = Number(elements.shareHours.value || 24);
  const maxDownloads = Number(elements.shareMax.value || 20);
  const data = await api(`/api/files/${state.shareTargetId}/share`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expires_hours: expiresHours, max_downloads: maxDownloads }),
  });

  elements.shareOutput.textContent = data.share_url;
  try {
    await navigator.clipboard.writeText(data.share_url);
    toast("分享链接已复制");
  } catch {
    toast("分享链接已生成，可手动复制");
  }
}

async function refreshAll() {
  await Promise.all([loadStats(), loadNetwork(), loadFiles()]);
}

async function bootstrapAuthenticatedView() {
  elements.loginMask.style.display = "none";
  await Promise.all([refreshAll(), loadNote(true)]);
  connectRealtime();
}

async function checkSession() {
  try {
    await api("/api/me");
    await bootstrapAuthenticatedView();
  } catch {
    elements.loginMask.style.display = "grid";
    disconnectRealtime();
  }
}

function bindEvents() {
  elements.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const password = elements.passwordInput.value.trim();
    if (!password) return;

    elements.loginError.textContent = "";
    try {
      await login(password);
      elements.passwordInput.value = "";
      await bootstrapAuthenticatedView();
    } catch (err) {
      elements.loginError.textContent = err.message;
    }
  });

  elements.refreshBtn.addEventListener("click", async () => {
    await Promise.all([refreshAll(), loadNote(true)]);
    toast("已刷新");
  });

  elements.logoutBtn.addEventListener("click", async () => {
    disconnectRealtime();
    await logout();
    elements.loginMask.style.display = "grid";
    toast("已退出登录");
  });

  elements.pickBtn.addEventListener("click", () => elements.fileInput.click());
  elements.fileInput.addEventListener("change", async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    await uploadFiles(files);
  });

  ["dragenter", "dragover"].forEach((name) => {
    elements.dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      elements.dropzone.classList.add("active");
    });
  });

  ["dragleave", "drop"].forEach((name) => {
    elements.dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      elements.dropzone.classList.remove("active");
    });
  });

  elements.dropzone.addEventListener("drop", async (event) => {
    const files = Array.from(event.dataTransfer?.files || []);
    await uploadFiles(files);
  });

  elements.searchBtn.addEventListener("click", async () => {
    state.query = elements.searchInput.value.trim();
    state.sort = elements.sortSelect.value;
    state.order = elements.orderSelect.value;
    state.page = 1;
    await loadFiles();
  });

  elements.searchInput.addEventListener("keydown", async (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      state.query = elements.searchInput.value.trim();
      state.page = 1;
      await loadFiles();
    }
  });

  elements.prevPageBtn.addEventListener("click", async () => {
    if (state.page <= 1) return;
    state.page -= 1;
    await loadFiles();
  });

  elements.nextPageBtn.addEventListener("click", async () => {
    if (state.page >= state.totalPages) return;
    state.page += 1;
    await loadFiles();
  });

  elements.fileTableBody.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const action = target.dataset.action;
    const id = target.dataset.id;
    if (!action || !id) return;

    try {
      if (action === "download") {
        downloadFile(id);
      }
      if (action === "delete") {
        await deleteFile(id);
      }
      if (action === "share") {
        openShareModal(id);
      }
    } catch (err) {
      toast(err.message || "操作失败", "error");
    }
  });

  elements.shareModalMask.addEventListener("click", (event) => {
    if (event.target === elements.shareModalMask) {
      closeShareModal();
    }
  });

  elements.closeShareBtn.addEventListener("click", closeShareModal);
  elements.createShareBtn.addEventListener("click", async () => {
    try {
      await createShare();
    } catch (err) {
      toast(err.message || "分享失败", "error");
    }
  });

  elements.networkBox.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const text = target.dataset.copy;
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast("地址已复制");
    } catch {
      toast("复制失败", "error");
    }
  });

  elements.noteInput.addEventListener("input", () => {
    state.noteDirty = true;
    setNoteMeta("检测到本地编辑，准备自动同步...");
    scheduleNoteSave();
  });

  elements.noteInput.addEventListener("blur", () => {
    if (state.noteDirty) {
      saveNote(false);
    }
  });

  elements.saveNoteBtn.addEventListener("click", async () => {
    await saveNote(true);
  });
}

(async function boot() {
  bindEvents();
  requestAnimationFrame(() => {
    document.body.classList.add("is-ready");
  });
  await checkSession();
})();
