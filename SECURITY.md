# Security

SoBatista AI is an orchestration layer that connects language models to
authorized external systems. Its security posture is built on one principle:
**data retrieved from any external system is untrusted data, not instructions.**

## Reporting a vulnerability

Please report security issues privately to the maintainer rather than opening a
public issue. Include reproduction steps and impact. We aim to acknowledge
reports promptly and coordinate a fix and disclosure timeline with you.

Do **not** include real credentials or tokens in a report. Report privately via
[GitHub Security Advisories](https://github.com/SoBatista/sobatista-ai/security/advisories/new).

## Supported versions

This project is **pre-1.0 and pre-release**: the API and CLI surface may change
between minor versions (see [`RELEASING.md`](RELEASING.md) for the compatibility
policy). Security fixes are provided only for the **most recent released
version**. There is no supported stable release yet; `0.1.0.dev0` is a
development version and must not be treated as stable.

| Version line | Supported |
|--------------|-----------|
| latest release | ✅ security fixes |
| any older pre-release | ❌ upgrade to latest |

When a fixed release is published, older affected pre-releases are
[yanked](https://pypi.org/help/#yanked) on PyPI where appropriate.

## Security model & controls

### Credentials
- Stored **only** in the OS keyring (Secret Service / libsecret / KWallet), never
  in TOML, `.env`, shell history, or subprocess arguments.
- Namespaced under the `sobai` keyring service so you can audit every secret.
- Any secret read at runtime is registered with the redaction engine and scrubbed
  from all output, logs, and exception messages.

### Least privilege
- Connectors default to **read-only** scopes. Monetary/analytics scopes and any
  write scope are separate, explicit opt-ins.
- OAuth uses installed-application flows with PKCE and `state` validation
  (connectors, when enabled).

### Prompt-injection & untrusted content
- Retrieved content can never enable a tool, change policy, or alter the system
  prompt.
- All external text is passed through `safeterm.sanitize` before display, which
  strips ANSI/OSC/control sequences so a malicious title or page body cannot
  drive your terminal.

### Execution safety
- No model-generated shell execution by default; no arbitrary Python; no dynamic
  `eval`.
- CLI bridges spawn subprocesses with **argv arrays** (`create_subprocess_exec`),
  never a shell — no interpolation or injection surface. Every call has a timeout
  and is cancellable.
- Tool loops are bounded by `policy.max_tool_rounds`; every HTTP call has a
  timeout and bounded, classified retries.

### Data egress
- Only `ollama` is treated as a local provider. Cloud providers and the CLI
  bridges are egress.
- `--local-only` fails **closed** before any external request.
- Connector data is classified and gated by an egress policy
  (`public`/`internal`/`sensitive`/`restricted`); cloud egress of connector data
  prompts for consent unless a persistent policy is set. Each egress is recorded
  in the local audit log (metadata only — never content).

### No silent fallback
- SoBatista AI never silently switches providers (e.g. local → cloud) on error.

### Notion connector (read-only)
- The integration token is entered via a hidden prompt and stored **only** in the
  OS keyring — never in TOML, env, SQLite, arguments, logs, exceptions, fixtures,
  shell history, or audit records — and is redacted from all output. The
  integration can read only content explicitly shared with it; Phase 1 performs
  no writes of any kind.
- Retrieved Notion content is treated as untrusted data: it cannot change policy,
  enable tools, raise limits, request secrets, or authorize writes, and terminal
  escape sequences are stripped before display. Page references accept only ids
  or `notion.so` URLs (arbitrary URLs are refused). Traversal is bounded with
  cycle/duplicate prevention; rate limits are handled with `Retry-After`.

### Self-update (`sobai update`)
- Updates only from a **local checkout you point it at**, validated by reading
  `pyproject.toml` and confirming the project name is `sobatista-ai`; missing,
  non-directory, root/overly-broad, or non-matching paths are refused and nothing
  is changed.
- Runs `uv` via **argv arrays** — never a shell string, `shell=True`, `eval`,
  interpolation, or globs — with timeouts and redacted errors. The source is
  built/validated before the installed tool is replaced, and the refreshed
  executable is verified afterward.
- Never runs `git`, fetches remote code, changes branches, discards local
  changes, publishes, tags, or releases. Each update writes a privacy-preserving
  audit event.

### Skills
- A Skill is **prompt and data only** — a TOML manifest plus a Markdown prompt.
  It cannot execute code, call a tool, open a file, reach the network, spawn a
  process, or read an environment variable. There is no code in the Skills
  package that could, so this is structural rather than a check that can be
  forgotten (see [ADR-0007](docs/adr/0007-skills-not-executable-plugins.md)).
- **A Skill is subordinate to system policy.** The immutable policy layer is
  always first in the system prompt; the Skill's text follows, labelled as
  subordinate. A Skill cannot override privacy policy, enable a connector or
  tool, raise tool rounds or size limits, request credentials, authorize writes,
  disable redaction, or bypass `--local-only`. Skills run with no tool registry
  at all; one that *declares* required tools is refused, never silently run
  without them.
- **Input is separated from instructions.** Your input is a distinct user
  message inside explicit boundary markers, never interpolated into the system
  layer, and text impersonating those markers is defanged so input cannot close
  its own block.
- **The renderer offers nothing to attack.** Single-pass substitution of
  declared scalar variables. No `eval`, expressions, Jinja, attribute access,
  calls, loops, includes, filters, environment expansion, filesystem reads,
  network access, command substitution, or dynamic imports. Unknown, missing,
  duplicate, or ill-typed variables fail *before* a provider is contacted.
- **No auto-discovery.** Skills load only from packaged built-ins and
  `~/.config/sobai/skills/`. The working directory, the repository you are
  running inside, `.sobai/`, and environment-named paths are never searched, so
  an untrusted checkout cannot supply a system prompt.
- **No silent shadowing.** `builtin:` and `user:` namespaces; a short name
  matching both is an actionable ambiguity error naming both candidates. The
  namespace comes from the load location, never the manifest, so a user Skill
  cannot claim to be a built-in.
- **Installation is local-only, validated, atomic, and race-safe.** Nothing is
  ever downloaded. Symlinks, hard links, special files, path traversal,
  unexpected or case-colliding entries, oversized files, invalid encodings, and
  binary content are refused. Terminal-control and Unicode bidirectional
  characters in a Skill's text are refused rather than stripped — a prompt that
  renders differently from how it reads cannot be reviewed. The bytes installed
  are the bytes validated and hashed, so a source modified mid-install cannot
  substitute content, and a failed replacement rolls back.
- **Content-addressed.** A SHA-256 digest over the normalized manifest and
  prompt is computed (never asserted by the author) and shown wherever a Skill
  is identified.
- **Egress is gated as usual.** Each Skill recommends a data classification
  (`--data-class` overrides; default `internal`), `restricted` is denied, cloud
  egress shows the skill, class, destination provider and model, and input size
  before sending, non-interactive runs fail rather than bypass a required
  confirmation, and `--local-only` hard-fails before a provider is constructed.
- `--dry-run` makes no provider, connector, network, or subprocess call and
  never prints or transmits the input — only its source, size, and hash.

### Interactive session
- Running `sobai` with no subcommand opens a conversational session that reuses
  the same security model: it never enables connector tools, never executes
  shell/Python/`eval`/MCP/web tools, never falls back between providers, and
  sanitizes all model output (ANSI/OSC/control + Unicode bidirectional controls)
  before display. `--local-only` still fails closed. Prompt history is held in
  memory only and never written to disk. `/skills` lists available Skills for
  discovery only — the session does not execute them, so there is no second
  path around the input bounds, egress consent, and audit that `sobai run`
  enforces.

### Supply chain
- **Dependencies:** pinned via `uv.lock`, reviewed, and updated by Dependabot.
  Dependency Review blocks high-severity and copyleft additions on PRs.
- **Actions:** every third-party GitHub Action is pinned to a full commit SHA
  with a human-readable version comment; Dependabot updates those pins. Workflows
  are linted with `actionlint` and audited with `zizmor`.
- **Static analysis:** CodeQL (security-and-quality) and OpenSSF Scorecard run on
  a schedule and upload SARIF to code scanning.
- **Secrets:** a deterministic, offline secret scan runs in CI in addition to
  platform secret scanning; a license policy check rejects copyleft runtime deps.
- **Releases:** published to PyPI via **Trusted Publishing (OIDC)** — there is no
  long-lived PyPI token in the repository — from a protected `pypi` environment.
  Each release ships SHA-256 checksums, a CycloneDX SBOM, signed build-provenance
  attestations, and PyPI's PEP 740 attestations. Least-privilege permissions are
  set per job. See [`RELEASING.md`](RELEASING.md).

## Threat model

See [`THREAT_MODEL.md`](THREAT_MODEL.md) for the enumerated threats and mitigations.
