#!/usr/bin/env python3
"""Render a constrained markdown subset to one self-contained HTML file.

The point is token discipline. A model writing HTML spends most of its output on
markup; a model writing markdown spends it on content. So skills emit clean
markdown and this turns it into a page — no model ever writes a tag.

Stdlib only, no network, no CDN: the output is one file that opens from disk and
still works in five years. The supported subset is deliberately small and listed
in SUPPORTED; anything outside it passes through as text rather than breaking.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

SUPPORTED = (
    "headings, paragraphs, bullet and numbered lists, fenced code, inline code, "
    "GFM pipe tables, blockquotes, horizontal rules, links, bold, italic, strikethrough"
)

CODE_SPAN = re.compile(r"`([^`]+)`")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
STRIKE = re.compile(r"~~([^~]+)~~")
AUTOLINK = re.compile(r"(?<![\"=>])\bhttps?://[^\s<>\"')]+")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE = re.compile(r"^```(\w*)\s*(.*)$")
RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")

STYLE = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfa; --fg: #1d1d1f; --muted: #6b6b70; --rule: #e3e3e0;
  --card: #ffffff; --code-bg: #f4f4f2; --accent: #2f6f4f; --shadow: rgba(0,0,0,.06);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17181a; --fg: #e8e8e6; --muted: #9a9a9f; --rule: #2c2d30;
    --card: #1e1f22; --code-bg: #232428; --accent: #7fc4a0; --shadow: rgba(0,0,0,.4);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2.5rem 1rem 4rem; background: var(--bg); color: var(--fg);
  font: 16px/1.65 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
main { max-width: 46rem; margin: 0 auto; }
h1, h2, h3, h4 { line-height: 1.25; margin: 2.2rem 0 .8rem; font-weight: 650; }
h1 { font-size: 1.9rem; margin-top: 0; letter-spacing: -.02em; }
h2 { font-size: 1.35rem; padding-bottom: .35rem; border-bottom: 1px solid var(--rule); }
h3 { font-size: 1.1rem; }
h4 { font-size: 1rem; color: var(--muted); }
p, ul, ol, table, pre, blockquote { margin: 0 0 1rem; }
ul, ol { padding-left: 1.4rem; }
li { margin: .25rem 0; }
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
code {
  background: var(--code-bg); padding: .12em .35em; border-radius: 4px;
  font: .87em/1.5 ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace;
}
pre {
  background: var(--code-bg); padding: .9rem 1rem; border-radius: 8px;
  overflow-x: auto; border: 1px solid var(--rule);
}
pre code { background: none; padding: 0; font-size: .85em; }
blockquote {
  margin-left: 0; padding: .1rem 0 .1rem 1rem; border-left: 3px solid var(--rule);
  color: var(--muted);
}
table { border-collapse: collapse; width: 100%; font-size: .94em; }
th, td { text-align: left; padding: .45rem .7rem; border-bottom: 1px solid var(--rule); }
th { font-weight: 620; color: var(--muted); font-size: .85em; text-transform: uppercase;
     letter-spacing: .04em; }
tbody tr:hover { background: var(--card); }
hr { border: 0; border-top: 1px solid var(--rule); margin: 2rem 0; }
.meta { color: var(--muted); font-size: .9em; margin: -.4rem 0 2rem; }
@media (max-width: 34rem) { body { padding: 1.5rem 1rem 3rem; } h1 { font-size: 1.5rem; } }
"""


# --------------------------------------------------------------------------- inline


def inline(text: str) -> str:
    """Escape first, then add markup, so a `<` in the source can never become a tag.

    Code spans are pulled out before anything else runs over them: `**x**` inside
    backticks is two asterisks, not bold.
    """
    spans: list[str] = []

    def stash(match: re.Match) -> str:
        spans.append(html.escape(match.group(1)))
        return f"\x00{len(spans) - 1}\x00"

    text = CODE_SPAN.sub(stash, text)
    text = html.escape(text)
    text = LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text
    )
    text = AUTOLINK.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', text)
    text = BOLD.sub(r"<strong>\1</strong>", text)
    text = STRIKE.sub(r"<del>\1</del>", text)
    text = ITALIC.sub(r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{spans[int(m.group(1))]}</code>", text)


# --------------------------------------------------------------------------- blocks


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_divider(line: str) -> bool:
    cells = split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells)


def starts_block(line: str) -> bool:
    stripped = line.lstrip()
    return bool(
        HEADING.match(line)
        or FENCE.match(line)
        or RULE.match(line)
        or stripped.startswith(">")
        or stripped.startswith("|")
    )


def render_list(lines: list[str], start: int, ordered: bool) -> tuple[str, int]:
    """Nesting is by indent width; two levels are plenty for a briefing."""
    pattern = NUMBERED if ordered else BULLET
    tag = "ol" if ordered else "ul"
    out = [f"<{tag}>"]
    index = start
    base = len(pattern.match(lines[start]).group(1))

    def nest(block: str) -> None:
        """A sublist belongs *inside* the <li> above it, not beside it — a <ul>
        as a direct child of <ol> is invalid HTML even though browsers cope."""
        if len(out) > 1 and out[-1].endswith("</li>"):
            out[-1] = out[-1][: -len("</li>")] + block + "</li>"
        else:
            out.append(f"<li>{block}</li>")

    def extend(text: str) -> bool:
        """Lazy continuation: a wrapped bullet is still that bullet.

        Writers wrap long list items at the margin without re-indenting, and
        treating the second line as a new paragraph shreds the list — which is
        exactly what a generated briefing looks like when it goes wrong.
        """
        if len(out) > 1 and out[-1].endswith("</li>"):
            out[-1] = out[-1][: -len("</li>")] + " " + inline(text) + "</li>"
            return True
        return False

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            # One blank line between items is a loose list, not the end of one.
            following = index + 1
            while following < len(lines) and not lines[following].strip():
                following += 1
            nxt = pattern.match(lines[following]) if following < len(lines) else None
            if nxt and len(nxt.group(1)) == base:
                index = following
                continue
            break

        match = pattern.match(line)
        other = (BULLET if ordered else NUMBERED).match(line)
        if not match:
            if other and len(other.group(1)) > base:
                block, index = render_list(lines, index, not ordered)
                nest(block)
                continue
            if other or starts_block(line) or not extend(line.strip()):
                break
            index += 1
            continue
        indent = len(match.group(1))
        if indent > base:
            block, index = render_list(lines, index, ordered)
            nest(block)
            continue
        if indent < base:
            break
        out.append(f"<li>{inline(match.group(2))}</li>")
        index += 1
    out.append(f"</{tag}>")
    return "".join(out), index


def render_table(lines: list[str], start: int) -> tuple[str, int]:
    header = split_row(lines[start])
    index = start + 2
    rows = []
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        rows.append(split_row(lines[index]))
        index += 1
    head = "".join(f"<th>{inline(cell)}</th>" for cell in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>", index


def to_html(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = FENCE.match(line)
        if fence:
            language = fence.group(1)
            index += 1
            body = []
            while index < len(lines) and not lines[index].startswith("```"):
                body.append(lines[index])
                index += 1
            index += 1  # closing fence, or end of input
            attribute = f' class="language-{html.escape(language)}"' if language else ""
            out.append(f"<pre><code{attribute}>{html.escape(chr(10).join(body))}</code></pre>")
            continue

        if RULE.match(line):
            out.append("<hr>")
            index += 1
            continue

        heading = HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if "|" in line and index + 1 < len(lines) and is_divider(lines[index + 1]):
            table, index = render_table(lines, index)
            out.append(table)
            continue

        if BULLET.match(line) or NUMBERED.match(line):
            block, index = render_list(lines, index, bool(NUMBERED.match(line)))
            out.append(block)
            continue

        if line.lstrip().startswith(">"):
            quote = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                quote.append(lines[index].lstrip()[1:].strip())
                index += 1
            out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            continue

        paragraph = []
        while index < len(lines) and lines[index].strip() and not (
            HEADING.match(lines[index])
            or FENCE.match(lines[index])
            or BULLET.match(lines[index])
            or NUMBERED.match(lines[index])
            or lines[index].lstrip().startswith(">")
            or RULE.match(lines[index])
        ):
            paragraph.append(lines[index].strip())
            index += 1
        if paragraph:
            out.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(out)


def page(markdown: str, title: str | None, subtitle: str | None) -> str:
    body = to_html(markdown)
    if title is None:
        first = HEADING.match(next((l for l in markdown.split("\n") if l.startswith("# ")), ""))
        title = first.group(2) if first else "Briefing"
    meta = f'<p class="meta">{inline(subtitle)}</p>' if subtitle else ""
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
<main>
{meta}
{body}
</main>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wf_render.py", description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="markdown file, or - for stdin")
    parser.add_argument("-o", "--output", help="write here instead of stdout")
    parser.add_argument("--title")
    parser.add_argument("--subtitle", help="one muted line under the title")
    parser.add_argument("--supported", action="store_true", help="print the supported subset")
    args = parser.parse_args(argv)

    if args.supported:
        print(SUPPORTED)
        return 0

    if args.input == "-":
        markdown = sys.stdin.read()
    else:
        source = Path(args.input).expanduser()
        if not source.is_file():
            print(f"no such file: {source}", file=sys.stderr)
            return 3
        markdown = source.read_text(encoding="utf-8")

    rendered = page(markdown, args.title, args.subtitle)
    if args.output:
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(target)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
