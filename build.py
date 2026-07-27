#!/usr/bin/env python3
"""
Build the site from Markdown.

    python3 build.py

Reads  content/posts/*.md   (your Obsidian vault)
Writes posts/<slug>.html    plus the post lists in posts/index.html and index.html
Copies content/attachments/ into assets/posts/

Everything it writes is generated — edit the Markdown, never the HTML.
On first run it creates .venv and installs the one dependency it needs.

The avatar is a self-hosted copy of the GitHub one, deliberately not hotlinked.
Refresh it after changing your picture on GitHub:
    curl -sL "https://avatars.githubusercontent.com/u/64750699?s=512&v=4" \
      -o assets/avatar.jpg

Design note: this script fails loudly. Anything ambiguous — two posts claiming
one slug, an unterminated front matter block, a date it cannot read — stops the
build with a message naming the file. A blog build that silently drops a post is
worse than one that refuses to run.
"""

import os
import json
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
MANIFEST = ROOT / ".build-manifest"
FEED = ROOT / "feed.xml"
SITEMAP = ROOT / "sitemap.xml"
ROBOTS = ROOT / "robots.txt"

SITE = "https://daffailhamramadan.github.io"
SITE_NAME = "Daffa Ilham Ramadan"
AUTHOR_EMAIL = "daffailhamramadan127@gmail.com"
X_HANDLE = "@FroztNova127"
RECENT_ON_HOME = 5
WORDS_PER_MINUTE = 220

# Cloudflare Web Analytics site token. Empty emits no beacon at all, so a fresh
# clone builds a tracker-free site until this is filled in.
ANALYTICS_TOKEN = "29dcc3b4453f45fcbeffe88e05ce15dd"

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


# Leading whitespace is allowed: Obsidian's property editor writes block lists
# indented ("tags:\n  - general"), which is also just how YAML is normally written.
FM_LINE = re.compile(r"^\s*(?:[A-Za-z_][\w.-]*\s*:|-\s|#|$)")


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


def image_size(path):
    """Width/height straight from the file header. Declaring them lets a card
    renderer lay the image out before it has finished downloading it."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return (int.from_bytes(data[i + 7:i + 9], "big"),
                        int.from_bytes(data[i + 5:i + 7], "big"))
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
        return None
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return (int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"))
    return None


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
        warn(f"{path.name}: no `title:` in front matter, using '{title}'.")

    # Optional banner. Put the image in content/attachments/ and name it in
    # the front matter: `cover: shot.png`. It becomes the hero and the og:image.
    cover = meta.get("cover")
    cover_url = ""
    if cover:
        cover_url = f"/assets/posts/{cover}"
        if not (ATTACHMENTS / str(cover)).exists():
            warn(
                f"{path.name}: cover '{cover}' is not in content/attachments/ — "
                "the banner will be a broken image."
            )

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
        "cover": cover_url,
        "cover_alt": str(meta.get("cover_alt") or ""),
        "reading_time": max(1, round(words / WORDS_PER_MINUTE)),
        "end": str(meta.get("end") or ""),
    }


def cover_figure(post):
    """Declare the file's real intrinsic size. Hardcoding 1200x630 lies to the
    browser about the aspect ratio it should reserve."""
    if not post["cover"]:
        return ""
    dims = image_size(ATTACHMENTS / Path(post["cover"]).name)
    size = f' width="{dims[0]}" height="{dims[1]}"' if dims else ""
    return (
        '        <figure class="cover">\n'
        f'          <img src="{post["cover"]}" alt="{esc(post["cover_alt"])}"'
        f'{size} fetchpriority="high" decoding="async">\n'
        "        </figure>"
    )


def og_image_tags(post):
    """og:image plus the extras that make a share card render properly."""
    if not post["cover"]:
        return ""
    url = f"{SITE}{post['cover']}"
    tags = [
        f'<meta property="og:image" content="{url}" />',
        f'<meta name="twitter:image" content="{url}" />',
    ]
    dims = image_size(ATTACHMENTS / Path(post["cover"]).name)
    if dims:
        tags.append(f'<meta property="og:image:width" content="{dims[0]}" />')
        tags.append(f'<meta property="og:image:height" content="{dims[1]}" />')
    if post["cover_alt"]:
        tags.append(f'<meta property="og:image:alt" content="{esc(post["cover_alt"])}" />')
        tags.append(f'<meta name="twitter:image:alt" content="{esc(post["cover_alt"])}" />')
    return "\n" + "\n".join("    " + t for t in tags)


# Every profile the site already links to. sameAs is how a search engine ties
# these identities to one person.
SAME_AS = [
    "https://github.com/daffailhamramadan",
    "https://www.linkedin.com/in/daffa-ilham-ramadan/",
    "https://x.com/FroztNova127",
    "https://hackerone.com/daffailhamramadan",
    "https://app.intigriti.com/profile/daffailhamramadan127",
    "https://yeswehack.com/hunters/daffailhamramadan127",
    "https://bugcrowd.com/h/daffailhamramadan127",
]


def json_ld(post):
    """BlogPosting + its author. json.dumps handles all escaping, so a title
    with a quote or a backslash cannot break out of the script block."""
    node = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "url": f"{SITE}/posts/{post['slug']}.html",
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"{SITE}/posts/{post['slug']}.html"},
        "datePublished": post["date"].isoformat(),
        "dateModified": post["date"].isoformat(),
        "inLanguage": "en",
        "author": {
            "@type": "Person",
            "name": SITE_NAME,
            "url": SITE + "/",
            "sameAs": SAME_AS,
        },
        "publisher": {"@type": "Person", "name": SITE_NAME, "url": SITE + "/"},
    }
    if post["description"]:
        node["description"] = post["description"]
    if post["tags"]:
        node["keywords"] = ", ".join(post["tags"])
    if post["cover"]:
        node["image"] = SITE + post["cover"]

    body = json.dumps(node, indent=2, ensure_ascii=False)
    # A literal </script> inside a JSON string would close the block early.
    body = body.replace("</", "<\\/")
    return ('\n    <script type="application/ld+json">\n'
            + "\n".join("    " + ln for ln in body.splitlines())
            + "\n    </script>")


def write_feed(posts):
    """Atom. Full content, because a feed that only teases is a worse feed."""
    stamp = (
        max(p["date"] for p in posts).isoformat() + "T00:00:00Z"
        if posts else "1970-01-01T00:00:00Z"
    )
    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{esc(SITE_NAME)}</title>",
        f"  <subtitle>Security research, notes, and everything else.</subtitle>",
        f'  <link href="{SITE}/feed.xml" rel="self" type="application/atom+xml"/>',
        f'  <link href="{SITE}/" rel="alternate" type="text/html"/>',
        f"  <id>{SITE}/</id>",
        f"  <updated>{stamp}</updated>",
        "  <author>",
        f"    <name>{esc(SITE_NAME)}</name>",
        f"    <email>{AUTHOR_EMAIL}</email>",
        f"    <uri>{SITE}/</uri>",
        "  </author>",
    ]
    for post in posts:
        url = f"{SITE}/posts/{post['slug']}.html"
        when = post["date"].isoformat() + "T00:00:00Z"
        out += [
            "  <entry>",
            f"    <title>{esc(post['title'])}</title>",
            f'    <link href="{url}" rel="alternate" type="text/html"/>',
            f"    <id>{url}</id>",
            f"    <published>{when}</published>",
            f"    <updated>{when}</updated>",
        ]
        if post["description"]:
            out.append(f"    <summary>{esc(post['description'])}</summary>")
        for tag in post["tags"]:
            out.append(f'    <category term="{esc(tag)}"/>')
        out.append(
            '    <content type="html">' + esc(post["html"]) + "</content>"
        )
        out.append("  </entry>")
    out.append("</feed>")
    FEED.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_sitemap(posts):
    urls = [(SITE + "/", None), (SITE + "/posts/", None)]
    urls += [(f"{SITE}/posts/{p['slug']}.html", p["date"].isoformat()) for p in posts]
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    newest = max((p["date"] for p in posts), default=None)
    for loc, lastmod in urls:
        out.append("  <url>")
        out.append(f"    <loc>{loc}</loc>")
        stamp = lastmod or (newest.isoformat() if newest else None)
        if stamp:
            out.append(f"    <lastmod>{stamp}</lastmod>")
        out.append("  </url>")
    out.append("</urlset>")
    SITEMAP.write_text("\n".join(out) + "\n", encoding="utf-8")


def write_robots():
    ROBOTS.write_text(
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {SITE}/sitemap.xml\n",
        encoding="utf-8",
    )


PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def write_post(post, template):
    url = f"{SITE}/posts/{post['slug']}.html"
    beacon = analytics_snippet()
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
        "OG_IMAGE": og_image_tags(post),
        "ANALYTICS": f"\n{beacon}" if beacon else "",
        "COVER": cover_figure(post),
        "TWITTER_CARD": "summary_large_image" if post["cover"] else "summary",
        "JSONLD": json_ld(post),
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
ANALYTICS_START, ANALYTICS_END = "<!-- ANALYTICS:START -->", "<!-- ANALYTICS:END -->"


def replace_between(text, block, path, start=START, end=END, closing_indent=" " * 10):
    if text.count(start) != 1 or text.count(end) != 1:
        die(
            f"{path.name}: expected exactly one {start} and one {end}. "
            "build.py needs them to know where the generated block goes."
        )
    i, j = text.index(start), text.index(end)
    if j < i:
        die(f"{path.name}: {end} appears before {start}.")
    body = f"\n{block}" if block else ""
    return text[: i + len(start)] + body + "\n" + closing_indent + text[j:]


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


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------

def analytics_snippet(indent_spaces=4):
    """The Cloudflare Web Analytics beacon, or nothing if no token is set.

    Cloudflare filters incoming hits by hostname, so a local preview of a page
    carrying this beacon never shows up in the dashboard. No need to strip it
    from anything but a real build.
    """
    if not ANALYTICS_TOKEN:
        return ""
    pad = " " * indent_spaces
    # type="module" is Cloudflare's own form. Modules defer by default, so this
    # never blocks rendering and needs no explicit defer.
    return (
        f'{pad}<script\n'
        f'{pad}  type="module"\n'
        f'{pad}  src="https://static.cloudflareinsights.com/beacon.min.js"\n'
        f'{pad}  data-cf-beacon=\'{{"token": "{ANALYTICS_TOKEN}"}}\'\n'
        f'{pad}></script>'
    )


def inject_analytics():
    """Post pages get the beacon through the template placeholder. These three
    are hand-written shells, so they carry marker comments instead."""
    block = analytics_snippet()
    for page in (HOME_PAGE, OUT / "index.html", ROOT / "404.html"):
        if not page.exists():
            die(f"{page.relative_to(ROOT)} is missing — it is a page shell, not generated.")
        page.write_text(
            replace_between(
                read_text(page),
                block,
                page,
                start=ANALYTICS_START,
                end=ANALYTICS_END,
                closing_indent=" " * 4,
            ),
            encoding="utf-8",
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

    inject_analytics()
    print(
        "  ✓ analytics                   Cloudflare beacon on every page"
        if ANALYTICS_TOKEN
        else "  · analytics                   ANALYTICS_TOKEN is empty, no beacon"
    )

    # Never during a preview. These two are the files you hand to Google and to
    # feed readers, so a draft URL landing in them leaks further than a stray
    # HTML page would — and unlike that page, nothing later cleans it up.
    if include_drafts:
        print("  · feed.xml / sitemap.xml      not written during a --drafts preview")
    else:
        write_feed(posts)
        write_sitemap(posts)
        write_robots()
        print(f"  ✓ feed.xml                    {len(posts)} entr(y/ies)")
        print(f"  ✓ sitemap.xml                 {len(posts) + 2} url(s)")
        print("  ✓ robots.txt")

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

    # Clean up pages this script generated on a previous run that no longer
    # have a Markdown source. Tracked in a manifest rather than sniffed from
    # the file's contents, so nothing hand-written in posts/ is ever at risk
    # and the generated HTML needs no marker comment.
    #
    # This matters most right after a --drafts preview: the draft's page would
    # otherwise linger and stay publicly reachable by direct URL even though
    # nothing links to it.
    written = sorted(p["slug"] for p in posts)
    previous = []
    if MANIFEST.exists():
        previous = [ln.strip() for ln in read_text(MANIFEST).splitlines() if ln.strip()]

    for slug in previous:
        if slug in written or slug in RESERVED_SLUGS:
            continue
        stale = OUT / f"{slug}.html"
        if stale.exists():
            stale.unlink()
            print(f"  ✗ posts/{slug}.html            removed (no Markdown source)")

    MANIFEST.write_text("\n".join(written) + "\n", encoding="utf-8")

    untracked = sorted(
        p.name for p in OUT.glob("*.html")
        if p.name[:-5] not in set(written) | RESERVED_SLUGS
    )
    if untracked:
        print("\n  In posts/ but not generated by build.py, left alone:")
        for name in untracked:
            print(f"    posts/{name}")


if __name__ == "__main__":
    main()
