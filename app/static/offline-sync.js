/**
 * مزامنة دون اتصال — طابور محلي + إرسال تلقائي عند عودة Wi‑Fi.
 * يعمل داخل WebView والمتصفح.
 */
(function () {
  var DB_NAME = "lf_offline_sync_v1";
  var STORE = "queue";
  var dbPromise = null;

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "op-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function deviceHeaders() {
    var d = window.LFDevice || {};
    var h = {};
    if (d.id) h["X-LF-Device-Id"] = String(d.id);
    if (d.name) h["X-LF-Device-Name"] = String(d.name);
    return h;
  }

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "client_operation_id" });
        }
      };
      req.onsuccess = function () {
        resolve(req.result);
      };
      req.onerror = function () {
        reject(req.error);
      };
    });
    return dbPromise;
  }

  function idbPut(item) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(item);
        tx.oncomplete = function () {
          resolve(item);
        };
        tx.onerror = function () {
          reject(tx.error);
        };
      });
    });
  }

  function idbAll() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readonly");
        var req = tx.objectStore(STORE).getAll();
        req.onsuccess = function () {
          resolve(req.result || []);
        };
        req.onerror = function () {
          reject(req.error);
        };
      });
    });
  }

  function idbDelete(id) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).delete(id);
        tx.oncomplete = function () {
          resolve();
        };
        tx.onerror = function () {
          reject(tx.error);
        };
      });
    });
  }

  function nativeOffline() {
    return !!(window.LFNativeOffline && window.LFNativeOffline.available);
  }

  function storagePut(item) {
    if (nativeOffline()) {
      window.LFNativeOffline.enqueue(JSON.stringify(item));
      return Promise.resolve(item);
    }
    return idbPut(item);
  }

  function storageAll() {
    if (nativeOffline()) return Promise.resolve([]);
    return idbAll();
  }

  function storageDelete(id) {
    if (nativeOffline()) return Promise.resolve();
    return idbDelete(id);
  }

  function pendingCount() {
    if (nativeOffline()) {
      return Promise.resolve(window.LFNativeOffline.pendingCount());
    }
    return idbAll().then(function (rows) {
      return rows.length;
    });
  }

  function serverReachable() {
    if (nativeOffline() && typeof window.LFNativeOffline.isServerReachable === "function") {
      return !!window.LFNativeOffline.isServerReachable();
    }
    return typeof navigator.onLine === "boolean" ? navigator.onLine : true;
  }

  function isOffline() {
    return !serverReachable();
  }

  function shouldQueueUrl(url) {
    if (!url) return false;
    var u = String(url);
    if (u.indexOf("/save-results") >= 0) return true;
    if (u.indexOf("/eval-criterion-media/upload") >= 0) return true;
    if (u.indexOf("/api/sync/") >= 0) return false;
    return false;
  }

  function banner(show, text) {
    var el = document.getElementById("lf-offline-banner");
    if (!el) {
      el = document.createElement("div");
      el.id = "lf-offline-banner";
      el.className = "lf-offline-banner";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    if (!show) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.textContent = text || "وضع عدم الاتصال — سيتم حفظ التغييرات ومزامنتها تلقائياً عند عودة الشبكة.";
  }

  function showOfflineBanner() {
    banner(true);
  }

  function hideOfflineBanner() {
    if (!isOffline()) banner(false);
  }

  function formDataToObject(fd) {
    var out = {};
    fd.forEach(function (value, key) {
      if (Object.prototype.hasOwnProperty.call(out, key)) return;
      out[key] = value;
    });
    return out;
  }

  function fileToBase64(file) {
    return new Promise(function (resolve, reject) {
      var rd = new FileReader();
      rd.onload = function () {
        var s = String(rd.result || "");
        var i = s.indexOf(",");
        resolve(i >= 0 ? s.slice(i + 1) : s);
      };
      rd.onerror = reject;
      rd.readAsDataURL(file);
    });
  }

  function queueEvalSave(url, formData) {
    var fields = formDataToObject(formData);
    var itemId = fields.evaluation_list_item_id || "";
    if (!itemId) {
      var m = String(url).match(/\/view\/(\d+)\/save-results/);
      if (m) itemId = m[1];
    }
    var op = {
      client_operation_id: uuid(),
      type: "eval_save",
      url: url,
      payload_json: fields.payload_json || "",
      evaluation_list_item_id: itemId,
      item_id: itemId,
      created_at: Date.now(),
    };
    return storagePut(op);
  }

  function queueMediaUpload(url, formData) {
    var fields = formDataToObject(formData);
    var file = fields.file;
    if (!file || !file.size) return Promise.resolve(false);
    return fileToBase64(file).then(function (b64) {
      var op = {
        client_operation_id: uuid(),
        type: "media_upload",
        url: url,
        file_base64: b64,
        row_index: fields.row_index || "",
        media_kind: fields.media_kind || "photo",
        evaluation_list_item_id: fields.evaluation_list_item_id || "",
        bundle_action_eval_id: fields.bundle_action_eval_id || "",
        exercise_id: fields.exercise_id || "",
        unit_level_key: fields.unit_level_key || "",
        mime_type: file.type || "image/jpeg",
        created_at: Date.now(),
      };
      return storagePut(op);
    });
  }

  function registerDevice(isLogin) {
    var d = window.LFDevice || {};
    if (!d.id) return Promise.resolve();
    return fetch("/api/device/register", {
      method: "POST",
      credentials: "same-origin",
      headers: Object.assign({ "Content-Type": "application/json", Accept: "application/json" }, deviceHeaders()),
      body: JSON.stringify({
        device_id: d.id,
        device_name: d.name || "",
        is_login: !!isLogin,
      }),
    }).catch(function () {});
  }

  function deviceHeartbeat() {
    var d = window.LFDevice || {};
    if (!d.id) return Promise.resolve();
    return pendingCount().then(function (n) {
      return fetch("/api/device/heartbeat", {
        method: "POST",
        credentials: "same-origin",
        headers: Object.assign({ "Content-Type": "application/json", Accept: "application/json" }, deviceHeaders()),
        body: JSON.stringify({
          device_id: d.id,
          device_name: d.name || "",
          sync_status: n > 0 ? "pending" : "idle",
          pending_sync_count: n,
        }),
      });
    }).catch(function () {});
  }

  var flushing = false;
  function flush() {
    if (flushing || isOffline()) return Promise.resolve({ ok: false, reason: "offline" });
    if (nativeOffline()) {
      banner(true, "جاري مزامنة البيانات المحلية…");
      window.LFNativeOffline.triggerSync();
      setTimeout(function () {
        pendingCount().then(function (n) {
          if (n === 0) banner(false);
        });
      }, 3000);
      return Promise.resolve({ ok: true, native: true });
    }
    flushing = true;
    banner(true, "جاري مزامنة البيانات المحلية…");
    return storageAll()
      .then(function (rows) {
        if (!rows.length) {
          banner(false);
          flushing = false;
          return { ok: true, synced: 0 };
        }
        return fetch("/api/sync/batch", {
          method: "POST",
          credentials: "same-origin",
          headers: Object.assign({ "Content-Type": "application/json", Accept: "application/json" }, deviceHeaders()),
          body: JSON.stringify({
            device_id: (window.LFDevice && window.LFDevice.id) || "",
            device_name: (window.LFDevice && window.LFDevice.name) || "",
            operations: rows,
          }),
        })
          .then(function (r) {
            return r.json().then(function (j) {
              return { r: r, j: j || {} };
            });
          })
          .then(function (pack) {
            var j = pack.j;
            if (!pack.r.ok || !j.ok) throw new Error("sync_failed");
            var results = j.results || [];
            return Promise.all(
              results.map(function (res) {
                if (res && res.ok) return storageDelete(res.client_operation_id);
                return Promise.resolve();
              })
            ).then(function () {
              return j;
            });
          });
      })
      .then(function (j) {
        banner(false);
        flushing = false;
        if (j && j.synced > 0) {
          try {
            sessionStorage.setItem("lf_offline_sync_reload", "1");
          } catch (e) {}
          window.location.reload();
        }
        return j || { ok: true };
      })
      .catch(function () {
        banner(true);
        flushing = false;
        return { ok: false };
      });
  }

  var nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var method = ((init.method || "GET") + "").toUpperCase();
    if (method !== "POST" || !shouldQueueUrl(url)) {
      return nativeFetch(input, init).catch(function (err) {
        if (shouldQueueUrl(url) && init.body instanceof FormData) {
          return queueFromForm(url, init.body).then(function () {
            showOfflineBanner();
            return new Response(JSON.stringify({ ok: true, offline_queued: true }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            });
          });
        }
        throw err;
      });
    }
    if ((isOffline() || !serverReachable()) && init.body instanceof FormData) {
      return queueFromForm(url, init.body).then(function () {
        showOfflineBanner();
        return new Response(JSON.stringify({ ok: true, offline_queued: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      });
    }
    return nativeFetch(input, init).catch(function (err) {
      if (shouldQueueUrl(url) && init.body instanceof FormData) {
        return queueFromForm(url, init.body).then(function () {
          showOfflineBanner();
          return new Response(JSON.stringify({ ok: true, offline_queued: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        });
      }
      throw err;
    });
  };

  function queueFromForm(url, body) {
    if (url.indexOf("/eval-criterion-media/upload") >= 0) {
      return queueMediaUpload(url, body);
    }
    return queueEvalSave(url, body);
  }

  window.addEventListener("online", function () {
    flush();
    deviceHeartbeat();
  });
  window.addEventListener("offline", function () {
    showOfflineBanner();
  });
  window.addEventListener("lf-server-online", function () {
    hideOfflineBanner();
    flush();
    deviceHeartbeat();
  });
  window.addEventListener("lf-server-offline", function () {
    showOfflineBanner();
  });

  setInterval(function () {
    deviceHeartbeat();
    if (!isOffline()) flush();
  }, 15000);

  document.addEventListener("DOMContentLoaded", function () {
    registerDevice(false);
    if (isOffline()) banner(true);
    else flush();
    try {
      if (sessionStorage.getItem("lf_offline_sync_reload")) {
        sessionStorage.removeItem("lf_offline_sync_reload");
      }
    } catch (e) {}
  });

  window.LFOfflineSync = {
    flush: flush,
    pendingCount: pendingCount,
    isOffline: isOffline,
    serverReachable: serverReachable,
    showOfflineBanner: showOfflineBanner,
    hideOfflineBanner: hideOfflineBanner,
  };
})();
