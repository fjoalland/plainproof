"""The ``plainproof`` command.

    plainproof run e2e/ --model anthropic:claude-sonnet-5-5 --url https://staging.example.com
    plainproof replay e2e/                       # without any model, from the recordings
    plainproof run "Open example.com and check that the title says Example Domain" -m ollama:qwen2.5vl:7b
    plainproof history history/ --pin 2026-10-12_0930
    plainproof init e2e/                         # a scenario folder to start from
    plainproof providers                         # supported models and API keys

Exit codes: 0 when every scenario conforms, 1 when one does not, 2 for a setup problem.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__
from .agent.runner import Agent
from .browser.playwright import BrowserLauncher
from .config import Settings, find_config, load_config_file, resolve_settings
from .console import ConsoleReporter
from .errors import ConfigError
from .history import META_FILE, build, campaign_folder, compress, git_info, save_meta
from .history import pin as pin_campaign
from .i18n import get_language, resolve_language, set_language, t
from .llm.pricing import price_for
from .llm.registry import create_client, provider_statuses
from .replay.replayer import REPLAY_MODEL, Replayer
from .replay.storage import load_recording
from .report.paths import display_path
from .report.summary import SUMMARY_FILE
from .results import SuiteResult
from .scenario import Scenario, find_contexts, load_scenarios
from .suite import Runner, run_suite

app = typer.Typer(
    name="plainproof",
    help="Browser tests written in plain language, run by the LLM of your choice, with every verdict proven on the page.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)


def make_launcher(settings: Settings) -> BrowserLauncher:
    """One browser for the whole suite (replaced by a fake one in plainproof's own tests)."""
    return BrowserLauncher(
        browser_name=settings.browser,
        headless=settings.headless,
        slow_mo=settings.slow_mo,
        viewport=settings.viewport,
        locale=settings.locale,
        record_video=settings.video,
    )


def parse_llm_options(items: Sequence[str]) -> dict[str, Any]:
    """``KEY=VALUE`` pairs (VALUE read as JSON when it is JSON; dotted keys nest) for the model requests."""
    options: dict[str, Any] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not sep or not key.strip():
            raise ConfigError(t("cli.bad_llm_option", value=item))
        try:
            value: Any = json.loads(raw)
        except ValueError:
            value = raw
        *parents, last = key.strip().split(".")
        node = options
        for parent in parents:
            node = node.setdefault(parent, {})
        node[last] = value
    return options


# -- shared plumbing ------------------------------------------------------------------------------
def _console() -> Console:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")  # a legacy console must never crash on "✓"
    return Console(soft_wrap=True)


def _fail(console: Console, error: Exception) -> NoReturn:
    console.print(Text(str(error), style="red"))
    raise typer.Exit(2)


def _settings(
    target: str, config: Path | None, cli_values: dict[str, Any], env: dict[str, str], console: Console
) -> Settings:
    if config is not None and not config.is_file():
        raise ConfigError(f"--config: {config} not found")
    path = Path(target)
    start = path if path.is_dir() else path.parent if path.is_file() else Path.cwd()
    config_path = config or find_config(start)
    file_values = load_config_file(config_path) if config_path else {}
    if config_path:
        console.print(Text(t("cli.config", path=display_path(config_path)), style="dim"))
    return resolve_settings(cli_values, env, file_values)


def _out_dir(settings: Settings, campaign: Path | None, started: datetime, update: bool) -> Path:
    if update:
        if settings.out is None or not (settings.out / SUMMARY_FILE).is_file():
            raise ConfigError(t("cli.update_needs_out"))
        return settings.out
    if settings.out is not None:
        return settings.out
    if campaign is not None:
        return campaign_folder(campaign, started)
    return Path("runs") / started.strftime("%Y%m%d-%H%M%S")


def _contexts(console: Console, scenarios: Sequence[Scenario], settings: Settings) -> None:
    paths = (
        [settings.context]
        if settings.context
        else sorted({c for s in scenarios if s.path for c in find_contexts(s.path.parent)})
    )
    for path in paths:
        if path is not None:
            console.print(Text(t("log.context", path=display_path(path)), style="dim"))


def _execute(
    console: Console,
    settings: Settings,
    scenarios: Sequence[Scenario],
    out_dir: Path,
    make_runner: Callable[[Scenario], Runner],
    reporter: ConsoleReporter,
    *,
    update: bool,
    record: bool,
) -> SuiteResult:
    try:
        with make_launcher(settings) as launcher:
            suite = run_suite(
                scenarios,
                out_dir,
                make_runner,
                launcher.session,
                start_url=settings.url,
                update=update,
                record=record,
                label=settings.label or "",
                listener=reporter,
            )
    except ConfigError as err:
        _fail(console, err)
    reporter.summary(suite, out_dir)
    return suite


def _close_campaign(
    console: Console,
    root: Path,
    out_dir: Path,
    started: datetime,
    settings: Settings,
    model: str,
    mode: str,
    repo: Path | None,
    note: str,
    pin: bool,
) -> None:
    """Compress the run, describe what was tested, rebuild the history page."""
    sizes = compress(out_dir)
    if sizes:
        console.print(
            Text(t("cli.compressed", before=f"{sizes[0] / 1e6:.1f}", after=f"{sizes[1] / 1e6:.1f}"), style="dim")
        )
    first_time = not (out_dir / META_FILE).exists()
    save_meta(
        out_dir,
        id=out_dir.name,
        date=started.isoformat(timespec="seconds") if first_time else None,
        label=settings.label or "—",
        model=model,
        mode=mode,
        url=settings.url,
        note=note or None,
        pinned=True if pin else None,
        language=get_language(),
        **git_info(repo),
    )
    for line in build(root, settings.budget_mb):
        console.print(Text(line, style="dim"))
    console.print(Text(t("cli.history", index=display_path(root / "index.html"))))


# -- options shared by run and replay --------------------------------------------------------------
Target = Annotated[str, typer.Argument(help="A folder of .txt scenarios, one .txt file, or the text of a scenario.")]
Url = Annotated[str | None, typer.Option("--url", help="Page opened before each scenario.")]
Out = Annotated[Path | None, typer.Option("--out", "-o", help="Report folder (default: runs/<date-time>).")]
Update = Annotated[bool, typer.Option("--update", help="Rerun the given scenarios inside the existing report --out.")]
Headed = Annotated[
    bool | None, typer.Option("--headed/--headless", help="Show the browser window (default: headless).")
]
BrowserName = Annotated[
    str | None, typer.Option("--browser", help="chromium (default), chrome, msedge, firefox or webkit.")
]
Viewport = Annotated[str | None, typer.Option("--viewport", help="Window size, e.g. 1280x800.")]
Locale = Annotated[
    str | None, typer.Option("--locale", help="Browser locale, e.g. fr-FR (also sets the report language).")
]
Language = Annotated[
    str | None, typer.Option("--language", "-l", help="Language of reports and explanations: en or fr.")
]
Video = Annotated[bool | None, typer.Option("--video/--no-video", help="Record a video of each scenario.")]
SlowMo = Annotated[int | None, typer.Option("--slow-mo", help="Slow every browser action down (ms), to watch.")]
Label = Annotated[str | None, typer.Option("--label", help="What is tested (environment, version), shown in reports.")]
ConfigFile = Annotated[
    Path | None, typer.Option("--config", help="Settings file (default: plainproof.toml next to the scenarios).")
]
Campaign = Annotated[
    Path | None, typer.Option("--campaign", help="Keep this run in a history folder (see `plainproof history`).")
]
Repo = Annotated[
    Path | None,
    typer.Option("--repo", help="With --campaign: the tested application's repository (branch, commit, version)."),
]
Note = Annotated[str, typer.Option("--note", help="With --campaign: a remark kept with the campaign.")]
Pin = Annotated[bool, typer.Option("--pin", help="With --campaign: never delete this campaign from the history.")]
Budget = Annotated[
    float | None, typer.Option("--budget-mb", help="With --campaign: maximum size of the history folder.")
]
Context = Annotated[
    Path | None,
    typer.Option("--context", help="Project context file (default: the context.md files next to the scenarios)."),
]


def _browser_values(
    url: str | None,
    out: Path | None,
    headed: bool | None,
    browser: str | None,
    viewport: str | None,
    locale: str | None,
    language: str | None,
    video: bool | None,
    slow_mo: int | None,
    label: str | None,
    context: Path | None,
    budget_mb: float | None,
) -> dict[str, Any]:
    return {
        "url": url,
        "out": out,
        "headless": None if headed is None else not headed,
        "browser": browser,
        "viewport": viewport,
        "locale": locale,
        "language": language,
        "video": video,
        "slow_mo": slow_mo,
        "label": label,
        "context": context,
        "budget_mb": budget_mb,
    }


# -- commands ---------------------------------------------------------------------------------------
def _version(value: bool) -> None:
    if value:
        typer.echo(f"plainproof {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version.")
    ] = False,
) -> None:
    """Browser tests written in plain language, run by the LLM of your choice, with every verdict proven on the page."""


@app.command()
def run(
    target: Target,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="provider:model, e.g. anthropic:claude-sonnet-5-5, openai:gpt-6.1-sol, gemini, mistral, ollama:qwen2.5vl:7b (see `plainproof providers`).",
        ),
    ] = None,
    url: Url = None,
    out: Out = None,
    update: Update = False,
    headed: Headed = None,
    browser: BrowserName = None,
    viewport: Viewport = None,
    locale: Locale = None,
    language: Language = None,
    max_steps: Annotated[
        int | None, typer.Option("--max-steps", help="Maximum number of actions per scenario (default 30).")
    ] = None,
    interpret: Annotated[
        bool | None,
        typer.Option(
            "--interpret/--no-interpret", help="Turn the business wording into precise steps first (one call)."
        ),
    ] = None,
    diagnose: Annotated[
        bool | None, typer.Option("--diagnose/--no-diagnose", help="Explain each failure in plain language (one call).")
    ] = None,
    video: Video = None,
    record: Annotated[
        bool | None, typer.Option("--record/--no-record", help="Write a replayable recording of each passing scenario.")
    ] = None,
    vision: Annotated[
        bool | None,
        typer.Option("--vision/--no-vision", help="Send screenshots to the model (--no-vision for text-only models)."),
    ] = None,
    temperature: Annotated[
        str | None,
        typer.Option(
            "--temperature", help="Sampling temperature (default 0.1; 'none' to leave the provider's default)."
        ),
    ] = None,
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="Address of the model server (local or OpenAI-compatible servers).")
    ] = None,
    llm_option: Annotated[
        list[str] | None, typer.Option("--llm-option", help="KEY=VALUE added to every model request (repeatable).")
    ] = None,
    slow_mo: SlowMo = None,
    context: Context = None,
    label: Label = None,
    config: ConfigFile = None,
    campaign: Campaign = None,
    repo: Repo = None,
    note: Note = "",
    pin: Pin = False,
    budget_mb: Budget = None,
) -> None:
    """Run scenarios with a model. A passing scenario leaves a recording, replayable without a model."""
    console = _console()
    started = datetime.now()
    try:
        load_dotenv(find_dotenv(usecwd=True))
        env = dict(os.environ)
        values = _browser_values(
            url, out, headed, browser, viewport, locale, language, video, slow_mo, label, context, budget_mb
        )
        values.update(
            model=model,
            max_steps=max_steps,
            interpret=interpret,
            diagnose=diagnose,
            record=record,
            vision=vision,
            temperature=temperature,
            base_url=base_url,
        )
        settings = _settings(target, config, values, env, console)
        set_language(resolve_language(settings.language, None, settings.locale))
        scenarios = load_scenarios(target, env, context_path=settings.context)
        llm = create_client(
            settings.model,
            env=env,
            base_url=settings.base_url,
            temperature=settings.temperature,
            vision=settings.vision,
            options={**settings.llm_options, **parse_llm_options(llm_option or [])},
        )
        price = price_for(llm.name, settings.pricing, env)
        out_dir = _out_dir(settings, campaign, started, update)
    except ConfigError as err:
        _fail(console, err)
    window = t("cli.window_headless") if settings.headless else t("cli.window_headed")
    console.print(
        Text(
            t(
                "cli.intro",
                n=len(scenarios),
                model=llm.name,
                browser=settings.browser,
                window=window,
                language=get_language(),
                out=display_path(out_dir),
            )
        )
    )
    _contexts(console, scenarios, settings)
    reporter = ConsoleReporter(console)

    def make_runner(scenario: Scenario) -> Runner:
        return Agent(
            llm,
            max_steps=settings.max_steps,
            interpret=settings.interpret,
            diagnose=settings.diagnose,
            price=price,
            listener=reporter,
        )

    suite = _execute(
        console, settings, scenarios, out_dir, make_runner, reporter, update=update, record=settings.record
    )
    if campaign is not None:
        _close_campaign(console, campaign, out_dir, started, settings, llm.name, "model", repo, note, pin)
    raise typer.Exit(0 if suite.ok else 1)


@app.command()
def replay(
    target: Target,
    url: Url = None,
    out: Out = None,
    update: Update = False,
    headed: Headed = None,
    browser: BrowserName = None,
    viewport: Viewport = None,
    locale: Locale = None,
    language: Language = None,
    video: Video = None,
    slow_mo: SlowMo = None,
    context: Context = None,
    label: Label = None,
    config: ConfigFile = None,
    campaign: Campaign = None,
    repo: Repo = None,
    note: Note = "",
    pin: Pin = False,
    budget_mb: Budget = None,
) -> None:
    """Replay the recordings of the scenarios, without any model: no API key, no cost."""
    console = _console()
    started = datetime.now()
    try:
        load_dotenv(find_dotenv(usecwd=True))
        env = dict(os.environ)
        values = _browser_values(
            url, out, headed, browser, viewport, locale, language, video, slow_mo, label, context, budget_mb
        )
        settings = _settings(target, config, values, env, console)
        set_language(resolve_language(settings.language, None, settings.locale))
        scenarios = load_scenarios(target, env, context_path=settings.context)
        out_dir = _out_dir(settings, campaign, started, update)
    except ConfigError as err:
        _fail(console, err)
    console.print(Text(t("cli.replay_intro"), style="cyan"))
    reporter = ConsoleReporter(console)

    def make_runner(scenario: Scenario) -> Runner:
        return Replayer(load_recording(scenario), listener=reporter)

    suite = _execute(console, settings, scenarios, out_dir, make_runner, reporter, update=update, record=False)
    if campaign is not None:
        _close_campaign(console, campaign, out_dir, started, settings, REPLAY_MODEL, "replay", repo, note, pin)
    raise typer.Exit(0 if suite.ok else 1)


@app.command()
def history(
    folder: Annotated[Path, typer.Argument(help="The history folder (the one given to --campaign).")],
    pin: Annotated[str | None, typer.Option("--pin", help="Never delete this campaign.")] = None,
    unpin: Annotated[str | None, typer.Option("--unpin", help="Let this campaign be deleted again.")] = None,
    title: Annotated[str | None, typer.Option("--title", help="Title of the history page (kept).")] = None,
    budget_mb: Annotated[float, typer.Option("--budget-mb", help="Maximum size of the history folder.")] = 90.0,
    language: Language = None,
) -> None:
    """Rebuild the history page of a campaigns folder; pin or unpin a campaign."""
    console = _console()
    load_dotenv(find_dotenv(usecwd=True))
    set_language(resolve_language(language, os.environ.get("PLAINPROOF_LANGUAGE")))
    try:
        if pin:
            pin_campaign(folder, pin, True)
        if unpin:
            pin_campaign(folder, unpin, False)
    except FileNotFoundError as err:
        _fail(console, err)
    for line in build(folder, budget_mb, title):
        console.print(Text(line, style="dim"))
    console.print(Text(t("cli.history", index=display_path(folder / "index.html"))))


@app.command()
def init(
    folder: Annotated[Path, typer.Argument(help="Where to create the scenario folder.")] = Path("e2e"),
) -> None:
    """Create a scenario folder to start from: a project context, an example scenario, settings."""
    console = _console()
    folder.mkdir(parents=True, exist_ok=True)
    templates = resources.files("plainproof").joinpath("scaffold")
    for name, source in (
        ("context.md", "context.md"),
        ("01-example.txt", "01-example.txt"),
        ("plainproof.toml", "plainproof.toml"),
        (".env.example", "env.example"),
    ):
        path = folder / name
        if path.exists():
            console.print(Text(t("cli.kept", path=display_path(path)), style="dim"))
            continue
        path.write_text(templates.joinpath(source).read_text(encoding="utf-8"), encoding="utf-8")
        console.print(Text(t("cli.created", path=display_path(path)), style="green"))
    console.print(
        Text(
            t(
                "cli.next_steps",
                context=display_path(folder / "context.md"),
                scenario=display_path(folder / "01-example.txt"),
                folder=display_path(folder),
            )
        )
    )


@app.command()
def providers() -> None:
    """The supported model providers, their default models and whether their API key is set."""
    console = _console()
    load_dotenv(find_dotenv(usecwd=True))
    table = Table(title=t("cli.providers_title"))
    for column in (t("cli.provider"), t("cli.ready"), t("cli.default_model"), t("cli.example")):
        table.add_column(column)
    for status in provider_statuses():
        if not status.key_env:
            ready = Text("✓ " + t("cli.no_key_needed"), style="green")
        elif status.ready:
            ready = Text("✓ " + t("cli.key_set"), style="green")
        else:
            ready = Text("✗ " + t("cli.set_key", key=" / ".join(status.key_env)), style="yellow")
        table.add_row(
            Text(f"{status.name}\n{status.description}"), ready, Text(status.default_model or "—"), Text(status.example)
        )
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
