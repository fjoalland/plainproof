# How verdicts stay honest

A model may say "success". plainproof decides. Between the model and the verdict sits a layer of
deterministic guards; each one answers a failure, or worse a **false success**, seen on a real business
application (a Vue / PrimeVue single-page app) while plainproof was developed. Each has a test that
replays the case behind it (`tests/unit/agent/`, `tests/browser/`).

## On the page

- **The whole page is listed, not only what is on screen.** A button three screens down is clicked
  directly; plainproof scrolls to it. Searching by scrolling made the agent oscillate until its budget ran out.
- **The target is confirmed by its name.** `click`, `type` and `select` carry the label of the element
  aimed at. A stale number is corrected only toward an element carrying exactly that name, and refused
  otherwise with the candidates: "Create the invoice" once became "Add Jane DOE to the recipients"
  because a list had shifted every number.
- **Labels are found** even when a component wires them badly (`<label for>` on a wrapper instead of the
  field), on invisible styled checkboxes, and from table headers ("Monday / Morning").
- **Date fields** are typed, committed, and their calendar closed, so that numbers stay stable.
- **Folded text**: a check on a text that is in the page but hidden in a closed menu says so and names
  the toggle that opens it.
- **Covered elements**: a button under a calendar or a list left open is reported with the way out
  (Escape); one under a fixed footer, with the other way out (scroll).
- **Transient notifications**: a "saved successfully" toast that disappears after three seconds still
  counts, if it appeared after the last action — never an older one.
- **No proof by echo**: a text found only in a field the agent typed it into proves nothing (seen: the
  expected row did not exist, the agent typed its name into the filter, and the check found it there).

## On the run

- **Step tracking.** The step number can only grow. An action of the next step is **refused without being
  executed** while the current step's verification is missing: otherwise the next click changes the
  page and makes the verification impossible. A step number lagging one behind is realigned on the plan.
- **No sterile repetition.** A check or a typing that already succeeded is not run again; the next step
  is handed over instead. A check that failed twice is not run a third time. Scrolling in circles, the
  same action repeated, and circling one step end the run as a failure instead of burning the budget.
- **Notes.** A value read on the page for later (a name, an identifier) is noted and given back at every
  turn — the rest of the model's reasoning is not.
- **The author's sentence stays in front of the agent**: the interpretation may lose a nuance ("even if
  the field refuses it, do not retry"); the original line is shown with the current step.

## On the verdict

- **The expectation is not negotiable.** For a verification step, the judge always judges the step's own
  wording, never the agent's rephrasing. Seen before this guard: the expected message was missing (a real
  defect), the agent checked "an error message is shown" instead, and the test passed.
- **A vague check proves nothing.** A text check proves a step only when it looks for one of the step's
  exact values (a quoted text, a date, a number) or for a passage of four words or more of the
  expectation; otherwise the step is judged on meaning, on the same page, right away.
- **The judge must quote the page.** A positive verdict counts only when its quote really is on the page,
  is long enough to say something ("on" once "proved" that a box was ticked), and keeps every exact
  wording and every label the expectation names.
- **The scenario's values are untouchable.** The model may not change a date the form refuses to make it
  pass. Seen: the test no longer tested anything, and created data.
- **The interpretation cannot reverse a test.** An expectation can be made precise, never turned into an
  absence when the line negates nothing ("I see a Statistics menu" became "there is no Statistics menu",
  because the context listed the real menus), nor stripped of a value it names; "there is only one record
  left" is not an absence.
- **A success is refused** when the last proof of a verification step failed, when a requested
  verification was never made, or when the scenario was not carried out to the end.

## What remains

The model is sampled at a low temperature, but it is still a model: run a new suite a few times before
calling it stable, then use [replays](record-and-replay.md) for regressions. And when a verdict looks
wrong, the report shows why: the plan, each action with its screenshots and the evidence of each check.
