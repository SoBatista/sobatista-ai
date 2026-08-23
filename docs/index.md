# SoBatista AI

**One CLI. Any model. Your tools.**

`sobai` is a provider-neutral AI command-line interface — a secure orchestration
layer that connects the models you already use (Anthropic Claude, OpenAI, local
Ollama, and optionally the Claude Code / Codex CLIs) to explicitly authorized
external tools (YouTube, Notion, and more).

This site collects the reference and developer documentation. Project overview,
install, and quick-start live in the
[README](https://github.com/SoBatista/sobatista-ai#readme).

## Using the connectors

- [YouTube connector](youtube.md) — read-only analytics via OAuth.
- [Notion connector](notion.md) — read-only search, pages, and weekly review.
- [Subscription CLIs](subscriptions.md) — use Claude Code / Codex logins as
  providers.
- [Screenshots & recordings](screenshots.md) — how to contribute terminal
  captures.

## Extending SoBatista AI

- [Authoring a provider](authoring-providers.md)
- [Authoring a connector](authoring-connectors.md)

## Project & release

- [Architecture decisions](adr/0001-provider-connector-separation.md)
- [Repository settings handoff](repo-settings-checklist.md) — the manual
  GitHub/PyPI steps a maintainer applies.
- Release process and versioning:
  [RELEASING.md](https://github.com/SoBatista/sobatista-ai/blob/main/RELEASING.md).
- Security model:
  [SECURITY.md](https://github.com/SoBatista/sobatista-ai/blob/main/SECURITY.md).
