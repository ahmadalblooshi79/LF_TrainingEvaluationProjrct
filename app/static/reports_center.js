(function () {
  var root = document.getElementById("reports-center");
  if (!root) return;

  var catalogEl = document.getElementById("reports-catalog-json");
  var catalog = { phases: [], units: [], judges: [], lists: [], ratings: [] };
  try {
    catalog = JSON.parse(catalogEl ? catalogEl.textContent || "{}" : "{}") || catalog;
  } catch (e) {
    catalog = { phases: [], units: [], judges: [], lists: [], ratings: [] };
  }

  var typeSel = document.getElementById("report-type");
  var existingPanel = document.getElementById("existing-export-panel");
  var detailedPanel = document.getElementById("detailed-report-panel");
  var phaseSel = document.getElementById("filter-phase");
  var unitSel = document.getElementById("filter-unit");
  var judgeSel = document.getElementById("filter-judge");
  var listSel = document.getElementById("filter-list");
  var listSearch = document.getElementById("filter-list-search");
  var ratingAll = document.getElementById("rating-all");
  var ratingBoxes = Array.prototype.slice.call(document.querySelectorAll(".rating-box"));
  var showNotes = document.getElementById("show-notes");
  var notesOnly = document.getElementById("notes-only");
  var previewSearch = document.getElementById("preview-search");
  var tbody = document.querySelector("#preview-table tbody");
  var matchCount = document.getElementById("match-count");
  var emptyMsg = document.getElementById("empty-msg");
  var summaryWrap = document.getElementById("summary-wrap");
  var previewWrap = document.getElementById("preview-wrap");
  var summaryCards = document.getElementById("summary-cards");
  var btnPreview = document.getElementById("btn-preview");
  var previewButtons = Array.prototype.slice.call(document.querySelectorAll(".js-reports-preview"));
  var btnExport = document.getElementById("btn-export");
  var btnReset = document.getElementById("btn-reset");

  var PRESETS = {
    full: ["ممتاز", "جيد جدا", "جيد", "مقبول", "راسب"],
    weakness: ["مقبول", "راسب"],
    high_performance: ["ممتاز", "جيد جدا"],
    detailed: ["ممتاز", "جيد جدا", "جيد", "مقبول", "راسب"]
  };

  var lastPreviewFilters = null;
  var lastRows = [];
  var sortKey = "";
  var sortAsc = true;

  function fillSelect(sel, options, allLabel, current) {
    if (!sel) return;
    var keep = current || "";
    sel.innerHTML = "";
    var all = document.createElement("option");
    all.value = "";
    all.textContent = allLabel;
    sel.appendChild(all);
    (options || []).forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.key;
      o.textContent = opt.label;
      sel.appendChild(o);
    });
    var valid = !keep || Array.prototype.some.call(sel.options, function (o) { return o.value === keep; });
    sel.value = valid ? keep : "";
  }

  function listsFor(phase, unit, judge, q) {
    return (catalog.lists || []).filter(function (row) {
      if (phase && row.phase_key !== phase) return false;
      if (unit && row.unit_key !== unit) return false;
      if (judge && row.judge_key !== judge) return false;
      if (q && String(row.list_label || "").indexOf(q) === -1) return false;
      return true;
    });
  }

  function uniqueOptions(rows, keyField, labelField) {
    var seen = {};
    var out = [];
    rows.forEach(function (row) {
      var k = row[keyField];
      if (!k || seen[k]) return;
      seen[k] = true;
      out.push({ key: k, label: row[labelField] || k });
    });
    return out;
  }

  function refreshCascades() {
    var phaseKeep = phaseSel.value;
    var unitKeep = unitSel.value;
    var judgeKeep = judgeSel.value;
    var listKeep = listSel.value;
    var q = (listSearch.value || "").trim();
    var phaseBase = (catalog.phases && catalog.phases.length) ? catalog.phases : uniqueOptions(catalog.lists || [], "phase_key", "phase_label");
    fillSelect(phaseSel, phaseBase, "جميع المراحل", phaseKeep);
    var phase = phaseSel.value;
    fillSelect(unitSel, uniqueOptions(listsFor(phase, "", "", ""), "unit_key", "unit_label"), "جميع الوحدات", unitKeep);
    var unit = unitSel.value;
    fillSelect(judgeSel, uniqueOptions(listsFor(phase, unit, "", ""), "judge_key", "judge_label"), "جميع المحكمين", judgeKeep);
    var judge = judgeSel.value;
    var listOpts = [];
    var seen = {};
    listsFor(phase, unit, judge, q).forEach(function (row) {
      if (seen[row.list_key]) return;
      seen[row.list_key] = true;
      listOpts.push({ key: row.list_key, label: row.list_label });
    });
    fillSelect(listSel, listOpts, "جميع القوائم", listKeep);
    markStale();
  }

  function selectedRatings() {
    return ratingBoxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
  }

  function syncRatingAll() {
    ratingAll.checked = ratingBoxes.every(function (b) { return b.checked; });
  }

  function applyPreset(name) {
    var set = PRESETS[name] || PRESETS.detailed;
    ratingBoxes.forEach(function (b) {
      b.checked = set.indexOf(b.value) !== -1;
    });
    syncRatingAll();
    markStale();
  }

  function currentFilters() {
    var organize = "unified";
    var radio = document.querySelector('input[name="organize"]:checked');
    if (radio) organize = radio.value;
    return {
      report_type: typeSel.value,
      phase_key: phaseSel.value,
      unit_key: unitSel.value,
      judge_key: judgeSel.value,
      list_key: listSel.value,
      ratings: selectedRatings(),
      show_notes: showNotes.checked,
      notes_only: notesOnly.checked,
      organize: organize
    };
  }

  function filtersEqual(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  function markStale() {
    if (!lastPreviewFilters) return;
    if (!filtersEqual(currentFilters(), lastPreviewFilters)) {
      btnExport.disabled = true;
    }
  }

  function toggleType() {
    var existing = typeSel.value === "existing_excel";
    existingPanel.hidden = !existing;
    detailedPanel.hidden = existing;
  }

  function ratingClass(rating) {
    if (rating === "راسب") return "reports-rating--fail";
    if (rating === "مقبول") return "reports-rating--weak";
    return "";
  }

  function renderSummary(data) {
    var counts = data.counts || {};
    var pcts = data.percentages || {};
    var total = data.total || 0;
    var cards = [{ label: "إجمالي العناصر", value: total, pct: "" }];
    ["ممتاز", "جيد جدا", "جيد", "مقبول", "راسب"].forEach(function (k) {
      var n = counts[k] || 0;
      var p = pcts[k];
      cards.push({
        label: k,
        value: n,
        pct: total ? (p == null ? "" : String(p) + "%") : "0%",
        rating: k
      });
    });
    summaryCards.innerHTML = cards.map(function (c) {
      return '<div class="reports-summary__card ' + ratingClass(c.rating || "") + '">' +
        '<div class="reports-summary__label">' + c.label + "</div>" +
        '<div class="reports-summary__value">' + c.value + "</div>" +
        (c.pct ? '<div class="reports-summary__pct">' + c.pct + "</div>" : "") +
        "</div>";
    }).join("");
    summaryWrap.hidden = false;
  }

  function visibleRows() {
    var q = (previewSearch.value || "").trim();
    var rows = lastRows.slice();
    if (q) {
      rows = rows.filter(function (r) {
        var blob = [r.unit, r.judge, r.list_title, r.element, r.notes, r.phase, r.rating].join(" ");
        return blob.indexOf(q) !== -1;
      });
    }
    if (sortKey) {
      rows.sort(function (a, b) {
        var av = String(a[sortKey] || "");
        var bv = String(b[sortKey] || "");
        if (av < bv) return sortAsc ? -1 : 1;
        if (av > bv) return sortAsc ? 1 : -1;
        return 0;
      });
    }
    return rows;
  }

  function addCell(tr, text, className) {
    var td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = text == null ? "" : String(text);
    tr.appendChild(td);
  }

  function renderTable() {
    var rows = visibleRows();
    tbody.innerHTML = "";
    rows.forEach(function (r, idx) {
      var tr = document.createElement("tr");
      addCell(tr, idx + 1);
      addCell(tr, r.phase);
      addCell(tr, r.unit);
      addCell(tr, r.judge);
      addCell(tr, r.list_title);
      addCell(tr, r.element);
      addCell(tr, r.rating, ratingClass(r.rating));
      addCell(tr, r.notes);
      tbody.appendChild(tr);
    });
    matchCount.textContent = "النتائج المطابقة: " + rows.length;
    emptyMsg.hidden = rows.length > 0;
    document.getElementById("preview-table").hidden = rows.length === 0;
  }

  function setPreviewBusy(busy) {
    previewButtons.forEach(function (btn) {
      btn.disabled = busy;
    });
  }

  function loadPreview() {
    var body = currentFilters();
    setPreviewBusy(true);
    fetch(root.getAttribute("data-preview-url"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      if (!res.ok) throw new Error("preview failed");
      return res.json();
    }).then(function (data) {
      lastPreviewFilters = body;
      lastRows = data.rows || [];
      renderSummary(data);
      previewWrap.hidden = false;
      renderTable();
      btnExport.disabled = !lastRows.length;
      summaryWrap.scrollIntoView({ behavior: "smooth", block: "start" });
    }).catch(function () {
      lastRows = [];
      summaryWrap.hidden = false;
      previewWrap.hidden = false;
      emptyMsg.hidden = false;
      matchCount.textContent = "النتائج المطابقة: 0";
      btnExport.disabled = true;
      previewWrap.scrollIntoView({ behavior: "smooth", block: "start" });
    }).finally(function () {
      setPreviewBusy(false);
    });
  }

  function exportXlsx() {
    if (!lastPreviewFilters || btnExport.disabled) return;
    if (!filtersEqual(currentFilters(), lastPreviewFilters)) {
      btnExport.disabled = true;
      return;
    }
    fetch(root.getAttribute("data-export-url"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastPreviewFilters)
    }).then(function (res) {
      if (!res.ok) throw new Error("export failed");
      var disp = res.headers.get("Content-Disposition") || "";
      var match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disp);
      var name = "report.xlsx";
      if (match) name = decodeURIComponent(match[1] || match[2] || name);
      return res.blob().then(function (blob) { return { blob: blob, name: name }; });
    }).then(function (file) {
      var url = URL.createObjectURL(file.blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
  }

  function resetFilters() {
    typeSel.value = "detailed";
    phaseSel.value = "";
    unitSel.value = "";
    judgeSel.value = "";
    listSel.value = "";
    listSearch.value = "";
    previewSearch.value = "";
    showNotes.checked = true;
    notesOnly.checked = false;
    document.querySelector('input[name="organize"][value="unified"]').checked = true;
    applyPreset("detailed");
    lastPreviewFilters = null;
    lastRows = [];
    summaryWrap.hidden = true;
    previewWrap.hidden = true;
    btnExport.disabled = true;
    toggleType();
    refreshCascades();
  }

  typeSel.addEventListener("change", function () {
    if (PRESETS[typeSel.value]) applyPreset(typeSel.value);
    toggleType();
    markStale();
  });
  document.querySelectorAll("[data-preset]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var name = btn.getAttribute("data-preset");
      typeSel.value = name === "full" || name === "weakness" || name === "high_performance" ? name : "detailed";
      applyPreset(name);
    });
  });
  [phaseSel, unitSel, judgeSel, listSel].forEach(function (sel) {
    sel.addEventListener("change", refreshCascades);
  });
  listSearch.addEventListener("input", refreshCascades);
  ratingAll.addEventListener("change", function () {
    ratingBoxes.forEach(function (b) { b.checked = ratingAll.checked; });
    markStale();
  });
  ratingBoxes.forEach(function (b) {
    b.addEventListener("change", function () {
      syncRatingAll();
      markStale();
    });
  });
  [showNotes, notesOnly].forEach(function (el) {
    el.addEventListener("change", markStale);
  });
  document.querySelectorAll('input[name="organize"]').forEach(function (el) {
    el.addEventListener("change", markStale);
  });
  previewSearch.addEventListener("input", renderTable);
  document.querySelectorAll("#preview-table th[data-sort]").forEach(function (th) {
    th.style.cursor = "pointer";
    th.addEventListener("click", function () {
      var key = th.getAttribute("data-sort");
      if (sortKey === key) sortAsc = !sortAsc;
      else { sortKey = key; sortAsc = true; }
      renderTable();
    });
  });
  previewButtons.forEach(function (btn) {
    btn.addEventListener("click", loadPreview);
  });
  if (btnExport) btnExport.addEventListener("click", exportXlsx);
  if (btnReset) btnReset.addEventListener("click", resetFilters);

  toggleType();
  refreshCascades();
})();
