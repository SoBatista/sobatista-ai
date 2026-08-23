"""Transcript resolution for video summaries, following the required precedence.

Precedence:

1. **Authorized captions** belonging to the user's own channel, via the official
   Data API (only when the caption scope was explicitly granted).
2. A **transcript explicitly supplied by the user** (``--transcript FILE``).
3. An explicitly authorized local media/transcript workflow (not implemented
   here; documented).

If none applies, we say so plainly and never fabricate a transcript. We never
scrape arbitrary public captions.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path

from sobai.core.errors import ConnectorError

from .client import YouTubeApiError, YouTubeClient

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(value: str) -> str:
    """Extract an 11-char video id from a raw id or a YouTube URL."""
    value = value.strip()
    if _YOUTUBE_ID.match(value):
        return value
    import urllib.parse

    parsed = urllib.parse.urlparse(value)
    host = (parsed.hostname or "").lower()
    if host.endswith("youtu.be"):
        candidate = parsed.path.lstrip("/").split("/")[0]
        if _YOUTUBE_ID.match(candidate):
            return candidate
    if "youtube.com" in host:
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs and _YOUTUBE_ID.match(qs["v"][0]):
            return qs["v"][0]
        # /shorts/<id>, /embed/<id>, /live/<id>
        parts = [p for p in parsed.path.split("/") if p]
        for i, part in enumerate(parts):
            if (
                part in ("shorts", "embed", "live")
                and i + 1 < len(parts)
                and _YOUTUBE_ID.match(parts[i + 1])
            ):
                return parts[i + 1]
    raise ConnectorError(
        f"Could not parse a YouTube video id from '{value}'.",
        hint="Pass an 11-character video id or a youtube.com/youtu.be URL.",
    )


@dataclass(slots=True)
class TranscriptResult:
    source: str  # "authorized-captions" | "user-supplied" | "none"
    text: str | None
    detail: str


def _read_transcript_file(transcript_path: str) -> str:
    """Read a user-supplied transcript file (sync; small local read)."""
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        raise ConnectorError(f"Transcript file not found: {path}")
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _strip_srt(srt: str) -> str:
    """Reduce SRT/VTT caption text to plain prose (drop indices and timestamps)."""
    lines: list[str] = []
    for raw in srt.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or "-->" in line or line.upper() == "WEBVTT":
            continue
        lines.append(line)
    return "\n".join(lines).strip()


async def resolve_transcript(
    client: YouTubeClient,
    video_id: str,
    *,
    captions_granted: bool,
    transcript_path: str | None = None,
) -> TranscriptResult:
    # (1) Authorized own-channel captions via official API.
    if captions_granted:
        with contextlib.suppress(YouTubeApiError):
            tracks = await client.list_captions(video_id)
            if tracks:
                # Prefer a human/standard track over auto-generated (ASR).
                tracks.sort(key=lambda t: t.get("snippet", {}).get("trackKind", "") == "asr")
                track = tracks[0]
                srt = await client.download_caption(track["id"], fmt="srt")
                text = _strip_srt(srt)
                if text:
                    return TranscriptResult(
                        source="authorized-captions",
                        text=text,
                        detail=f"Downloaded authorized caption track '{track['id']}'.",
                    )

    # (2) User-supplied transcript.
    if transcript_path:
        text = _read_transcript_file(transcript_path)
        if text:
            return TranscriptResult(
                source="user-supplied",
                text=text,
                detail=f"Using user-supplied transcript: {transcript_path}",
            )

    # (3) None available — report clearly, do not fabricate.
    reason = "No authorized transcript is available for this video."
    if not captions_granted:
        reason += (
            " Caption access is not granted (re-run `sobai connect youtube --captions` "
            "to authorize your own channel's captions)."
        )
    reason += " You can also supply one with --transcript FILE."
    return TranscriptResult(source="none", text=None, detail=reason)
