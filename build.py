#!/usr/bin/env python3
"""
Build the site from Markdown.

    python3 build.py

Reads  content/posts/*.md   (your Obsidian vault)
Writes posts/<slug>.html    plus the post lists in posts/index.html and index.html
Copies content/attachments/ into assets/posts/

Everything it writes is generated — edit the Markdown, never the HTML.
On first run it creates .venv and installs the one dependency it needs.

Design note: this script fails loudly. Anything ambiguous — two posts claiming
one slug, an unterminated front matter block, a date it cannot read — stops the
build with a message naming the file. A blog build that silently drops a post is
worse than one that refuses to run.
"""

import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

CONTENT = ROOT / "content" / "posts"
ATTACHMENTS = ROOT / "content" / "attachments"
OUT = ROOT / "posts"
ASSETS_POSTS = ROOT / "assets" / "posts"
TEMPLATE = ROOT / "templates" / "post.html"
HOME_PAGE = ROOT / "index.html"

SITE = "https://daffailhamramadan.github.io"
RECENT_ON_HOME = 5
WORDS_PER_MINUTE = 220

# posts/index.html is the archive shell, not a post.
RESERVED_SLUGS = {"index"}

WARNINGS = []


def warn(message):
    WARNINGS.append(message)


def die(message):
    raise SystemExit(f"\nbuild failed: {message}\n")


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------

BOOTSTRAP_FLAG = "BUILD_PY_BOOTSTRAPPED"


def ensure_deps():
    """Import markdown, creating .venv and installing it on first run."""
    try:
        import markdown  # noqa: F401
        return
    except ImportError:
        pass

    stage = os.environ.get(BOOTSTRAP_FLAG)

    # Bounded at two re-execs. Without a guard, a venv where the install
    # "succeeds" but the import still fails would exec itself forever.
    if stage == "installed":
        die(
            "the markdown package is still not importable after installing it into\n"
            f"  {VENV}\n"
            "Delete that directory and run again, or install it yourself with:\n"
            f"  {VENV_PY} -m pip install markdown"
        )

    # Common path: the venv already exists and is fine. Hand over to it before
    # reaching for pip, so a normal build never touches the network.
    if stage is None and VENV_PY.exists():
        os.environ[BOOTSTRAP_FLAG] = "tried-venv"
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

    try:
        if not VENV_PY.exists():
            print("First run — creating .venv ...", file=sys.stderr)
            # --clear repairs a half-built or dangling venv rather than dying on it.
            subprocess.check_call(
                [sys.executable, "-m", "venv", "--clear", str(VENV)]
            )
        print("Installing markdown ...", file=sys.stderr)
        subprocess.check_call(
            [str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip", "markdown"]
        )
    except subprocess.CalledProcessError as exc:
        die(
            f"could not set up .venv ({exc}).\n"
            "If you are offline, connect and retry. Otherwise remove .venv and run again."
        )

    os.environ[BOOTSTRAP_FLAG] = "installed"
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])


ensure_deps()
import markdown  # noqa: E402


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def read_text(path):
    """utf-8-sig strips a BOM if present. A BOM before '---' would otherwise
    make front matter invisible and publish drafts."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        die(f"{path.name}: not valid UTF-8 ({exc}). Re-save the file as UTF-8.")


FM_LINE = re.compile(r"^(?:[A-Za-z_][\w-]*\s*:|-\s|#|\s*$)")


def parse_front_matter(text, name="<string>"):
    """A small YAML subset: key: value, [a, b] lists, and - item lists.

    The closing fence is only looked for within the run of lines that actually
    look like front matter. Searching the whole file means one forgotten '---'
    swallows the post body up to the next horizontal rule.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text

    close = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            close = i
            break
        if not FM_LINE.match(line):
            break

    if close is None:
        die(
            f"{name}: the front matter block is never closed.\n"
            "Add a line containing only --- after the last key."
        )

    meta = {}
    key = None
    for line in lines[1:close]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        stripped = line.strip()
        if stripped.startswith("- ") and key:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_scalar(stripped[2:]))
            continue

        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [_scalar(p) for p in inner.split(",") if p.strip()] if inner else []
        elif value == "":
            meta[key] = []
        else:
            meta[key] = _scalar(value)

    return meta, "\n".join(lines[close + 1 :]).lstrip("\n")


def _scalar(v):
    v = v.strip()
    # Only a matched pair. Stripping unconditionally truncates a title that
    # legitimately ends in a quote.
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    return v


# --------------------------------------------------------------------------
# Obsidian syntax -> plain Markdown
# --------------------------------------------------------------------------

# Fenced blocks and inline spans, so rewrites can skip them. Without this,
# `[[ -f x ]]` in a shell snippet is eaten by the wikilink rule.
CODE_SPAN = re.compile(
    r"(?P<fenced>^(?P<fence>```+|~~~+)[^\n]*\n.*?(?:^(?P=fence)[^\n]*$|\Z))"
    r"|(?P<inline>`+[^`\n]*`+)",
    re.M | re.S,
)

CALLOUT = re.compile(
    r"^> \[!(?P<kind>[A-Za-z]+)\][+-]?[ \t]*(?P<title>[^\n]*)(?:\n|$)"
    r"(?P<body>(?:^>[^\n]*(?:\n|$))*)",
    re.M,
)

WARN_KINDS = {"warning", "caution", "danger", "bug", "failure", "error", "attention"}


def outside_code(text, fn):
    """Apply fn to every part of text that is not fenced or inline code."""
    parts = []
    pos = 0
    for m in CODE_SPAN.finditer(text):
        parts.append(fn(text[pos : m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(fn(text[pos:]))
    return "".join(parts)


def obsidian_to_markdown(text, aliases):
    """Rewrite Obsidian-only syntax into Markdown the renderer understands.

    Every rule runs only outside code, so posts can document this syntax and
    shell snippets keep their brackets.
    """

    def callout(m):
        kind = m.group("kind").lower()
        title = m.group("title").strip()
        body = "\n".join(
            re.sub(r"^>[ \t]?", "", ln) for ln in m.group("body").split("\n")
        ).strip()
        variant = " note--warn" if kind in WARN_KINDS else ""
        # Title as its own block: gluing it onto the first body line breaks any
        # list or fence that starts the body.
        lead = f"**{title}.**\n\n" if title else ""
        return f'\n<aside class="note{variant}" markdown="1">\n\n{lead}{body}\n\n</aside>\n\n'

    def embed(m):
        target = m.group(1).strip()
        extra = (m.group(2) or "").strip()
        # Obsidian's size syntax: ![[img.png|400]] or |400x300 — not a caption.
        if re.fullmatch(r"\d+(x\d+)?", extra):
            return f"![](/assets/posts/{target})"
        return f"![{extra}](/assets/posts/{target})"

    def wikilink(m):
        target = m.group(1).strip()
        label = (m.group(2) or target).strip()
        page, _, anchor = target.partition("#")
        slug = aliases.get(slugify(page or target))
        if not slug:
            return label
        frag = f"#{slugify(anchor)}" if anchor else ""
        return f"[{label}](/posts/{slug}.html{frag})"

    def rewrite(chunk):
        chunk = CALLOUT.sub(callout, chunk)
        chunk = re.sub(r"!\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]", embed, chunk)
        chunk = re.sub(r"\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]", wikilink, chunk)
        return chunk

    return outside_code(text, rewrite)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def slugify(value):
    value = re.sub(r"[^\w\s-]", "", str(value)).strip().lower()
    return re.sub(r"[\s_]+", "-", value)


def strip_date_prefix(stem):
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)


def esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def postprocess(html):
    """Turn generic Markdown output into this site's components."""

    def code_figure(m):
        attrs = m.group("attrs") or ""
        lang = "code"
        cls = re.search(r'class="([^"]*)"', attrs)
        if cls:
            for token in cls.group(1).split():
                lang = token[9:] if token.startswith("language-") else token
                break
        return (
            '<figure class="code">\n'
            '  <div class="code__bar">\n'
            f"    <span>{lang}</span>\n"
            '    <button type="button" class="code__copy" hidden>Copy</button>\n'
            "  </div>\n"
            f"  <pre><code>{m.group('body')}</code></pre>\n"
            "</figure>"
        )

    html = re.sub(
        r"<pre[^>]*><code(?P<attrs>[^>]*)>(?P<body>.*?)</code></pre>",
        code_figure,
        html,
        flags=re.S,
    )

    # A paragraph holding nothing but one image becomes a figure. A paragraph
    # with an image *and* text must not be touched.
    def figure(m):
        src, alt = m.group("src"), m.group("alt") or ""
        cap = f"\n  <figcaption>{alt}</figcaption>" if alt else ""
        return (
            f'<figure class="figure">\n  <img src="{src}" alt="{alt}" '
            f'loading="lazy" decoding="async">{cap}\n</figure>'
        )

    html = re.sub(
        r'<p>\s*<img\s+(?=[^>]*src="(?P<src>[^"]+)")(?=[^>]*alt="(?P<alt>[^"]*)")[^>]*>\s*</p>',
        figure,
        html,
    )

    # Tables scroll in their own container. Only real table elements — a
    # <table> written inside a code sample is already escaped to &lt;table&gt;
    # by this point, so it cannot be hit here.
    html = html.replace("<table>", '<div class="table-wrap">\n<table>')
    html = html.replace("</table>", "</table>\n</div>")

    counter = {"n": 0}

    def number_h2(m):
        counter["n"] += 1
        return (
            f'<h2 id="{m.group("id")}"><span class="num">{counter["n"]:02d}</span>'
            f'{m.group("text")}</h2>'
        )

    html = re.sub(
        r'<h2 id="(?P<id>[^"]+)">(?P<text>.*?)</h2>', number_h2, html, flags=re.S
    )

    return html


def build_toc(tokens):
    if len(tokens) < 2:
        return ""
    # toc_tokens names arrive already HTML-escaped; esc() here would double it.
    items = "\n".join(
        f'            <li><a href="#{t["id"]}">{t["name"]}</a></li>' for t in tokens
    )
    return (
        '\n        <details class="toc">\n'
        "          <summary>Contents</summary>\n"
        "          <ol>\n" + items + "\n          </ol>\n"
        "        </details>\n"
    )


def indent(block, spaces):
    """Indent for readability, but never inside <pre> — whitespace is content
    there, and padding it silently rewrites every code sample."""
    pad = " " * spaces
    out = []
    inside_pre = False
    for line in block.split("\n"):
        out.append(line if inside_pre else (pad + line if line.strip() else line))
        if not inside_pre and "<pre" in line and "</pre>" not in line:
            inside_pre = True
        elif inside_pre and "</pre>" in line:
            inside_pre = False
    return "\n".join(out)


# --------------------------------------------------------------------------
# Posts
# --------------------------------------------------------------------------

def post_slug(path, meta):
    raw = meta.get("slug") or strip_date_prefix(path.stem)
    slug = slugify(raw)
    if not slug:
        die(
            f"{path.name}: the title and filename contain no characters usable in a "
            "URL. Add an explicit `slug:` to the front matter."
        )
    if slug in RESERVED_SLUGS:
        die(
            f"{path.name}: the slug '{slug}' is reserved — it would overwrite "
            f"posts/{slug}.html. Add a different `slug:` to the front matter."
        )
    return slug


def collect():
    if not CONTENT.exists():
        die(f"no {CONTENT.relative_to(ROOT)} directory — nothing to build.")

    sources = sorted(p for p in CONTENT.glob("*.md") if not p.name.startswith("_"))

    # One pass to map slugs and catch collisions before writing anything.
    claims = {}
    aliases = {}
    parsed = []
    for path in sources:
        meta, body = parse_front_matter(read_text(path), path.name)
        slug = post_slug(path, meta)
        claims.setdefault(slug, []).append(path.name)
        parsed.append((path, meta, body, slug))

    clashes = {s: names for s, names in claims.items() if len(names) > 1}
    if clashes:
        lines = [
            f"  '{slug}' claimed by: {', '.join(names)}"
            for slug, names in sorted(clashes.items())
        ]
        die(
            "two or more posts want the same URL, so one would overwrite the other:\n"
            + "\n".join(lines)
            + "\nGive one of them a distinct `slug:` in its front matter."
        )

    # Real slugs first; title aliases only fill gaps, so a title can never
    # hijack another post's actual filename slug.
    for _, meta, _, slug in parsed:
        if not meta.get("draft"):
            aliases[slug] = slug
    for _, meta, _, slug in parsed:
        if not meta.get("draft") and meta.get("title"):
            aliases.setdefault(slugify(meta["title"]), slug)

    posts, drafts = [], []
    for path, meta, body, slug in parsed:
        post = read_post(path, meta, body, slug, aliases)
        (drafts if post["draft"] else posts).append(post)

    posts.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)
    return posts, drafts


def resolve_date(path, meta):
    raw = meta.get("date")
    prefix = re.match(r"^(\d{4}-\d{2}-\d{2})-", path.stem)

    if raw:
        try:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except ValueError:
            if prefix:
                warn(
                    f"{path.name}: date '{raw}' is not YYYY-MM-DD — using the "
                    f"filename date {prefix.group(1)} instead."
                )
                return datetime.strptime(prefix.group(1), "%Y-%m-%d").date()
            die(
                f"{path.name}: date '{raw}' is not YYYY-MM-DD and the filename has "
                "no date prefix to fall back on."
            )

    if prefix:
        return datetime.strptime(prefix.group(1), "%Y-%m-%d").date()

    stamp = date.fromtimestamp(path.stat().st_mtime)
    warn(
        f"{path.name}: no date in front matter — using the file's modification "
        f"time ({stamp}). Add `date:` so it does not move between checkouts."
    )
    return stamp


def read_post(path, meta, body, slug, aliases):
    when = resolve_date(path, meta)
    md_body = obsidian_to_markdown(body, aliases)

    md = markdown.Markdown(
        extensions=["fenced_code", "tables", "attr_list", "md_in_html",
                    "sane_lists", "footnotes", "toc"],
        extension_configs={"toc": {"toc_depth": "2-2", "anchorlink": False}},
    )
    html = postprocess(md.convert(md_body))

    words = len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", html)))

    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    title = meta.get("title")
    if not title:
        title = strip_date_prefix(path.stem).replace("-", " ").title()
        warn(f"{path.name}: no `title:` in front matter — using '{title}'.")

    return {
        "source": path.name,
        "slug": slug,
        "title": str(title),
        "description": str(meta.get("description") or ""),
        "date": when,
        "tags": tags,
        "draft": bool(meta.get("draft", False)),
        "html": html,
        "toc": build_toc(getattr(md, "toc_tokens", [])),
        "reading_time": max(1, round(words / WORDS_PER_MINUTE)),
        "end": str(meta.get("end") or ""),
    }


PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def write_post(post, template):
    url = f"{SITE}/posts/{post['slug']}.html"
    values = {
        "TITLE": esc(post["title"]),
        "DESCRIPTION": esc(post["description"] or post["title"]),
        "URL": url,
        # Percent-encoded for the share intents. quote() with no safe chars so
        # ':' and '/' are encoded too — some share endpoints mangle raw ones.
        "URL_ENC": quote(url, safe=""),
        "TITLE_ENC": quote(post["title"], safe=""),
        "DATE_ISO": post["date"].isoformat(),
        "DATE_HUMAN": post["date"].strftime("%-d %B %Y"),
        "READING_TIME": str(post["reading_time"]),
        "SOURCE": post["source"],
        "DEK": (
            f'          <p class="post__dek">{esc(post["description"])}</p>'
            if post["description"] else ""
        ),
        "TAGS_META": (
            f'            <span>{esc(" · ".join(post["tags"]))}</span>'
            if post["tags"] else ""
        ),
        "TOC": post["toc"],
        "BODY": indent(post["html"], 10),
        # Only what the author actually wrote. A default sign-off reads as
        # padding under a short post.
        "END": f"          <p>{esc(post['end'])}</p>" if post["end"] else "",
    }

    # One pass: a sequence of .replace() calls would re-scan inserted text, so a
    # post that mentions {{BODY}} would have its own content substituted again.
    page = PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)

    target = OUT / f"{post['slug']}.html"
    target.write_text(page, encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# Index lists
# --------------------------------------------------------------------------

def row_html(post):
    anchor = f"p-{post['slug']}"
    tags = "".join(f"<span>{esc(t)}</span>" for t in post["tags"])
    tags_block = f'\n              <span class="row__tags">{tags}</span>' if tags else ""
    dek = (
        f'\n              <span class="row__dek">{esc(post["description"])}</span>'
        if post["description"] else ""
    )
    return f"""          <li class="row">
            <a
              class="row__link"
              href="/posts/{post['slug']}.html"
              aria-labelledby="{anchor}"
            >
              <span class="row__date">
                <time datetime="{post['date'].isoformat()}">{post['date'].strftime('%-d %b %Y')}</time>
              </span>
              <span class="row__title" id="{anchor}">{esc(post['title'])}</span>{dek}{tags_block}
            </a>
          </li>"""


START, END = "<!-- POSTS:START -->", "<!-- POSTS:END -->"


def replace_between(text, block, path):
    if text.count(START) != 1 or text.count(END) != 1:
        die(
            f"{path.name}: expected exactly one {START} and one {END}. "
            "build.py needs them to know where the post list goes."
        )
    i, j = text.index(START), text.index(END)
    if j < i:
        die(f"{path.name}: {END} appears before {START}.")
    return text[: i + len(START)] + "\n" + block + "\n          " + text[j:]


def rebuild_indexes(posts):
    archive = OUT / "index.html"
    for page in (archive, HOME_PAGE):
        if not page.exists():
            die(f"{page.relative_to(ROOT)} is missing — it is the page shell, not generated.")

    rows = "\n".join(row_html(p) for p in posts)
    archive.write_text(
        replace_between(read_text(archive), rows, archive), encoding="utf-8"
    )

    recent = "\n".join(row_html(p) for p in posts[:RECENT_ON_HOME])
    HOME_PAGE.write_text(
        replace_between(read_text(HOME_PAGE), recent, HOME_PAGE), encoding="utf-8"
    )


def copy_attachments():
    if not ATTACHMENTS.exists():
        return 0
    n = 0
    seen = {}
    for src in sorted(ATTACHMENTS.rglob("*")):
        if not src.is_file() or src.name.startswith("."):
            continue
        # Embeds are written as /assets/posts/<name>, so the tree is flattened.
        if src.name in seen:
            warn(
                f"two attachments are both named {src.name} "
                f"({seen[src.name]} and {src.relative_to(ATTACHMENTS)}) — "
                "one will win. Rename one of them."
            )
            continue
        seen[src.name] = src.relative_to(ATTACHMENTS)
        ASSETS_POSTS.mkdir(parents=True, exist_ok=True)
        dst = ASSETS_POSTS / src.name
        if not dst.exists() or src.stat().st_size != dst.stat().st_size \
                or src.stat().st_mtime != dst.stat().st_mtime:
            shutil.copy2(src, dst)
            n += 1
    return n


# --------------------------------------------------------------------------

def main():
    if not TEMPLATE.exists():
        die(f"{TEMPLATE.relative_to(ROOT)} is missing — it is the post page shell.")
    OUT.mkdir(parents=True, exist_ok=True)

    include_drafts = "--drafts" in sys.argv[1:]

    template = read_text(TEMPLATE)
    posts, drafts = collect()

    if include_drafts:
        posts = sorted(posts + drafts, key=lambda p: (p["date"], p["slug"]), reverse=True)
        drafts = []

    for post in posts:
        write_post(post, template)
        print(f"  ✓ posts/{post['slug']}.html   {post['date']}  {post['title']}")

    for post in drafts:
        print(f"  · draft (skipped)             {post['title']}")

    rebuild_indexes(posts)
    print(f"  ✓ posts/index.html            {len(posts)} post(s)")
    print(f"  ✓ index.html                  {min(len(posts), RECENT_ON_HOME)} recent")

    n = copy_attachments()
    if n:
        print(f"  ✓ assets/posts/               {n} attachment(s) updated")

    for message in WARNINGS:
        print(f"  ! {message}")

    if include_drafts:
        print(
            "\n  ⚠  Built WITH drafts for preview. Do not commit this output —\n"
            "     run `python3 build.py` again before committing."
        )

    # Anything in posts/ with no Markdown behind it. Files this script wrote
    # are removed; anything hand-written is only reported.
    #
    # This matters most right after a --drafts preview: the draft's HTML would
    # otherwise linger and stay publicly reachable by direct URL even though
    # nothing links to it.
    keep = {p["slug"] for p in posts} | RESERVED_SLUGS
    removed, foreign = [], []
    for path in sorted(OUT.glob("*.html")):
        if path.name[:-5] in keep:
            continue
        if "GENERATED by build.py" in path.read_text(encoding="utf-8", errors="ignore"):
            path.unlink()
            removed.append(path.name)
        else:
            foreign.append(path.name)

    for name in removed:
        print(f"  ✗ posts/{name}            removed (no Markdown source)")
    if foreign:
        print("\n  Not generated by build.py, left alone:")
        for name in foreign:
            print(f"    posts/{name}")


if __name__ == "__main__":
    main()
