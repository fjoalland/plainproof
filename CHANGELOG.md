# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-12

First public release.

### Added

- Scenarios in plain language (`.txt` files, any language), project contexts (`context.md`, inherited
  from parent folders), `${VARIABLES}` and secrets that never reach the model nor the reports.
- Interpretation of business wording into precise steps, shown in every report.
- The agent loop with its guards: label-checked actions, step tracking, refused premature actions, loop
  detection, verdict objections, checks bound to their verification step, a judge whose quotes must be
  on the page.
- Model providers over HTTP, without vendor SDK: Anthropic, OpenAI, Google Gemini, Mistral, Ollama,
  LM Studio, OpenRouter, any OpenAI-compatible server, plugins through the `plainproof.providers` entry
  point, and a scripted model for tests and demos. Retries with back-off, automatic fallback when a model
  rejects `temperature` or JSON mode, text-only models with `--no-vision`.
- Costs per scenario and per suite from a built-in price table, overridable in `plainproof.toml`.
- A Playwright browser driver: whole-page element numbering, invisible styled checkboxes, custom
  dropdowns, date pickers, covered elements, folded texts, transient notifications, videos.
- Recording of passing runs, replay without a model (`plainproof replay`), and a generated
  pytest-playwright test per scenario.
- Reports: static HTML (light and dark), `junit.xml`, `summary.json`, `report.json`, `report.md`;
  `--update` to rerun scenarios inside an existing report.
- Canary scenarios (`# expect: failure`) that conform when they fail.
- Campaigns and a history page comparing verdicts over time, with a size budget and pinning.
- `plainproof init` and `plainproof providers`; settings from `plainproof.toml`, `PLAINPROOF_*`
  variables and the command line.
- Reports, console and explanations in English and French.
