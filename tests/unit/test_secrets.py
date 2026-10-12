"""Secrets never reach the model, the reports or the logs: only their ${PLACEHOLDER} does."""

from typing import ClassVar

import pytest

from plainproof.secrets import MissingVariablesError, Secrets, expand_variables, is_secret_name


@pytest.mark.parametrize(
    "name", ["APP_PASSWORD", "DB_PASS", "API_KEY", "GITHUB_TOKEN", "CLIENT_SECRET", "ADMIN_PWD", "app_password"]
)
def test_secret_names(name: str) -> None:
    assert is_secret_name(name)


@pytest.mark.parametrize("name", ["APP_USER", "BASE_URL", "LOGIN"])
def test_plain_names(name: str) -> None:
    assert not is_secret_name(name)


class TestSecrets:
    secrets = Secrets({"APP_PASSWORD": "s3cret!", "API_TOKEN": "tok-123"})

    def test_substitute_placeholders_at_execution_time_only(self) -> None:
        assert self.secrets.substitute('type "${APP_PASSWORD}"') == 'type "s3cret!"'
        assert self.secrets.substitute("${UNKNOWN} stays") == "${UNKNOWN} stays"

    def test_hide_puts_placeholders_back(self) -> None:
        assert self.secrets.hide('Typed "s3cret!" into [2]') == 'Typed "${APP_PASSWORD}" into [2]'

    def test_redact_walks_nested_structures(self) -> None:
        data = {"action": "type", "text": "s3cret!", "list": ["tok-123!", 3, None], "pair": ("s3cret!",)}
        assert self.secrets.redact(data) == {
            "action": "type",
            "text": "${APP_PASSWORD}",
            "list": ["${API_TOKEN}!", 3, None],
            "pair": ("${APP_PASSWORD}",),
        }

    def test_the_longest_value_is_hidden_first(self) -> None:
        nested = Secrets({"SHORT_KEY": "abcd", "LONG_KEY": "abcdef"})
        assert nested.hide("abcdef abcd") == "${LONG_KEY} ${SHORT_KEY}"

    def test_empty_secrets_change_nothing(self) -> None:
        empty = Secrets()
        assert not empty
        assert empty.redact({"a": "b"}) == {"a": "b"}
        assert empty.substitute("${X}") == "${X}"

    def test_values_names_and_merge(self) -> None:
        merged = self.secrets.merge(Secrets({"OTHER_SECRET": "zzz"}))
        assert merged.names == ("APP_PASSWORD", "API_TOKEN", "OTHER_SECRET")
        assert set(merged.values) == {"s3cret!", "tok-123", "zzz"}
        assert bool(merged)


class TestExpandVariables:
    env: ClassVar[dict[str, str]] = {"APP_USER": "alice", "APP_PASSWORD": "s3cret!", "EMPTY_PASSWORD": ""}

    def test_plain_variables_are_expanded(self) -> None:
        text, secrets = expand_variables("login as ${APP_USER}", self.env)
        assert text == "login as alice"
        assert not secrets

    def test_secret_variables_stay_placeholders(self) -> None:
        text, secrets = expand_variables("login as ${APP_USER} with ${APP_PASSWORD}", self.env)
        assert text == "login as alice with ${APP_PASSWORD}"  # the model never sees the value
        assert secrets.substitute(text) == "login as alice with s3cret!"

    def test_an_empty_secret_is_just_empty(self) -> None:
        text, secrets = expand_variables("[${EMPTY_PASSWORD}]", self.env)
        assert text == "[]"
        assert not secrets

    def test_missing_variables_are_all_reported(self) -> None:
        with pytest.raises(MissingVariablesError) as err:
            expand_variables("${B_VAR} ${A_VAR} ${B_VAR} ${APP_USER}", self.env)
        assert err.value.names == ("A_VAR", "B_VAR")
        assert "A_VAR, B_VAR" in str(err.value)

    def test_dollar_signs_without_braces_are_text(self) -> None:
        assert expand_variables("costs $5 and $HOME", self.env)[0] == "costs $5 and $HOME"
