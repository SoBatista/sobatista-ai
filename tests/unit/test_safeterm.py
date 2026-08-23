from __future__ import annotations

from sobai.core.safeterm import sanitize


def test_strips_csi_color_sequences() -> None:
    assert sanitize("\x1b[31mred\x1b[0m") == "red"


def test_strips_osc_title_sequence() -> None:
    # OSC set-window-title, BEL terminated
    assert sanitize("\x1b]0;pwned\x07hello") == "hello"


def test_strips_osc_st_terminated() -> None:
    assert sanitize("\x1b]8;;http://evil\x1b\\link") == "link"


def test_keeps_newlines_and_tabs() -> None:
    assert sanitize("line1\nline2\tcol") == "line1\nline2\tcol"


def test_strips_bare_control_chars() -> None:
    assert sanitize("a\x00b\x07c\x1bd") == "abcd"


def test_empty() -> None:
    assert sanitize("") == ""


def test_plain_text_unchanged() -> None:
    text = "Normal title: My Video (2026) — 90% viewed!"
    assert sanitize(text) == text
