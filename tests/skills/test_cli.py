"""End-to-end CLI behaviour for `sobai skills` and `sobai run`."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sobai.core.errors import ExitCode
from sobai.core.types import Usage

from .conftest import CliOutcome, ExplodingProvider, ScriptedProvider, manifest_toml

Cli = Callable[..., CliOutcome]

CONFIG = """version = 1
active_provider = "ollama"
active_model = "fast"

[models]
fast = "ollama:qwen2.5:7b"
cloudy = "anthropic:some-model-id"
"""


def write_skill(
    env: dict[str, str],
    name: str = "demo",
    *,
    prompt: str = "Summarize the supplied material.\n",
    manifest: str | None = None,
    **kwargs: Any,
) -> Path:
    directory = Path(env["SOBAI_CONFIG_DIR"]) / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "skill.toml").write_text(
        manifest if manifest is not None else manifest_toml(name=name, **kwargs),
        encoding="utf-8",
    )
    (directory / "prompt.md").write_text(prompt, encoding="utf-8")
    return directory


def write_config(env: dict[str, str], body: str = CONFIG) -> None:
    config_dir = Path(env["SOBAI_CONFIG_DIR"])
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(body, encoding="utf-8")


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> ScriptedProvider:
    provider = ScriptedProvider()
    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: provider)
    return provider


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to build or call a provider fails the test."""

    def _explode(*args: object, **kwargs: object) -> ExplodingProvider:
        raise AssertionError("a provider was constructed when none was expected")

    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", _explode)


def _query(env: dict[str, str], sql: str) -> list[dict[str, Any]]:
    """Read a table, treating "no database at all" as "no rows"."""
    path = Path(env["SOBAI_DATA_DIR"]) / "state.db"
    if not path.exists():
        return []
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql)]
    finally:
        db.close()


def audit_rows(env: dict[str, str]) -> list[dict[str, Any]]:
    return _query(env, "SELECT * FROM audit")


def run_rows(env: dict[str, str]) -> list[dict[str, Any]]:
    return _query(env, "SELECT * FROM runs")


# -- discovery commands ----------------------------------------------------
def test_list_json_schema(cli: Cli, env: dict[str, str]) -> None:
    write_skill(env, "demo")
    result = cli(["--json", "skills", "list"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "skill-list"
    assert payload["view_version"] == 1
    entry = next(s for s in payload["skills"] if s["name"] == "demo")
    assert entry["qualified_name"] == "user:demo"
    assert entry["digest"].startswith("sha256:")
    assert entry["license"] == "MIT"
    assert entry["required_tools"] == []


def test_list_reports_a_broken_skill_rather_than_hiding_it(cli: Cli, env: dict[str, str]) -> None:
    write_skill(env, "broken", manifest="not [ toml")
    result = cli(["--json", "skills", "list"])
    payload = json.loads(result.stdout)
    assert [s["qualified_name"] for s in payload["skills"] if s["namespace"] == "user"] == []
    assert payload["broken"][0]["qualified_name"] == "user:broken"


def test_show_json_includes_prompt_provenance_and_resolution(cli: Cli, env: dict[str, str]) -> None:
    write_config(env)
    write_skill(env, "demo", prompt="Summarize precisely.\n")
    result = cli(["--json", "skills", "show", "demo"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "skill-detail"
    assert payload["prompt"].strip() == "Summarize precisely."
    assert payload["provenance"]["source"] == "test fixtures"
    assert payload["model"]["provider"] == "ollama"
    assert payload["model"]["source"] == "config-default"


def test_show_reports_why_a_model_cannot_be_resolved(cli: Cli, env: dict[str, str]) -> None:
    write_skill(env, "demo")
    payload = json.loads(cli(["--json", "skills", "show", "demo"]).stdout)
    assert payload["model"] is None
    assert "No model selected" in payload["model_resolution_error"]


def test_show_explains_a_per_skill_mapping(cli: Cli, env: dict[str, str]) -> None:
    write_config(env, CONFIG + '\n[skills.models]\n"user:demo" = "cloudy"\n')
    write_skill(env, "demo")
    payload = json.loads(cli(["--json", "skills", "show", "demo"]).stdout)
    assert payload["model"]["source"] == "skill-mapping"
    assert payload["model"]["provider"] == "anthropic"


def test_paths_names_what_is_never_searched(cli: Cli, env: dict[str, str]) -> None:
    payload = json.loads(cli(["--json", "skills", "paths"]).stdout)
    assert payload["kind"] == "skill-paths"
    assert payload["user_skills_dir"].endswith("/skills")
    joined = " ".join(payload["never_searched"])
    assert "current working directory" in joined
    assert "remote" in joined


def test_validate_json_on_success(cli: Cli, env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / "demo"
    source.mkdir()
    (source / "skill.toml").write_text(manifest_toml(), encoding="utf-8")
    (source / "prompt.md").write_text("Do the thing.\n", encoding="utf-8")
    result = cli(["--json", "skills", "validate", str(source)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "kind": "skill-validation",
        "view_version": 1,
        "valid": True,
        "path": str(source),
        "qualified_name": "user:demo",
        "name": "demo",
        "version": "1.0.0",
        "digest": payload["digest"],
        "license": "MIT",
        "variables": [],
        "error": None,
        "hint": None,
    }


def test_validate_json_on_failure_exits_nonzero(
    cli: Cli, env: dict[str, str], tmp_path: Path
) -> None:
    source = tmp_path / "demo"
    source.mkdir()
    (source / "skill.toml").write_text("not [ toml", encoding="utf-8")
    (source / "prompt.md").write_text("x\n", encoding="utf-8")
    result = cli(["--json", "skills", "validate", str(source)])
    assert result.exit_code == int(ExitCode.SKILL)
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert "not valid TOML" in payload["error"]


def test_install_json_and_then_runnable(cli: Cli, env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / "demo"
    source.mkdir()
    (source / "skill.toml").write_text(manifest_toml(), encoding="utf-8")
    (source / "prompt.md").write_text("Do the thing.\n", encoding="utf-8")
    result = cli(["--json", "skills", "install", str(source)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "skill-install"
    assert payload["action"] == "installed"
    assert payload["changed"] is True
    listing = json.loads(cli(["--json", "skills", "list"]).stdout)
    user_skills = [s["qualified_name"] for s in listing["skills"] if s["namespace"] == "user"]
    assert user_skills == ["user:demo"]


def test_install_never_accepts_a_url(cli: Cli, env: dict[str, str]) -> None:
    result = cli(["skills", "install", "https://example.com/skills/demo.tar.gz"])
    assert result.exit_code != 0
    assert "not a directory" in result.output or "cannot read" in result.output


# -- running ---------------------------------------------------------------
def test_run_sends_policy_skill_and_input_in_the_right_layers(
    cli: Cli, env: dict[str, str], scripted: ScriptedProvider
) -> None:
    write_config(env)
    write_skill(env, "demo", prompt="Summarize precisely.\n")
    result = cli(["run", "demo", "CANARY-input-text"])
    assert result.exit_code == 0, result.output
    assert "You are SoBatista AI running a Skill" in scripted.system
    assert "Summarize precisely." in scripted.system
    assert "CANARY-input-text" not in scripted.system
    assert "CANARY-input-text" in scripted.user


def test_sobai_run_and_sobai_skills_run_are_the_same_implementation() -> None:
    from sobai.cli.app import app as cli_app
    from sobai.cli.skills_cmd import skills_run

    top_level = next(c for c in cli_app.registered_commands if c.name == "run")
    assert top_level.callback is skills_run


def test_run_from_a_file(
    cli: Cli, env: dict[str, str], scripted: ScriptedProvider, tmp_path: Path
) -> None:
    write_config(env)
    write_skill(env, "demo")
    article = tmp_path / "article.md"
    article.write_text("File article body", encoding="utf-8")
    result = cli(["run", "demo", "--file", str(article)])
    assert result.exit_code == 0, result.output
    assert "File article body" in scripted.user


def test_run_from_stdin(cli: Cli, env: dict[str, str], scripted: ScriptedProvider) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["run", "demo"], stdin=b"Piped article body")
    assert result.exit_code == 0, result.output
    assert "Piped article body" in scripted.user


def test_ambiguous_input_is_refused(
    cli: Cli, env: dict[str, str], no_provider: None, tmp_path: Path
) -> None:
    write_config(env)
    write_skill(env, "demo")
    article = tmp_path / "a.md"
    article.write_text("x", encoding="utf-8")
    result = cli(["run", "demo", "text", "--file", str(article)])
    assert result.exit_code == int(ExitCode.SKILL)
    assert "both given" in result.output


def test_variables_are_typed_and_validated_before_any_provider(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    extra = '\n[[variables]]\nname = "language"\ntype = "string"\nrequired = true\n'
    write_skill(env, "demo", prompt="Translate into {{language}}.\n", extra=extra)
    result = cli(["run", "demo", "hello"])
    assert result.exit_code == int(ExitCode.SKILL)
    assert "requires a value for 'language'" in result.output


def test_variable_is_substituted(cli: Cli, env: dict[str, str], scripted: ScriptedProvider) -> None:
    write_config(env)
    extra = '\n[[variables]]\nname = "language"\ntype = "string"\nrequired = true\n'
    write_skill(env, "demo", prompt="Translate into {{language}}.\n", extra=extra)
    result = cli(["run", "demo", "Hello", "--var", "language=pt-PT"])
    assert result.exit_code == 0, result.output
    assert "Translate into pt-PT." in scripted.system


@pytest.mark.parametrize("bad", ["language", "=pt", " =x"])
def test_malformed_var_option_is_refused(
    cli: Cli, env: dict[str, str], no_provider: None, bad: str
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["run", "demo", "hi", "--var", bad])
    assert result.exit_code != 0
    assert "name=value" in result.output


def test_repeated_var_is_refused(cli: Cli, env: dict[str, str], no_provider: None) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["run", "demo", "hi", "--var", "a=1", "--var", "a=2"])
    assert result.exit_code != 0
    assert "more than once" in result.output


def test_ambiguous_skill_name_is_refused_at_the_cli(
    cli: Cli, env: dict[str, str], no_provider: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(env)
    write_skill(env, "demo")
    monkeypatch.setattr("sobai.skills.registry.builtin_names", lambda: ["demo"])
    monkeypatch.setattr(
        "sobai.skills.registry.load_builtin_skill",
        lambda name: __import__("sobai.skills.loader", fromlist=["parse_skill"]).parse_skill(
            manifest_toml(name=name).encode(), b"builtin prompt\n", namespace="builtin"
        ),
    )
    result = cli(["run", "demo", "hi"])
    assert result.exit_code == int(ExitCode.SKILL)
    assert "ambiguous" in result.output
    assert "builtin:demo" in result.output
    assert "user:demo" in result.output


def test_skill_requiring_tools_is_refused(cli: Cli, env: dict[str, str], no_provider: None) -> None:
    manifest = manifest_toml().replace(
        "[policy]\nrecommended_data_class",
        '[policy]\nrequired_tools = ["notion_search"]\nrecommended_data_class',
    )
    write_config(env)
    write_skill(env, "demo", manifest=manifest)
    result = cli(["run", "demo", "hi"])
    assert result.exit_code == int(ExitCode.SKILL)
    assert "notion_search" in result.output


# -- output modes ----------------------------------------------------------
def test_json_result_schema(cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ScriptedProvider("The summary.", usage=Usage(input_tokens=20, output_tokens=9))
    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: provider)
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--json", "run", "demo", "CANARY-body"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "skill-run-result"
    assert payload["output"] == "The summary."
    assert payload["skill"]["qualified_name"] == "user:demo"
    assert payload["provenance"]["digest"].startswith("sha256:")
    assert payload["usage"]["input_tokens"] == 20
    assert payload["input"]["bytes"] == len("CANARY-body")
    assert "CANARY-body" not in json.dumps(payload["input"])
    assert isinstance(payload["duration_ms"], int)
    assert payload["run_id"]


def test_json_mode_emits_no_decorative_text(
    cli: Cli, env: dict[str, str], scripted: ScriptedProvider
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--json", "run", "demo", "hi"])
    json.loads(result.stdout)  # the whole of stdout is one JSON document


def test_quiet_suppresses_chatter_but_keeps_output(
    cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider("Body text.", stream_deltas=False)
    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: provider)
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--quiet", "run", "demo", "hi"])
    assert result.exit_code == 0, result.output
    assert "Body text." in result.stdout


def test_no_color_output_has_no_ansi(
    cli: Cli, env: dict[str, str], scripted: ScriptedProvider
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--no-color", "skills", "list"])
    assert "\x1b[" not in result.stdout


def test_model_output_is_sanitized_before_display(
    cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    hostile = "Summary\x1b[2J\x1b]0;pwned\x07 and ‮reversed"
    provider = ScriptedProvider(hostile, stream_deltas=False)
    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: provider)
    write_config(env)
    write_skill(env, "demo")
    result = cli(["run", "demo", "hi"])
    assert result.exit_code == 0, result.output
    assert "\x1b[2J" not in result.stdout
    assert "\x1b]0;" not in result.stdout
    assert "‮" not in result.stdout
    assert "Summary" in result.stdout


def test_streaming_and_one_shot_providers_both_produce_output(
    cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(env)
    write_skill(env, "demo")
    for deltas in (True, False):
        provider = ScriptedProvider("Streamed body.", stream_deltas=deltas)
        monkeypatch.setattr(
            "sobai.cli.skills_cmd.build_provider",
            lambda *a, _p=provider, **k: _p,
        )
        result = cli(["run", "demo", "hi"])
        assert result.exit_code == 0, result.output
        assert "Streamed body." in result.stdout


def test_no_stream_still_prints(cli: Cli, env: dict[str, str], scripted: ScriptedProvider) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["run", "demo", "hi", "--no-stream"])
    assert "scripted answer" in result.stdout


# -- dry run ---------------------------------------------------------------
def test_dry_run_makes_no_provider_call(cli: Cli, env: dict[str, str], no_provider: None) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--dry-run", "--json", "run", "demo", "hello"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "skill-run-plan"


def test_dry_run_records_no_run_and_no_audit(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    write_skill(env, "demo")
    cli(["--dry-run", "run", "demo", "hello"])
    assert run_rows(env) == []
    assert audit_rows(env) == []


def test_dry_run_never_prints_the_input(cli: Cli, env: dict[str, str], no_provider: None) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--dry-run", "run", "demo", "CANARY-secret-input"])
    assert result.exit_code == 0, result.output
    assert "CANARY-secret-input" not in result.output
    assert "never printed or transmitted" in result.output


def test_dry_run_works_without_credentials(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    """Planning a cloud run must not require a key to be configured."""
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--dry-run", "--json", "-p", "anthropic", "-m", "x", "run", "demo", "hi"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["egress"]["data_leaves_machine"] is True
    assert payload["egress"]["decision"] == "consent"


def test_dry_run_shows_a_denial_without_performing_it(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(
        [
            "--dry-run",
            "--json",
            "-p",
            "anthropic",
            "-m",
            "x",
            "run",
            "demo",
            "hi",
            "--data-class",
            "restricted",
        ]
    )
    payload = json.loads(result.stdout)
    assert payload["egress"]["decision"] == "deny"
    assert payload["data_class"] == "restricted"
    assert payload["data_class_source"] == "flag"


# -- policy ----------------------------------------------------------------
def test_local_only_hard_fails_before_a_provider_is_built(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--local-only", "-p", "anthropic", "-m", "x", "run", "demo", "hi"])
    assert result.exit_code == int(ExitCode.POLICY)
    assert "--local-only is active" in result.output
    assert run_rows(env) == []


def test_local_only_never_silently_switches_provider(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--local-only", "-p", "anthropic", "-m", "x", "run", "demo", "hi"])
    assert "ollama" not in result.stdout


def test_local_only_allows_a_local_provider(
    cli: Cli, env: dict[str, str], scripted: ScriptedProvider
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["--local-only", "run", "demo", "hi"])
    assert result.exit_code == 0, result.output


def test_noninteractive_consent_fails_with_instructions(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["-p", "anthropic", "-m", "x", "run", "demo", "hi"])
    assert result.exit_code == int(ExitCode.POLICY)
    assert "Cannot prompt for consent" in result.output
    assert "policy.egress" in result.output


def test_restricted_data_is_denied_outright(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["-p", "anthropic", "-m", "x", "run", "demo", "hi", "--data-class", "restricted"])
    assert result.exit_code == int(ExitCode.POLICY)
    assert "is denied" in result.output


def test_public_data_to_a_cloud_provider_needs_no_prompt(
    cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider("ok")
    provider.name = "anthropic"
    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: provider)
    write_config(env)
    write_skill(env, "demo")
    result = cli(["-p", "anthropic", "-m", "x", "run", "demo", "hi", "--data-class", "public"])
    assert result.exit_code == 0, result.output


def test_egress_summary_names_skill_model_and_input(
    cli: Cli, env: dict[str, str], no_provider: None
) -> None:
    write_config(env)
    write_skill(env, "demo")
    result = cli(["-p", "anthropic", "-m", "x", "run", "demo", "hi"])
    assert "skill 'user:demo'" in result.output
    assert "internal" in result.output
    assert "anthropic" in result.output


# -- records ---------------------------------------------------------------
def test_run_is_recorded_with_usage_but_not_content(
    cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider("Output body.", usage=Usage(input_tokens=31, output_tokens=12))
    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: provider)
    write_config(env)
    write_skill(env, "demo")
    cli(["run", "demo", "CANARY-input-body"])

    rows = run_rows(env)
    assert len(rows) == 1
    row = rows[0]
    assert row["command"] == "skills run"
    assert row["status"] == "ok"
    assert row["input_tokens"] == 31
    assert row["output_tokens"] == 12
    assert row["summary"] == "skill user:demo@1.0.0"
    assert "CANARY-input-body" not in json.dumps(row)
    assert "Output body." not in json.dumps(row)


def test_audit_records_identity_and_shape_not_content(
    cli: Cli, env: dict[str, str], scripted: ScriptedProvider
) -> None:
    write_config(env)
    write_skill(env, "demo")
    cli(["run", "demo", "CANARY-input-body"])

    rows = audit_rows(env)
    assert len(rows) == 1
    detail = json.loads(rows[0]["detail"])
    assert rows[0]["event"] == "skill_run"
    assert rows[0]["data_class"] == "internal"
    assert detail["skill"] == "user:demo"
    assert detail["skill_digest"].startswith("sha256:")
    assert detail["input_bytes"] == len("CANARY-input-body")
    assert "CANARY-input-body" not in rows[0]["detail"]
    assert "scripted answer" not in rows[0]["detail"]


def test_a_failed_run_is_recorded_as_an_error(
    cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobai.core.errors import OperationTimeout

    class TimingOut(ScriptedProvider):
        async def generate(self, params: Any) -> Any:
            raise OperationTimeout("provider timed out", hint="raise provider timeout_s")

        async def stream(self, params: Any) -> Any:
            raise OperationTimeout("provider timed out", hint="raise provider timeout_s")
            yield  # pragma: no cover

    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: TimingOut())
    write_config(env)
    write_skill(env, "demo")
    result = cli(["run", "demo", "hi"])
    assert result.exit_code == int(ExitCode.TIMEOUT)
    assert run_rows(env)[0]["status"] == "error"


def test_cancellation_leaves_the_terminal_and_state_clean(
    cli: Cli, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class Cancelled(ScriptedProvider):
        async def generate(self, params: Any) -> Any:
            raise KeyboardInterrupt

        async def stream(self, params: Any) -> Any:
            raise KeyboardInterrupt
            yield  # pragma: no cover

    provider = Cancelled()
    monkeypatch.setattr("sobai.cli.skills_cmd.build_provider", lambda *a, **k: provider)
    write_config(env)
    write_skill(env, "demo")
    result = cli(["run", "demo", "hi"])
    assert result.exit_code == int(ExitCode.CANCELLED)
    assert provider.closed, "the provider is closed even when the run is cancelled"
