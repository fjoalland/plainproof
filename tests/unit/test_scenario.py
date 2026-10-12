"""Loading scenarios: inline text, one file, or a folder tree with its project contexts."""

from pathlib import Path

import pytest

from plainproof.scenario import ScenarioError, find_contexts, load_scenarios

ENV = {"APP_USER": "alice", "APP_PASSWORD": "s3cret!"}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestInlineScenario:
    def test_text_that_is_not_a_path_is_a_scenario(self) -> None:
        (scenario,) = load_scenarios("Open example.com and check that the title says Example", env={})
        assert scenario.name == "inline"
        assert scenario.text == scenario.source == "Open example.com and check that the title says Example"
        assert scenario.path is None
        assert scenario.context == ""

    @pytest.mark.parametrize("target", ["scenarios/login.txt", "login.txt", "tests/e2e/", "tests\\e2e"])
    def test_a_missing_path_is_reported_not_run_as_text(self, target: str) -> None:
        with pytest.raises(ScenarioError, match="not found"):
            load_scenarios(target, env={})

    def test_variables_are_expanded(self) -> None:
        (scenario,) = load_scenarios("Log in as ${APP_USER} with ${APP_PASSWORD}", env=ENV)
        assert scenario.text == "Log in as alice with ${APP_PASSWORD}"
        assert scenario.source == "Log in as ${APP_USER} with ${APP_PASSWORD}"
        assert scenario.secrets.names == ("APP_PASSWORD",)


class TestScenarioFile:
    def test_comments_give_the_description_and_are_not_executed(self, tmp_path: Path) -> None:
        file = write(
            tmp_path / "01-login.txt",
            "# A valid account can log in.\n# It lands on the dashboard.\nOpen the app.\n\n"
            "  # a note in the middle\nI log in as ${APP_USER}.\nI see the dashboard.\n",
        )
        (scenario,) = load_scenarios(str(file), env=ENV)
        assert scenario.name == "01-login"
        assert scenario.description == "A valid account can log in. It lands on the dashboard."
        assert scenario.source == "Open the app.\n\nI log in as ${APP_USER}.\nI see the dashboard."
        assert scenario.steps == ["Open the app.", "I log in as alice.", "I see the dashboard."]
        assert scenario.expected_failure is False

    @pytest.mark.parametrize("directive", ["# expect: failure", "#expected: fail", "  # Expect = FAILURE"])
    def test_a_directive_marks_an_expected_failure(self, tmp_path: Path, directive: str) -> None:
        file = write(tmp_path / "canary.txt", f"{directive}\n# Checks that a defect is caught.\nClick Pay.")
        (scenario,) = load_scenarios(str(file), env={})
        assert scenario.expected_failure is True
        assert scenario.description == "Checks that a defect is caught."

    def test_an_empty_file_is_an_error(self, tmp_path: Path) -> None:
        file = write(tmp_path / "empty.txt", "# only a comment\n\n")
        with pytest.raises(ScenarioError, match="empty"):
            load_scenarios(str(file), env={})

    def test_a_missing_variable_names_the_file(self, tmp_path: Path) -> None:
        file = write(tmp_path / "02-pay.txt", "Pay with ${CARD_NUMBER}.")
        with pytest.raises(ScenarioError, match=r"02-pay\.txt.*CARD_NUMBER"):
            load_scenarios(str(file), env={})


def tree(root: Path) -> Path:
    """A project with a shared context and one context per functional area."""
    (root / ".git").mkdir(parents=True)
    write(root / "context.md", "Shared by the repository.")  # the repository root itself is included
    suite = root / "e2e"
    write(suite / "context.md", "Log in as ${APP_USER} / ${APP_PASSWORD}.")
    write(suite / "billing" / "context.md", "Invoices are under Billing.")
    write(suite / "billing" / "01-invoice.txt", "Create an invoice.")
    write(suite / "billing" / "02-refund.txt", "Refund an invoice.")
    write(suite / "accounts" / "01-signup.txt", "Sign up.")
    write(suite / "recordings" / "notes.txt", "not a scenario")
    write(suite / ".hidden" / "x.txt", "not a scenario")
    return suite


class TestScenarioFolder:
    def test_every_txt_of_the_tree_in_path_order_with_flat_names(self, tmp_path: Path) -> None:
        names = [s.name for s in load_scenarios(str(tree(tmp_path)), env=ENV)]
        assert names == ["accounts-01-signup", "billing-01-invoice", "billing-02-refund"]

    def test_each_scenario_gets_the_contexts_of_its_folders_outermost_first(self, tmp_path: Path) -> None:
        by_name = {s.name: s for s in load_scenarios(str(tree(tmp_path)), env=ENV)}
        assert by_name["billing-01-invoice"].context == (
            "Shared by the repository.\n\nLog in as alice / ${APP_PASSWORD}.\n\nInvoices are under Billing."
        )
        assert by_name["accounts-01-signup"].context.endswith("Log in as alice / ${APP_PASSWORD}.")
        assert by_name["accounts-01-signup"].secrets.names == ("APP_PASSWORD",)

    def test_a_sub_folder_runs_alone_with_the_contexts_of_its_parents(self, tmp_path: Path) -> None:
        scenarios = load_scenarios(str(tree(tmp_path) / "billing"), env=ENV)
        assert [s.name for s in scenarios] == ["01-invoice", "02-refund"]
        assert scenarios[0].context.endswith("Invoices are under Billing.")

    def test_an_explicit_context_replaces_the_context_files(self, tmp_path: Path) -> None:
        other = write(tmp_path / "staging.md", "Staging context.")
        scenarios = load_scenarios(str(tree(tmp_path)), env=ENV, context_path=other)
        assert {s.context for s in scenarios} == {"Staging context."}

    def test_a_folder_without_scenario_is_an_error(self, tmp_path: Path) -> None:
        write(tmp_path / "context.md", "x")
        with pytest.raises(ScenarioError, match=r"No \.txt scenario"):
            load_scenarios(str(tmp_path), env={})

    def test_a_missing_context_variable_names_the_context_file(self, tmp_path: Path) -> None:
        write(tmp_path / "context.md", "Use ${TENANT_ID}.")
        write(tmp_path / "a.txt", "Go.")
        with pytest.raises(ScenarioError, match=r"context\.md.*TENANT_ID"):
            load_scenarios(str(tmp_path), env={})


def test_find_contexts_stops_at_the_repository_root(tmp_path: Path) -> None:
    write(tmp_path / "context.md", "outside the repository")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    write(repo / "context.md", "root")
    write(repo / "a" / "b" / "context.md", "deep")
    assert find_contexts(repo / "a" / "b") == [repo / "context.md", repo / "a" / "b" / "context.md"]
