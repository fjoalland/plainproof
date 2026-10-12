# Continuous integration

Any CI works the same way: install plainproof and a browser, run the suite against a deployed instance,
keep the report folder as an artifact and give `junit.xml` to the test tab. The exit code fails the job
when a scenario does not conform.

Two strategies, often combined:

- **Replay on every change** (`plainproof replay`): no model, no key, no cost, deterministic.
- **Run with a model** nightly or on demand (`plainproof run`): it adapts to changed screens, refreshes
  the recordings, and finds what a replay cannot.

Pin the plainproof version (`pip install plainproof==0.1.0`): a new engine version should not change
your verdicts without you noticing. Put the API key and the test account in masked CI variables. The
runner must reach the model's API (or run a local model).

## GitHub Actions

[`examples/ci/github-actions.yml`](../examples/ci/github-actions.yml):

```yaml
name: e2e
on:
  schedule: [{ cron: "0 4 * * *" }]
  workflow_dispatch:

jobs:
  plainproof:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install "plainproof==0.1.0" && playwright install --with-deps chromium
      - run: plainproof run e2e --url "$APP_URL" --out e2e-report --label "nightly · ${{ github.sha }}"
        env:
          APP_URL: https://staging.example.com
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          APP_USER: ${{ secrets.APP_USER }}
          APP_PASSWORD: ${{ secrets.APP_PASSWORD }}
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: e2e-report, path: e2e-report }
```

Use any JUnit reporter action on `e2e-report/junit.xml` to see the scenarios in the run summary.

## GitLab CI

[`examples/ci/gitlab-ci.yml`](../examples/ci/gitlab-ci.yml):

```yaml
plainproof:
  image: python:3.12
  script:
    - pip install "plainproof==0.1.0"
    - playwright install --with-deps chromium
    - plainproof run e2e --url "$APP_URL" --out e2e-report
  artifacts:
    when: always
    paths: [e2e-report/]
    reports:
      junit: e2e-report/junit.xml       # the merge request's test tab
```

To save the browser download, use one of Microsoft's `mcr.microsoft.com/playwright/python` images and
pin the `playwright` package to the image's version.

## Publishing the report

The report folder is a static site. Publish it with restricted access — it shows what the test account
saw (see [Reports](reports.md#publishing-reports)). With `--campaign history` and a persistent folder
(a branch, a bucket, Pages), the [history page](campaigns.md) follows the application over time.
