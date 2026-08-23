# Governance

SoBatista AI is an open-source project in its early phase. This document
describes how decisions are made so contributors know what to expect.

## Roles

- **Users** — anyone using `sobai`. Feedback and issues are welcome and valued.
- **Contributors** — anyone who opens a PR. Contributions follow
  [`CONTRIBUTING.md`](CONTRIBUTING.md) and the engineering rules in
  [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md).
- **Maintainers** — trusted contributors with write access who review and merge
  changes, cut releases, and safeguard the project's invariants. The current list
  is in [`MAINTAINERS.md`](MAINTAINERS.md).

## Decision-making

- **Day-to-day changes** are decided through pull-request review. At least one
  maintainer approval is required to merge; the author does not merge their own
  change without a second maintainer's approval once there is more than one
  maintainer.
- **Security-sensitive areas** (`src/sobai/auth/`, `src/sobai/policies/`,
  `src/sobai/core/redaction.py`, `.github/workflows/`, release configuration)
  are protected by [`CODEOWNERS`](.github/CODEOWNERS) and require owner review.
- **Significant or cross-cutting changes** (new provider/connector abstractions,
  security-model changes, breaking changes) should be proposed first — as an
  issue or a short [ADR](docs/adr/) — and are decided by maintainer consensus.
  If consensus cannot be reached, the lead maintainer decides.

## Project invariants

Some rules are non-negotiable and enforced in review and CI regardless of who
proposes a change:

- Providers and connectors stay decoupled (see [`ARCHITECTURE.md`](ARCHITECTURE.md)).
- Secrets live only in the OS keyring; nothing weakens redaction.
- `--local-only` fails closed; untrusted external data is never treated as
  instructions.
- Write actions stay behind an explicit opt-in.

See [`SECURITY.md`](SECURITY.md) and [`THREAT_MODEL.md`](THREAT_MODEL.md).

## Releases

Releases are prepared automatically and **published only with explicit maintainer
approval** through a protected environment. The process is documented in
[`RELEASING.md`](RELEASING.md).

## Changing this document

Governance changes are made by pull request with maintainer consensus.
