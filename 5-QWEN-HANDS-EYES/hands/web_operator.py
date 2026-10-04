"""
Autonomous Web Operator & Search Agent ('Hands' Web Navigator).
Performs live web searches (DuckDuckGo/SearXNG), fetches webpages, extracts text, and returns structured knowledge.
"""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("qwen_hands_eyes.web_operator")

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


class WebOperator:
    """Executes online information retrieval, page reading, and summarization."""

    def __init__(self, timeout_sec: int = 15, user_agent: Optional[str] = None):
        self.timeout_sec = timeout_sec
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Perform search using DuckDuckGo HTML endpoint without requiring third-party libraries."""
        clean_query = query.strip()
        if not clean_query:
            return {"ok": False, "error": "Query cannot be empty"}

        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(clean_query)}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fa,en-US;q=0.8,en;q=0.5",
        }

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw_html = resp.read().decode("utf-8", errors="replace")
                results = self._parse_ddg_html(raw_html, max_results)
                return {
                    "ok": True,
                    "query": clean_query,
                    "results": results,
                    "count": len(results),
                }
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return {"ok": False, "query": clean_query, "error": str(e), "results": []}

    def _parse_ddg_html(self, raw_html: str, max_results: int) -> List[Dict[str, str]]:
        results = []
        # Find result snippets in DuckDuckGo HTML
        pattern = re.compile(
            r'<a class="result__url"[^>]*href="(?P<url>[^"]+)"[^>]*>.*?</a>.*?<a class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )

        # Fallback simpler regex pattern
        title_pattern = re.compile(r'<a class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.DOTALL | re.IGNORECASE)
        snippet_pattern = re.compile(r'<a class="result__snippet"[^>]*>(?P<snippet>.*?)</a>', re.DOTALL | re.IGNORECASE)

        titles_urls = title_pattern.findall(raw_html)
        snippets = snippet_pattern.findall(raw_html)

        for i, (u, t) in enumerate(titles_urls[:max_results]):
            s = snippets[i] if i < len(snippets) else ""
            clean_title = html.unescape(HTML_TAG_RE.sub("", t).strip())
            clean_snippet = html.unescape(HTML_TAG_RE.sub("", s).strip())

            # Unquote DDG redirect URL if needed
            actual_url = u
            if "uddg=" in u:
                m = re.search(r"uddg=([^&]+)", u)
                if m:
                    actual_url = urllib.parse.unquote(m.group(1))

            results.append({
                "title": clean_title,
                "url": actual_url,
                "snippet": clean_snippet,
            })

        return results

    def fetch_page_content(self, url: str, max_chars: int = 10000) -> Dict[str, Any]:
        """Fetch and extract readable plain text from a URL."""
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        headers = {"User-Agent": self.user_agent}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read().decode("utf-8", errors="replace")

                # Strip script and style tags
                no_scripts = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", raw, flags=re.IGNORECASE)
                # Strip remaining HTML tags
                plain_text = HTML_TAG_RE.sub(" ", no_scripts)
                # Normalize whitespace
                clean_text = WHITESPACE_RE.sub(" ", html.unescape(plain_text)).strip()

                return {
                    "ok": True,
                    "url": url,
                    "title": self._extract_title(raw),
                    "text": clean_text[:max_chars],
                    "total_chars": len(clean_text),
                    "truncated": len(clean_text) > max_chars,
                }
        except Exception as e:
            return {"ok": False, "url": url, "error": str(e)}

    def _extract_title(self, raw_html: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        return html.unescape(m.group(1).strip()) if m else "Untitled Page"
