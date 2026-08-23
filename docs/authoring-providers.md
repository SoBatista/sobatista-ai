# Authoring a provider

A **provider** is a model backend that reasons and (optionally) requests tool
calls. Providers must never import connectors — the two abstractions meet only in
`core/`. See
[ADR-0001](adr/0001-provider-connector-separation.md) and the engineering rules
in [CLAUDE.md](https://github.com/SoBatista/sobatista-ai/blob/main/CLAUDE.md).

## The interface

Subclass `sobai.providers.base.Provider`:

```python
from collections.abc import AsyncIterator
from sobai.providers.base import Provider, ProviderHealth
from sobai.core.types import Completion, GenerateParams, ModelInfo, StreamEvent


class MyProvider(Provider):
    name = "myprovider"  # registry name
    is_local = False  # True only if it runs entirely on this machine

    async def generate(self, params: GenerateParams) -> Completion: ...
    def stream(self, params: GenerateParams) -> AsyncIterator[StreamEvent]: ...
    async def list_models(self) -> list[ModelInfo]: ...
    async def health(self) -> ProviderHealth: ...
    async def aclose(self) -> None: ...  # optional; close HTTP clients
```

- `generate` returns a full `Completion` (with `Usage`).
- `stream` yields `StreamEvent`s and ends with a `DONE` event carrying the final
  `Completion` — reuse the shared streaming types so the orchestrator and UI work
  unchanged.
- `list_models` powers discovery — **do not hard-code vendor model IDs**; models
  are discovered or user-configured.

## Registering

Wire the provider into `sobai/providers/registry.py`:

- Add its name to `ALL_PROVIDERS` (and to `CLI_BRIDGE_PROVIDERS` if it shells out
  to an installed CLI).
- Construct it in `build_provider(...)`.
- Add any aliases in `canonical_provider(...)` and its billing classification in
  `billing_mode(...)` (`metered-api`, `subscription`, or `local`).

## Rules to follow

- **Credentials** load from `sobai.auth.CredentialStore` via `cred_key(...)` and
  are registered with `sobai.core.redaction` so they are scrubbed everywhere.
  Never read a key from env/TOML/argv; never log or raise it.
- **HTTP** uses raw `httpx` with an explicit timeout on every call, and bounded,
  classified retries via `retry_async` / `RetryClass` (see ADR-0002). Never use a
  shell for subprocess bridges — use `asyncio.create_subprocess_exec` with argv
  arrays, and never place the prompt in argv.
- **Local-only:** set `is_local` correctly. Only truly local providers may run
  under `--local-only`; the policy engine fails closed before egress otherwise.
- **No silent fallback:** raise a `SobaiError` on failure; never switch providers
  automatically.
- **Untrusted output:** model text is rendered through `safeterm.sanitize`; do not
  bypass the UI helpers.

## Testing

- Mock HTTP with `respx`; tests must pass with **no live API and no real
  credentials** (the `live` marker is opt-in).
- Cover streaming, tool-call round-trips, timeouts/retries, cancellation, and
  usage accounting. Add focused tests, then run the full quality suite.
