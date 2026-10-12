# Record and replay

plainproof has two modes:

| Mode | Command | What happens |
|---|---|---|
| **With a model** | `plainproof run e2e` | The model reads the page and acts. When a scenario **passes**, its recording is written next to it, replacing the previous one. |
| **Without a model** | `plainproof replay e2e` | The recordings are played back, without any model call or API key, at no cost. A scenario without a recording fails with a clear message. |

Use the model to write and maintain the suite, the replay for frequent regression runs (every commit,
every night), and the model again when a screen changed.

## Where recordings live

```text
e2e/
├── context.md
├── 01-login.txt
└── recordings/
    ├── 01-login.json         replayed by `plainproof replay`
    └── test_01_login.py      the same actions as a plain Playwright test (pytest)
```

A failing run never overwrites a valid recording. `--no-record` disables writing them. Commit the
recordings with the scenarios.

## What is recorded

- Every **successful** action, with a stable description of its target — tag, role, label, text, rank
  among identical elements, and the text of its table row when it sits in one — instead of its number,
  which changes on every page.
- Text and URL checks as they are.
- Checks judged on meaning, as the quote the judge had to find on the page, checked again as a text on
  replay (in the page text and the state of the form controls, where the judge read it). An absence
  judged on meaning has nothing precise to look for: it is marked "not verifiable without a model" on
  replay, without failing the test.
- Secrets as `${NAME}`, never their value.

## Safety of data on replay

Before clicking a checkbox or a radio button, the replay checks that its state is the one it had when
recorded. Otherwise it stops **before** clicking: if the data changed since the recording, the replay
does not modify it blindly. In a table, a button is found by its row: exactly one row must match (by its
dates first), or nothing is clicked.

## The replay, or the generated test

- `plainproof replay` plays the recording with plainproof's own browser driver: the same help with
  dropdowns, dates and overlays, the same reports. It is the reference replay.
- The `.py` file is an ordinary Playwright test (pytest-playwright), to read what was done or to run it
  without plainproof:

  ```bash
  pip install pytest-playwright
  PLAINPROOF_URL=https://staging.example.com APP_PASSWORD=... pytest e2e/recordings -v
  ```

  In a table, the button is found by the dates of its row (an identifier in its name, like "Delete
  order 61", may change from one run to the next). It has none of plainproof's help: a particular
  dropdown or date picker may need a manual adjustment. It is rewritten each time the scenario passes
  with a model.

## When to record again

Run the scenario with a model again when the screen changes (a label, the order of the fields, a new
step): the replay then stops with "... is not on the page any more: the screen changed since the
recording".
