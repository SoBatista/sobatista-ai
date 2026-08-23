# Terminal recordings & screenshots

We do **not** fabricate screenshots. This page lists the captures we'd like for
the README and docs, with exact commands and target filenames, so a maintainer
can record them from a real terminal.

## How to capture

Use [asciinema](https://asciinema.org/) for recordings, or a clean screenshot of
the terminal. Use a fresh, isolated config so nothing personal is shown:

```bash
export SOBAI_CONFIG_DIR=$(mktemp -d) SOBAI_DATA_DIR=$(mktemp -d) SOBAI_CACHE_DIR=$(mktemp -d)
```

Save recordings under `docs/assets/` with the filenames below and reference them
from `README.md`.

## Requested captures

| Filename | Command(s) to run | Notes |
|----------|-------------------|-------|
| `docs/assets/help.svg` | `sobai --help` | Top-level help |
| `docs/assets/doctor.svg` | `sobai doctor` | Show keyring + providers status |
| `docs/assets/ask-stream.cast` | `sobai -p ollama -m qwen14b ask "Explain a race condition"` | Streaming output |
| `docs/assets/providers.svg` | `sobai providers list` | Provider table |
| `docs/assets/local-only.svg` | `sobai --local-only -p anthropic -m … ask "x"` | Shows the hard-fail |

Before recording anything that would send data to a cloud provider, confirm the
prompt contains nothing sensitive.
