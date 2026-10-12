# Architecture

```text
src/plainproof/
├── cli.py, console.py       the `plainproof` command and what it prints
├── config.py                settings: defaults < plainproof.toml < PLAINPROOF_* < command line
├── scenario.py              scenarios and project contexts: loading, comments, directives, variables
├── secrets.py               ${VARIABLES}; secrets kept as placeholders, redacted everywhere
├── text.py, lexicon.py      normalisation and the language heuristics used by the guards
├── suite.py                 runs scenarios one after another, writes the reports
├── results.py               what a run produced (steps, plan, verdict, usage), JSON round trip
├── history.py               campaigns and the history page
├── i18n/                    en.json, fr.json: everything a human reads
├── llm/                     the model side
│   ├── base.py              ChatRequest, Completion, TokenUsage, LLMClient (the provider protocol)
│   ├── http.py              retries, back-off, parameter fallbacks shared by the adapters
│   ├── openai.py, anthropic.py, gemini.py, mistral.py
│   ├── registry.py          "provider:model" specs, presets, API keys, plugins (entry points)
│   ├── pricing.py           prices, usage, cost formatting
│   ├── json_answer.py       reading the JSON object in an answer
│   └── scripted.py          answers from a file (tests, demos)
├── browser/                 the page side
│   ├── driver.py            BrowserDriver: what the agent and the replay need from a browser
│   ├── playwright.py        PlaywrightBrowser (one session) and BrowserLauncher (one browser per suite)
│   ├── scripts/*.js         what runs in the page: numbering, page text, control states, toasts...
│   ├── matching.py          the label guard, option matching (pure functions)
│   ├── imaging.py           annotated and highlighted screenshots
│   └── video.py             ffmpeg re-encoding
├── agent/                   the loop and its guards
│   ├── runner.py            Agent.run: observe, decide, guard, act, verify, conclude
│   ├── guards.py            loops, redundancy, verdict objections, check binding, realignment
│   ├── plan.py              interpretation of the business wording, and its safety rules
│   ├── judge.py             checks judged on meaning, validated against the page
│   ├── progress.py          what the model is reminded of at every turn
│   ├── prompts.py           the instructions given to the model
│   ├── diagnosis.py         the plain-language explanation of a failure
│   ├── calls.py             one request, one JSON answer, usage counted
│   └── actions.py           the actions and their outcome
├── replay/                  recordings
│   ├── recorder.py, targets.py   recording actions with stable targets
│   ├── replayer.py          replaying without a model
│   ├── codegen.py           the plain Playwright test
│   └── storage.py           recordings/ next to each scenario
└── report/                  outputs
    ├── html.py, templates/  the HTML pages (Jinja2, autoescaped, no external resource)
    ├── files.py             report.json, report.md
    ├── summary.py           summary.json, and reading a report back for --update
    ├── junit.py             junit.xml
    └── paths.py             paths fit for publication
```

## Design decisions

**The model decides, plainproof judges.** Everything the model answers goes through deterministic code
before it touches the page or the verdict ([the guards](reliability.md)). That is why plainproof owns its
agent loop and its browser layer instead of handing the browser to a general-purpose agent.

**Playwright drives the browser.** It is open source, headless, scriptable, fast, records videos, runs on
every CI and every OS, and supports Chromium, Firefox and WebKit. Agent-oriented browser extensions (such
as Claude in Chrome) are excellent for interactive, exploratory work in a user's own browser, but they
are tied to one assistant and one browser profile, are not headless, and leave no room for guards
between the model and the page. Playwright MCP servers expose the browser as tools to an agent; again,
plainproof needs to sit between the decision and the action. Other drivers can be added by implementing
`browser.driver.BrowserDriver`.

**Set-of-Marks, by number and by name.** Every interactive element of the page is numbered and drawn on
the screenshot; the model answers with a number *and* the label of its target, and acts are performed by
selector, never by pixel. Coordinates guessed by a model are fragile; numbers alone go stale; the pair is
checked.

**Providers over HTTP, no SDK.** Each adapter is a hundred lines describing a URL, headers, a payload and
an answer. The retry policy, the parameter fallbacks (a model refusing `temperature` or JSON mode) and
the usage accounting are shared, and tests check the exact requests sent. New providers plug in through
the `plainproof.providers` entry point.

**One prompt in English, reports in your language.** Models follow English instructions best; what they
write for humans (reasoning, verdicts, explanations) follows `--language`, like every label of the
reports.

**Everything a report contains is publishable.** Secrets are redacted at the source (the model only ever
sees placeholders), paths are relative, password fields are never read, hidden fields never reach the
model.

## Extension points

| To add | Where |
|---|---|
| a model provider | a class with `name`, `vision` and `complete()`; entry point `plainproof.providers` ([guide](llm-providers.md#writing-your-own-provider)) |
| a report language | `src/plainproof/i18n/<code>.json` and `SUPPORTED`, `LANGUAGE_NAMES` in `i18n/__init__.py` |
| the heuristics of a language (verification and negation words) | a `Lexicon` in `lexicon.py` |
| a browser automation library | an implementation of `browser.driver.BrowserDriver` |
| a guard | `agent/guards.py`, wired in `agent/runner.py`, with the real case as a test |
