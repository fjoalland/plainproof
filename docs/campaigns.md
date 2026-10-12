# Campaigns: following an application over time

To follow an application across versions, branches or a technical migration, each run becomes a
**campaign** kept in a history folder, and a page compares the verdicts scenario by scenario from one
campaign to the next.

```bash
plainproof run e2e --url http://localhost:8080/ --campaign history \
  --label "v2.3 · Java 21" --repo ../my-app --note "after the framework upgrade"
```

| Option | Effect |
|---|---|
| `--campaign <folder>` | the run goes to `<folder>/campaigns/<date>`; videos and screenshots are made lighter (with ffmpeg, when installed); `<folder>/index.html` is rebuilt |
| `--label` | what is tested (version, branch, stack); one colour per label in the history |
| `--repo` | the tested application's repository: its branch, commit and version are recorded (read only; the version comes from `package.json`, `pyproject.toml`, `pom.xml`, Gradle, or the latest git tag) |
| `--note` | a remark kept with the campaign |
| `--pin` | never delete this campaign (keep the last campaign of a version as a reference) |
| `--budget-mb` | maximum size of the history (default 90 MB; GitLab Pages accepts 100 MB per site) |

`plainproof replay ... --campaign history` keeps replays in the same history (shown as "replay, no model").

The history page shows, for the 15 latest campaigns, a matrix scenario × campaign (✓ conforms, ✗ failed,
! a canary scenario that passed, · not run; each cell opens its step-by-step report), then the table of
every campaign: date, label, model, conforming scenarios, failing ones, cost, duration, size, code
version. `history.json` holds the same for scripts.

## Size

The folder is a static site. Over the budget, the oldest campaigns are first **lightened** (their
step-by-step screenshots are removed; the video, the final screenshot and the report text are kept),
then the oldest **unpinned** ones are deleted. The latest campaign is never touched.

```bash
plainproof history history                     # rebuild the page
plainproof history history --pin 2026-10-12_0930
plainproof history history --unpin 2026-10-12_0930
plainproof history history --title "Shop: test history"   # kept for the next rebuilds
```

## A suggested layout

One folder per tested application, **outside its repository**, with its scenarios, context,
recordings, `.env` and history. Check out the branch to test in the application's repository, start
it, and run plainproof from the test folder: any branch can be tested without adding anything to it.

```text
my-app-tests/
├── e2e/            scenarios, context.md, recordings/, plainproof.toml
├── history/        --campaign: index.html, history.json, campaigns/
└── .env            test account, API key (never committed)
```
