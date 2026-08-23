"""Application context — the dependency-injection container.

Built once per CLI invocation from the global options, then threaded to command
handlers. Owns the config store, credential store, UI, database, and policy
engine, so command code never reaches for globals or constructs these directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sobai.auth import CredentialStore
from sobai.policies import PolicyEngine
from sobai.providers.registry import select_provider_model
from sobai.storage import Database
from sobai.ui import UI, OutputMode

from .config import ConfigStore
from .paths import Paths


@dataclass(slots=True)
class GlobalOptions:
    provider: str | None = None
    model: str | None = None
    profile: str | None = None
    local_only: bool = False
    dry_run: bool = False
    apply: bool = False
    json: bool = False
    quiet: bool = False
    no_color: bool = False


@dataclass(slots=True)
class AppContext:
    paths: Paths
    store: ConfigStore
    creds: CredentialStore
    ui: UI
    opts: GlobalOptions
    _db: Database | None = field(default=None, repr=False)
    _policy: PolicyEngine | None = field(default=None, repr=False)

    @classmethod
    def build(cls, opts: GlobalOptions) -> AppContext:
        paths = Paths.resolve()
        store = ConfigStore.load(paths)
        ui = UI(
            mode=OutputMode.JSON if opts.json else OutputMode.TEXT,
            quiet=opts.quiet,
            no_color=opts.no_color,
        )
        return cls(paths=paths, store=store, creds=CredentialStore(), ui=ui, opts=opts)

    @property
    def config(self) -> ConfigStore:
        return self.store

    @property
    def db(self) -> Database:
        if self._db is None:
            self.paths.ensure()
            self._db = Database(self.paths.state_db)
        return self._db

    @property
    def policy(self) -> PolicyEngine:
        if self._policy is None:
            override = True if self.opts.local_only else None
            self._policy = PolicyEngine(self.store.config.policy, local_only_override=override)
        return self._policy

    def selected_provider_model(self) -> tuple[str, str]:
        return select_provider_model(
            self.store.config,
            provider=self.opts.provider,
            model=self.opts.model,
            profile_name=self.opts.profile,
        )

    def save_config(self) -> None:
        self.store.save()

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
