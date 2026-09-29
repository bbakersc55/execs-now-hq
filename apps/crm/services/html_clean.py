"""Email HTML from a person's editor, cleaned on the server (2026-09-29).

The same allow-list as `frontend/src/components/RichText.tsx`: bold, italic,
underline, links, paragraphs, line breaks and lists. The browser cleans as the
person types; this cleans again here, because what reaches a prospect's inbox
must not depend on the browser having been the app's own. Tags outside the
list are dropped and their text kept; every attribute is dropped except an
`href` that is http, https or mailto. `script` and `style` lose their contents
as well.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

ALLOWED = {"b", "strong", "i", "em", "u", "a", "p", "br", "ul", "ol", "li"}
VOID = {"br"}
DROP_CONTENT = {"script", "style", "head", "title"}
SAFE_HREF = re.compile(r"^(https?:|mailto:)", re.I)


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.skipping += 1
            return
        if self.skipping or tag not in ALLOWED:
            return
        # As a browser does: a new item or paragraph ends an open one.
        if tag in ("li", "p") and self.open and self.open[-1] == tag:
            self.handle_endtag(tag)
        if tag == "a":
            href = next((v for k, v in attrs if k == "href" and v), "")
            self.out.append(f'<a href="{escape(href)}">' if SAFE_HREF.match(href.strip())
                            else "<a>")
        else:
            self.out.append(f"<{tag}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.open and tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.skipping = max(self.skipping - 1, 0)
            return
        if self.skipping or tag not in self.open:
            return
        while self.open:                     # close anything left open inside it
            top = self.open.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(escape(data, quote=False))


def clean(html: str) -> str:
    parser = _Cleaner()
    parser.feed(html or "")
    parser.close()
    return "".join(parser.out) + "".join(f"</{t}>" for t in reversed(parser.open))


def to_text(html: str) -> str:
    """The plain-text part every message carries alongside its HTML."""
    from html import unescape

    text = re.sub(r"(?i)<br\s*/?>", "\n", html or "")
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)<(ul|ol)>", "\n", text)
    text = re.sub(r"(?i)</(ul|ol)>", "\n\n", text)
    text = re.sub(r"(?i)<li>", "- ", text)
    text = re.sub(r"(?i)</li>", "\n", text)
    text = re.sub(r'(?i)<a href="([^"]*)">(.*?)</a>', r"\2 (\1)", text)
    text = unescape(re.sub(r"<[^>]+>", "", text))
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()
