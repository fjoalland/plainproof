# Writing scenarios

A scenario is a `.txt` file written in everyday language by whoever knows the product. No code, no page
address, no technical name: you tell what you do in the application and what you expect to see. Any
language works; the examples here are in English.

```text
# A leave request is created, appears in my requests, then is cancelled.
I request leave from 02/03/2050 to 06/03/2050, reason: annual leave.
I send it. It must appear in my requests, waiting for approval.
I cancel this request (and I confirm): it must not be there any more.
```

Before running it, plainproof reads it again with the [project context](project-context.md) and splits
it into precise steps ("Click My requests", "Verify that the request of 02/03/2050 is listed"...). That
split is shown at the top of the report, under **How plainproof understood the scenario**: it is where
you see whether a sentence was misunderstood.

## What to write

**What you do**, in order, with your own words: "I go to", "I create", "I choose", "I confirm". One or
several actions per line, sentences or bullet-like notes: it does not matter.

**What you must see.** This is what makes a test: without an expected result, plainproof cannot
conclude that it passed. Any wording works: "I should see...", "normally it shows...", "the row is gone",
"it is refused", "I stay on the form".

**Exact values when you know them**: dates, names, numbers, and the exact text of a message between
double quotes when you have it in front of you. Otherwise describe the message ("a message tells me the
end date is wrong"): plainproof checks it on its meaning, and the report shows the text really read.

## What you do not need to write

- **The login.** It is described once and for all in the project context. Write it only when the login
  is what you test.
- **The technical path**: page addresses, invisible button names, scrolling, "wait 2 seconds".
- **How lists, calendars and menus work**: that is the job of the context and of plainproof.

## Three rules all the same

1. **A test does not depend on today's data.** It creates what it needs then deletes it, or reads what
   exists, or plans for the empty case ("if there is no request, the test stops: success"). Use dates
   far in the future (2050, 2051): they get in the way of no real data.
2. **An expected result stays demanding.** If you write "a message explains that the end date must be
   after the start date", a generic error message will not do — on purpose: that is how real defects
   are found.
3. **Each scenario starts from a fresh browser**: it does not benefit from what another scenario did
   before it.

## Comments, descriptions and canaries

Lines starting with `#` are for humans and are never executed. The comment block above the first step
becomes the scenario's description in the reports; comments further down are notes for whoever
maintains the scenario (a known defect, the business rule tested).

A scenario can check that a **known defect is still detected**: mark it with `# expect: failure`. It
conforms when it fails, and the suite stays green; if it starts passing, the suite fails and says so.

```text
# expect: failure
# Ticket 412: the export ignores the date filter. This scenario must keep failing until it is fixed.
I export the orders of March 2050: the file only contains March orders.
```

## Variables and secrets

Scenarios (and contexts) may use environment variables: `${APP_USER}`. A variable whose name contains
`PASSWORD`, `PASS`, `PWD`, `SECRET`, `TOKEN` or `KEY` is **never shown to the model**: the model types
`${APP_PASSWORD}` and plainproof substitutes the real value when the browser types it. Histories,
reports, logs and JUnit only ever show `${APP_PASSWORD}`.

## Organising a suite

```text
e2e/
├── context.md                  shared: login, menus
├── 01-login.txt
├── orders/
│   ├── context.md              specific to orders, added after the shared context
│   ├── 01-create.txt
│   └── 02-refund.txt
└── recordings/                 written by plainproof when scenarios pass
```

Every `.txt` file of the folder tree is a scenario, run in path order; sub-folders give functional
areas (`plainproof run e2e/orders` runs one area, with the shared context). In reports, a scenario is
named after its path: `orders-01-create`.

## When a scenario fails

Open its `report.html`. At the top: your scenario, how plainproof understood it, the verdict with an
explanation in plain words, and the probable cause:

| Probable cause | What it means | What to do |
|---|---|---|
| **application behaviour** | the application did not do what was expected | check by hand: it may be a real defect |
| **scenario wording** | a sentence was misunderstood, or names something that does not exist | read "how plainproof understood it", make the sentence precise or complete the context |
| **test agent limitation** | the screen was right but a component could not be operated | describe the component in the context; report it with the report attached |
| **environment or data** | rights, data, network, credentials | check the test account and the environment |

A failure is not necessarily a false alarm: a scenario "inconsistent dates are refused with an explicit
message" once revealed that, for one request type, users got a generic technical error instead.
