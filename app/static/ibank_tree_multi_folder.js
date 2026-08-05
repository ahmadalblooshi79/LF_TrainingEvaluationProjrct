/**
 * إرفاق مجلدات بنك المعلومات / المكتبة.
 * - الإدراج فوري بعد اختيار المجلد (أو بعد سحب عدة مجلدات).
 * - الرفع على دفعات بدون حد عملي لعدد الملفات أو حجمها من جهة الواجهة.
 */
(function (global) {
  'use strict';

  var CHUNK_SIZE = 35;

  function openPicker(inp) {
    try {
      if (typeof inp.showPicker === 'function') {
        inp.showPicker();
        return;
      }
    } catch (e) { /* fall through */ }
    inp.click();
  }

  function appendFileList(pending, fileList) {
    if (!fileList || !fileList.length) return 0;
    var n = 0;
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      var rel = (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
      pending.push({ file: f, rel: rel || f.name });
      n += 1;
    }
    return n;
  }

  function countFolderRoots(pending) {
    var roots = {};
    for (var i = 0; i < pending.length; i++) {
      var parts = String(pending[i].rel || '').split('/');
      if (parts.length > 1 && parts[0]) roots[parts[0]] = true;
      else if (parts[0]) roots[parts[0]] = true;
    }
    return Object.keys(roots).length;
  }

  function setStatus(el, text) {
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.textContent = text;
  }

  function readAllDirectoryEntries(dirEntry) {
    return new Promise(function (resolve, reject) {
      var reader = dirEntry.createReader();
      var all = [];
      function readBatch() {
        reader.readEntries(function (entries) {
          if (!entries.length) {
            resolve(all);
            return;
          }
          all = all.concat(entries);
          readBatch();
        }, reject);
      }
      readBatch();
    });
  }

  function filesFromFileEntry(entry, relPath) {
    return new Promise(function (resolve, reject) {
      entry.file(function (file) {
        resolve([{ file: file, rel: relPath }]);
      }, reject);
    });
  }

  function filesFromDirEntry(entry, prefix) {
    var base = prefix ? prefix.replace(/\/?$/, '/') : (entry.name + '/');
    return readAllDirectoryEntries(entry).then(function (entries) {
      var jobs = entries.map(function (child) {
        var childRel = base + child.name;
        if (child.isFile) return filesFromFileEntry(child, childRel);
        if (child.isDirectory) return filesFromDirEntry(child, childRel);
        return Promise.resolve([]);
      });
      return Promise.all(jobs).then(function (chunks) {
        var out = [];
        chunks.forEach(function (c) { out = out.concat(c); });
        return out;
      });
    });
  }

  function collectDroppedItems(dataTransfer) {
    if (!dataTransfer) return Promise.resolve([]);
    var items = dataTransfer.items;
    if (items && items.length && typeof items[0].webkitGetAsEntry === 'function') {
      var jobs = [];
      for (var i = 0; i < items.length; i++) {
        var entry = items[i].webkitGetAsEntry && items[i].webkitGetAsEntry();
        if (!entry) continue;
        if (entry.isFile) {
          jobs.push(filesFromFileEntry(entry, entry.name));
        } else if (entry.isDirectory) {
          jobs.push(filesFromDirEntry(entry, entry.name));
        }
      }
      return Promise.all(jobs).then(function (chunks) {
        var out = [];
        chunks.forEach(function (c) { out = out.concat(c); });
        return out;
      });
    }
    var pending = [];
    appendFileList(pending, dataTransfer.files);
    return Promise.resolve(pending);
  }

  function appendPendingToFormData(fd, pending) {
    for (var i = 0; i < pending.length; i++) {
      var item = pending[i];
      fd.append('files', item.file, item.rel || item.file.name);
    }
  }

  function buildBaseFormData(form, parentId) {
    var fd = new FormData();
    var kindInp = form.querySelector('input[name="kind"]');
    if (kindInp) fd.append('kind', kindInp.value);
    if (parentId) fd.append('parent_id', String(parentId));
    var dayInp = form.querySelector('input[name="action_eval_day"]');
    if (dayInp && dayInp.value) fd.append('action_eval_day', dayInp.value);
    fd.append('chunk_mode', '1');
    return fd;
  }

  /**
   * رفع على دفعات ثم إعادة توجيه لصفحة النجاح/الخطأ.
   * opts: { form, parentId, pending, statusEl, onDone?, onError? }
   */
  function uploadPendingChunked(opts) {
    var form = opts.form;
    var pending = opts.pending || [];
    var statusEl = opts.statusEl || null;
    var parentId = opts.parentId || '';
    if (!form || !pending.length) {
      if (typeof opts.onError === 'function') opts.onError('لا توجد ملفات للإدراج.');
      return Promise.resolve();
    }

    var total = pending.length;
    var totalAdded = 0;
    var lastErrors = [];
    var redirectUrl = '';

    function uploadSlice(start) {
      var slice = pending.slice(start, start + CHUNK_SIZE);
      if (!slice.length) {
        return Promise.resolve();
      }
      var final = start + slice.length >= total;
      setStatus(
        statusEl,
        'جاري الإدراج… ' + Math.min(start + slice.length, total) + ' / ' + total + ' ملف'
      );
      var fd = buildBaseFormData(form, parentId);
      fd.append('chunk_final', final ? '1' : '0');
      appendPendingToFormData(fd, slice);
      return fetch(form.action, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      }).then(function (r) {
        var ct = (r.headers.get('content-type') || '').toLowerCase();
        if (ct.indexOf('application/json') >= 0) {
          return r.json().then(function (j) {
            if (!j || !j.ok) {
              var err = (j && (j.error || j.err)) || ('HTTP ' + r.status);
              throw new Error(err);
            }
            totalAdded += Number(j.added || 0);
            if (j.errors && j.errors.length) lastErrors = j.errors;
            if (j.redirect) redirectUrl = j.redirect;
            if (!final) return uploadSlice(start + CHUNK_SIZE);
            return null;
          });
        }
        // استجابة تحويل تقليدية (دفعة أخيرة)
        redirectUrl = r.url || redirectUrl;
        if (!final) return uploadSlice(start + CHUNK_SIZE);
        return null;
      });
    }

    return uploadSlice(0)
      .then(function () {
        if (!totalAdded) {
          var msg = (lastErrors && lastErrors.length)
            ? lastErrors.slice(0, 3).join(' ')
            : 'لم يُدرج أي ملف مدعوم (PDF أو Word أو Excel).';
          setStatus(statusEl, '');
          throw new Error(msg);
        }
        setStatus(statusEl, 'اكتمل الإدراج (' + totalAdded + ' ملف).');
        if (typeof opts.onDone === 'function') opts.onDone({ added: totalAdded, errors: lastErrors, redirect: redirectUrl });
        if (redirectUrl) {
          window.location.href = redirectUrl;
          return;
        }
        window.location.reload();
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : 'تعذر الإدراج.';
        setStatus(statusEl, '');
        if (typeof opts.onError === 'function') opts.onError(msg);
        else window.alert(msg);
      });
  }

  function runValidatedCommit(opts, pending) {
    var ok = true;
    var parentId = '';
    if (typeof opts.validateAndPrepare === 'function') {
      var v = opts.validateAndPrepare(pending);
      if (v === false) ok = false;
      else if (typeof v === 'string' && v) {
        window.alert(v);
        ok = false;
      } else if (v && typeof v === 'object' && v.parentId) {
        parentId = String(v.parentId);
      }
    }
    if (!ok) return;
    if (!parentId && opts.form) {
      var pInp = opts.form.querySelector('input[name="parent_id"]');
      if (pInp) parentId = pInp.value || '';
    }
    var nFolders = countFolderRoots(pending);
    setStatus(
      opts.statusEl,
      'بدء إدراج ' + nFolders + ' مجلد (' + pending.length + ' ملف)…'
    );
    uploadPendingChunked({
      form: opts.form,
      parentId: parentId,
      pending: pending,
      statusEl: opts.statusEl,
      onError: function (msg) {
        window.alert(msg || 'تعذر الإدراج.');
        if (typeof opts.onError === 'function') opts.onError(msg);
      },
    });
  }

  /** اختيار مجلد → إدراج فوري. للعدد المتعدد: كرر الزر أو اسحب عدة مجلدات. */
  function bindMultiFolderPick(opts) {
    var pick = opts.pickBtn;
    var inp = opts.input;
    var statusEl = opts.statusEl || null;
    if (!pick || !inp) return { clear: function () {} };

    pick.addEventListener('click', function () {
      setStatus(statusEl, 'اختر مجلداً للإدراج الفوري. لإرفاق عدة مجلدات دفعة واحدة اسحبها إلى الشريط.');
      openPicker(inp);
    });

    inp.addEventListener('change', function () {
      if (!inp.files || !inp.files.length) return;
      var pending = [];
      appendFileList(pending, inp.files);
      try { inp.value = ''; } catch (e2) {}
      runValidatedCommit(opts, pending);
    });

    return { clear: function () { setStatus(statusEl, ''); } };
  }

  function bindFolderDropZone(zoneEl, opts) {
    if (!zoneEl) return;
    var dragDepth = 0;

    zoneEl.addEventListener('dragenter', function (e) {
      if (!e.dataTransfer) return;
      e.preventDefault();
      dragDepth += 1;
      zoneEl.classList.add('ibank-tree-drop-active');
    });
    zoneEl.addEventListener('dragover', function (e) {
      if (!e.dataTransfer) return;
      e.preventDefault();
      try { e.dataTransfer.dropEffect = 'copy'; } catch (err) {}
    });
    zoneEl.addEventListener('dragleave', function () {
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) zoneEl.classList.remove('ibank-tree-drop-active');
    });
    zoneEl.addEventListener('drop', function (e) {
      e.preventDefault();
      dragDepth = 0;
      zoneEl.classList.remove('ibank-tree-drop-active');
      collectDroppedItems(e.dataTransfer).then(function (pending) {
        if (!pending.length) return;
        runValidatedCommit(opts, pending);
      }).catch(function () {
        window.alert('تعذر قراءة المجلدات المُفلَتة.');
      });
    });
  }

  global.ibankTreeMultiFolder = {
    bindMultiFolderPick: bindMultiFolderPick,
    bindFolderDropZone: bindFolderDropZone,
    collectDroppedItems: collectDroppedItems,
    appendPendingToFormData: appendPendingToFormData,
    uploadPendingChunked: uploadPendingChunked,
    countFolderRoots: countFolderRoots,
    openPicker: openPicker,
    CHUNK_SIZE: CHUNK_SIZE,
  };
})(window);
