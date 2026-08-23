from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from sobai.connectors.youtube.captions import (
    _strip_srt,
    parse_video_id,
    resolve_transcript,
)
from sobai.connectors.youtube.client import DATA_BASE, YouTubeClient
from sobai.core.errors import ConnectorError

CAPTIONS_URL = f"{DATA_BASE}/captions"
VID = "dQw4w9WgXcQ"


def test_parse_video_id_forms() -> None:
    assert parse_video_id(VID) == VID
    assert parse_video_id(f"https://www.youtube.com/watch?v={VID}&t=10s") == VID
    assert parse_video_id(f"https://youtu.be/{VID}") == VID
    assert parse_video_id(f"https://www.youtube.com/shorts/{VID}") == VID
    assert parse_video_id(f"https://www.youtube.com/embed/{VID}") == VID


def test_parse_video_id_invalid() -> None:
    with pytest.raises(ConnectorError):
        parse_video_id("not a video")


def test_strip_srt() -> None:
    srt = "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n2\n00:00:02,000 --> 00:00:03,000\nBye"
    assert _strip_srt(srt) == "Hello world\nBye"


async def test_precedence_authorized_captions(yt_auth) -> None:
    client = YouTubeClient(yt_auth(captions=True))
    with respx.mock as mock:
        mock.get(CAPTIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {"id": "capASR", "snippet": {"trackKind": "asr"}},
                        {"id": "capSTD", "snippet": {"trackKind": "standard"}},
                    ]
                },
            )
        )
        mock.get(f"{DATA_BASE}/captions/capSTD").mock(
            return_value=httpx.Response(200, text="1\n00:00 --> 00:01\nHello there\n")
        )
        result = await resolve_transcript(client, VID, captions_granted=True)
    await client.aclose()
    assert result.source == "authorized-captions"
    assert "Hello there" in result.text  # prefers standard over ASR


async def test_precedence_user_supplied(tmp_path: Path, yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    f = tmp_path / "t.txt"
    f.write_text("my transcript body")
    result = await resolve_transcript(client, VID, captions_granted=False, transcript_path=str(f))
    await client.aclose()
    assert result.source == "user-supplied"
    assert result.text == "my transcript body"


async def test_precedence_none_reports_clearly(yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    result = await resolve_transcript(client, VID, captions_granted=False)
    await client.aclose()
    assert result.source == "none"
    assert result.text is None
    assert "not granted" in result.detail.lower()
    assert "--transcript" in result.detail


async def test_missing_transcript_file_errors(yt_auth) -> None:
    client = YouTubeClient(yt_auth())
    with pytest.raises(ConnectorError):
        await resolve_transcript(
            client, VID, captions_granted=False, transcript_path="/no/such/file.txt"
        )
    await client.aclose()


async def test_captions_list_403_falls_through_to_none(yt_auth) -> None:
    client = YouTubeClient(yt_auth(captions=True))
    with respx.mock as mock:
        mock.get(CAPTIONS_URL).mock(
            return_value=httpx.Response(
                403, json={"error": {"message": "no", "errors": [{"reason": "forbidden"}]}}
            )
        )
        result = await resolve_transcript(client, VID, captions_granted=True)
    await client.aclose()
    assert result.source == "none"
