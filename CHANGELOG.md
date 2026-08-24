# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-24

### Added — Skills: secure, reusable task recipes
- **`sobai run NAME`** (and `sobai skills run NAME`, bound to the same function
  so there is one execution path) runs a **Skill**: a versioned, inspectable
  task recipe made of a `skill.toml` manifest and a `prompt.md`. Skills are
  prompt and data only — they cannot execute code, call a tool, open a file, or
  reach the network, and a Skill prompt is always subordinate to the immutable
  system policy. See [ADR-0007](docs/adr/0007-skills-not-executable-plugins.md).
- **Seven original built-in Skills**, packaged as application resources and
  loadable from a wheel or sdist: `summarize`, `extract-insights`,
  `analyze-claims`, `explain-code`, `security-review`, `creator-ideas`, and
  `rewrite`. Each states an output contract, separates evidence from inference,
  refuses to fabricate facts or claim access to sources it was not given, and
  works across providers. `security-review` stays defensive and authorized.
- **Namespaces without silent shadowing.** `builtin:` and `user:`; a short name
  that matches both raises an actionable ambiguity error naming both candidates,
  so a user Skill can never quietly replace a built-in. The namespace is
  assigned by load location, never read from the manifest.
- **Explicit, local-only installation.** `sobai skills list|show|paths|validate|install`.
  Skills load only from packaged built-ins and `~/.config/sobai/skills/` — never
  the working directory, the repository being worked in, `.sobai/`, or an
  environment-named path, so a checkout cannot supply a system prompt. Nothing
  is ever downloaded. Installation is atomic, race-safe under an `O_EXCL` lock,
  and writes the bytes that were validated and hashed, so a source modified
  mid-install cannot substitute content; a failed replacement rolls back.
- **A deliberately minimal renderer.** Single-pass substitution of declared
  scalar variables (`--var name=value`) and nothing else — no `eval`,
  expressions, template execution, attribute access, calls, loops, includes,
  environment expansion, filesystem reads, or shell interpolation. Unknown,
  missing, duplicate, or ill-typed variables fail before a provider is
  contacted. Input is a separate user message inside boundary markers it cannot
  forge.
- **Per-skill model mapping** in `[skills.models]`, keyed by fully qualified
  name and mapping to logical aliases rather than vendor model ids. Resolution
  is CLI flags → skill mapping → profile → defaults, and `skills show` and
  `--dry-run` both explain which rule won.
- **Typed `--dry-run` plans** that make no provider, connector, network, or
  subprocess call, need no credentials, and describe the input by source, size,
  and SHA-256 hash rather than content. The plan models are written for reuse by
  the later `explain-plan` work.
- **Data classification and egress gating.** `--data-class` overrides each
  Skill's recommendation (default `internal`); `restricted` is denied; cloud
  egress shows the skill, class, destination provider and model, and input size;
  non-interactive runs that need a decision fail with instructions rather than
  proceeding; `--local-only` hard-fails before a provider is constructed.
- **Provenance.** A stable SHA-256 digest over the normalized manifest and
  prompt, computed rather than asserted, shown in `list`, `show`, plans,
  results, and audit records. Run history and audit records carry identity and
  size only — never the prompt or the output.
- **Stable JSON contracts** for listing, inspection, validation, installation,
  paths, dry-run plans, and execution results, each with a `kind` discriminator
  and a version.
- `/skills` in the interactive session lists what is available and how to run
  it. The session does not execute Skills, so there is no second path around the
  input bounds, egress consent, and audit that `sobai run` enforces.
- Terminal-control characters and Unicode bidirectional controls in a Skill's
  text are **refused rather than stripped**: a prompt that renders differently
  from how it reads cannot be reviewed.

### Fixed
- `sobai` exited **0 after a cancelled run**. Typer converts `KeyboardInterrupt`
  into an `Exit(130)` which, under `standalone_mode=False`, is *returned* rather
  than raised; the entry point discarded that return value, so Ctrl-C — and any
  command raising `typer.Exit(code)` — reported success. `main` now honours it.

### Documentation
- New [Skills guide](docs/skills.md) covering the format, trust boundaries,
  namespaces, installation, authoring, model mappings, pipelines, dry-run
  behaviour, data classification, why current-directory auto-loading is
  forbidden, why remote installation and executable extensions are deferred, and
  how Skills differ from connectors, tools, workflows, and MCP.
- New [ADR-0007](docs/adr/0007-skills-not-executable-plugins.md) and
  [Acknowledgements](docs/acknowledgements.md), recording
  [Fabric](https://github.com/danielmiessler/Fabric)'s conceptual influence
  (inspected 2026-08-24) and confirming that every built-in prompt is original
  work rather than copied or adapted material.
- README, QUICKSTART, ARCHITECTURE, SECURITY, PRIVACY, THREAT_MODEL, AI_GUIDE,
  the example config, and the MkDocs navigation updated for Skills.

## [0.1.1] - 2026-08-24

### Changed — releases are cut from the reviewed pull request
- Replaced Release Please with **one pull request, one version**: every PR now
  carries its own version bump, changelog section, and exactly one
  `release:major|minor|patch` label, validated by `scripts/check_version.py`.
  The version that reaches `main` is the one that was reviewed — a
  `release:minor` at `0.1.1` is always `0.2.0`, with no pre-1.0 special cases.
- `release.yml` now triggers on a successful CI run on `main` and creates the
  tag and GitHub Release itself via `scripts/release.py`, then publishes to PyPI.
  Publishing no longer depends on a Release created by `GITHUB_TOKEN`, which
  could not trigger it, so a merged release now publishes without manual
  dispatch and without a personal access token.
- Removed `release-please.yml`, `release-please-config.json`,
  `.release-please-manifest.json`, and `scripts/check_release_impact.py`.
- `CHANGELOG.md` now genuinely follows Keep a Changelog, as its own header has
  always claimed; `## [x.y.z] - YYYY-MM-DD` sections are the source of release
  notes.

## [0.1.0] - 2026-08-23

### Changed — canonical repository URL
- Corrected the canonical repository URL to `https://github.com/SoBatista/sobatista-ai`
  across package metadata (`pyproject` project URLs), clone instructions, issue
  configuration, and documentation. The previous `sobatistacyber/...` URL was
  wrong.

### Added — OSS release, CI, and supply-chain hardening
- **Versioning:** single authoritative version source (`pyproject` +
  `importlib.metadata` at runtime); documented SemVer↔PEP 440 lifecycle
  (alpha/beta/rc/stable), pre-1.0 compatibility, deprecation, supported Pythons,
  security support, and rollback/yank in `RELEASING.md`.
- **Release automation (prepared, inert):** Release Please prepares release PRs
  (version + changelog); a separate, prepared-but-inert `release.yml` publishes on
  a published GitHub Release via **PyPI Trusted Publishing (OIDC)** — no
  long-lived token — from a protected `pypi` environment, with tag↔version check,
  `twine check`, both-artifact smoke installs, SHA-256 checksums, a CycloneDX
  SBOM, signed build-provenance + PEP 740 attestations, and idempotent
  re-runs. No tag/release is created by this change.
- **PR release-impact** validation (exactly one of major/minor/patch/none).
- **CI hardening:** lint, strict types, branch-coverage tests (floor raised to
  85%), build + metadata validation, install smoke tests (wheel/sdist × pip/uv
  tool/pipx, incl. non-TTY launch), strict MkDocs build, offline doc-link check,
  and lockfile consistency. All third-party Actions pinned to full commit SHAs.
- **Security automation:** `actionlint` + `zizmor` workflow audits, deterministic
  offline secret scan, runtime license policy, retained CodeQL, Dependency Review
  (with copyleft denylist), and OpenSSF Scorecard (SARIF).
- **Repo standards:** `RELEASING.md`, `GOVERNANCE.md`, `MAINTAINERS.md`,
  `SUPPORT.md`, `CITATION.cff`, ADR-0004/0005, provider/connector authoring
  guides, a maintainer settings-handoff checklist, structured issue forms,
  expanded CODEOWNERS, and real status badges.

### Added — interactive `sobai` session
- Running `sobai` with no subcommand in an interactive terminal opens a polished,
  provider-neutral chat session (Rich welcome screen; version/provider/model/
  profile/local-only shown, no identity/paths/secrets). Non-interactive
  invocations never hang — they print actionable `sobai ask` guidance; `--help`
  and `--version` never launch the session; `--json` with no subcommand is
  refused with guidance.
- Multi-turn in-memory conversation with explicit context bounds (never
  persisted); reuses existing providers, aliases, profiles, policy, streaming,
  usage/audit accounting, timeouts, retries, and cancellation. Slash commands:
  `/help /status /provider[ NAME] /model[ NAME] /profile[ NAME] /usage /clear
  /exit /quit`. Session-only switches (never rewrite persistent defaults);
  unknown commands are never sent to the model; empty input ignored; EOF exits;
  Ctrl-C cancels a generation and, twice at idle, exits.
- Never enables connector tools, never runs shell/Python/MCP/web/eval, never
  silently falls back to another provider; model output is sanitized (ANSI/OSC/
  control + Unicode bidi controls) before display. Line editing via stdlib
  `readline` (in-memory only; no history written to disk).
- `core.safeterm` now also strips Unicode bidirectional/format controls
  (Trojan-Source class).

### Added — Notion connector (read-only)
- Read-only Notion connector via the official API (`Notion-Version 2026-03-11`);
  the integration reads only content explicitly shared with it. Never scrapes;
  never creates, edits, archives, comments on, or deletes anything.
- Auth: integration token via a hidden prompt, stored **only** in the OS keyring
  (never in TOML, env, SQLite, arguments, logs, exceptions, fixtures, or audit
  records) and redacted everywhere. `connect notion` explains the shared-only
  access model and validates the token; `disconnect notion` removes the keyring
  credential and local connection metadata.
- Commands: `connect/disconnect notion`, `notion search`, `recent`, `projects`
  (deterministic), and `summarize`, `weekly-review`, `ask` (provider-backed).
- Retrieval: search + cursor pagination; page + recursive block traversal with
  explicit depth/total bounds, cycle/duplicate prevention, unsupported-block
  tolerance, and feature-detection of page/data_source/legacy-database shapes;
  page-id/`notion.so`-URL normalization that refuses arbitrary URLs; UTC
  timezone-aware `--since` boundaries; 429/529 handling honoring `Retry-After`
  with bounded retries and timeouts. Every item carries source provenance.
- `weekly-review` separates observed facts (created/edited pages, to-do-derived
  completed/open tasks, keyword-heuristic decisions/blockers, project mentions,
  source references) from clearly-labeled AI interpretation; `projects` uses a
  documented, non-authoritative heuristic.
- `notion ask` uses the existing bounded provider/tool orchestration over typed,
  JSON-Schema, read-only tools; retrieved content is untrusted data (cannot
  change policy, enable tools, raise limits, request secrets, or authorize
  writes) and terminal escapes are sanitized before rendering.
- Privacy: Notion data classified `internal`; cloud egress applies the existing
  policy (connector + class shown, consent required) with privacy-preserving
  audit; `--local-only` hard-fails before any external disclosure and never
  switches providers.
- Docs: `docs/notion.md` (setup, sharing, limitations, privacy, troubleshooting).

### Added — safe local self-update (`sobai update`)
- `sobai update` refreshes the globally installed `sobai` from a validated local
  `sobatista-ai` checkout; `--source PATH` validates and remembers the checkout
  (stored in config), so later `sobai update` works from anywhere.
- `--check` delegates to the existing `update-check` logic and changes nothing;
  `--yes` skips confirmation; JSON/quiet output stays machine-clean.
- Validates the source by reading `pyproject.toml` and confirming the project
  name is `sobatista-ai`; refuses missing, non-directory, root/overly-broad, or
  non-sobatista-ai paths — and makes no changes when validation fails.
- Requires `uv`; builds/validates the source (into a temp dir) before replacing
  the tool with the argv-array equivalent of `uv tool install --force <abs>`,
  then verifies the refreshed executable. Everything uses argv arrays — never a
  shell string, `shell=True`, `eval`, interpolation, or globs — with timeouts,
  sanitized errors, and a privacy-preserving audit event. Never runs `git`,
  fetches remote code, changes branches, publishes, tags, or releases.
- Meaningful exit codes: missing `uv` (11), invalid source (3), missing path
  (9), build failure (12), declined (130), install/verify failure (13).
- New optional `sobai-update` shell wrapper (bash/zsh/fish) via
  `sobai aliases install` that only forwards args to `sobai update`.
- Docs: `QUICKSTART.md`; README/SECURITY/THREAT_MODEL updated.

### Changed — subscription-authenticated CLI providers are first-class
- `sobai init` now leads with detected **subscription** CLIs (Claude Code, Codex)
  and local Ollama; direct Anthropic/OpenAI API access is an optional advanced
  choice, clearly labeled "separate metered billing". Detection uses safe argv
  status commands (`claude auth status`, `codex login status`) with timeouts,
  never reads credential files, never imports CLI credentials, and never exposes
  account identity. Installed-but-unauthenticated CLIs can be logged in on
  confirmation; non-interactive init never launches a login or browser.
- Subscription-backed model aliases seeded without inventing model IDs:
  `claude-subscription = "claude-cli:default"`, `codex-subscription =
  "codex-cli:default"`. `default` is a documented sentinel meaning "let the CLI
  pick its configured default"; `--model default` is never passed to the CLI.
- **Hardened CLI bridges.** Prompts are delivered via stdin (never argv); flags
  are feature-detected and the bridge fails closed if a boundary can't be
  enforced. Claude Code: `--tools ""`, empty strict MCP config, `--safe-mode`,
  no slash commands / session persistence / setting sources, empty working dir,
  API-key env stripped (never `--bare`). Codex: `--sandbox read-only`,
  `--ephemeral`, `--ignore-user-config`/`--ignore-rules`, web search + MCP
  disabled via config overrides, empty working dir, API-key env stripped; never
  `--yolo` / `danger-full-access` / bypass flags.
- `sobai providers list` and `sobai doctor` now show billing mode and
  authentication status (no identity or credentials exposed).
- New `sobai usage [--period] [--provider]` shows recorded token usage and cost,
  labeled actual / estimated / unavailable. Runs now record billing mode,
  cached-input and reasoning tokens, and cost kind (storage schema v2, migrated
  in place). `claude-cli` costs are labeled API-equivalent client estimates;
  `codex-cli` records tokens with no invented cost; Ollama is local ($0).
- Docs: `docs/subscriptions.md` (setup, security arguments, billing semantics).

### Added — YouTube connector (read-only)
- Installed-application OAuth 2.0 with loopback redirect, PKCE (S256), and state
  validation; tokens stored only in the OS keyring and redacted everywhere.
- Least-privilege scopes by default (`youtube.readonly`, `yt-analytics.readonly`);
  `--monetary` and `--captions` are separate opt-ins (the latter a broad scope).
- Official APIs only (Data API v3 + Analytics API v2) — never scrapes.
- Commands: `connect/disconnect youtube`, `youtube channel`, `analytics`,
  `compare`, `top`, `video`, `summarize`, `ideas`, `ask`.
- Typed, read-only JSON-Schema tools power `youtube ask` via the bounded tool loop.
- Feature-detection of unsupported metric/dimension combinations; unavailable
  metrics (thumbnail impressions/CTR, new-vs-returning) reported, never fabricated.
- Every report carries date range, timezone (Pacific), freshness, and query/source
  metadata, with observed facts kept separate from labeled AI interpretation.
- Caption/transcript precedence (authorized captions → user-supplied → local
  workflow), with a clear message when no authorized transcript exists.
- Cloud-egress consent + audit and `--local-only` enforcement for AI commands.
- Setup guide and API-limitation docs in `docs/youtube.md`.
- Neutral `core.retry` extracted so connectors and providers share retry/backoff
  without importing each other.

### Added — Phase 1 secure core
- Provider-neutral CLI `sobai` (Typer) with global `--provider/--model/--profile`,
  `--local-only`, `--dry-run`, `--apply`, `--json`, `--quiet`, `--no-color`.
- Providers over async HTTPX: `anthropic` (Messages API), `openai` (Responses
  API), `ollama` (local) — streaming, tool-call parsing, and model discovery.
- Optional CLI bridges `claude-cli` and `codex-cli` that fail safely when absent
  and never accept API keys or silently fall back.
- Provider/model/profile switching with logical model aliases (no hard-coded
  vendor model IDs); `providers list`, `models list`, `models discover`,
  `provider use`, `model use`, `profile create/use/list/delete`.
- Keyring-backed credential storage with runtime secret redaction across output,
  logs, and exceptions.
- Policy engine: `--local-only` hard-fail and cloud-egress consent with data
  classification; privacy audit log.
- Bounded tool-call orchestrator with read/write tool separation.
- SQLite local state: run history (`history`, `runs show`), audit (`audit`),
  tool calls, cache metadata, KB import table.
- `init`, `doctor`, `config show`, `connections`, `privacy explain`,
  `update-check`, `tools`.
- Safe shell wrappers via `aliases install {bash,zsh,fish}` (no `eval`).
- Documentation: README, ARCHITECTURE, SECURITY, PRIVACY, THREAT_MODEL,
  CONTRIBUTING, CODE_OF_CONDUCT, AI_GUIDE, CLAUDE/AGENTS, and ADRs 0001–0003.
- Test suite (unit, provider contract via `respx`, CLI) that runs without any
  live external API.

### Not yet implemented (planned)
- Connectors: YouTube (read-only analytics via OAuth), Notion (read-only search
  & weekly review).
- Natural-language → typed plan routing, `explain-plan`.
- MCP server (`mcp serve/list/doctor`).
- Controlled writes behind `--apply`; GitHub/Jira/website connectors.

### Fixed
- **init:** align subscription-CLI billing mode and per-run usage metrics
  ([36328b8](https://github.com/SoBatista/sobatista-ai/commit/36328b8edd27b58ccfbaa805f16e9ea49b65ae7a))
- **init:** support subscription-authenticated CLI providers
  ([fcacc3d](https://github.com/SoBatista/sobatista-ai/commit/fcacc3d0914db1af3305e96d2a5497800798e8df))
