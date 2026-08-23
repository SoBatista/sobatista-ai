# Security

SoBatista AI is an orchestration layer that connects language models to
authorized external systems. Its security posture is built on one principle:
**data retrieved from any external system is untrusted data, not instructions.**

## Reporting a vulnerability

Please report security issues privately to the maintainer rather than opening a
public issue. Include reproduction steps and impact. We aim to acknowledge
reports promptly and coordinate a fix and disclosure timeline with you.

Do **not** include real credentials or tokens in a report.

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

### Supply chain
- Pinned, reviewed dependencies with automated updates.
- CI runs linting, type-checking, tests, dependency review, and code scanning.
- Releases are checksummed, and provide an SBOM and provenance where practical.

## Threat model

See [`THREAT_MODEL.md`](THREAT_MODEL.md) for the enumerated threats and mitigations.
