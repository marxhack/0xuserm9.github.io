/* daffailhamramadan.github.io — progressive enhancement only.
   Every page works with this file blocked. No dependencies. */

(function () {
  "use strict";

  /* --- Ambient constellation background ----------------------------------- */
  /* Purely decorative. Kept faint enough to sit under long-form reading, and
     it stops entirely when off-tab or when reduced motion is requested. */

  (function background() {
    var host = document.querySelector(".bg");
    if (!host) return;

    var cv = host.querySelector("canvas");
    if (!cv || !cv.getContext) return;

    var ctx = cv.getContext("2d");
    if (!ctx) return;

    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    var LINK_DIST = 150;
    var CURSOR_DIST = 210;
    var LEAN = 0.16;

    /* The network is drawn everywhere but is almost invisible until the
       pointer is near it: the cursor carries a reveal radius that lifts
       nodes and links from BASE_* up to LIT_*. */
    var REVEAL_R = 340;
    var BASE_NODE = 0.05;
    var LIT_NODE = 0.8;
    var BASE_LINK = 0.015;
    var LIT_LINK = 0.5;
    var nodes = [];
    var w = 0;
    var h = 0;
    var raf = null;

    /* Pointer state. `sx`/`sy` chase the raw position so the pull trails the
       cursor instead of snapping to it, and `strength` fades the whole effect
       in and out rather than switching it. */
    var ptr = { x: 0, y: 0, sx: 0, sy: 0, strength: 0, target: 0, seen: false };

    var build = function () {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      var count = Math.max(14, Math.min(66, Math.round((w * h) / 18000)));
      nodes = [];
      for (var i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.16,
          vy: (Math.random() - 0.5) * 0.16,
          r: 0.9 + Math.random() * 1.1
        });
      }
    };

    var draw = function () {
      ctx.clearRect(0, 0, w, h);

      var i, j, a, b, dx, dy, d, f;

      /* Ease the pointer and its influence. */
      ptr.strength += (ptr.target - ptr.strength) * 0.07;
      ptr.sx += (ptr.x - ptr.sx) * 0.12;
      ptr.sy += (ptr.y - ptr.sy) * 0.12;
      var pull = ptr.seen ? ptr.strength : 0;

      /* Reduced motion draws one still frame and never sees a cursor, so the
         reveal would leave it blank. Fall back to an even wash instead. */
      var uniform = reduced.matches;

      /* Drift the base positions, then derive a render position that leans
         toward the cursor. Leaning the render position rather than nudging
         velocity means nodes spring back and can never clump permanently. */
      for (i = 0; i < nodes.length; i++) {
        a = nodes[i];
        a.x += a.vx;
        a.y += a.vy;
        if (a.x < -40) a.x = w + 40;
        else if (a.x > w + 40) a.x = -40;
        if (a.y < -40) a.y = h + 40;
        else if (a.y > h + 40) a.y = -40;

        a.rx = a.x;
        a.ry = a.y;
        a.near = 0;

        if (pull > 0.001) {
          dx = ptr.sx - a.x;
          dy = ptr.sy - a.y;
          d = Math.sqrt(dx * dx + dy * dy);
          if (d < CURSOR_DIST && d > 0.5) {
            a.near = 1 - d / CURSOR_DIST;
            f = a.near * LEAN * pull;
            a.rx += dx * f;
            a.ry += dy * f;
          }
        }
      }

      ctx.lineWidth = 1;

      /* How lit is this point? 1 under the cursor, 0 beyond the reveal
         radius, smoothstepped so the edge of the pool has no hard rim. */
      var lit = function (x, y) {
        if (pull <= 0.001) return 0;
        var ex = x - ptr.sx;
        var ey = y - ptr.sy;
        var ed = Math.sqrt(ex * ex + ey * ey);
        if (ed >= REVEAL_R) return 0;
        var t = 1 - ed / REVEAL_R;
        return t * t * (3 - 2 * t) * pull;
      };

      /* Node-to-node links, lit by the midpoint of each segment. */
      for (i = 0; i < nodes.length; i++) {
        a = nodes[i];
        for (j = i + 1; j < nodes.length; j++) {
          b = nodes[j];
          dx = a.rx - b.rx;
          dy = a.ry - b.ry;
          if (dx > LINK_DIST || dx < -LINK_DIST || dy > LINK_DIST || dy < -LINK_DIST) {
            continue;
          }
          d = Math.sqrt(dx * dx + dy * dy);
          if (d >= LINK_DIST) continue;
          f = uniform
            ? BASE_LINK * 5
            : BASE_LINK +
              (LIT_LINK - BASE_LINK) * lit((a.rx + b.rx) / 2, (a.ry + b.ry) / 2);
          ctx.strokeStyle =
            "rgba(240,179,87," + (f * (1 - d / LINK_DIST)).toFixed(3) + ")";
          ctx.beginPath();
          ctx.moveTo(a.rx, a.ry);
          ctx.lineTo(b.rx, b.ry);
          ctx.stroke();
        }
      }

      /* Links to the cursor itself, so the pointer reads as the hub. */
      if (pull > 0.001) {
        for (i = 0; i < nodes.length; i++) {
          a = nodes[i];
          dx = ptr.sx - a.rx;
          dy = ptr.sy - a.ry;
          if (dx > CURSOR_DIST || dx < -CURSOR_DIST || dy > CURSOR_DIST || dy < -CURSOR_DIST) {
            continue;
          }
          d = Math.sqrt(dx * dx + dy * dy);
          if (d >= CURSOR_DIST) continue;
          ctx.strokeStyle =
            "rgba(240,179,87," +
            (0.4 * (1 - d / CURSOR_DIST) * pull).toFixed(3) +
            ")";
          ctx.beginPath();
          ctx.moveTo(a.rx, a.ry);
          ctx.lineTo(ptr.sx, ptr.sy);
          ctx.stroke();
        }
      }

      for (i = 0; i < nodes.length; i++) {
        a = nodes[i];
        f = uniform
          ? 0.2
          : BASE_NODE + (LIT_NODE - BASE_NODE) * lit(a.rx, a.ry);
        ctx.fillStyle = "rgba(233,230,224," + f.toFixed(3) + ")";
        ctx.beginPath();
        ctx.arc(a.rx, a.ry, a.r, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    var frame = function () {
      draw();
      raf = window.requestAnimationFrame(frame);
    };

    var stop = function () {
      if (raf !== null) {
        window.cancelAnimationFrame(raf);
        raf = null;
      }
    };

    var start = function () {
      if (raf === null && !reduced.matches && !document.hidden) {
        raf = window.requestAnimationFrame(frame);
      }
    };

    var sync = function () {
      stop();
      if (reduced.matches) draw();
      else start();
    };

    build();
    sync();

    var resizeTimer = null;
    window.addEventListener(
      "resize",
      function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(function () {
          build();
          sync();
        }, 200);
      },
      { passive: true }
    );

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
      else if (!reduced.matches) start();
    });

    /* Mouse only. Touch would fire once on tap and leave the pull stranded
       where the finger last was, which reads as a bug rather than an effect. */
    window.addEventListener(
      "pointermove",
      function (e) {
        if (e.pointerType === "touch") return;
        if (!ptr.seen) {
          ptr.sx = e.clientX;
          ptr.sy = e.clientY;
          ptr.seen = true;
        }
        ptr.x = e.clientX;
        ptr.y = e.clientY;
        ptr.target = 1;
      },
      { passive: true }
    );

    /* relatedTarget === null means the pointer left the window entirely. */
    document.addEventListener("pointerout", function (e) {
      if (!e.relatedTarget) ptr.target = 0;
    });

    window.addEventListener("blur", function () {
      ptr.target = 0;
    });

    if (reduced.addEventListener) reduced.addEventListener("change", sync);
    else if (reduced.addListener) reduced.addListener(sync);
  })();

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

  /* --- Clipboard ---------------------------------------------------------- */

  var writeClipboard = function (text, done) {
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

    /* Fallback for non-secure contexts, e.g. a plain-http local preview. */
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
  };

  /* Swap a label to Copied/Failed and back. The resting text is captured once
     at wiring time — reading it back mid-flight latches the button on "Copied"
     after two clicks inside the timeout. */
  var feedback = function (el) {
    var label = el.textContent;
    var timer = null;
    return function (ok) {
      el.textContent = ok ? "Copied" : "Failed";
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        el.textContent = label;
      }, 1600);
    };
  };

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

    var done = feedback(btn);
    btn.hidden = false;

    btn.addEventListener("click", function () {
      /* textContent, not innerText: <mark> is display:block, which makes
         innerText inject blank lines — enough to corrupt a copied HTTP
         request, where a blank line ends the header section. */
      writeClipboard(pre.textContent, done);
    });
  });

  /* --- Share: copy link --------------------------------------------------- */

  document.querySelectorAll(".share__copy").forEach(function (btn) {
    var text = btn.querySelector(".share__text");
    if (!text) return;

    var done = feedback(text);
    btn.hidden = false;

    btn.addEventListener("click", function () {
      writeClipboard(btn.getAttribute("data-url") || location.href, done);
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
