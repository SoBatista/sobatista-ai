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

## 6. Terminal escape / Unicode injection
- **Risk:** ANSI/OSC sequences or Unicode bidirectional controls in external text
  (or model output) rewrite the screen, set the window title, spoof prompts, or
  visually reorder text (Trojan-Source).
- **Controls:** ✅ `core/safeterm.py` strips CSI/OSC/DCS, stray C0/C1 control
  bytes, **and Unicode bidi/format controls**; Rich markup is escaped
  (`ui/console.py`). Applied to connector data, to model output from every
  command through the shared renderer (`cli/common.py::ModelOutput`, used by
  `ask`, `run`, and the session), and to values read back out of local state —
  a run summary written by an older build can still hold prompt text
  (`cli/history_cmd.py`). Covered by tests.

## 6a. Interactive session abuse
- **Risk:** The chat session executes tools/shell, leaks identity, persists
  secrets, or silently changes providers.
- **Controls:** ✅ No connector tools/shell/Python/MCP/web/eval in the session
  (`registry=None`); model output sanitized; conversation is in-memory only with
  explicit bounds and no disk history; welcome screen shows no identity/paths/
  secrets; `--local-only` hard-fails before cloud egress; no provider fallback;
  session-only switches never rewrite persistent defaults (`cli/session.py`).

## 6b. A malicious or careless Skill
- **Risk:** A shared "task recipe" carries a hostile system prompt, silently
  replaces one the user trusts, smuggles executable content, or hides text a
  reviewer cannot see.
- **Controls:**
  - ✅ Skills are **prompt/data only**: a TOML manifest plus a Markdown prompt.
    No executable content, no dependencies, no registered tools. The
    `sobai.skills` package contains no code that can execute, fetch, or open
    anything (`docs/adr/0007-skills-not-executable-plugins.md`).
  - ✅ A Skill grants nothing. Runs use `registry=None`, so no tool can be called
    whatever the prompt asks; a Skill *declaring* required tools is refused
    rather than run without them (`skills/runner.py::assert_tools_available`).
  - ✅ Immutable policy is always first in the system prompt and the Skill's text
    is labelled subordinate; it cannot change policy, raise limits, request
    credentials, authorize writes, disable redaction, or bypass `--local-only`
    (`skills/renderer.py::SYSTEM_POLICY`).
  - ✅ **No silent shadowing:** `builtin:`/`user:` namespaces, ambiguity is an
    error naming both candidates, and the namespace comes from the load location
    rather than the manifest, so a user Skill cannot claim to be a built-in
    (`skills/registry.py`).
  - ✅ **No auto-discovery:** only packaged built-ins and
    `~/.config/sobai/skills/` are searched — never the working directory, the
    repository being worked in, `.sobai/`, or an environment-named path — so a
    checkout cannot supply a system prompt merely because `sobai` runs inside it.
  - ✅ Terminal-control characters and Unicode bidirectional controls in a Skill's
    manifest or prompt are **refused, not stripped**: a prompt that displays
    differently from how it reads cannot be reviewed
    (`skills/loader.py::assert_reviewable_text`).
  - ✅ Content-addressed by a SHA-256 digest computed over the normalized
    manifest and prompt — never asserted by the author — and shown in `show`,
    `list`, plans, results, and audit records.
  - ✅ Strict portable names reject separators, traversal, control characters,
    non-ASCII look-alikes, and reserved names; every accepted name is provably a
    direct child of the Skills directory (property-tested).

## 6c. Untrusted input to a Skill run
- **Risk:** The material a user pipes in contains an injection, forges the input
  boundary, or is a device/binary/oversized file that hangs or floods the run.
- **Controls:**
  - ✅ Input is a **separate user message** inside explicit boundary markers,
    never interpolated into the system layer; text impersonating the markers is
    defanged so input cannot close its own block (`skills/renderer.py`).
  - ✅ Exactly one input source per run; a positional argument plus `--file` is an
    error, and stdin is a fallback so an inherited pipe cannot replace an
    explicit argument. With no input on a terminal the run fails immediately and
    never blocks (`skills/inputs.py`).
  - ✅ Bounded by bytes *and* decoded characters, per Skill; binary content,
    invalid UTF-8, directories, devices, and FIFOs are refused with actionable
    errors.
  - ✅ Input is inert: a URL in it is never fetched, a path never opened, a
    command never run — there is no code in the package that could.
  - ✅ Variables carry parameters, not content: declared scalars only, validated
    by type before any provider is contacted, capped in length, and refused if
    they contain control or bidirectional characters.

## 6d. Skill installation tampering
- **Risk:** A crafted directory escapes the Skills directory, swaps content
  between validation and install, wins a race with a concurrent install, or
  leaves a half-installed Skill the loader will happily use.
- **Controls:**
  - ✅ Symlinks, hard links, non-regular files, unexpected entries, case-only
    collisions, oversized files, and partial directories are all refused
    (`skills/loader.py::read_skill_files`).
  - ✅ The destination is derived from the validated manifest name and asserted to
    be a direct child of the Skills directory.
  - ✅ Installation writes the **bytes that were validated and hashed**, held in
    memory — never a second read of the source — so a TOCTOU swap cannot
    substitute content (regression-tested).
  - ✅ Atomic: staged in a private directory and moved with a single rename; a
    failed replacement rolls back the previous version.
  - ✅ Race-safe: an `O_EXCL` directory lock serialises installs; a concurrent
    install is refused, not interleaved. Debris from an interrupted install is
    cleared only while that lock is held.
  - ✅ Nothing is ever downloaded: `sobai skills install` takes a local path
    only. Remote installation is deferred until signing and a trust root exist.

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
  - ✅ Skill runs are classified (`--data-class`, default `internal`) and gated
    by the same engine; the prompt names the skill, class, destination provider
    and model, and input size. Non-interactive runs that need a decision **fail
    with instructions** rather than proceeding, and `restricted` is denied
    outright (`cli/skills_cmd.py`).
  - ✅ `--dry-run` on a Skill makes no provider, connector, network, or
    subprocess call and reports the input by source, size, and hash — never
    content (`skills/plan.py`).
  - ✅ Run history and audit records carry identity and shape only, for **every**
    model-backed command. Summaries are built by
    `cli/common.py::history_summary` (`ask`, the session, `notion ask`,
    `youtube ask`) or `skills/runner.py::run_summary` (`run`); the prompt, the
    output, and connector content are never persisted. A prompt *digest* is not
    stored either — a short or predictable prompt can be guessed and confirmed
    against a hash. Enforced by a source-level test over every `start_run` call
    site, not only by review.
  - ⚠️ Databases written by development builds before 0.2.0 still contain the
    first 200 characters of each prompt in historical run summaries. Existing
    history is never rewritten or deleted on the user's behalf; PRIVACY.md
    documents how to review it and how to discard the database.

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
- **Prompt injection is reduced, not eliminated.** Layering, boundary markers,
  marker defanging, and refusing tools during a Skill run bound *what a model can
  reach*; they cannot make a model's behaviour immune to hostile text. The
  durable guarantees are the ones outside the model: no tools, no shell, no
  filesystem, no network, no silent egress, `--local-only` failing closed. Model
  output is treated as untrusted for the same reason.
- The size and source of a prompt are recorded in run history. Byte counts are
  metadata, but they are not nothing: they reveal that a run happened and roughly
  how large it was.
- Trusting the local OS keyring and the user's own account credentials with the
  third-party providers.
- A compromised local machine (malware with the user's privileges) is out of
  scope.
- Third-party providers' own handling/retention of data sent to them is governed
  by their terms, not by SoBatista AI.
