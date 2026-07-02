(function () {
  'use strict';

  function initPlannerFlowTable(section) {
    if (!section || section.dataset.pfFlowInit === '1') return;

    var tbody = section.querySelector('#pf-flow-table-body');
    var table = section.querySelector('#pf-flow-table');
    var wrap = section.querySelector('#pf-flow-table-wrap');
    var menu = section.querySelector('#pf-flow-table-menu');
    var statusEl = section.querySelector('#pf-flow-table-save-status');
    if (!tbody || !table || !wrap || !menu) return;

    section.dataset.pfFlowInit = '1';

    var saveUrl = section.getAttribute('data-save-url') || '';
    var insertAfter = null;
    var selectedRow = null;
    var saveTimer = null;
    var saving = false;

    function cellText(el) {
      if (!el) return '';
      var raw = el.innerText != null ? el.innerText : el.textContent;
      return (raw || '').replace(/\r\n/g, '\n').replace(/\u00a0/g, ' ').trim();
    }

    function rowText(el) {
      return cellText(el);
    }

    function renumberRows() {
      var n = 0;
      tbody.querySelectorAll('.pf-flow-row--data').forEach(function (tr) {
        n += 1;
        var seq = tr.querySelector('.pf-flow-seq');
        if (seq) seq.textContent = String(n);
      });
    }

    function collectRows() {
      var rows = [];
      tbody.querySelectorAll('.pf-flow-row').forEach(function (tr) {
        var kind = tr.getAttribute('data-kind') || 'row';
        if (kind === 'event' || kind === 'dilemma') {
          var merged = tr.querySelector('.pf-flow-merged-cell');
          rows.push({ kind: kind, text: rowText(merged) });
        } else {
          var cells = tr.querySelectorAll('.pf-flow-cell');
          rows.push({
            kind: 'row',
            time: rowText(cells[0]),
            description: rowText(cells[1]),
            assignee: rowText(cells[2]),
            method: rowText(cells[3]),
            reaction: rowText(cells[4])
          });
        }
      });
      return rows;
    }

    function setStatus(msg, isErr) {
      if (!statusEl) return;
      statusEl.textContent = msg || '';
      statusEl.classList.toggle('planner-flow-table-save-status--err', !!isErr);
    }

    function scheduleSave() {
      if (!saveUrl) return;
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(doSave, 800);
    }

    function doSave() {
      if (!saveUrl || saving) return;
      if (saveTimer) {
        clearTimeout(saveTimer);
        saveTimer = null;
      }
      saving = true;
      setStatus('جاري الحفظ…', false);
      fetch(saveUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ rows: collectRows() })
      })
        .then(function (r) {
          return r.json().then(function (j) {
            return { ok: r.ok, j: j };
          });
        })
        .then(function (res) {
          if (res.ok && res.j && res.j.ok) {
            setStatus('تم الحفظ', false);
            setTimeout(function () {
              if (statusEl && statusEl.textContent === 'تم الحفظ') setStatus('', false);
            }, 2500);
          } else {
            setStatus('تعذّر الحفظ', true);
          }
        })
        .catch(function () {
          setStatus('تعذّر الحفظ', true);
        })
        .finally(function () {
          saving = false;
        });
    }

    function selectRow(tr) {
      if (selectedRow) selectedRow.classList.remove('is-selected');
      selectedRow = tr && tr.classList.contains('pf-flow-row') ? tr : null;
      if (selectedRow) selectedRow.classList.add('is-selected');
    }

    function deleteSelectedRow() {
      if (!selectedRow || !selectedRow.parentNode) {
        setStatus('اختر صفاً من الجدول ثم اضغط «حذف الصف».', true);
        return;
      }
      selectedRow.remove();
      selectedRow = null;
      renumberRows();
      hideMenu();
      doSave();
    }

    function hideMenu() {
      menu.classList.remove('is-open');
      menu.setAttribute('aria-hidden', 'true');
      insertAfter = null;
    }

    function showMenu(x, y, afterRow) {
      insertAfter = afterRow;
      if (menu.parentNode !== document.body) document.body.appendChild(menu);
      menu.classList.add('is-open');
      menu.setAttribute('aria-hidden', 'false');
      menu.style.left = '0px';
      menu.style.top = '0px';
      var mw = menu.offsetWidth || 168;
      var mh = menu.offsetHeight || 140;
      menu.style.left = Math.max(8, Math.min(x, window.innerWidth - mw - 8)) + 'px';
      menu.style.top = Math.max(8, Math.min(y, window.innerHeight - mh - 8)) + 'px';
    }

    function makeMergedRow(kind) {
      var tr = document.createElement('tr');
      tr.className = 'pf-flow-row pf-flow-row--' + (kind === 'event' ? 'event' : 'dilemma');
      tr.setAttribute('data-kind', kind);
      var td = document.createElement('td');
      td.colSpan = 6;
      td.className = 'pf-flow-merged-cell';
      td.contentEditable = 'true';
      td.spellcheck = true;
      tr.appendChild(td);
      bindRow(tr);
      return tr;
    }

    function makeDataRow() {
      var tr = document.createElement('tr');
      tr.className = 'pf-flow-row pf-flow-row--data';
      tr.setAttribute('data-kind', 'row');
      var seq = document.createElement('td');
      seq.className = 'planner-flow-action-col-num pf-flow-seq';
      seq.setAttribute('aria-label', 'ت');
      tr.appendChild(seq);
      for (var i = 0; i < 5; i += 1) {
        var td = document.createElement('td');
        td.className = 'pf-flow-cell';
        td.contentEditable = 'true';
        td.spellcheck = true;
        tr.appendChild(td);
      }
      bindRow(tr);
      return tr;
    }

    function focusEditable(tr) {
      var focusEl = tr.querySelector('[contenteditable="true"]');
      if (focusEl) focusEl.focus();
    }

    function insertRow(kind) {
      var tr = kind === 'row' ? makeDataRow() : makeMergedRow(kind);
      if (insertAfter && insertAfter.parentNode === tbody) {
        insertAfter.insertAdjacentElement('afterend', tr);
      } else {
        tbody.appendChild(tr);
      }
      renumberRows();
      hideMenu();
      selectRow(tr);
      focusEditable(tr);
      scheduleSave();
    }

    function bindRow(tr) {
      tr.querySelectorAll('[contenteditable="true"]').forEach(function (cell) {
        cell.addEventListener('input', scheduleSave);
        cell.addEventListener('blur', scheduleSave);
        if (cell.classList.contains('pf-flow-cell')) {
          cell.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' || e.shiftKey) return;
            e.stopPropagation();
          });
        }
      });
    }

    function inTableArea(node) {
      return !!(node && node.closest('#pf-flow-table-wrap'));
    }

    function onContextMenu(e) {
      if (!inTableArea(e.target)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      var tr = e.target.closest('.pf-flow-row');
      if (tr) selectRow(tr);
      showMenu(e.clientX, e.clientY, tr);
      return false;
    }

    tbody.addEventListener('click', function (e) {
      var tr = e.target.closest('.pf-flow-row');
      if (tr && tbody.contains(tr)) selectRow(tr);
    });

    tbody.querySelectorAll('.pf-flow-row').forEach(bindRow);
    renumberRows();

    section.addEventListener('contextmenu', onContextMenu, true);

    section.addEventListener('click', function (e) {
      if (e.target.closest('[data-pf-save]')) {
        e.preventDefault();
        doSave();
        return;
      }
      if (e.target.closest('[data-pf-delete-row]')) {
        e.preventDefault();
        deleteSelectedRow();
        return;
      }
      var ins = e.target.closest('[data-pf-insert]');
      if (ins) {
        e.preventDefault();
        insertAfter = null;
        insertRow(ins.getAttribute('data-pf-insert') || 'row');
      }
    });

    menu.querySelectorAll('[data-action]').forEach(function (btn) {
      btn.addEventListener('mousedown', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
      });
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var action = btn.getAttribute('data-action') || 'row';
        if (action === 'delete') deleteSelectedRow();
        else insertRow(action);
      });
    });

    document.addEventListener(
      'click',
      function (e) {
        if (!menu.classList.contains('is-open')) return;
        if (e.target.closest('.pf-flow-context-menu')) return;
        hideMenu();
      },
      true
    );

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hideMenu();
    });
    window.addEventListener('scroll', hideMenu, true);
    window.addEventListener('resize', hideMenu);
  }

  function boot() {
    document.querySelectorAll('#pf-flow-table-section[data-save-url]').forEach(initPlannerFlowTable);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
