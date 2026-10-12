# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting
(**Security** tab of the repository, then **Report a vulnerability**). You will get an answer within a
week. Once fixed, the problem is disclosed in the changelog, with credit if you wish.

Supported versions: the latest release.

## What plainproof does with your data

- **Secrets.** A variable whose name contains `PASSWORD`, `PASS`, `PWD`, `SECRET`, `TOKEN` or `KEY` is
  kept as its `${NAME}` placeholder in everything sent to the model; its value is substituted only when
  the browser types it. Every report, log, recording and JUnit file shows the placeholder, and any
  occurrence of the value is replaced by it. Password fields are never read. Hidden form fields never
  reach the model.
- **What the model receives.** Screenshots of the pages under test, the list of their interactive
  elements, their text (for checks judged on meaning), the scenario and the project context. Use test
  accounts and test data, and choose a provider (or a local model) whose data policy suits you.
- **Reports** contain screenshots and videos of what the test account saw: publish them with restricted
  access. They contain no absolute path of the machine that produced them.
- **No telemetry.** plainproof sends nothing anywhere except the model requests you configure.

A secret typed into a plain text field (not a password field) remains visible on screenshots and videos.
