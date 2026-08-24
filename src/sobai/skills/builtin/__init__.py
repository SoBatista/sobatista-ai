"""The built-in Skill pack, shipped inside the installed package.

Each subdirectory is one Skill: a ``skill.toml`` manifest and a ``prompt.md``.
They are packaged as application resources and read through
:mod:`importlib.resources`, so they load identically from a wheel, an sdist, and
a source checkout — no filesystem layout assumptions and no post-install step.

The prompts here are original work written for SoBatista AI. See
``docs/acknowledgements.md`` for the projects that influenced the idea.
"""
