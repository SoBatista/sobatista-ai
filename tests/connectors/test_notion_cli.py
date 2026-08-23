from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sobai.cli import notion_cmd
from sobai.cli.app import app
from sobai.connectors.notion.tools import build_registry
from sobai.core.errors import ConnectorError, LocalOnlyViolation, PolicyError
from sobai.core.types import Completion, GenerateParams, StopReason, StreamEvent, Usage
from sobai.providers.base import Provider, ProviderHealth

from ._notion_fakes import FakeClient, data_source, page, para, todo


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "SOBAI_CONFIG_DIR": str(tmp_path / "config"),
        "SOBAI_DATA_DIR": str(tmp_path / "data"),
        "SOBAI_CACHE_DIR": str(tmp_path / "cache"),
        "NO_COLOR": "1",
    }


class FakeConnector:
    client_obj: FakeClient = FakeClient()
    connected: bool = True

    def __init__(self, creds: Any, **kwargs: Any) -> None:
        from sobai.connectors.notion.auth import NotionAuth

        self.auth = NotionAuth(creds)

    def is_connected(self) -> bool:
        return FakeConnector.connected

    def client(self) -> FakeClient:
        return FakeConnector.client_obj

    def tools(self):  # type: ignore[no-untyped-def]
        return build_registry(FakeConnector.client_obj)

    async def aclose(self) -> None:
        return None


class FakeProvider(Provider):
    name = "ollama"
    is_local = True

    async def generate(self, params: GenerateParams) -> Completion:
        return Completion(text="AI OUTPUT", stop_reason=StopReason.END_TURN, usage=Usage())

    async def stream(
        self, params: GenerateParams
    ) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        from sobai.core.types import StreamEventType

        yield StreamEvent(type=StreamEventType.DONE, completion=await self.generate(params))

    async def list_models(self) -> list[Any]:
        return []

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, detail="ok")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def _set(client: FakeClient, *, connected: bool = True) -> None:
        FakeConnector.client_obj = client
        FakeConnector.connected = connected
        monkeypatch.setattr(notion_cmd, "NotionConnector", FakeConnector)

    return _set


def test_not_connected(runner: CliRunner, env: dict[str, str]) -> None:
    r = runner.invoke(app, ["notion", "search", "x"], env=env)
    assert r.exit_code != 0
    assert isinstance(r.exception, ConnectorError)


def test_search_json_provenance(runner: CliRunner, env: dict[str, str], fake) -> None:
    fake(FakeClient(search=[page("P1", "Alpha")]))
    r = runner.invoke(app, ["--json", "notion", "search", "Alpha"], env=env)
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["observed"][0]["title"] == "Alpha"
    assert data["sources"][0]["url"]
    assert data["meta"]["timezone"].startswith("UTC")


def test_search_text_sanitizes_untrusted_title(
    runner: CliRunner, env: dict[str, str], fake
) -> None:
    fake(FakeClient(search=[page("P1", "\x1b[31mEVIL\x1b]0;pwn\x07")]))
    r = runner.invoke(app, ["notion", "search"], env=env)
    assert r.exit_code == 0
    assert "\x1b[31m" not in r.output and "\x1b]0;" not in r.output
    assert "EVIL" in r.output


def test_recent_json(runner: CliRunner, env: dict[str, str], fake) -> None:
    fake(FakeClient(search=[page("P1", "Recent", edited="2026-08-22T00:00:00.000Z")]))
    r = runner.invoke(app, ["--json", "notion", "recent", "--since", "3650d"], env=env)
    assert r.exit_code == 0
    assert json.loads(r.output)["report"] == "notion.recent"


def test_projects_heuristic_notes(runner: CliRunner, env: dict[str, str], fake) -> None:
    fake(FakeClient(search=[data_source("db", "Projects DB"), page("p", "Grocery")]))
    r = runner.invoke(app, ["--json", "notion", "projects"], env=env)
    data = json.loads(r.output)
    assert any("heuristic" in n.lower() for n in data["notes"])
    assert {row["title"] for row in data["observed"]} == {"Projects DB"}


def test_summarize_no_text_no_provider(runner: CliRunner, env: dict[str, str], fake) -> None:
    dashed = "abcdef01-2345-6789-abcd-ef0123456789"
    fake(FakeClient(pages={dashed: page(dashed, "Empty")}, blocks={dashed: []}))
    r = runner.invoke(app, ["--json", "notion", "summarize", dashed], env=env)
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["ai_interpretation"] is None  # no fabrication, no model call


def test_summarize_with_provider(runner: CliRunner, env: dict[str, str], fake, monkeypatch) -> None:
    dashed = "abcdef01-2345-6789-abcd-ef0123456789"
    fake(FakeClient(pages={dashed: page(dashed, "Doc")}, blocks={dashed: [para("b", "content")]}))
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    r = runner.invoke(
        app, ["--json", "-p", "ollama", "-m", "ollama:x", "notion", "summarize", dashed], env=env
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["ai_interpretation"] == "AI OUTPUT"


def test_weekly_review(runner: CliRunner, env: dict[str, str], fake, monkeypatch) -> None:
    fake(
        FakeClient(
            search=[
                page(
                    "c1",
                    "Spec",
                    created="2026-08-22T00:00:00.000Z",
                    edited="2026-08-22T12:00:00.000Z",
                )
            ],
            blocks={"c1": [todo("t", "do it", checked=False)]},
        )
    )
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    r = runner.invoke(
        app, ["--json", "-p", "ollama", "-m", "ollama:x", "notion", "weekly-review"], env=env
    )
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert "observed" in data and data["ai_interpretation"] == "AI OUTPUT"
    assert "created" in data["observed"]


def test_ask_records_run(runner: CliRunner, env: dict[str, str], fake, monkeypatch) -> None:
    fake(FakeClient(search=[page("P1", "Alpha")]))
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    r = runner.invoke(
        app, ["--json", "-p", "ollama", "-m", "ollama:x", "notion", "ask", "what changed"], env=env
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["answer"] == "AI OUTPUT"
    hist = json.loads(runner.invoke(app, ["--json", "history"], env=env).output)
    assert hist["runs"][0]["command"] == "notion ask"
    assert hist["runs"][0]["auth_mode"] == "local"


def test_ask_local_only_blocks_cloud(runner: CliRunner, env: dict[str, str], fake) -> None:
    fake(FakeClient())
    r = runner.invoke(
        app,
        ["--local-only", "-p", "anthropic", "-m", "anthropic:x", "notion", "ask", "hi"],
        env=env,
    )
    assert r.exit_code != 0
    assert isinstance(r.exception, LocalOnlyViolation)


def test_ask_cloud_requires_egress_consent(
    runner: CliRunner, env: dict[str, str], fake, monkeypatch, mem_keyring
) -> None:
    fake(FakeClient())
    monkeypatch.setattr("sobai.cli.common.build_provider", lambda *a, **k: FakeProvider())
    r = runner.invoke(app, ["-p", "openai", "-m", "openai:x", "notion", "ask", "hi"], env=env)
    assert r.exit_code != 0
    assert isinstance(r.exception, PolicyError)


def test_connect_stores_token_and_meta(
    runner: CliRunner, env: dict[str, str], fake, monkeypatch, mem_keyring
) -> None:
    fake(FakeClient(me={"bot": {"workspace_name": "My Workspace"}}), connected=False)
    monkeypatch.setattr("sobai.ui.console.UI.is_interactive", lambda self: True)
    r = runner.invoke(app, ["connect", "notion"], env=env, input="secret_ntn_tokenvalue123\n")
    assert r.exit_code == 0, r.output
    from sobai.auth import CredentialStore

    assert CredentialStore().has("connector:notion:token")
    conns = json.loads(runner.invoke(app, ["--json", "connections"], env=env).output)
    assert conns["connectors"]["notion"]["status"] == "connected"


def test_disconnect_removes_token(
    runner: CliRunner, env: dict[str, str], fake, mem_keyring
) -> None:
    from sobai.auth import CredentialStore
    from sobai.connectors.notion.auth import NotionAuth

    NotionAuth(CredentialStore()).save_token("secret_ntn_tokenvalue123")
    fake(FakeClient(), connected=True)
    r = runner.invoke(app, ["disconnect", "notion"], env=env)
    assert r.exit_code == 0
    assert not CredentialStore().has("connector:notion:token")
