# Application context

Written once by the team that knows the application. plainproof gives this file to the model for
every scenario of this folder and its sub-folders, so that scenarios can stay in business words.
Replace each section with what is true for your application.
Guide: https://github.com/fjoalland/plainproof/blob/main/docs/project-context.md

## Access and login

No login is needed.

When the application needs one, describe its login page here: its fields, what to type in each
and the button to click. Refer to the test account with environment variables (set in .env, see
.env.example): a variable whose name contains PASSWORD, PASS, PWD, SECRET, TOKEN or KEY is never
shown to the model.

## Where the screens are

- Main menu on the left: "Dashboard", "Orders", "Settings".
- An order: "Orders", then click its number in the list.

## Vocabulary

- "my orders" = the "Orders" page.

## How the screens behave

- Dropdowns: click the field, then click the option.
- Dates: type them as DD/MM/YYYY; do not use the calendar.
- After "Save", a confirmation appears for a few seconds at the top right.
