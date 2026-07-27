# daffailhamramadan.github.io

Personal site. Hand-written static HTML, CSS, and vanilla JS — no build step, no
dependencies, no trackers. Pushing to `main` publishes it.

Live at <https://daffailhamramadan.github.io>

## Structure

```
.
├── index.html                  home — masthead, recent writeups, contact
├── 404.html                    served by GitHub Pages on any missing path
├── favicon.svg
├── .nojekyll                   stops Pages running Jekyll over these files
├── assets/
│   ├── style.css               the whole design system
│   ├── main.js                 progressive enhancement only
│   └── avatar.jpg              self-hosted copy of the GitHub avatar
└── writeups/
    ├── index.html              archive listing
    └── sample-post.html        template post (lorem ipsum — replace it)
```

`.nojekyll` matters. Without it GitHub Pages runs Jekyll, which silently drops
any file or directory whose name starts with `_` or `.`.

## Adding a writeup

1. Copy `writeups/sample-post.html` to `writeups/your-slug.html`.
2. Replace the `<title>`, `<meta name="description">`, `og:` tags, and
   `<link rel="canonical">` with the real values.
3. Write the post inside `.post__body`. Update the `<details class="toc">` list
   so each entry points at a section `id`.
4. Add a `<li class="row">` to `writeups/index.html`, and to the
   "Recent writeups" list in `index.html` if it belongs there.

There is no index to regenerate and nothing to compile — the archive is a plain
list you edit by hand.

### Elements available inside `.post__body`

| Element | Markup |
| --- | --- |
| Section heading | `<h2 id="sec-1"><span class="num">01</span>Title</h2>` |
| Code block | `<figure class="code">` with a `.code__bar` and `<pre><code>` |
| Highlighted line | `<mark>` inside `<pre>` (block-level, amber bar) |
| Code tokens | `.tk-c` comment, `.tk-s` literal, `.tk-f` flag/number |
| Aside | `<aside class="note">` |
| Screenshot | `<figure class="figure">` with `<img>` and `<figcaption>` |
| Table | `<div class="table-wrap"><table>` — scrolls on its own, never the page |
| Quote | `<blockquote>` |

Syntax highlighting is deliberately hand-applied rather than automatic. Three
token colours, used sparingly, plus `<mark>` to point at the line that matters.

## Local preview

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000>. Use a server rather than opening the files
directly — every internal link is root-relative (`/assets/style.css`), so
`file://` will not resolve them.

## Design notes

- **Type carries the design.** System serif for reading, sans for micro-UI,
  mono for code. Zero network requests for fonts, so nothing reflows on load.
- **Measure is 68ch** with a 1.68 line-height. Code blocks intentionally break
  out of it — wrapping code is worse than scrolling it.
- **One accent** (`#f0b357`) and exactly one gradient, a 2px rule under the
  masthead on the home page.
- **Links are an underline, not a colour**, so link text keeps full contrast.
- Everything degrades without JS: the reading-progress bar, copy buttons, and
  active-section highlighting are enhancements, and the copy button stays
  hidden until JS enables it.
- `main.js` also sets `tabindex="0"` on scrollable code blocks and tables so
  they are keyboard-scrollable — you do not need to write it into each post.
- **Ambient background.** A fixed `<canvas>` behind everything draws drifting
  nodes that link up when they come close. It is decorative: `aria-hidden`,
  `pointer-events: none`, stops when the tab is hidden, and renders a single
  still frame under `prefers-reduced-motion`. Deliberately faint — line alpha
  peaks at `0.085` — so it stays under long-form reading. To make it denser,
  raise the node count in the `background()` block; to slow it, shrink `vx`/`vy`.
  Removing the `.bg` div from a page removes it from that page.
- **Printing is supported.** The print block re-points the colour tokens rather
  than overriding `body`, so code figures and callouts stay legible on paper.

## Avatar

`assets/avatar.jpg` is a self-hosted copy of the GitHub avatar, not a hotlink —
hotlinking would send every visitor to `avatars.githubusercontent.com`. That
means it does not update automatically. After changing your picture on GitHub:

```bash
curl -sL "https://avatars.githubusercontent.com/u/64750699?s=512&v=4" \
  -o assets/avatar.jpg
```

The circular frame is `border-radius: 50%` plus `object-fit: cover`, so any
square image works — no cropping needed before you drop it in. Size comes from
the `--avatar-size` token (112px, 132px from 900px up).

The ring is a solid 3px `--text` border, not one of the `--rule` tokens. Those
sit at 1.26:1 against the background on purpose — fine for a long hairline
between rows, invisible once bent into a small circle.

## Licence

Content © Daffa Ilham Ramadan. Code is free to reuse.
