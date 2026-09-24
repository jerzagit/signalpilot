from core.news import clean_headline, matches_keywords


def test_matches_gold_keyword():
    assert matches_keywords("Gold slips on Fed tightening bets")


def test_matches_usd_dollar_keyword():
    assert matches_keywords("Dollar steadies as yields rise")


def test_does_not_match_unrelated_news():
    assert not matches_keywords("Tech stocks hit fresh records on AI optimism")


def test_matches_symbol_case_insensitively():
    assert matches_keywords("XAUUSD holds above $4,280")


def test_rejects_promo_spam_even_with_keyword():
    assert not matches_keywords("Crushed Another GOLD Move! 460+ pips move done BOOOOOM")
    assert not matches_keywords("Free GOLD signals, join my VIP group")


def test_cleans_links_and_markdown():
    cleaned = clean_headline(
        "Gold slides *1%* https://example.com/story as _yields_ jump"
    )
    assert "http" not in cleaned
    assert "*" not in cleaned
    assert "_" not in cleaned
    assert "  " not in cleaned


SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><item>
<title>Gold muted on Fed policy tightening bets - Reuters</title>
</item><item>
<title>Tech stocks hit fresh records - Reuters</title>
</item><item>
<title>Reuters | Dollar steadies as yields rise</title>
</item></channel></rss>"""


def test_rss_titles_parsed_and_cleaned(monkeypatch):
    import core.rss_news as rss_news

    class _Resp:
        content = SAMPLE_RSS.encode()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(rss_news.requests, "get", lambda url, **kw: _Resp())
    titles = rss_news._feed_titles("https://example.com/feed", limit=3)
    assert "Gold muted on Fed policy tightening bets" in titles
    assert "Dollar steadies as yields rise" in titles


def test_rss_poll_ingests_only_matching(monkeypatch):
    import core.rss_news as rss_news
    import core.news as news

    class _Resp:
        content = SAMPLE_RSS.encode()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(rss_news.requests, "get", lambda url, **kw: _Resp())
    monkeypatch.setattr(rss_news, "NEWS_RSS_QUERIES", ["https://example.com/feed"])
    monkeypatch.setattr(news, "NEWS_BUFFER_MAX", 30)

    news._save_seen(set())
    dropped = news._save_buffer([])
    ingested = rss_news.poll_feeds()
    assert ingested == 2  # gold + dollar match, tech headline is rejected
    buffer = news._load_buffer()
    assert len(buffer) == 2
    texts = {item.text for item in buffer}
    assert any("Gold muted" in t for t in texts)