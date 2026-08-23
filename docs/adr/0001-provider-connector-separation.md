# ADR-0001: Separate provider and connector abstractions

- Status: Accepted
- Date: 2026-08-23

## Context

The product must let any model (Claude, OpenAI, Ollama, CLI bridges) work with
any external system (YouTube, Notion, GitHub, …). A naive design couples a
connector to a specific model, producing an N×M explosion of bespoke scripts and
tight coupling.

## Decision

Define two independent abstractions:

- **Provider** (`providers.base.Provider`) — models that reason and request tool
  calls. One common interface: messages, system prompt, streaming, structured
  output, typed tools, tool-call loops, usage, cancellation, timeouts, retry
  classification, and model discovery where supported.
- **Connector** — external systems that fetch/modify data, exposed to models as
  typed **tools** (JSON Schema) via the shared tools layer.

Providers and connectors must never import each other. They meet only in `core/`
(the orchestrator and tool registry). Data classification and egress policy sit
between a connector's output and any cloud provider.

## Consequences

- Adding a provider or a connector is additive and local; neither touches the
  other.
- The same connector tools can later be exposed over MCP without change.
- Slightly more indirection than a monolithic script — worth it for testability
  and the security boundary (untrusted connector data is mediated by the core).
