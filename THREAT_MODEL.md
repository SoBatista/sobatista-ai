# Threat Model

Scope: the `sobai` CLI, its providers, connectors, credential storage, local
state, and release pipeline. Below, each threat is paired with the control(s)
that mitigate it and where they live in the codebase.

Legend: ✅ implemented · 🚧 planned (arrives with the relevant connector/feature).

## 1. Stolen tokens
- **Risk:** API keys / OAuth tokens exfiltrated from disk, logs, or memory.
- **Controls:**
  - ✅ Secrets stored only in the OS keyring (`auth/keyring_store.py`); never in
    TOML/env/argv.
  - ✅ Runtime redaction of all output/logs/exceptions (`core/redaction.py`),
    with registered exact-value scrubbing.
  - ✅ Config and state files created `0600`; directories `0700`.
  - ✅ Least-privilege OAuth scopes (YouTube): read-only by default; monetary and
    caption (`force-ssl`) scopes are separate explicit opt-ins
    (`connectors/youtube/scopes.py`).
  - ✅ Installed-app OAuth uses PKCE (S256) and `state` CSRF validation
    (`connectors/youtube/oauth.py`).

## 2. Malicious Notion pages / documents
- **Risk:** A shared page instructs the model to exfiltrate data or take actions.
- **Controls:**
  - ✅ System posture: retrieved Notion content is untrusted data, not
    instructions — it cannot change policy, enable tools, raise limits, request
    secrets, or authorize writes (`cli/notion_cmd.py` system prompts; enforced by
    the allowlisted-tool orchestrator, `tools/base.py`, `core/orchestrator.py`).
  - ✅ Terminal-escape sanitization on display (`core/safeterm.py`), applied to
    untrusted Notion titles/content in `cli/notion_cmd.py` (and YouTube fields).
  - ✅ Notion data classified INTERNAL and egress-gated before reaching a cloud
    model (`policies/engine.py`, enforced in the Notion/YouTube AI commands);
    `--local-only` hard-fails first.
  - ✅ Read-only: no Notion write endpoints are ever called; block traversal is
    bounded with cycle/duplicate prevention; page refs accept only ids/notion.so
    URLs (`connectors/notion/`).

## 3. Prompt injection from comments / issues
- **Risk:** Attacker-controlled text in a GitHub/Jira comment steers the model.
- **Controls:** same as #2 — untrusted-data posture, allowlisted tools, bounded
  tool rounds (`policy.max_tool_rounds`), no model-driven shell/writes.

## 4. Malicious URLs and transcripts
- **Risk:** A fetched URL or supplied transcript carries an injection or terminal
  attack.
- **Controls:**
  - ✅ Sanitize before render (`core/safeterm.py`).
  - ✅ Transcript precedence rules (authorized captions → user-supplied →
    explicit local workflow) in `connectors/youtube/captions.py`; never scrapes
    arbitrary captions; reports clearly when no authorized transcript exists and
    never claims a transcript was retrieved when it wasn't.

## 5. Subprocess injection & over-privileged CLI bridges
- **Risk:** Shell metacharacters in a prompt execute commands; or a bridged CLI
  loads repo content / tools / MCP and acts beyond a read-only Q&A.
- **Controls:**
  - ✅ `create_subprocess_exec` with argv arrays, never a shell; no `eval`
    (`providers/cli_bridge.py`). The **prompt is delivered over stdin**, never as
    an argv element (not in the process list). Covered by injection tests.
  - ✅ Bridges are hardened and **fail closed** if a required security flag is
    unsupported: built-in tools, MCP, hooks, plugins, slash commands, session
    persistence, and project/local settings are disabled; the CLI runs from an
    empty working directory; API-key env vars are stripped so the subscription
    login is used (never `--bare` / API billing). Codex runs `--sandbox
    read-only` and never uses bypass/`danger-full-access`/`--yolo` flags.
  - ✅ Auth is detected via the CLI's own status subcommand (argv + timeout);
    credential files are never read and CLI credentials are never imported into
    the keyring; account identity is never displayed. No silent provider fallback.
  - ✅ Timeouts + kill-on-timeout + cancellation.
  - ✅ Generated shell wrappers forward `"$@"` / `$argv` verbatim, no `eval`
    (`cli/aliases.py`).

## 6. Terminal escape injection
- **Risk:** ANSI/OSC sequences in external text rewrite the screen, set the
  window title, or spoof prompts.
- **Controls:** ✅ `core/safeterm.py` strips CSI/OSC/DCS and stray control bytes;
  Rich markup is escaped (`ui/console.py`). Covered by tests.

## 7. Excessive model tool loops
- **Risk:** A runaway agent loops tools indefinitely (cost/DoS).
- **Controls:** ✅ Bounded rounds (`ToolLimitError` in `core/orchestrator.py`),
  per-provider timeouts, classified bounded retries (`providers/base.py`).

## 8. Accidental cloud disclosure
- **Risk:** Sensitive local/connector data sent to a cloud model unintentionally.
- **Controls:**
  - ✅ `--local-only` fails closed (`policies/engine.py`).
  - ✅ No silent local→cloud fallback.
  - ✅ Egress consent prompt showing connector + data class before send, and an
    audit record of each egress — wired through the YouTube AI commands
    (`cli/youtube_cmd.py` → `cli/common.py::enforce_egress`, `storage/db.py`).

## 8a. Malicious or unintended self-update source
- **Risk:** `sobai update` installs code from an attacker-controlled or wrong
  path, or a crafted path triggers shell execution.
- **Controls:**
  - ✅ Source must be a directory whose `pyproject.toml` names project
    `sobatista-ai`; missing / non-directory / root / overly-broad / non-matching
    paths are refused, and **no change is made** on validation failure
    (`cli/update_cmd.py::validate_source`).
  - ✅ `uv` invoked via argv arrays (no shell / `eval` / interpolation / globs);
    paths with spaces or shell metacharacters are passed literally. Timeouts and
    redacted errors apply.
  - ✅ Source is built/validated before the installed tool is replaced; the
    refreshed executable is verified afterward; each update is audited.
  - ✅ Never runs `git`, fetches remote code, changes branches, or publishes.

## 9. Dependency and release compromise
- **Risk:** A malicious dependency or tampered release artifact.
- **Controls:**
  - ✅ Pinned, reviewed deps; `uv.lock`.
  - 🚧 CI: dependency review, CodeQL, secret scanning, package audit.
  - 🚧 Signed/checksummed release artifacts, SBOM, provenance/attestation.
  - ✅ Human approval required for any publish/release.

## Residual risks / non-goals (Phase 1)
- Trusting the local OS keyring and the user's own account credentials with the
  third-party providers.
- A compromised local machine (malware with the user's privileges) is out of
  scope.
- Third-party providers' own handling/retention of data sent to them is governed
  by their terms, not by SoBatista AI.
