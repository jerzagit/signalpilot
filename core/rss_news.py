"""
core/rss_news.py
Polls RSS/API news feeds (default: Google News RSS constrained to Reuters
gold/USD coverage) and feeds matching headlines into the shared NewsItem
buffer. Runs as a background coroutine inside the listener.

Headlines are short factual titles from a public feed — we never download or
redistribute full articles.
"""

import asyncio
import logging
import xml.etree.ElementTree as ET

import requests

from core.config import NEWS_POLL_SECS, NEWS_RSS_LIMIT, NEWS_RSS_QUERIES
from core.news import add_headline, clean_headline, matches_keywords

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


def _feed_titles(url: str, limit: int = NEWS_RSS_LIMIT) -> list[str]:
    """Download an RSS feed and return clean headlines (newest first)."""
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    titles = []
    for item in root.findall(".//item"):
        title_tag = item.find("title")
        title = title_tag.text if title_tag is not None and title_tag.text else ""
        title = title.removeprefix("Reuters | ").removesuffix(" - Reuters").strip()
        headline = clean_headline(title)
        if headline:
            titles.append(headline)
        if len(titles) >= limit:
            break
    return titles


def poll_feeds() -> int:
    """Fetch all configured feeds and ingest matching headlines once."""
    ingested = 0
    for url in NEWS_RSS_QUERIES:
        try:
            for headline in _feed_titles(url):
                if matches_keywords(headline):
                    add_headline(headline)
                    ingested += 1
        except Exception as exc:
            log.warning("News poll failed for %s: %s", url.split("?")[0], exc)
    if ingested:
        log.info("News poll ingested %d headline(s).", ingested)
    return ingested


async def poll_news_loop() -> None:
    """Run the poller forever (used as a background listener task)."""
    while True:
        try:
            await asyncio.to_thread(poll_feeds)
        except Exception as exc:
            log.warning("News poller crashed: %s", exc)
        await asyncio.sleep(NEWS_POLL_SECS)