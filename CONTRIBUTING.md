# Contributing to plainproof

Thanks for considering a contribution. Bug reports, providers, languages, guards against a false verdict
you met, documentation: everything helps.

## Reporting a problem

Open an issue with:

- the command you ran and plainproof's version (`plainproof --version`);
- the model (`provider:model`) and the browser;
- the scenario, and the `report.json` of the run if you can share it — it holds the plan, every action
  and its evidence. Remove anything confidential first: screenshots show what your test account sees.

A wrong verdict (a test that passes while it should fail, or the reverse) is the most valuable report
there is: it usually becomes a new guard.

## Development setup

```bash
git clone https://github.com/fjoalland/plainproof.git && cd plainproof
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

## Tests first

plainproof is developed test-first, and every pull request keeps it that way:

1. write the test that shows the problem or the behaviour (it fails);
2. write the code that makes it pass;
3. tidy up, tests still green.

A guard comes with the real case that motivated it, written as a test (see `tests/unit/agent/` for many
examples), with neutral data: no customer, product or person of a real organisation.

```bash
pytest -m "not browser"          # unit tests: a few seconds, no browser, no network
pytest                           # everything: also a real headless Chromium on local pages
pytest --cov                     # with coverage (the CI requires 92 %)
```

No test calls a real model or the network: the scripted model (`plainproof.llm.scripted.ScriptedClient`)
answers from a list, provider adapters are tested against `httpx.MockTransport`, and browser tests load
local HTML. `tests/fakes.py` has a fake browser for agent and replay tests.

## Code style

```bash
ruff check src tests && ruff format src tests && mypy
```

- Type hints everywhere; `mypy --strict` passes on `src/`.
- Small modules with one job; pure functions where possible (they are the easiest to test).
- Comments explain *why*, especially the real-world failure behind a rule.
- Messages read by the model are in English and say what to do instead ("Option X is not in the list.
  Available options: ...").
- Everything a human reads goes through `plainproof.i18n.t()`.

## Common contributions

**A model provider.** Most providers speak the OpenAI chat API: a preset in `llm/registry.py` may be
enough. Otherwise subclass `llm/http.py:HttpClient` (URL, headers, payload, answer parsing), add it to the
registry, and test the exact request and answer formats against a scripted server like
`tests/unit/llm/test_providers.py`. A provider can also live in its own package, through the
`plainproof.providers` entry point (see [docs/llm-providers.md](docs/llm-providers.md)).

**A report language.** Copy `src/plainproof/i18n/en.json` to `<code>.json`, translate the values (keep the
`{placeholders}`), and add the code to `SUPPORTED` and `LANGUAGE_NAMES` in `i18n/__init__.py`. A test checks
that every catalog has the same keys and placeholders. To make the guards understand scenarios written in
that language, add its verification and negation words to `lexicon.py`, with tests.

**A browser behaviour.** Reproduce the widget in local HTML in `tests/browser/`, then fix
`browser/playwright.py` or the scripts in `browser/scripts/`.

## Pull requests

- One topic per pull request, with its tests and, when behaviour changes, its documentation.
- Update `CHANGELOG.md` under "Unreleased".
- Commit messages: imperative mood, what and why (`Refuse a check that only finds text typed by the agent`).

## Releasing (maintainers)

1. Update the version in `pyproject.toml` and `src/plainproof/__init__.py`, and the changelog.
2. Tag `vX.Y.Z` and publish a GitHub release: `.github/workflows/release.yml` publishes to PyPI with
   trusted publishing.

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE), and you
follow the [Code of Conduct](CODE_OF_CONDUCT.md).
