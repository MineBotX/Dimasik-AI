"""Small HTML search-result parsers for free public search engines."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse


class SearchResultParser(HTMLParser):
    """Extract DuckDuckGo HTML/Lite and Bing web result cards."""

    TITLE_CLASSES = {"result__a", "result-link"}
    SNIPPET_CLASSES = {"result__snippet", "result-snippet"}

    def __init__(self, provider: str):
        super().__init__(convert_charrefs=True)
        self.provider = provider
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.in_bing_result = False
        self.in_bing_heading = False
        self.title_active = False
        self.title_depth = 0
        self.snippet_depth = 0
        self.capture = None

    def _begin_title(self, attrs):
        attrs = dict(attrs)
        href = html.unescape(attrs.get("href", "")).strip()
        self.current = {"title": "", "url": href, "snippet": ""}
        self.title_active = True
        self.title_depth = 1
        self.capture = "title"

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        classes = set(attr.get("class", "").split())

        if self.title_active:
            self.title_depth += 1

        if self.snippet_depth:
            self.snippet_depth += 1

        if self.provider == "bing":
            if tag == "li" and "b_algo" in classes:
                self.in_bing_result = True
                self.current = {"title": "", "url": "", "snippet": ""}
            elif self.in_bing_result and tag == "h2":
                self.in_bing_heading = True
            elif self.in_bing_result and tag == "a" and self.in_bing_heading:
                self._begin_title(attr)
            elif self.in_bing_result and tag == "p" and not self.snippet_depth:
                self.snippet_depth = 1
                self.capture = "snippet"
                if self.current is None:
                    self.current = {"title": "", "url": "", "snippet": ""}
        else:
            if tag == "a" and classes.intersection(self.TITLE_CLASSES):
                self._begin_title(attr)
            elif classes.intersection(self.SNIPPET_CLASSES):
                self.snippet_depth = 1
                self.capture = "snippet"
                if self.current is None:
                    self.current = {"title": "", "url": "", "snippet": ""}

    def handle_data(self, data):
        if self.title_active and self.current is not None:
            self.current["title"] += data
        elif self.snippet_depth and self.current is not None:
            self.current["snippet"] += data

    def handle_endtag(self, tag):
        if self.title_active:
            self.title_depth -= 1
            if tag == "a" and self.title_depth <= 0:
                self.title_active = False
                self.capture = None

        if self.snippet_depth:
            self.snippet_depth -= 1
            if self.snippet_depth <= 0:
                self.snippet_depth = 0
                self.capture = None

        if self.provider == "bing":
            if tag == "h2":
                self.in_bing_heading = False
            elif tag == "li" and self.in_bing_result:
                self._finish_current()
                self.in_bing_result = False
        elif tag == "a" and not self.title_active:
            self._finish_current()

    def _finish_current(self):
        item = self.current
        self.current = None
        if not item:
            return
        title = " ".join(html.unescape(item.get("title", "")).split())
        snippet = " ".join(html.unescape(item.get("snippet", "")).split())
        url = normalize_result_url(item.get("url", ""))
        if title and url:
            self.items.append({"title": title, "url": url, "snippet": snippet})


def normalize_result_url(value: str) -> str:
    """Unwrap common search redirect URLs and reject non-web destinations."""
    url = html.unescape(str(value or "")).strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [])
        if target:
            url = unquote(target[0])
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    if re.search(r"\s", url):
        return ""
    return url


def parse_search_results(markup: str, provider: str, limit: int = 5):
    parser = SearchResultParser(provider)
    parser.feed(str(markup or ""))
    results = []
    seen = set()
    for item in parser.items:
        key = item["url"].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= max(1, int(limit)):
            break
    return results
