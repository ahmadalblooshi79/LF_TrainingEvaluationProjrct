/* يستأنف تنزيل تصدير القوائم بعد الانتقال إلى صفحة أخرى في نفس التبويب. */
(function () {
  var STATE_KEY = "lfEvalExportState";
  var DB_NAME = "lf-eval-export";
  var running = false;
  var unloading = false;
  var dock = null;

  function loadState() {
    try {
      var raw = sessionStorage.getItem(STATE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return null;
    }
  }
  function saveState(state) {
    try {
      sessionStorage.setItem(STATE_KEY, JSON.stringify(state));
    } catch (err) {}
  }
  function clearState() {
    try { sessionStorage.removeItem(STATE_KEY); } catch (err) {}
  }
  function idb() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        if (!req.result.objectStoreNames.contains("kv")) req.result.createObjectStore("kv");
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }
  function idbSet(key, value) {
    return idb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction("kv", "readwrite");
        tx.objectStore("kv").put(value, key);
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }
  function idbGet(key) {
    return idb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction("kv", "readonly");
        var req = tx.objectStore("kv").get(key);
        req.onsuccess = function () { resolve(req.result || null); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }
  function page() {
    return {
      statusEl: document.getElementById("eval-export-status"),
      progressEl: document.getElementById("eval-export-progress"),
      fillEl: document.getElementById("eval-export-progress-fill"),
      metaEl: document.getElementById("eval-export-progress-meta"),
      nameEl: document.getElementById("eval-export-progress-name"),
      logEl: document.getElementById("eval-export-progress-log"),
      successEl: document.getElementById("eval-export-success"),
      btnFolder: document.getElementById("btn-export-folder"),
      btnZip: document.getElementById("btn-export-zip")
    };
  }
  function ensureDock() {
    if (dock) return dock;
    dock = document.createElement("aside");
    dock.className = "lf-export-dock";
    dock.hidden = true;
    dock.setAttribute("dir", "rtl");
    dock.innerHTML =
      '<div class="lf-export-dock__row">' +
      '<strong class="lf-export-dock__title">تنزيل قوائم التقييم</strong>' +
      '<button type="button" class="lf-export-dock__close" aria-label="إغلاق">×</button>' +
      "</div>" +
      '<div class="lf-export-dock__track" aria-hidden="true"><div class="lf-export-dock__fill"></div></div>' +
      '<p class="lf-export-dock__meta"></p>' +
      '<p class="lf-export-dock__name" dir="auto"></p>' +
      '<p class="lf-export-dock__msg" role="status"></p>' +
      '<button type="button" class="btn lf-export-dock__resume" hidden>متابعة التنزيل</button>';
    document.body.appendChild(dock);
    dock.querySelector(".lf-export-dock__close").addEventListener("click", function () {
      var state = loadState();
      if (state && state.status === "running") return;
      clearState();
      dock.hidden = true;
    });
    dock.querySelector(".lf-export-dock__resume").addEventListener("click", function () {
      var state = loadState();
      if (!state || state.status !== "running") return;
      resumeWithGesture(state);
    });
    return dock;
  }
  function setBusy(on) {
    var ui = page();
    if (ui.btnFolder) ui.btnFolder.disabled = !!on;
    if (ui.btnZip) ui.btnZip.disabled = !!on;
  }
  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }
  function fetchTimeout(url, ms) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, ms);
    return fetch(url, { credentials: "same-origin", cache: "no-store", signal: ctrl.signal }).finally(function () {
      clearTimeout(timer);
    });
  }
  async function readBody(response) {
    if (!response.body || !response.body.getReader) return await response.blob();
    var reader = response.body.getReader();
    var parts = [];
    while (true) {
      var step = await reader.read();
      if (step.done) break;
      if (unloading) throw new Error("unload");
      parts.push(step.value);
    }
    return new Blob(parts);
  }
  async function ensureDir(root, parts) {
    var handle = root;
    for (var i = 0; i < parts.length; i++) {
      handle = await handle.getDirectoryHandle(parts[i], { create: true });
    }
    return handle;
  }
  async function writeBlob(folder, fileName, blob) {
    var handle = await folder.getFileHandle(fileName, { create: true });
    var writable = await handle.createWritable();
    try {
      await writable.write(blob);
      await writable.close();
    } catch (err) {
      try { await writable.abort(); } catch (ignore) {}
      try { await folder.removeEntry(fileName); } catch (ignore2) {}
      throw err;
    }
  }
  async function getDir(root, parts) {
    var handle = root;
    for (var i = 0; i < parts.length; i++) handle = await handle.getDirectoryHandle(parts[i]);
    return handle;
  }
  async function removeListFolder(root, parts) {
    if (!parts || !parts.length) return;
    try {
      var parent = parts.length === 1 ? root : await getDir(root, parts.slice(0, -1));
      await parent.removeEntry(parts[parts.length - 1], { recursive: true });
    } catch (ignore) {}
    for (var i = parts.length - 1; i >= 1; i--) {
      try {
        var up = i === 1 ? root : await getDir(root, parts.slice(0, i - 1));
        await up.removeEntry(parts[i - 1]);
      } catch (ignore2) {
        break;
      }
    }
  }
  async function granted(handle) {
    if (!handle) return null;
    if (!handle.queryPermission) return handle;
    try {
      var q = await handle.queryPermission({ mode: "readwrite" });
      if (q === "granted") return handle;
    } catch (err) {}
    return null;
  }
  async function askPermission(handle) {
    if (!handle) return null;
    if (!handle.requestPermission) return handle;
    var q = await handle.requestPermission({ mode: "readwrite" });
    return q === "granted" ? handle : null;
  }
  function markGroup(state, gid, fromIndex) {
    for (var j = fromIndex; j < state.files.length; j++) {
      if (state.files[j].gid === gid) state.done[j] = true;
    }
  }
  function countDone(state) {
    var n = 0;
    for (var i = 0; i < state.done.length; i++) if (state.done[i]) n += 1;
    state.finished = n;
  }
  async function runFolder(state) {
    if (running) return;
    running = true;
    state.status = "running";
    state.needsPermission = false;
    saveState(state);
    render(state);
    var dir = null;
    try {
      dir = await granted(await idbGet("dir"));
    } catch (err) {
      dir = null;
    }
    if (!dir) {
      state.needsPermission = true;
      saveState(state);
      render(state);
      running = false;
      return;
    }
    try {
      for (var i = 0; i < state.files.length; i++) {
        if (unloading) return;
        if (state.done[i]) continue;
        var file = state.files[i];
        state.current = file.label.indexOf("جاري") === 0 ? file.label : ("جاري التنزيل: " + file.label);
        saveState(state);
        render(state);
        try {
          var res = await fetchTimeout(file.href, file.role === "media" ? 300000 : 120000);
          if (unloading) return;
          if (!res.ok) throw new Error(file.role === "media" ? "تعذّر تنزيل المرفق" : "تعذّر بناء ملف Excel");
          var blob = await readBody(res);
          if (unloading) return;
          if (!blob || !blob.size) throw new Error(file.role === "media" ? "المرفق فارغ" : "ملف Excel فارغ");
          var folder = await ensureDir(dir, file.parts);
          await writeBlob(folder, file.fileName, blob);
          state.saved += 1;
          state.names.push(file.label);
          state.done[i] = true;
        } catch (err) {
          if (unloading || (err && err.message === "unload")) return;
          if (!state.error) state.error = (err && err.message) ? String(err.message) : "تعذّر حفظ الملف";
          if (file.role === "xlsx") {
            try { await removeListFolder(dir, file.parts); } catch (ignore) {}
            markGroup(state, file.gid, i);
          } else {
            state.done[i] = true;
          }
        }
        countDone(state);
        saveState(state);
        render(state);
      }
      if (unloading) return;
      if (state.saved > 0) {
        state.status = "done";
        state.current = "";
        state.error = "";
      } else {
        state.status = "error";
        state.error = state.error || "تعذّر حفظ الملفات في المجلد.";
        state.current = "";
      }
      saveState(state);
      render(state);
    } finally {
      running = false;
    }
  }
  async function pipeZip(handle, url, state) {
    var res = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    if (!res.ok || !res.body) throw new Error("تعذّر تنزيل الأرشيف.");
    var total = Number(res.headers.get("Content-Length") || 0);
    var writable = await handle.createWritable();
    var reader = res.body.getReader();
    var loaded = 0;
    try {
      while (true) {
        var step = await reader.read();
        if (unloading) {
          try { await writable.abort(); } catch (ignore) {}
          return;
        }
        if (step.done) break;
        if (step.value && step.value.byteLength) await writable.write(new Blob([step.value]));
        loaded += (step.value && step.value.byteLength) || 0;
        if (total > 0) {
          state.finished = loaded;
          state.total = total;
          state.current = "جاري تنزيل الأرشيف…";
          saveState(state);
          render(state);
        }
      }
      await writable.close();
    } catch (err) {
      try { await writable.abort(); } catch (ignore) {}
      throw err;
    }
  }
  async function runZip(state) {
    if (running) return;
    running = true;
    state.status = "running";
    state.needsPermission = false;
    saveState(state);
    render(state);
    try {
      var lastMark = "";
      var lastMove = Date.now();
      var snap = null;
      while (state.phase === "build") {
        if (unloading) return;
        var st = await fetch(state.statusUrl, { credentials: "same-origin", cache: "no-store" });
        snap = await st.json().catch(function () { return {}; });
        if (unloading) return;
        if (!st.ok) {
          state.status = "error";
          state.error = snap.error || "تعذّر التصدير.";
          saveState(state);
          render(state);
          return;
        }
        state.finished = (snap.done || 0);
        state.fraction = Number(snap.file_fraction || 0);
        state.total = snap.total || state.total || 0;
        state.current = snap.current || state.current || "";
        if (snap.recent && snap.recent.length) state.names = snap.recent.slice();
        if (snap.download_name) state.downloadName = snap.download_name;
        if (snap.status === "ready") {
          state.phase = "save";
          state.finished = state.total;
          saveState(state);
          render(state);
          break;
        }
        if (snap.status === "error") {
          state.status = "error";
          state.error = snap.error || "تعذّر التصدير.";
          saveState(state);
          render(state);
          return;
        }
        var mark = String(snap.done || 0) + ":" + String(snap.file_fraction || 0) + ":" + String(snap.current || "");
        if (mark !== lastMark) {
          lastMark = mark;
          lastMove = Date.now();
        } else if (Date.now() - lastMove > 240000) {
          state.status = "error";
          state.error = "توقف التنزيل قبل الاكتمال. أعد المحاولة.";
          saveState(state);
          render(state);
          return;
        }
        countZipBar(state);
        saveState(state);
        render(state);
        await sleep(350);
      }
      if (unloading) return;
      var handle = null;
      try { handle = await granted(await idbGet("zipFile")); } catch (err) { handle = null; }
      if (state.usePicker && !handle) {
        state.needsPermission = true;
        saveState(state);
        render(state);
        return;
      }
      if (handle) await pipeZip(handle, state.downloadUrl, state);
      else triggerAnchorDownload(state.downloadUrl, state.downloadName);
      if (unloading) return;
      state.status = "done";
      state.current = "";
      state.finished = state.total || state.finished;
      saveState(state);
      render(state);
    } catch (err) {
      if (unloading || (err && err.message === "unload")) return;
      state.status = "error";
      state.error = (err && err.message) ? String(err.message) : "تعذّر التصدير.";
      saveState(state);
      render(state);
    } finally {
      running = false;
    }
  }
  function countZipBar(state) {
    state.barDone = (state.finished || 0) + Number(state.fraction || 0);
  }
  function triggerAnchorDownload(url, filename) {
    var a = document.createElement("a");
    a.href = url;
    a.download = filename || "قوائم_التقييم.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  function render(state) {
    if (!state) return;
    if (state.mode === "zip" && state.phase === "build") countZipBar(state);
    var ui = page();
    var total = state.mode === "zip" && state.phase === "save" && state.total ? state.total : (state.total || 0);
    var done = state.mode === "zip" && state.phase === "build" ? (state.barDone || 0) : (state.finished || 0);
    var pct = total > 0 ? Math.max(0, Math.min(100, Math.round((100 * done) / total))) : 0;
    if (state.status === "done") pct = 100;
    if (ui.progressEl) ui.progressEl.hidden = false;
    if (ui.fillEl) ui.fillEl.style.width = pct + "%";
    if (ui.metaEl) {
      if (state.mode === "zip" && state.phase === "save" && state.status === "running") {
        ui.metaEl.textContent = pct ? ("جاري تنزيل الأرشيف " + pct + "%") : "";
      } else if (state.status === "running" && total > 0) {
        ui.metaEl.textContent = Math.floor(done) + " من " + total;
      } else ui.metaEl.textContent = "";
    }
    if (ui.nameEl) ui.nameEl.textContent = state.status === "running" ? (state.current || "") : "";
    if (ui.logEl) {
      ui.logEl.replaceChildren();
      (state.names || []).forEach(function (name) {
        var li = document.createElement("li");
        li.dir = "auto";
        li.textContent = name;
        ui.logEl.appendChild(li);
      });
      ui.logEl.scrollTop = ui.logEl.scrollHeight;
    }
    if (ui.successEl) ui.successEl.hidden = state.status !== "done";
    if (ui.statusEl) ui.statusEl.textContent = state.status === "error" ? (state.error || "تعذّر التصدير.") : "";
    setBusy(state.status === "running");
    var box = ensureDock();
    box.hidden = false;
    box.querySelector(".lf-export-dock__fill").style.width = pct + "%";
    var meta = "";
    if (state.status === "running" && total > 0) {
      meta = state.mode === "zip" && state.phase === "save" ? ("جاري تنزيل الأرشيف " + pct + "%") : (Math.floor(done) + " من " + total);
    }
    box.querySelector(".lf-export-dock__meta").textContent = meta;
    box.querySelector(".lf-export-dock__name").textContent = state.status === "running" ? (state.current || "جاري التنزيل…") : "";
    var msg = box.querySelector(".lf-export-dock__msg");
    if (state.status === "done") msg.textContent = "تم التنزيل بنجاح";
    else if (state.status === "error") msg.textContent = state.error || "تعذّر التصدير.";
    else if (state.needsPermission) msg.textContent = "التنزيل متوقف حتى تؤكد متابعة الحفظ.";
    else msg.textContent = "";
    box.querySelector(".lf-export-dock__resume").hidden = !(state.status === "running" && state.needsPermission);
    box.querySelector(".lf-export-dock__close").hidden = state.status === "running";
  }
  async function resumeWithGesture(state) {
    try {
      if (state.mode === "folder") {
        var dir = await askPermission(await idbGet("dir"));
        if (!dir) return;
      } else if (state.usePicker) {
        var zip = await askPermission(await idbGet("zipFile"));
        if (!zip) return;
      }
    } catch (err) {
      return;
    }
    state.needsPermission = false;
    saveState(state);
    if (state.mode === "folder") runFolder(state);
    else runZip(state);
  }
  function resume() {
    var state = loadState();
    if (!state) return;
    render(state);
    if (state.status !== "running" || running) return;
    if (state.mode === "folder") runFolder(state);
    else runZip(state);
  }
  function flatten(groups) {
    var files = [];
    groups.forEach(function (group, gid) {
      files.push({
        href: group.xlsx.href,
        parts: group.parts,
        fileName: group.xlsx.fileName,
        label: group.xlsx.label,
        role: "xlsx",
        gid: gid
      });
      (group.media || []).forEach(function (media) {
        files.push({
          href: media.href,
          parts: group.parts,
          fileName: media.fileName,
          label: media.label,
          role: "media",
          gid: gid
        });
      });
    });
    return files;
  }
  window.LfEvalExport = {
    isBusy: function () {
      var state = loadState();
      return !!(running || (state && state.status === "running"));
    },
    startFolder: function (dir, groups) {
      var files = flatten(groups);
      var state = {
        mode: "folder",
        status: "running",
        files: files,
        done: files.map(function () { return false; }),
        finished: 0,
        total: files.length,
        saved: 0,
        names: [],
        current: "جاري تجهيز الملفات…",
        error: "",
        needsPermission: false
      };
      saveState(state);
      return idbSet("dir", dir).then(function () {
        return runFolder(state);
      });
    },
    startZip: function (opts) {
      var fd = new FormData(opts.form);
      return fetch(opts.jobUrl, { method: "POST", body: fd, credentials: "same-origin" })
        .then(function (res) {
          return res.json().catch(function () { return {}; }).then(function (data) {
            return { res: res, data: data };
          });
        })
        .then(function (pack) {
          if (!pack.res.ok || !pack.data.job_id) {
            var err = new Error((pack.data && pack.data.error) || "تعذّر التصدير.");
            throw err;
          }
          var state = {
            mode: "zip",
            phase: "build",
            status: "running",
            statusUrl: opts.statusUrl.replace("__JOB__", pack.data.job_id),
            downloadUrl: opts.downloadUrl.replace("__JOB__", pack.data.job_id),
            downloadName: pack.data.download_name || "قوائم_التقييم.zip",
            total: pack.data.total || 0,
            finished: 0,
            fraction: 0,
            names: [],
            current: "جاري تجهيز الملفات…",
            error: "",
            usePicker: !!opts.saveHandle,
            needsPermission: false
          };
          saveState(state);
          var stored = opts.saveHandle ? idbSet("zipFile", opts.saveHandle) : Promise.resolve();
          return stored.then(function () { return runZip(state); });
        });
    }
  };
  window.addEventListener("beforeunload", function () { unloading = true; });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", resume);
  } else {
    resume();
  }
})();
