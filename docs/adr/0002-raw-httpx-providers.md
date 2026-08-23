# ADR-0002: Raw HTTPX for provider adapters

- Status: Accepted
- Date: 2026-08-23

## Context

Each cloud provider ships an official SDK (`anthropic`, `openai`). We could build
adapters on those SDKs, on raw HTTPX, or a hybrid. The product is a
provider-neutral orchestration layer whose value is a *uniform* interface and a
tight, auditable dependency surface.

## Decision

Implement all provider adapters over a single shared async **HTTPX** base
(`providers/http.py`), verifying each request/response shape against official
documentation. Ollama has no SDK and is HTTP anyway; using HTTPX for the cloud
providers as well keeps one client model, one retry/backoff/timeout policy, and
one error-wrapping path across every provider.

## Consequences

- Uniform behavior (streaming, retries, timeouts, redaction) across providers;
  the neutral `core.types` are the only currency.
- Minimal, consistent dependency surface (one HTTP client), easier supply-chain
  review.
- We own the wire details and must track API changes ourselves. Mitigated by
  contract tests using recorded/mocked responses (`respx`) and by keeping request
  building in one place per provider.
- Trade-off accepted vs. the convenience of vendor SDKs. Revisit if a provider's
  wire protocol becomes impractical to track by hand.
