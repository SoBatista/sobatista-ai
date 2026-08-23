"""Neutralize terminal control sequences in untrusted text.

Data retrieved from YouTube, Notion, GitHub, comments, issues, and web pages is
untrusted. If rendered verbatim it could inject ANSI escape sequences to rewrite
the screen, spoof prompts, set the window title, or emit hyperlinks/clipboard
sequences. Every piece of external text is passed through :func:`sanitize`
before it reaches the terminal.

We keep the common, safe whitespace (newline, tab) and drop everything else in
the C0/C1 control ranges, plus complete ANSI/OSC/DCS sequences.
"""

from __future__ import annotations

import re

# CSI/SS2/SS3 and other ESC-introduced sequences, plus OSC/DCS/APC/PM strings
# terminated by BEL or ST. Matched first so the introducer bytes are removed
# together with their payload.
_ANSI_SEQUENCE = re.compile(
    r"""
    \x1b            # ESC
    (?:
        \[[0-?]*[ -/]*[@-~]         # CSI ... final byte
      | \][^\x07\x1b]*(?:\x07|\x1b\\)   # OSC ... (BEL or ST terminated)
      | [PX^_][^\x1b]*\x1b\\        # DCS/SOS/PM/APC ... ST terminated
      | [@-Z\\-_]                   # two-char ESC sequences
    )
    """,
    re.VERBOSE,
)

# Remaining lone control characters, keeping \t (\x09) and \n (\x0a).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def sanitize(text: str) -> str:
    """Return *text* with terminal escape sequences and stray control bytes removed."""
    if not text:
        return text
    text = _ANSI_SEQUENCE.sub("", text)
    text = _CONTROL_CHARS.sub("", text)
    return text
