"""Skill discovery and namespaced name resolution.

Skills come from exactly two places, and the registry never looks anywhere else:

* ``builtin:`` — the pack shipped inside the installed package.
* ``user:``    — ``~/.config/sobai/skills/``, populated by ``sobai skills install``.

Notably absent: the current working directory, the repository being worked in,
``.sobai/``, environment variables, and arbitrary paths. Running ``sobai`` inside
a checkout must never let that checkout supply a system prompt — see
``docs/adr/0007`` and ``THREAT_MODEL.md``.

Resolution refuses to guess. A short name that exists in both namespaces is an
error naming both candidates, never a silent preference: a user Skill must not
be able to shadow ``builtin:security-review`` by being installed under that name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sobai.core.errors import AmbiguousSkillError, SkillError, SkillNotFoundError

from .loader import builtin_names, load_builtin_skill, load_skill_directory
from .models import Namespace, Skill, SkillNameError, qualify, validate_skill_name


@dataclass(frozen=True, slots=True)
class BrokenSkill:
    """A Skill directory that exists but could not be loaded."""

    namespace: str
    name: str
    reason: str

    @property
    def qualified_name(self) -> str:
        return qualify(self.namespace, self.name)


@dataclass(slots=True)
class SkillRegistry:
    """The Skills available to this invocation, keyed by ``namespace:name``."""

    skills: dict[str, Skill] = field(default_factory=dict)
    #: Directories that look like Skills but failed validation. Surfaced by
    #: `sobai skills list` so a broken install is visible rather than absent.
    broken: list[BrokenSkill] = field(default_factory=list)

    # -- population --------------------------------------------------------
    def add(self, skill: Skill) -> None:
        self.skills[skill.qualified_name] = skill

    # -- lookup ------------------------------------------------------------
    def get(self, namespace: str, name: str) -> Skill | None:
        return self.skills.get(qualify(namespace, name))

    def candidates(self, name: str) -> list[Skill]:
        """Every Skill matching an unqualified short *name*, in namespace order."""
        found = [self.get(ns, name) for ns in Namespace.ALL]
        return [s for s in found if s is not None]

    def list(self) -> list[Skill]:
        """All Skills, built-ins first, then user Skills, each alphabetically."""
        order = {ns: i for i, ns in enumerate(Namespace.ALL)}
        return sorted(
            self.skills.values(),
            key=lambda s: (order.get(s.namespace, len(order)), s.name),
        )

    def resolve(self, reference: str) -> Skill:
        """Resolve ``name`` or ``namespace:name`` to exactly one Skill.

        Raises :class:`SkillNotFoundError` when nothing matches and
        :class:`AmbiguousSkillError` when a short name matches more than one
        namespace — never a silent choice between them.
        """
        ref = reference.strip()
        if not ref:
            raise SkillNotFoundError(
                "No skill name given.",
                hint="Run `sobai skills list` to see what is available.",
            )
        if ":" in ref:
            return self._resolve_qualified(ref)
        return self._resolve_short(ref)

    def _resolve_qualified(self, ref: str) -> Skill:
        namespace, _, name = ref.partition(":")
        if namespace not in Namespace.ALL:
            raise SkillError(
                f"Unknown skill namespace {namespace!r} in {ref!r}.",
                hint=f"Valid namespaces: {', '.join(Namespace.ALL)}.",
            )
        self._validate(name, ref)
        skill = self.get(namespace, name)
        if skill is None:
            raise SkillNotFoundError(
                f"No skill named {ref!r}.",
                hint=self._nearby_hint(name),
            )
        return skill

    def _resolve_short(self, name: str) -> Skill:
        self._validate(name, name)
        matches = self.candidates(name)
        if not matches:
            raise SkillNotFoundError(
                f"No skill named {name!r}.",
                hint=self._nearby_hint(name),
            )
        if len(matches) > 1:
            qualified = ", ".join(s.qualified_name for s in matches)
            raise AmbiguousSkillError(
                f"{name!r} is ambiguous: it matches {qualified}.",
                hint=f"Use the fully qualified name, e.g. `{matches[0].qualified_name}`.",
            )
        return matches[0]

    @staticmethod
    def _validate(name: str, reference: str) -> None:
        try:
            validate_skill_name(name)
        except SkillNameError as exc:
            raise SkillError(
                f"{reference!r} is not a valid skill reference: {exc}",
                hint="Skill names use lowercase letters, digits, and single hyphens.",
            ) from exc

    def _nearby_hint(self, name: str) -> str:
        near = sorted({s.name for s in self.skills.values() if _is_near(name, s.name)})
        if near:
            return f"Did you mean: {', '.join(near[:3])}? See `sobai skills list`."
        return "Run `sobai skills list` to see what is available."


def _is_near(a: str, b: str) -> bool:
    """Cheap similarity test used only to improve a not-found hint."""
    if a == b:
        return True
    if a in b or b in a:
        return True
    return len(set(a) & set(b)) >= max(len(set(a)), len(set(b))) - 1


def discover_skills(user_skills_dir: Path | None = None) -> SkillRegistry:
    """Build the registry from packaged built-ins plus the user's Skill directory.

    A Skill that fails validation is recorded in :attr:`SkillRegistry.broken`
    rather than aborting discovery, so one bad user Skill cannot make every
    other Skill unusable.
    """
    registry = SkillRegistry()
    for name in builtin_names():
        try:
            registry.add(load_builtin_skill(name))
        except SkillError as exc:  # pragma: no cover - a shipped skill is tested
            registry.broken.append(BrokenSkill(Namespace.BUILTIN, name, exc.message))
    if user_skills_dir is not None:
        _discover_user(registry, user_skills_dir)
    return registry


def _discover_user(registry: SkillRegistry, directory: Path) -> None:
    if not directory.is_dir():
        return
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        name = entry.name
        # Skip installer scratch space and hidden entries entirely.
        if name.startswith((".", "_")):
            continue
        try:
            registry.add(load_skill_directory(entry, namespace=Namespace.USER))
        except SkillError as exc:
            registry.broken.append(BrokenSkill(Namespace.USER, name, exc.message))
