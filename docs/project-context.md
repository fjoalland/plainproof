# The project context

`context.md` is the technical half of a plainproof suite. Scenarios are written by the business, with
its own words; the context is written **once** by the team that knows the application, and gives
plainproof what the business does not know or should not have to write.

Without a context plainproof works, but each scenario must then explain the login, the path through the
menus and the traps of the components: you are back to technical scenarios. With a good context,
"I request leave from 01/03/2050 to 05/03/2050" is enough.

## Where it goes

```text
e2e/
├── context.md         read automatically
├── 01-login.txt
└── 02-leave-request.txt
```

Every `context.md` from the scenario's folder up to the repository root applies, outermost first: a
shared context at the top (login, menus), one per functional area in its sub-folder. It is given to the
model at every call: when the scenario is interpreted, then at every action. `--context other.md`
replaces them all (one context per environment, for instance).

## What goes in it

A useful context answers the questions a newcomer would ask in front of the screen. This outline suits
most web applications.

### 1. Access and login

The login page, its fields, its button, and the test account. Credentials are environment variables,
never values in clear:

```markdown
## Login
The application opens on a login page.
- Field "Email": type ${APP_USER}
- Field "Password": type ${APP_PASSWORD}
- Click "Sign in"
The test account has the Agent and Manager roles.
```

When the context describes the login, plainproof adds it at the beginning of every scenario that does
not mention it. A variable whose name contains `PASSWORD`, `PASS`, `PWD`, `SECRET`, `TOKEN` or `KEY` is
never sent to the model: it sees `${APP_PASSWORD}`, and plainproof types the real value.

Several profiles to test? One variable per profile, and say how the business names them: "when a
scenario says 'I am a manager', log in with ${APP_MANAGER_USER}".

### 2. Navigation: where each screen is

The sections, menus and sub-menus, and above all **the path to the screens that are not in a menu**:

```markdown
## Where the screens are
- Left menu: "My requests", "Approvals", "Administration" (folded sub-menu).
- An employee's file: "Administration" > "Employees", type the employee number in "Search", click the
  proposed employee.
- Editing a request: in the list, pencil button "Edit the request of DD/MM/YYYY".
```

Name icon-only buttons by their **accessible label** (their `aria-label` or `title`): that is what
plainproof sees.

### 3. Vocabulary

The business words that are not those of the screen, acronyms, homonyms:

```markdown
## Vocabulary
- "RTT" = the option "Reduced working time" of the "Absence type" list.
- "my manager" = the approver shown in the "Manager" column.
- Careful: "Export" is both a menu and a button of the list. In a scenario, "export the list" means the button.
```

### 4. How the screens behave

What already made a scenario fail while the application worked:

```markdown
## How the screens behave
- Dropdowns: click the field, then click the option.
- Dates: type them as DD/MM/YYYY, without the calendar.
- The first option of the "Reason" list is called "Other": it is a valid reason.
- After "Save", a success message shows for three seconds at the top right.
- Yes / No buttons are radio buttons.
```

An instruction written as a way of doing ("in two steps: click the field, then the option") is taken
as is by the interpretation.

## What does not go in it

- **Test values** (dates, employee names, numbers): they belong to the scenarios, and change from one
  test to another.
- **Internal URLs** to skip the navigation: the business does not know them, and a test that goes
  through the menus also tests the menus. Keep them for screens really unreachable otherwise.
- **Secrets in clear.**
- **General instructions about testing** ("check everything carefully"): plainproof applies them already.

## Tuning a context

1. Write a short first context: login, menus, obvious vocabulary.
2. Run the scenarios. For each failure, open the report:
   - **How plainproof understood the scenario** shows the split into steps. A wrong step (wrong menu,
     wrong button, forgotten verification) is almost always fixed in the context, not in the scenario.
   - The probable cause **scenario wording**, while the sentence is clear to a human, points at
     something missing from the context.
   - The probable cause **test agent limitation** on a component (list, calendar, table) is often worked
     around by an instruction in "How the screens behave".
3. Complete it, rerun. Two or three passes are usually enough.

The context is a living document: a new screen, a renamed menu, a new component are declared there.

## A complete example

[`examples/the-internet/`](../examples/the-internet/) holds a context and scenarios for a public demo
application:

```bash
plainproof run examples/the-internet
```
