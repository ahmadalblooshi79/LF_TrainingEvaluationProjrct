/**
 * جسر التحكم المباشر + علامة التابلت — التطبيق رقم 2.
 * يزامن التنقل فقط؛ لا يرسل أوامر تكبير (كانت تسبب وميض scale على شاشة العرض).
 */
(function () {
  var ua = navigator.userAgent || "";
  var isTabletApp = /LFSystemTablet/i.test(ua) || window.LFSystemTabletBridge;
  if (!isTabletApp && !window.__LF_FORCE_TABLET_CSS) return;

  document.documentElement.classList.add("lf-system-tablet");

  if (!document.querySelector('link[data-lf-system-tablet-css]')) {
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/system_tablet.css?v=st-3";
    link.setAttribute("data-lf-system-tablet-css", "1");
    document.head.appendChild(link);
  }

  /* ثبّت viewport ضد التكبير العرضي باللمس */
  var vp = document.querySelector('meta[name="viewport"]');
  if (vp) {
    vp.setAttribute(
      "content",
      "width=device-width, initial-scale=1, minimum-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover"
    );
  }

  var bridge = window.LFSystemTabletBridge || null;
  var rcToken = null;
  var rcDisplay = "default";
  var rcEnabled = false;
  var lastPath = location.pathname + location.search + location.hash;
  var scrollTimer = null;

  function postCommand(type, path, payload) {
    if (!rcEnabled || !rcToken) return;
    var body = {
      session_token: rcToken,
      type: type,
      path: path || (location.pathname + location.search + location.hash),
      payload: payload || {}
    };
    try {
      fetch("/api/remote-control/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body)
      }).catch(function () {});
    } catch (e) {}
    if (bridge && typeof bridge.onRemoteCommand === "function") {
      try { bridge.onRemoteCommand(JSON.stringify(body)); } catch (e2) {}
    }
  }

  function notifyNavigate() {
    var p = location.pathname + location.search + location.hash;
    if (p === lastPath) return;
    lastPath = p;
    postCommand("navigate", p, {});
    if (bridge && typeof bridge.onNavigate === "function") {
      try { bridge.onNavigate(p); } catch (e) {}
    }
  }

  window.LFRemoteControl = {
    enable: function (token, displayId) {
      rcToken = token;
      rcDisplay = displayId || "default";
      rcEnabled = true;
      postCommand("navigate", lastPath, {});
    },
    disable: function () {
      rcEnabled = false;
      rcToken = null;
    },
    isEnabled: function () { return !!rcEnabled; },
    /* معطّل عمداً — لا مزامنة تكبير */
    sendZoomPan: function () {}
  };

  ["pushState", "replaceState"].forEach(function (k) {
    var orig = history[k];
    history[k] = function () {
      var r = orig.apply(this, arguments);
      setTimeout(notifyNavigate, 0);
      return r;
    };
  });
  window.addEventListener("popstate", notifyNavigate);
  window.addEventListener("hashchange", notifyNavigate);

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    setTimeout(notifyNavigate, 50);
  }, true);

  /* تمرير الصفحة فقط — بدون scale */
  window.addEventListener("scroll", function () {
    if (!rcEnabled) return;
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(function () {
      postCommand("scroll", lastPath, {
        scrollX: window.scrollX || 0,
        scrollY: window.scrollY || 0
      });
    }, 150);
  }, { passive: true });

  if (bridge && typeof bridge.onPageReady === "function") {
    try { bridge.onPageReady(lastPath); } catch (e) {}
  }
})();
