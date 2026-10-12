# Getting started

## 1. Install

plainproof needs Python 3.10 or newer.

```bash
pip install plainproof            # or: pipx install plainproof / uv tool install plainproof
playwright install chromium       # the browser driven by the tests
```

On Linux CI machines, `playwright install --with-deps chromium` also installs the system libraries.
Already have Google Chrome or Microsoft Edge? Skip the download and use `--browser chrome` or
`--browser msedge`. When Playwright's Chromium is missing, plainproof falls back to an installed
Chrome, then Edge, on its own.

## 2. Choose a model

Set the API key of one provider (in the environment, or in a `.env` file in the folder where you run
plainproof or one of its parents):

```bash
export ANTHROPIC_API_KEY=...      # or OPENAI_API_KEY, GEMINI_API_KEY, MISTRAL_API_KEY, OPENROUTER_API_KEY
```

With a single key set, plainproof uses that provider's default model. Otherwise, pick one:

```bash
plainproof run e2e --model anthropic:claude-sonnet-5-5
plainproof run e2e --model ollama:qwen2.5vl:7b          # a local model, no key
```

`plainproof providers` lists every provider, its default model and whether its key is set.
Details, local models and costs: [Model providers](llm-providers.md).

## 3. A first run on a public demo

The repository ships scenarios for [the-internet](https://the-internet.herokuapp.com/), a public
playground made for browser automation:

```bash
git clone https://github.com/fjoalland/plainproof.git && cd plainproof
plainproof run examples/the-internet
```

Watch the browser with `--headed`, slow it down with `--slow-mo 500`. The report is written to
`runs/<date-time>/index.html`.

## 4. Your application

```bash
plainproof init e2e
```

creates:

```text
e2e/
├── context.md         how to log in, where the screens are, the vocabulary — written once by the team
├── 01-example.txt     a scenario, in business words — replace it with real ones
├── plainproof.toml    shared settings (model, URL, ...), found automatically
└── .env.example       copy to .env: the test account and the API key (never commit .env)
```

1. Describe the login, the menus and the vocabulary in `context.md` ([guide](project-context.md)).
2. Put the test account in `.env` (`APP_USER`, `APP_PASSWORD`) and refer to it as `${APP_USER}`.
3. Ask whoever knows the product to write two or three scenarios ([guide](writing-scenarios.md)).
4. Run them:

   ```bash
   plainproof run e2e --url https://staging.example.com
   ```

5. For each failure, read **How plainproof understood the scenario** and the **probable cause** in its
   report, complete the context or the scenario, and rerun only that scenario in the same report:

   ```bash
   plainproof run e2e/03-refund.txt --out runs/20261012-093000 --update
   ```

6. Once green, replay without a model as often as you like (`plainproof replay e2e`), and plug it into
   your CI ([guide](continuous-integration.md)).

## Troubleshooting

**`Cannot start chromium: Executable doesn't exist`** — run `playwright install chromium`, or use an
installed browser with `--browser chrome` / `--browser msedge`.

**Certificate errors behind a company proxy** (`CERTIFICATE_VERIFY_FAILED`) — the model API calls go
through [httpx](https://www.python-httpx.org/), which honours `SSL_CERT_FILE` (and `HTTPS_PROXY`):

```bash
export SSL_CERT_FILE=/path/to/company-root-ca.pem
```

**`No model chosen`** — no API key is set, or several are: choose with `--model`.

**`Missing environment variable(s): APP_PASSWORD`** — a scenario or a context refers to `${APP_PASSWORD}`:
set it in the environment or in `.env`.

**The model keeps failing on a widget** (a dropdown, a date picker) — say how it works in the context
("dropdowns: click the field, then click the option"). The report's probable cause "test agent
limitation" points at those cases.

**Strange characters in a Windows console** — use Windows Terminal, or `set PYTHONIOENCODING=utf-8`.
