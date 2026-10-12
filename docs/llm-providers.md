# Model providers

plainproof talks to the providers' HTTP APIs directly (no vendor SDK to install): the same retry policy
everywhere, and one dependency. Pick a model with `--model provider:model`, `PLAINPROOF_MODEL`, or
`model = "..."` in `plainproof.toml`.

```bash
plainproof run e2e --model anthropic:claude-sonnet-5-5
plainproof run e2e --model gemini                   # a provider alone: its default model
plainproof run e2e --model claude-haiku-5-5         # a well-known model name alone: its provider
plainproof providers                                # what is available here, and which keys are set
```

With no model given and exactly one API key set, that key's provider is used with its default model.

## Hosted providers

| Provider | Spec | Key | Default | Notes |
|---|---|---|---|---|
| Anthropic | `anthropic:<model>` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` | the system prompt is cached between turns (cheaper calls) |
| OpenAI | `openai:<model>` | `OPENAI_API_KEY` | `gpt-6.1-sol` | `OPENAI_BASE_URL` for a proxy or a gateway |
| Google Gemini | `gemini:<model>` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-3.8-flash` | thinking tokens are counted as output |
| Mistral | `mistral:<model>` | `MISTRAL_API_KEY` | `mistral-medium-latest` | |
| OpenRouter | `openrouter:<vendor/model>` | `OPENROUTER_API_KEY` | — | hundreds of models behind one key |

Choosing a model: the agent runs one call per action (10 to 40 per business scenario), plus one to
interpret the scenario, one per check judged on meaning and one to explain a failure. Balanced models
(Sonnet, GPT Sol, Gemini Flash, Mistral Medium) are the usual choice; small ones are faster and cheaper
on short, explicit scenarios but get lost more often in long forms, dropdowns and calendars.

## Local models

Any vision model served locally works through its OpenAI-compatible endpoint. Nothing leaves your
machine except what the browser itself loads.

```bash
ollama pull qwen2.5vl:7b
plainproof run e2e --model ollama:qwen2.5vl:7b                 # http://localhost:11434/v1
plainproof run e2e --model lmstudio:<model> --base-url http://localhost:1234/v1
```

Another address: `--base-url`, or `OLLAMA_BASE_URL` / `LMSTUDIO_BASE_URL`. Local models are priced at
zero.

Smaller local models are less reliable agents than hosted ones: start with short scenarios, and keep
`--max-steps` low. Reasoning models that print `<think>...</think>` blocks are fine: those blocks are
ignored when the answer is read.

## Any OpenAI-compatible server

vLLM, llama.cpp's server, a LiteLLM proxy, a company gateway:

```bash
export PLAINPROOF_BASE_URL=https://llm.example.com/v1
export PLAINPROOF_API_KEY=...                          # if the server needs one
plainproof run e2e --model openai-compatible:my-model
```

## Vision, or not

At every step a vision model gets an annotated screenshot (a red number on every interactive element)
along with the list of those elements. A text-only model can run with `--no-vision` (or
`vision = false`): it then relies on the element list alone, which describes every element's label,
value and state. Expect it to struggle where the layout matters.

## Request options

- `--temperature 0.1` is the default (low, for steadier decisions). `--temperature none` leaves the
  provider's default. A model that rejects the parameter (some reasoning models do) gets it dropped
  automatically after its first refusal; so does an unsupported JSON mode.
- `--llm-option KEY=VALUE` adds any field to every request (repeatable; the value is read as JSON when
  it is JSON; dotted keys nest):

  ```bash
  plainproof run e2e --model mistral:mistral-large-latest --llm-option reasoning_effort=none
  plainproof run e2e --model gemini --llm-option generationConfig.thinkingConfig.thinkingBudget=0
  ```

  The same in `plainproof.toml`:

  ```toml
  [llm-options]
  reasoning_effort = "low"
  ```

Rate limits, overloads, timeouts and network errors are retried with exponential back-off (honouring
`Retry-After`); an invalid key fails at once with a message naming the variable to check.

## Costs

Every report shows the model calls, the tokens and the cost of each scenario and of the suite. Prices
come from a built-in table (US dollars per million tokens, read on the providers' pricing pages; see
`src/plainproof/llm/pricing.py` and its date). Cache discounts are applied when the cache prices are
known. A model missing from the table still reports its tokens, with an unknown cost (`?`).

Override or add prices by model prefix:

```toml
# plainproof.toml
[pricing."anthropic:claude-sonnet-5-5"]
input = 2.0
output = 10.0
cache_read = 0.10      # optional
cache_write = 2.5      # optional

[pricing."mistral:mistral-vibe-cli"]   # a subscription key: usage included in the plan
input = 0
output = 0
```

or for one run: `PLAINPROOF_PRICE_INPUT=2 PLAINPROOF_PRICE_OUTPUT=10`.

## Writing your own provider

A provider is any object with a `name` (shown in reports, used to look up prices), a `vision` flag, and
a `complete()` method:

```python
# my_company_llm.py
from plainproof.llm.base import ChatRequest, Completion, LLMError, TokenUsage


class CompanyGateway:
    def __init__(self, model: str, *, base_url: str | None = None, temperature: float | None = 0.1,
                 vision: bool = True, options: dict | None = None) -> None:
        self.model, self.vision = model, vision

    @property
    def name(self) -> str:
        return f"company:{self.model}"

    def complete(self, request: ChatRequest) -> Completion:
        # request.system: the instructions; request.messages: one user message whose parts are
        # an ImagePart (the screenshot, when vision is on) and a TextPart.
        text, usage = ..., TokenUsage(input_tokens=..., output_tokens=...)
        return Completion(text=text, usage=usage)   # raise LLMError(..., transient=True) to be retried
```

Register it in your package's `pyproject.toml`:

```toml
[project.entry-points."plainproof.providers"]
company = "my_company_llm:CompanyGateway"
```

Once installed, `--model company:any-model` uses it. Subclassing
`plainproof.llm.openai.OpenAICompatibleClient` (or `HttpClient`) gives you the HTTP handling, retries and
parameter fallbacks for free.

## Offline: the scripted model

`--model scripted:answers.json` answers from a JSON list, in order: handy to check a setup, to demo the
reports, or to test plainproof itself. It is what plainproof's own end-to-end tests use.
