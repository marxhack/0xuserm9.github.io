/* Tiny inline syntax highlighter — no CDN, no build step, no network.
   Drop this <script> tag right before </body> on any post page.
   It reads the language label already shown in .code__bar and colors
   the matching <pre><code> block using the .tk-* classes in style.css. */
(function () {
  var RULES = {
    python: [
      [/(#.*$)/gm, "tk-c"],
      [/("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/g, "tk-s"],
      [/\b(def|class|import|from|as|return|if|elif|else|for|while|with|in|not|and|or|is|None|True|False|try|except|raise|yield|lambda|pass|break|continue)\b/g, "tk-k"],
      [/\b(\d+\.?\d*)\b/g, "tk-n"],
      [/\b([a-zA-Z_]\w*)(?=\()/g, "tk-fn"],
    ],
    bash: [
      [/(#.*$)/gm, "tk-c"],
      [/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/g, "tk-s"],
      [/\b(curl|echo|export|cd|ls|grep|cat|sudo|python3?|pip3?|chmod|if|then|fi|for|do|done)\b/g, "tk-k"],
      [/(\s)(-{1,2}[\w-]+)/g, "$1tk-p"],
    ],
    json: [
      [/("(?:\\.|[^"\\])*")(\s*:)/g, "tk-fn$2"],
      [/:\s*("(?:\\.|[^"\\])*")/g, ": tk-s"],
      [/\b(true|false|null)\b/g, "tk-k"],
      [/\b(-?\d+\.?\d*)\b/g, "tk-n"],
    ],
    http: [
      [/^(GET|POST|PUT|DELETE|PATCH|HTTP\/\d\.\d|HTTP\/1\.1)\b/gm, "tk-k"],
      [/^([\w-]+)(:)/gm, "tk-fn$2"],
      [/\b(\d{3})\b/g, "tk-n"],
    ],
  };

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Applies a list of [regex, class] rules to plain text, returns HTML.
  // Regexes must not overlap in a way that double-wraps — kept simple on purpose.
  function tokenize(text, rules) {
    var marks = []; // {start, end, cls}
    rules.forEach(function (rule) {
      var re = rule[0], cls = rule[1];
      var m;
      re.lastIndex = 0;
      while ((m = re.exec(text))) {
        if (cls.indexOf("$1") === -1 && cls.indexOf("$2") === -1) {
          marks.push({ start: m.index, end: m.index + m[0].length, cls: cls });
        } else {
          // group-aware class string like "tk-fn$2" -> color only group 1, keep group 2 plain
          var g1 = m[1] || "";
          marks.push({ start: m.index, end: m.index + g1.length, cls: cls.split("$")[0] });
        }
        if (m[0].length === 0) re.lastIndex++;
      }
    });
    marks.sort(function (a, b) { return a.start - b.start || b.end - a.end; });

    var out = "", pos = 0;
    marks.forEach(function (mk) {
      if (mk.start < pos) return; // skip overlaps, first match wins
      out += escapeHtml(text.slice(pos, mk.start));
      out += '<span class="' + mk.cls + '">' + escapeHtml(text.slice(mk.start, mk.end)) + "</span>";
      pos = mk.end;
    });
    out += escapeHtml(text.slice(pos));
    return out;
  }

  document.querySelectorAll(".code").forEach(function (fig) {
    var bar = fig.querySelector(".code__bar");
    var codeEl = fig.querySelector("pre > code");
    if (!bar || !codeEl) return;

    var lang = bar.textContent.trim().toLowerCase();
    var rules = RULES[lang];
    if (!rules) return; // leave text/plain/output blocks untouched

    var raw = codeEl.textContent;
    codeEl.innerHTML = tokenize(raw, rules);
  });
})();
