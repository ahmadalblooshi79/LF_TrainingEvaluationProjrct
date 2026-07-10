(function () {
  "use strict";

  var MIN_SCALE = 0.65;
  var MAX_SCALE = 3;
  var SCALE_STEP = 0.08;
  var PINCH_THRESHOLD = 0.006;

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function isFormTarget(el) {
    if (!el || !el.closest) return false;
    var node = el.closest("input, textarea, select, button, label, a, [contenteditable='true']");
    if (!node) return false;
    var tag = node.tagName;
    if (tag === "A" || tag === "BUTTON" || tag === "LABEL") return false;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || node.isContentEditable;
  }

  function touchDistance(touches) {
    if (touches.length < 2) return 0;
    var dx = touches[1].clientX - touches[0].clientX;
    var dy = touches[1].clientY - touches[0].clientY;
    return Math.hypot(dx, dy);
  }

  function touchCenter(touches) {
    if (!touches.length) return { x: 0, y: 0 };
    if (touches.length === 1) {
      return { x: touches[0].clientX, y: touches[0].clientY };
    }
    return {
      x: (touches[0].clientX + touches[1].clientX) / 2,
      y: (touches[0].clientY + touches[1].clientY) / 2,
    };
  }

  /* ── Header mobile drawer ── */
  function initHeaderNav() {
    var toggle = qs("#app-header-toggle");
    var backdrop = qs("#app-header-backdrop");
    if (!toggle) return;

    function setOpen(open) {
      document.body.classList.toggle("app-header-nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (backdrop) backdrop.hidden = !open;
    }

    toggle.addEventListener("click", function () {
      setOpen(!document.body.classList.contains("app-header-nav-open"));
    });

    if (backdrop) {
      backdrop.addEventListener("click", function () {
        setOpen(false);
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setOpen(false);
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth >= 1024) setOpen(false);
    });

    document.querySelectorAll(".header-bar__segment--center a, .header-bar__segment--trail a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.innerWidth < 1024) setOpen(false);
      });
    });
  }

  /* ── Admin sidebar drawer (tablet / mobile) ── */
  function initSidebar() {
    var sidebar = qs("#app-sidebar") || qs(".admin-shell__menu");
    var toggle = qs("#app-sidebar-toggle");
    var backdrop = qs("#app-sidebar-backdrop");
    if (!sidebar || !toggle) return;

    function setOpen(open) {
      document.body.classList.toggle("app-sidebar-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (backdrop) backdrop.hidden = !open;
    }

    toggle.addEventListener("click", function () {
      setOpen(!document.body.classList.contains("app-sidebar-open"));
    });

    if (backdrop) {
      backdrop.addEventListener("click", function () {
        setOpen(false);
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setOpen(false);
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth >= 1024) setOpen(false);
    });

    sidebar.querySelectorAll("a[href]").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.innerWidth < 1024) setOpen(false);
      });
    });
  }

  function ensureSidebarToggle() {
    if (!qs(".admin-shell__menu")) return;
    if (qs("#app-sidebar-toggle")) return;

    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = "app-sidebar-toggle";
    btn.className = "app-sidebar-toggle";
    btn.setAttribute("aria-controls", "app-sidebar");
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("title", "أوامر العمل");
    btn.innerHTML = '<i class="fa-solid fa-table-columns" aria-hidden="true"></i><span class="sr-only">أوامر العمل</span>';
    document.body.appendChild(btn);

    if (!qs("#app-sidebar-backdrop")) {
      var backdrop = document.createElement("button");
      backdrop.type = "button";
      backdrop.id = "app-sidebar-backdrop";
      backdrop.className = "app-sidebar-backdrop";
      backdrop.setAttribute("aria-label", "إغلاق القائمة");
      backdrop.hidden = true;
      document.body.appendChild(backdrop);
    }
  }

  /* ── Disable pull-to-refresh / overscroll bounce (Android / Samsung) ── */
  function initOverscrollGuard(state) {
    var touchStartY = 0;

    document.addEventListener(
      "touchstart",
      function (e) {
        if (e.touches.length) touchStartY = e.touches[0].clientY;
      },
      { passive: true }
    );

    document.addEventListener(
      "touchmove",
      function (e) {
        if (state.gesturing || e.touches.length >= 2 || state.scale > 1.02) {
          e.preventDefault();
          return;
        }
        if (isFormTarget(e.target)) return;

        var main = qs("main");
        var scrollTop = main ? main.scrollTop : window.scrollY || document.documentElement.scrollTop;
        var atTop = scrollTop <= 0;
        var pullingDown = e.touches.length === 1 && e.touches[0].clientY > touchStartY + 6;

        if (atTop && pullingDown) {
          e.preventDefault();
        }
      },
      { passive: false }
    );

    window.addEventListener(
      "wheel",
      function (e) {
        if (state.gesturing || state.scale > 1.02) {
          e.preventDefault();
        }
      },
      { passive: false }
    );
  }

  function getGestureSurface() {
    var mapRoot = qs("#battleOrgRoot");
    if (mapRoot) return mapRoot;
    var marked = qs("[data-gesture-surface]");
    if (marked) return marked;
    return qs("#app-zoom-surface");
  }

  /* ── Map-like pinch zoom + pan (1 or 2 fingers) ── */
  function initMapGestures() {
    var surface = getGestureSurface();
    if (!surface) return;

    surface.classList.add("app-gesture-surface");

    var state = {
      panX: 0,
      panY: 0,
      gesturing: false,
      mode: "none",
      lastDistance: 0,
      lastCenter: null,
      lastPointer: null,
      scale: 1,
    };

    var live = qs("#app-zoom-live");

    function announce() {
      if (live) live.textContent = Math.round(state.scale * 100) + "%";
    }

    function clampScale(value) {
      return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
    }

    function applyTransform() {
      if (state.scale === 1 && state.panX === 0 && state.panY === 0) {
        surface.style.transform = "";
        document.body.classList.remove("is-app-zoomed", "is-app-gesturing");
        surface.classList.remove("is-map-zoomed");
        announce();
        return;
      }
      surface.style.transform =
        "translate3d(" + state.panX + "px," + state.panY + "px,0) scale(" + state.scale + ")";
      document.body.classList.toggle("is-app-zoomed", state.scale > 1.02);
      surface.classList.toggle("is-map-zoomed", state.scale > 1.02);
      announce();
    }

    function resetTransform() {
      state.scale = 1;
      state.panX = 0;
      state.panY = 0;
      applyTransform();
    }

    function setGesturing(on) {
      state.gesturing = on;
      document.body.classList.toggle("is-app-gesturing", on);
    }

    function onTouchStart(e) {
      if (isFormTarget(e.target)) return;

      if (e.touches.length >= 2) {
        setGesturing(true);
        state.mode = "pinch";
        state.lastDistance = touchDistance(e.touches);
        state.lastCenter = touchCenter(e.touches);
        state.lastPointer = null;
        document.body.classList.add("is-app-zooming");
        return;
      }

      if (e.touches.length === 1 && state.scale > 1.02) {
        setGesturing(true);
        state.mode = "pan";
        state.lastPointer = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        state.lastDistance = 0;
        state.lastCenter = null;
        document.body.classList.add("is-app-zooming");
      }
    }

    function onTouchMove(e) {
      if (isFormTarget(e.target) && state.mode === "none") return;

      if (e.touches.length >= 2) {
        e.preventDefault();
        setGesturing(true);
        state.mode = "pinch";

        var dist = touchDistance(e.touches);
        var center = touchCenter(e.touches);

        if (state.lastDistance && state.lastCenter) {
          var ratio = dist / state.lastDistance;
          if (Math.abs(ratio - 1) > PINCH_THRESHOLD) {
            state.scale = clampScale(state.scale * ratio);
          }
          state.panX += center.x - state.lastCenter.x;
          state.panY += center.y - state.lastCenter.y;
        }

        state.lastDistance = dist;
        state.lastCenter = center;
        applyTransform();
        return;
      }

      if (e.touches.length === 1 && state.mode === "pan" && state.scale > 1.02) {
        e.preventDefault();
        setGesturing(true);
        var x = e.touches[0].clientX;
        var y = e.touches[0].clientY;
        if (state.lastPointer) {
          state.panX += x - state.lastPointer.x;
          state.panY += y - state.lastPointer.y;
        }
        state.lastPointer = { x: x, y: y };
        applyTransform();
      }
    }

    function onTouchEnd(e) {
      if (e.touches.length >= 2) return;

      if (e.touches.length === 1 && state.scale > 1.02) {
        state.mode = "pan";
        state.lastPointer = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        state.lastDistance = 0;
        state.lastCenter = null;
        return;
      }

      state.mode = "none";
      state.lastDistance = 0;
      state.lastCenter = null;
      state.lastPointer = null;
      setGesturing(false);
      document.body.classList.remove("is-app-zooming");

      if (state.scale < 0.92) {
        resetTransform();
      }
    }

    surface.addEventListener("touchstart", onTouchStart, { passive: true });
    surface.addEventListener("touchmove", onTouchMove, { passive: false });
    surface.addEventListener("touchend", onTouchEnd, { passive: true });
    surface.addEventListener("touchcancel", onTouchEnd, { passive: true });

    /* Ctrl + wheel (trackpad) */
    surface.addEventListener(
      "wheel",
      function (e) {
        if (!e.ctrlKey) return;
        e.preventDefault();
        setGesturing(true);
        document.body.classList.add("is-app-zooming");
        var delta = e.deltaY > 0 ? -SCALE_STEP : SCALE_STEP;
        state.scale = clampScale(state.scale + delta);
        applyTransform();
        window.setTimeout(function () {
          setGesturing(false);
          document.body.classList.remove("is-app-zooming");
        }, 120);
      },
      { passive: false }
    );

    /* Double-tap reset */
    var lastTap = 0;
    surface.addEventListener(
      "touchend",
      function (e) {
        if (state.gesturing || e.touches.length || e.changedTouches.length !== 1) return;
        var now = Date.now();
        if (now - lastTap < 320) resetTransform();
        lastTap = now;
      },
      { passive: true }
    );

    document.addEventListener("keydown", function (e) {
      if (e.key === "0" && (e.ctrlKey || e.metaKey)) resetTransform();
    });

    initOverscrollGuard(state);
  }

  function init() {
    initHeaderNav();
    ensureSidebarToggle();
    initSidebar();
    initMapGestures();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
