"""``sobai skills`` — list, inspect, validate, install, and run Skills.

``sobai run NAME`` is registered as an alias of ``sobai skills run`` and calls
the *same* function object. There is deliberately no second execution path: any
policy, limit, or audit change made here applies to both spellings.

The order of operations in a run is itself a security control, and it does not
change:

1. resolve the Skill (refusing ambiguity),
2. validate variables and render the prompt,
3. collect and bound the input,
4. resolve provider and model,
5. **enforce ``--local-only``**,
6. decide egress, and stop here for ``--dry-run``,
7. obtain consent,
8. only then construct a provider and send anything.

Everything that can fail without touching the network fails before step 8.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

import typer

from sobai.core.classification import DataClass
from sobai.core.context import AppContext
from sobai.core.errors import ExitCode, SkillError, SobaiError
from sobai.providers.registry import billing_mode, build_provider
from sobai.skills import views
from sobai.skills.inputs import SkillInput, collect_input
from sobai.skills.installer import install_skill, validate_source
from sobai.skills.loader import BUILTIN_PACKAGE, builtin_root
from sobai.skills.models import Skill
from sobai.skills.plan import (
    DataClassSource,
    SkillRunPlan,
    assess_egress,
    build_plan,
    resolve_skill_model,
)
from sobai.skills.registry import SkillRegistry, discover_skills
from sobai.skills.renderer import RenderedPrompt, render_skill
from sobai.skills.runner import (
    assert_tools_available,
    audit_detail,
    build_params,
    build_result,
    execute_skill,
    run_summary,
)
from sobai.ui import OutputMode
from sobai.ui.console import render_untrusted

from .common import cost_accounting, enforce_egress, get_ctx, recorded_model, run_async

skills_app = typer.Typer(
    help="Reusable, inspectable task recipes.",
    no_args_is_help=True,
)

#: Tool names available to a Skill run. Empty by design: Skills are prompt/data
#: only and cannot enable a connector. A Skill declaring required tools is
#: refused rather than run without them.
AVAILABLE_SKILL_TOOLS: frozenset[str] = frozenset()

#: Locations that are never searched for Skills, shown by `sobai skills paths`.
NEVER_SEARCHED = [
    "the current working directory",
    "the repository you are running inside",
    "./.sobai/",
    "paths named by environment variables",
    "any remote or network location",
]


def _registry(app: AppContext) -> SkillRegistry:
    """Discover Skills from packaged built-ins and the user's Skill directory only."""
    return discover_skills(app.paths.skills_dir)


def _parse_variables(pairs: list[str] | None) -> dict[str, str]:
    """Parse repeated ``--var name=value`` options into a mapping.

    Values are taken literally. They are never passed through a shell, expanded,
    or evaluated — ``--var x='$(id)'`` supplies those nine characters as text.
    """
    parsed: dict[str, str] = {}
    for raw in pairs or []:
        name, separator, value = raw.partition("=")
        name = name.strip()
        if not separator or not name:
            raise typer.BadParameter(
                f"--var expects name=value, got {raw!r}.",
                param_hint="--var",
            )
        if name in parsed:
            raise typer.BadParameter(
                f"--var {name} was given more than once.",
                param_hint="--var",
            )
        parsed[name] = value
    return parsed


# -- list ------------------------------------------------------------------
def skills_list(ctx: typer.Context) -> None:
    """List available Skills, built-ins first."""
    app = get_ctx(ctx)
    registry = _registry(app)
    payload = views.listing(registry)
    if app.ui.json_mode:
        app.ui.print_json(payload.to_json())
        return
    if not payload.skills:
        app.ui.print("[muted]No skills available.[/muted]")
    else:
        app.ui.table(
            "Skills",
            ["skill", "version", "description", "license"],
            [
                [
                    render_untrusted(entry.qualified_name),
                    render_untrusted(entry.version),
                    render_untrusted(entry.description),
                    render_untrusted(entry.license),
                ]
                for entry in payload.skills
            ],
        )
        app.ui.print(
            '[muted]Run one with[/muted] sobai run NAME "INPUT" '
            "[muted]· inspect with[/muted] sobai skills show NAME"
        )
    for broken in payload.broken:
        app.ui.warn(
            f"Skill {render_untrusted(broken.qualified_name)} could not be loaded: "
            f"{render_untrusted(broken.reason)}"
        )


# -- show ------------------------------------------------------------------
def skills_show(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill name, optionally namespaced.")],
) -> None:
    """Show a Skill's manifest, prompt, provenance, and model resolution."""
    app = get_ctx(ctx)
    skill = _registry(app).resolve(name)
    resolution = None
    error: str | None = None
    try:
        resolution = resolve_skill_model(
            app.config.config,
            skill,
            provider=app.opts.provider,
            model=app.opts.model,
            profile_name=app.opts.profile,
        )
    except SobaiError as exc:
        error = exc.message
    payload = views.detail(skill, model=resolution, model_resolution_error=error)
    if app.ui.json_mode:
        app.ui.print_json(payload.to_json())
        return
    _render_detail_text(app, payload)


def _render_detail_text(app: AppContext, payload: views.SkillDetail) -> None:
    ui = app.ui
    ui.print(f"[heading]{render_untrusted(payload.qualified_name)}[/heading] {payload.version}")
    ui.print(f"  {render_untrusted(payload.description)}\n")
    rows = [
        ("namespace", payload.namespace),
        ("digest", payload.digest),
        ("author", payload.author or "-"),
        ("license", payload.license),
        ("tags", ", ".join(payload.tags) or "-"),
        ("input", payload.input.get("description") or "-"),
        ("output", f"{payload.output.get('format')}"),
        ("data class", str(payload.recommended_data_class)),
        ("requires tools", ", ".join(payload.required_tools) or "none"),
        ("source", str(payload.provenance.get("source", "-"))),
    ]
    for label, value in rows:
        ui.print(f"  [muted]{label:<15}[/muted]{render_untrusted(str(value))}")
    if payload.model is not None:
        why = render_untrusted(f"{payload.model.source}: {payload.model.explanation}")
        ui.print(
            f"  [muted]{'model':<15}[/muted]"
            f"{render_untrusted(payload.model.provider)}/"
            f"{render_untrusted(recorded_model(payload.model.model))} "
            f"[muted]({why})[/muted]"
        )
    else:
        ui.print(f"  [muted]{'model':<15}[/muted]not resolvable — {payload.model_resolution_error}")
    if payload.variables:
        ui.print("\n[heading]Variables[/heading]")
        for var in payload.variables:
            need = "required" if var.required else f"default: {var.default!r}"
            ui.print(
                f"  --var {render_untrusted(var.name)}=<{var.type}>  "
                f"[muted]{need} · {render_untrusted(var.description)}[/muted]"
            )
    ui.print("\n[heading]Prompt[/heading]")
    ui.print_untrusted(payload.prompt.strip())


# -- paths -----------------------------------------------------------------
def skills_paths(ctx: typer.Context) -> None:
    """Show where Skills are loaded from — and what is deliberately never searched."""
    app = get_ctx(ctx)
    skills_dir = app.paths.skills_dir
    payload = views.SkillPaths(
        user_skills_dir=str(skills_dir),
        user_skills_dir_exists=skills_dir.is_dir(),
        builtin_source=f"{BUILTIN_PACKAGE} ({builtin_root()})",
        never_searched=list(NEVER_SEARCHED),
    )
    if app.ui.json_mode:
        app.ui.print_json(payload.to_json())
        return
    app.ui.print(f"[heading]User skills[/heading]  {payload.user_skills_dir}")
    app.ui.print(f"[muted]exists:[/muted] {'yes' if payload.user_skills_dir_exists else 'no'}")
    app.ui.print(f"[heading]Built-in skills[/heading]  {payload.builtin_source}")
    app.ui.print("\n[heading]Never searched[/heading]")
    for location in payload.never_searched:
        app.ui.print(f"  · {location}")
    app.ui.print(
        "\n[muted]A repository you run `sobai` inside can never supply a system "
        "prompt. Install skills explicitly with `sobai skills install PATH`.[/muted]"
    )


# -- validate --------------------------------------------------------------
def skills_validate(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Directory containing skill.toml and prompt.md.")],
) -> None:
    """Validate a local Skill directory without installing it."""
    app = get_ctx(ctx)
    try:
        skill = validate_source(path)
    except SkillError as exc:
        if not app.ui.json_mode:
            raise
        # In JSON mode the failure *is* the document: emit the typed report and
        # exit with the skill code. Re-raising would make the top-level handler
        # print a second JSON document to the same stream.
        app.ui.print_json(
            views.ValidationReport(
                valid=False,
                path=str(path),
                error=exc.message,
                hint=exc.hint,
            ).to_json()
        )
        raise typer.Exit(int(ExitCode.SKILL)) from exc
    payload = views.ValidationReport(
        valid=True,
        path=str(path),
        qualified_name=skill.qualified_name,
        name=skill.name,
        version=skill.version,
        digest=skill.digest,
        license=skill.manifest.skill.license,
        variables=[v.name for v in skill.manifest.variables],
    )
    if app.ui.json_mode:
        app.ui.print_json(payload.to_json())
        return
    app.ui.success(f"{skill.name} {skill.version} is a valid skill.")
    app.ui.print(f"  [muted]digest[/muted]   {skill.digest}")
    app.ui.print(f"  [muted]license[/muted]  {render_untrusted(skill.manifest.skill.license)}")
    app.ui.print(f"  [muted]install[/muted]  sobai skills install {path}")


# -- install ---------------------------------------------------------------
def skills_install(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Local directory to install. Never a URL.")],
    force: Annotated[
        bool, typer.Option("--force", help="Replace an existing skill of the same name.")
    ] = False,
) -> None:
    """Install a validated local Skill into your user Skill directory."""
    app = get_ctx(ctx)
    result = install_skill(path, app.paths.skills_dir, force=force)
    skill = result.skill
    payload = views.InstallReport(
        action=result.action,
        changed=result.changed,
        qualified_name=skill.qualified_name,
        name=skill.name,
        version=skill.version,
        digest=skill.digest,
        license=skill.manifest.skill.license,
        destination=str(result.destination),
    )
    if app.ui.json_mode:
        app.ui.print_json(payload.to_json())
        return
    if result.action == "unchanged":
        app.ui.info(f"{skill.qualified_name} {skill.version} is already installed (identical).")
    else:
        app.ui.success(f"{result.action} {skill.qualified_name} {skill.version}")
    app.ui.print(f"  [muted]digest[/muted]  {skill.digest}")
    app.ui.print(f"  [muted]path[/muted]    {result.destination}")
    app.ui.print(f'  [muted]run[/muted]     sobai run {skill.qualified_name} "..."')


# -- run -------------------------------------------------------------------
def skills_run(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill name, optionally namespaced.")],
    text: Annotated[
        str | None,
        typer.Argument(help="Input text. Omit to use --file or piped stdin."),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Read input from a UTF-8 text file."),
    ] = None,
    var: Annotated[
        list[str] | None,
        typer.Option("--var", help="Set a declared variable: --var name=value (repeatable)."),
    ] = None,
    data_class: Annotated[
        DataClass | None,
        typer.Option("--data-class", help="Classify the input for the egress policy."),
    ] = None,
    max_tokens: Annotated[int, typer.Option("--max-tokens", help="Maximum output tokens.")] = 4096,
    temperature: Annotated[
        float | None, typer.Option("--temperature", help="Sampling temperature.")
    ] = None,
    no_stream: Annotated[
        bool, typer.Option("--no-stream", help="Disable streaming output.")
    ] = False,
) -> None:
    """Run a Skill over explicitly supplied input.

    Examples:

      sobai run summarize "Long text to condense"

      sobai run summarize --file article.md

      cat article.md | sobai run summarize

      sobai run translate "Hello" --var language=pt-PT

      sobai --dry-run run security-review --file diff.patch
    """
    app = get_ctx(ctx)
    skill = _registry(app).resolve(name)
    variables = _parse_variables(var)

    # Tools first: refusing a skill we cannot honour costs nothing.
    assert_tools_available(skill, AVAILABLE_SKILL_TOOLS)

    data = collect_input(skill.manifest.input, positional=text, file=file)
    # Rendering validates every variable and the template. This must happen
    # before any provider work so a typo never reaches the network.
    rendered = render_skill(skill, input_text=data.text, variables=variables)

    effective_class = data_class or skill.manifest.policy.recommended_data_class
    class_source: DataClassSource = "flag" if data_class is not None else "skill-recommendation"

    resolution = resolve_skill_model(
        app.config.config,
        skill,
        provider=app.opts.provider,
        model=app.opts.model,
        profile_name=app.opts.profile,
    )
    # --local-only fails closed here: before a provider object exists, before a
    # credential is read, and before a single byte is prepared for the wire.
    app.policy.assert_provider_permitted(resolution.provider)

    decision = app.policy.decide_egress(resolution.provider, effective_class, connector=None)
    egress = assess_egress(app.policy, decision, resolution.provider)

    pconf = app.config.config.providers.get(resolution.provider)
    timeout_s = pconf.timeout_s if pconf else 120.0
    streaming = not no_stream and app.ui.mode is OutputMode.TEXT

    if app.opts.dry_run:
        plan = build_plan(
            skill,
            data,
            data_class=effective_class,
            data_class_source=class_source,
            resolution=resolution,
            egress=egress,
            variables=rendered.variables,
            max_output_tokens=max_tokens,
            timeout_s=timeout_s,
            max_tool_rounds=app.policy.max_tool_rounds,
            streaming=streaming,
        )
        _emit_plan(app, plan)
        return

    enforce_egress(
        app,
        decision,
        subject=f"skill '{skill.qualified_name}'",
        detail=_egress_detail(skill, data, resolution.provider, resolution.model),
        consent_hint=(
            "Re-run in an interactive terminal, use a local provider (`-p ollama`), "
            "or set an explicit policy.egress entry for "
            f"'{effective_class}' in config.toml."
        ),
    )

    _execute(
        app,
        skill,
        rendered,
        data,
        resolution_provider=resolution.provider,
        model_id=resolution.model,
        data_class=effective_class,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_s=timeout_s,
        streaming=streaming,
    )


def _egress_detail(skill: Skill, data: SkillInput, provider: str, model: str) -> str:
    return (
        f"skill {skill.reference} · input {data.describe()} · "
        f"destination {provider}/{recorded_model(model)}"
    )


def _execute(
    app: AppContext,
    skill: Skill,
    rendered: RenderedPrompt,
    data: SkillInput,
    *,
    resolution_provider: str,
    model_id: str,
    data_class: DataClass,
    max_tokens: int,
    temperature: float | None,
    timeout_s: float,
    streaming: bool,
) -> None:
    provider = build_provider(resolution_provider, app.config.config, app.creds)
    params = build_params(
        skill,
        rendered,
        model=model_id,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        temperature=temperature,
    )
    run_id = uuid.uuid4().hex
    app.db.start_run(
        run_id,
        command="skills run",
        provider=resolution_provider,
        model=recorded_model(model_id),
        profile=app.opts.profile or app.config.config.active_profile,
        local_only=app.policy.local_only,
        auth_mode=billing_mode(resolution_provider),
        # Identity only. The input is frequently the sensitive part of a skill
        # run, so it is never recorded here.
        summary=run_summary(skill),
    )
    app.db.record_audit(
        "skill_run",
        run_id=run_id,
        provider=resolution_provider,
        data_class=data_class,
        detail=audit_detail(skill, data),
    )

    async def _go() -> None:
        streamed = False

        def _on_text(chunk: str) -> None:
            nonlocal streamed
            streamed = True
            app.ui.stream_write(chunk)

        execution = await execute_skill(
            provider,
            params,
            db=app.db,
            run_id=run_id,
            stream=streaming,
            on_text=_on_text if streaming else None,
        )
        if streamed:
            app.ui.stream_end()
        mode, cost_usd, cost_kind = cost_accounting(resolution_provider, execution.usage)
        app.db.finish_run(
            run_id,
            status="ok",
            exit_code=int(ExitCode.OK),
            input_tokens=execution.usage.input_tokens,
            output_tokens=execution.usage.output_tokens,
            cached_input_tokens=execution.usage.cached_input_tokens,
            reasoning_tokens=execution.usage.reasoning_tokens,
            cost_usd=cost_usd,
            cost_kind=cost_kind,
            duration_ms=execution.duration_ms,
            tool_rounds=execution.tool_rounds,
        )
        result = build_result(
            skill,
            execution,
            data,
            run_id=run_id,
            provider=resolution_provider,
            model=recorded_model(model_id),
            billing_mode=mode,
            cost_kind=cost_kind,
            data_class=data_class,
        )
        if app.ui.json_mode:
            app.ui.print_json(result.to_json())
        elif not streamed and execution.text:
            # Either streaming was off, or a one-shot provider returned the whole
            # answer without emitting deltas. Both must still show the output.
            app.ui.print_untrusted(execution.text)

    try:
        run_async(_go())
    except SobaiError:
        app.db.finish_run(run_id, status="error", exit_code=1)
        raise


# -- dry-run rendering -----------------------------------------------------
def _emit_plan(app: AppContext, plan: SkillRunPlan) -> None:
    if app.ui.json_mode:
        app.ui.print_json(plan.to_json())
        return
    ui = app.ui
    ui.print(
        f"[heading]Plan[/heading] {render_untrusted(plan.skill.qualified_name)} "
        f"{plan.skill.version} [muted](nothing was sent)[/muted]"
    )
    rows: list[tuple[str, str]] = [
        ("digest", plan.skill.digest),
        ("namespace", plan.skill.namespace),
        ("license", plan.skill.license),
        ("input", f"{plan.input.source} · {plan.input.bytes} bytes · {plan.input.chars} chars"),
        ("input digest", plan.input.digest),
        ("data class", f"{plan.data_class} ({plan.data_class_source})"),
        ("provider", plan.model.provider),
        ("model", recorded_model(plan.model.model)),
        ("model source", f"{plan.model.source} — {plan.model.explanation}"),
        (
            "leaves machine",
            "yes" if plan.egress.data_leaves_machine else "no (local provider)",
        ),
        ("egress", f"{plan.egress.decision} — {plan.egress.reason}"),
        ("local-only", "on" if plan.egress.local_only else "off"),
        ("requires tools", ", ".join(plan.required_tools) or "none"),
        ("output", plan.output.format + (" + schema" if plan.output.has_schema else "")),
        (
            "limits",
            f"input ≤ {plan.limits.max_input_bytes}B / {plan.limits.max_input_chars} chars · "
            f"output ≤ {plan.limits.max_output_tokens} tokens · "
            f"timeout {plan.limits.timeout_s:g}s · tool rounds ≤ {plan.limits.max_tool_rounds}",
        ),
        (
            "shape",
            f"{plan.execution.provider_calls} provider call, "
            f"{plan.execution.tools_available} tools, "
            f"streaming {'on' if plan.execution.streaming else 'off'}, "
            f"writes {'on' if plan.execution.writes_enabled else 'off'}",
        ),
    ]
    for label, value in rows:
        ui.print(f"  [muted]{label:<15}[/muted]{render_untrusted(str(value))}")
    if plan.variables:
        ui.print(
            "  [muted]variables      [/muted]"
            + render_untrusted(", ".join(f"{k}={v}" for k, v in plan.variables.items()))
        )
    ui.print("\n[muted]Input content is never printed or transmitted by --dry-run.[/muted]")


skills_app.command("list")(skills_list)
skills_app.command("show")(skills_show)
skills_app.command("paths")(skills_paths)
skills_app.command("validate")(skills_validate)
skills_app.command("install")(skills_install)
skills_app.command("run")(skills_run)
