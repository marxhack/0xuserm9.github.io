/* daffailhamramadan.github.io — progressive enhancement only.
   Every page works with this file blocked. No dependencies. */

(function () {
  "use strict";

  /* --- Footer year ------------------------------------------------------- */

  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });

  /* --- Reading progress -------------------------------------------------- */
  /* scaleX, not width: width is a layout property and thrashes on every frame. */

  var bar = document.querySelector(".progress");
  if (bar) {
    var ticking = false;

    var update = function () {
      ticking = false;
      var doc = document.documentElement;
      var scrollable = doc.scrollHeight - window.innerHeight;
      var ratio = scrollable > 0 ? window.scrollY / scrollable : 0;
      if (ratio < 0) ratio = 0;
      if (ratio > 1) ratio = 1;
      bar.style.transform = "scaleX(" + ratio + ")";
    };

    var onScroll = function () {
      if (!ticking) {
        ticking = true;
        window.requestAnimationFrame(update);
      }
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    update();
  }

  /* --- Copy buttons on code blocks --------------------------------------- */

  /* Horizontally scrollable regions must be keyboard-reachable. Done here so
     every future post inherits it without the author remembering a tabindex. */
  document.querySelectorAll(".code pre, .table-wrap").forEach(function (el) {
    el.tabIndex = 0;
  });

  document.querySelectorAll(".code").forEach(function (fig) {
    var pre = fig.querySelector("pre");
    var btn = fig.querySelector(".code__copy");
    if (!pre || !btn) return;

    /* Captured once, outside the handler: reading it back mid-flight would
       latch the button on "Copied" after two clicks inside the timeout. */
    var label = btn.textContent;
    var timer = null;

    btn.hidden = false;

    var done = function (ok) {
      btn.textContent = ok ? "Copied" : "Failed";
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        btn.textContent = label;
      }, 1600);
    };

    btn.addEventListener("click", function () {
      /* textContent, not innerText: <mark> is display:block, which makes
         innerText inject blank lines — enough to corrupt a copied HTTP
         request, where a blank line ends the header section. */
      var text = pre.textContent;

      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(
          function () {
            done(true);
          },
          function () {
            done(false);
          }
        );
        return;
      }

      /* Fallback for non-secure contexts (e.g. plain-http local preview). */
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      document.body.removeChild(ta);
      done(ok);
    });
  });

  /* --- Active table-of-contents item ------------------------------------- */

  var toc = document.querySelector(".toc");
  if (toc && "IntersectionObserver" in window) {
    var items = {};
    var order = [];

    toc.querySelectorAll("a[href^='#']").forEach(function (a) {
      var id = a.getAttribute("href").slice(1);
      var li = a.closest("li");
      if (!id || !li) return;
      items[id] = li;
      order.push(id);
    });

    var visible = new Set();
    var lastActive = null;

    /* A heading only crosses the observation band briefly, so tracking just
       the currently-intersecting one leaves the TOC blank for most of the
       scroll. Latch the last heading that entered instead. */
    var paint = function () {
      var current = null;
      for (var i = 0; i < order.length; i++) {
        if (visible.has(order[i])) {
          current = order[i];
          break;
        }
      }
      if (current) lastActive = current;
      if (window.scrollY <= 0) lastActive = null;

      order.forEach(function (id) {
        items[id].classList.toggle("is-active", id === lastActive);
      });
    };

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        });
        paint();
      },
      { rootMargin: "0px 0px -70% 0px", threshold: 0 }
    );

    order.forEach(function (id) {
      var target = document.getElementById(id);
      if (target) observer.observe(target);
    });
  }
})();
