# Application context: the-internet

An example of project context, written once by the technical team. plainproof gives it to the model
for every scenario of this folder: the scenarios do not have to talk about URLs, menus or components.

[the-internet](https://the-internet.herokuapp.com/) is a public demo application made for browser
automation. Run these scenarios with `plainproof run examples/the-internet` (the `plainproof.toml` of
this folder opens its home page before each scenario).

## Access

Most screens need no login. The "Form Authentication" screen gives its own demo account on the page
itself. On an application that needs a login, this is where its page, fields and test account are
described, with environment variables: see docs/project-context.md.

## Where the screens are

The home page "Welcome to the-internet" lists the examples as links. To open a screen, click its link
on the home page:

- "Checkboxes": two checkboxes, labelled "checkbox 1" and "checkbox 2".
- "Dropdown": a list "Dropdown List" with the options "Option 1" and "Option 2".
- "Dynamic Controls": a checkbox "A checkbox" with a "Remove" button (then "Add"), and a disabled text
  field with an "Enable" button (then "Disable").
- "Form Authentication": the login page; it states which username and password to use.

## Vocabulary

- "checkboxes" = the "Checkboxes" screen.
- "dropdown list", "list of choices" = the "Dropdown" screen.
- "dynamic controls", "activation screen" = the "Dynamic Controls" screen.
- "login page" = the "Form Authentication" screen; "secure area" = the page reached once logged in.

## How the screens behave

- Dynamic Controls: after a click on "Remove", "Add", "Enable" or "Disable", a loading bar shows for a
  few seconds, then a message appears ("It's gone!", "It's back!", "It's enabled!", "It's disabled!").
  Wait for this message before going on.
- The "Dropdown List" is a native list: the select action works.
- After logging in or out, a message shows in a banner at the top of the page.
