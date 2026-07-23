/**
 * Shared "select all / deselect all" helpers for checkbox groups.
 * Safe to include on any page; binds only matching controls that exist.
 */
(function (global) {
  "use strict";

  function toArray(list) {
    return Array.prototype.slice.call(list || []);
  }

  function setAllChecked(checkboxes, checked) {
    toArray(checkboxes).forEach(function (cb) {
      if (!cb || cb.disabled) return;
      cb.checked = !!checked;
    });
  }

  function syncMaster(master, checkboxes) {
    if (!master) return;
    var boxes = toArray(checkboxes).filter(function (cb) { return cb && !cb.disabled; });
    if (!boxes.length) {
      master.checked = false;
      master.indeterminate = false;
      return;
    }
    var n = boxes.filter(function (cb) { return cb.checked; }).length;
    master.checked = n === boxes.length;
    master.indeterminate = n > 0 && n < boxes.length;
  }

  /**
   * Master checkbox controls a group of targets.
   * @param {HTMLInputElement} master
   * @param {function(): HTMLInputElement[]} getTargets
   * @param {{onBeforeUncheck?: function(HTMLInputElement[]): boolean}} [options]
   */
  function bindMasterCheckbox(master, getTargets, options) {
    if (!master || master.getAttribute("data-lf-select-all-bound") === "1") return;
    master.setAttribute("data-lf-select-all-bound", "1");
    options = options || {};

    function targets() {
      try { return getTargets() || []; } catch (_e) { return []; }
    }

    master.addEventListener("change", function () {
      var boxes = targets();
      if (!master.checked && typeof options.onBeforeUncheck === "function") {
        if (options.onBeforeUncheck(boxes) === false) {
          master.checked = true;
          master.indeterminate = false;
          return;
        }
      }
      setAllChecked(boxes, master.checked);
      master.indeterminate = false;
      syncMaster(master, targets());
    });

    targets().forEach(function (cb) {
      if (!cb || cb.getAttribute("data-lf-select-all-row") === "1") return;
      cb.setAttribute("data-lf-select-all-row", "1");
      cb.addEventListener("change", function () {
        syncMaster(master, targets());
      });
    });

    syncMaster(master, targets());
  }

  /**
   * Button that checks or unchecks a group.
   * @param {HTMLElement} btn
   * @param {function(): HTMLInputElement[]} getTargets
   * @param {boolean} checked
   * @param {function(HTMLInputElement[]): boolean} [beforeUncheck] return false to abort
   */
  function bindSelectButton(btn, getTargets, checked, beforeUncheck) {
    if (!btn || btn.getAttribute("data-lf-select-all-bound") === "1") return;
    btn.setAttribute("data-lf-select-all-bound", "1");
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      var boxes = [];
      try { boxes = getTargets() || []; } catch (_e) { boxes = []; }
      if (!checked && typeof beforeUncheck === "function") {
        if (beforeUncheck(boxes) === false) return;
      }
      setAllChecked(boxes, checked);
      // Notify any masters in the same scope
      var root = btn.closest(".ibank-tabpane, .eval-lists-dilemma-group, .eval-lists-unit-group, form, .card") || document;
      toArray(root.querySelectorAll("input[type='checkbox'].ibank-included-check-all, input[type='checkbox'][data-lf-master]")).forEach(function (master) {
        var scope = master.closest(".ibank-tabpane, table, .eval-lists-unit-group, .eval-lists-dilemma-group") || root;
        var name = master.getAttribute("data-targets-name");
        var formId = master.getAttribute("data-form-id");
        var rowSel = name
          ? 'input[type="checkbox"][name="' + name + '"]'
          : (formId ? 'input.ibank-included-cb[form="' + formId + '"]' : null);
        if (!rowSel) return;
        syncMaster(master, scope.querySelectorAll(rowSel));
      });
    });
  }

  /** Information-bank included tables (units + phases). */
  function bindIbankIncluded(root, options) {
    root = root || document;
    options = options || {};

    function unitTargets(pane, formId) {
      return toArray(pane.querySelectorAll('tbody input[type="checkbox"]')).filter(function (cb) {
        if (cb.disabled || cb.classList.contains("ibank-included-check-all")) return false;
        var f = cb.getAttribute("form") || "";
        var n = cb.getAttribute("name") || "";
        if (formId === "ibank-units-included-form") {
          return n === "included_unit_keys" || f === formId;
        }
        if (formId === "ibank-phases-included-form") {
          return n === "included_phase_keys" || f === formId;
        }
        return f === formId || cb.classList.contains("ibank-included-cb");
      });
    }

    function scopePaneFor(el, formId) {
      var pane = el.closest(".ibank-tabpane");
      if (pane) return pane;
      if (formId === "ibank-units-included-form") {
        return root.querySelector('.ibank-tabpane.is-active[data-tab-pane^="units-bg-"]')
          || root.querySelector('.ibank-tabpane[data-tab-pane^="units-bg-"]')
          || root;
      }
      if (formId === "ibank-phases-included-form") {
        return root.querySelector('.ibank-tabpane.is-active[data-tab-pane="phases"]')
          || root.querySelector('.ibank-tabpane[data-tab-pane="phases"]')
          || root;
      }
      return root.querySelector(".ibank-tabpane.is-active") || root;
    }

    toArray(root.querySelectorAll("input.ibank-included-check-all[data-form-id]")).forEach(function (master) {
      var formId = master.getAttribute("data-form-id") || "";
      bindMasterCheckbox(master, function () {
        return unitTargets(scopePaneFor(master, formId), formId);
      }, {
        onBeforeUncheck: options.onBeforeUncheck || null,
      });
    });

    toArray(root.querySelectorAll(".ibank-included-select-all[data-form-id]")).forEach(function (btn) {
      var formId = btn.getAttribute("data-form-id") || "";
      bindSelectButton(btn, function () {
        return unitTargets(scopePaneFor(btn, formId), formId);
      }, true);
    });

    toArray(root.querySelectorAll(".ibank-included-deselect-all[data-form-id]")).forEach(function (btn) {
      var formId = btn.getAttribute("data-form-id") || "";
      bindSelectButton(btn, function () {
        return unitTargets(scopePaneFor(btn, formId), formId);
      }, false, options.onBeforeUncheck || null);
    });
  }

  /** Generic: buttons with data-select-all-scope (CSS selector for checkboxes). */
  function bindDataSelectAllButtons(root) {
    root = root || document;
    toArray(root.querySelectorAll("[data-select-all-targets]")).forEach(function (btn) {
      var sel = btn.getAttribute("data-select-all-targets") || "";
      var action = (btn.getAttribute("data-select-all-action") || "all").toLowerCase();
      if (!sel) return;
      bindSelectButton(btn, function () {
        var scope = btn.closest("[data-select-all-root]") || root;
        return toArray(scope.querySelectorAll(sel));
      }, action !== "none");
    });
  }

  function autoBind(root) {
    root = root || document;
    var ibankOpts = global.LFSelectAllIbankOptions || {};
    try { bindIbankIncluded(root, ibankOpts); } catch (_e1) { /* keep going */ }
    try { bindDataSelectAllButtons(root); } catch (_e2) { /* keep going */ }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { autoBind(document); });
  } else {
    autoBind(document);
  }

  global.LFSelectAll = {
    setAllChecked: setAllChecked,
    syncMaster: syncMaster,
    bindMasterCheckbox: bindMasterCheckbox,
    bindSelectButton: bindSelectButton,
    bindIbankIncluded: bindIbankIncluded,
    autoBind: autoBind,
  };
})(window);
