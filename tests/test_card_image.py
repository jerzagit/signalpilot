from core.card_image import render_signal_card
from core.signal import Signal


def _signal() -> Signal:
    return Signal(
        symbol="XAUUSD",
        direction="buy",
        entry_low=4282.48,
        entry_high=4282.48,
        sl=4272.34,
        tps=[4287.48, 4292.48, 4297.48],
        raw_text="raw",
        source_id="geom",
    )


def test_renders_png(tmp_path):
    out = render_signal_card(_signal(), news_context=["Gold muted on Fed bets"], output_dir=str(tmp_path))
    assert out.exists()
    assert out.suffix == ".png"
    assert out.stat().st_size > 1000


def test_renders_without_news(tmp_path):
    out = render_signal_card(_signal(), output_dir=str(tmp_path))
    assert out.exists()