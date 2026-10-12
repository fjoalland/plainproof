# Configuration

Every setting has a default; each of these sources overrides the previous one:

1. `plainproof.toml`, looked up from the scenario folder upwards to the repository root (or `--config FILE`);
2. `PLAINPROOF_*` environment variables (also read from a `.env` file in the current folder or its parents);
3. the command line.

## Commands

```text
plainproof run TARGET        run scenarios with a model (a passing scenario leaves a recording)
plainproof replay TARGET     replay the recordings, without any model
plainproof history FOLDER    rebuild a campaigns history page; --pin / --unpin a campaign; --title
plainproof init [FOLDER]     create a scenario folder to start from (default: e2e)
plainproof providers         model providers, default models, which API keys are set
plainproof --version
```

`TARGET` is a folder (every `.txt` of its tree), one `.txt` file, or the text of a scenario between
quotes. Exit codes: `0` every scenario conforms, `1` at least one does not, `2` setup problem
(missing key or variable, unknown model, scenario not found...).

## Settings

| Option | `plainproof.toml` | Environment | Default | |
|---|---|---|---|---|
| `--model`, `-m` | `model` | `PLAINPROOF_MODEL` | the only provider with a key | `provider:model` ([providers](llm-providers.md)) |
| `--base-url` | `base_url` | per provider | | address of a local or OpenAI-compatible server |
| `--temperature` | `temperature` | `PLAINPROOF_TEMPERATURE` | `0.1` | `none`: the provider's default |
| `--vision/--no-vision` | `vision` | `PLAINPROOF_VISION` | on | send screenshots to the model |
| `--llm-option K=V` | `[llm-options]` | | | extra request fields |
| | `[pricing."prefix"]` | `PLAINPROOF_PRICE_INPUT`, `_OUTPUT` | built-in table | $ per million tokens |
| `--url` | `url` | `PLAINPROOF_URL` | | page opened before each scenario |
| `--headed/--headless` | `headless` | `PLAINPROOF_HEADLESS` | headless | show the browser window |
| `--browser` | `browser` | `PLAINPROOF_BROWSER` | `chromium` | `chrome`, `msedge`, `firefox`, `webkit` |
| `--viewport` | `viewport` | `PLAINPROOF_VIEWPORT` | `1280x800` | |
| `--locale` | `locale` | `PLAINPROOF_LOCALE` | `en-US` | browser locale; also picks the report language |
| `--slow-mo` | `slow_mo` | `PLAINPROOF_SLOW_MO` | `0` | ms added to every browser action, to watch |
| `--video/--no-video` | `video` | `PLAINPROOF_VIDEO` | on | a video per scenario (made lighter with ffmpeg when installed) |
| `--max-steps` | `max_steps` | `PLAINPROOF_MAX_STEPS` | `30` | actions per scenario before giving up |
| `--interpret/--no-interpret` | `interpret` | `PLAINPROOF_INTERPRET` | on | turn business wording into precise steps first |
| `--diagnose/--no-diagnose` | `diagnose` | `PLAINPROOF_DIAGNOSE` | on | explain each failure in plain language |
| `--record/--no-record` | `record` | `PLAINPROOF_RECORD` | on | write recordings of passing scenarios |
| `--context` | `context` | `PLAINPROOF_CONTEXT` | `context.md` files | replaces the project context files |
| `--language`, `-l` | `language` | `PLAINPROOF_LANGUAGE` | from the locale | reports: `en` or `fr` |
| `--label` | `label` | `PLAINPROOF_LABEL` | | what is tested, shown in reports |
| `--out`, `-o` | `out` | `PLAINPROOF_OUT` | `runs/<date-time>` | report folder |
| `--update` | | | | rerun the given scenarios inside the report `--out` |
| `--campaign` | | | | keep the run in a history folder ([campaigns](campaigns.md)) |
| `--repo`, `--note`, `--pin` | | | | with `--campaign` |
| `--budget-mb` | `budget_mb` | `PLAINPROOF_BUDGET_MB` | `90` | with `--campaign`: maximum size of the history |
| `--config` | | | | settings file to use |

Keys of `plainproof.toml` accept dashes or underscores (`max-steps` or `max_steps`); paths are relative to
the file. An unknown key is an error that lists the valid ones.

```toml
# plainproof.toml
model = "anthropic:claude-sonnet-5-5"
url = "https://staging.example.com"
locale = "en-GB"
max-steps = 40
label = "staging"

[llm-options]
reasoning_effort = "low"

[pricing."anthropic:claude-sonnet-5-5"]
input = 2.0
output = 10.0
```

## Other environment variables

| Variable | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` / `GOOGLE_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY` | provider keys |
| `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `GEMINI_BASE_URL`, `MISTRAL_BASE_URL`, `OLLAMA_BASE_URL`, `LMSTUDIO_BASE_URL` | provider addresses |
| `PLAINPROOF_BASE_URL`, `PLAINPROOF_API_KEY` | the `openai-compatible` provider |
| `SSL_CERT_FILE`, `HTTPS_PROXY` | company certificate authority and proxy, for the model calls |
| any name used as `${NAME}` | scenario and context variables; secret when the name contains `PASSWORD`, `PASS`, `PWD`, `SECRET`, `TOKEN` or `KEY` |
| `PLAINPROOF_URL` | also read by the Playwright tests generated from recordings |
