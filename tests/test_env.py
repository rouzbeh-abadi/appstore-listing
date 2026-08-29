"""Key ID and Issuer ID come from a .env file, not from the UI."""

import pytest

from appstore_listing.connect import env
from appstore_listing.errors import CredentialsError


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    for name in (env.KEY_ID, env.ISSUER_ID, env.KEY_PATH, env.BUNDLE_ID):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(env, "_loaded_from", None)
    monkeypatch.setattr(env, "_file_values", {})
    # Point the "installed CLI run from elsewhere" fallback at an empty directory,
    # so a developer's own .env at the real project root cannot leak into a test.
    monkeypatch.setattr(env, "PROJECT_ROOT", tmp_path / "nowhere")


def write_env(folder, body: str):
    (folder / ".env").write_text(body)
    return folder / ".env"


def test_loads_values_from_a_dotenv_file(tmp_path, monkeypatch):
    write_env(tmp_path, "ASC_KEY_ID=ABCD123456\nASC_ISSUER_ID=69a6de70-uuid\n")
    monkeypatch.chdir(tmp_path)

    assert env.load() == tmp_path / ".env"
    assert env.require_key_and_issuer() == ("ABCD123456", "69a6de70-uuid")
    assert env.source() == tmp_path / ".env"


def test_comments_and_blank_values_are_handled(tmp_path, monkeypatch):
    write_env(
        tmp_path,
        "# a comment\nASC_KEY_ID=ABCD123456\n\nASC_ISSUER_ID=uuid\nASC_BUNDLE_ID=com.example.app\n",
    )
    monkeypatch.chdir(tmp_path)
    env.load()
    assert env.get(env.BUNDLE_ID) == "com.example.app"
    assert env.get(env.KEY_PATH) == ""  # absent -> empty, never a KeyError


def test_real_environment_wins_over_the_file(tmp_path, monkeypatch):
    write_env(tmp_path, "ASC_KEY_ID=FROM-FILE\nASC_ISSUER_ID=uuid\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(env.KEY_ID, "FROM-SHELL")

    env.load()
    assert env.require_key_and_issuer()[0] == "FROM-SHELL"


def test_missing_values_say_what_to_add_and_where(tmp_path, monkeypatch):
    write_env(tmp_path, "ASC_KEY_ID=ABCD123456\n")
    monkeypatch.chdir(tmp_path)
    env.load()

    with pytest.raises(CredentialsError) as excinfo:
        env.require_key_and_issuer()
    message = str(excinfo.value)
    assert "ASC_ISSUER_ID" in message
    assert "ASC_KEY_ID" not in message  # that one was fine
    assert ".env" in message


def test_no_dotenv_file_at_all(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env.load()
    with pytest.raises(CredentialsError, match="ASC_KEY_ID and ASC_ISSUER_ID"):
        env.require_key_and_issuer()


def test_example_file_lists_every_setting():
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text()
    for name in (env.KEY_ID, env.ISSUER_ID, env.KEY_PATH, env.BUNDLE_ID):
        assert name in text


def test_project_root_is_the_fallback_when_cwd_has_no_dotenv(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    write_env(root, "ASC_KEY_ID=FROM-ROOT\nASC_ISSUER_ID=uuid\n")
    monkeypatch.setattr(env, "PROJECT_ROOT", root)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert env.load() == root / ".env"
    assert env.require_key_and_issuer()[0] == "FROM-ROOT"


def test_error_grammar_matches_how_many_are_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    write_env(tmp_path, "ASC_KEY_ID=ABCD123456\n")  # only the issuer is missing
    env.load()
    with pytest.raises(CredentialsError, match=r"ASC_ISSUER_ID not set\. Add it to"):
        env.require_key_and_issuer()

    write_env(tmp_path, "# nothing set at all\n")
    env.load()
    with pytest.raises(CredentialsError, match=r"and ASC_ISSUER_ID not set\. Add them to"):
        env.require_key_and_issuer()


def test_deleting_a_line_from_dotenv_takes_effect_on_reload(tmp_path, monkeypatch):
    """The bug this guards: a value copied into os.environ could never be removed."""
    monkeypatch.chdir(tmp_path)

    write_env(tmp_path, "ASC_KEY_ID=ABCD123456\nASC_ISSUER_ID=69a6de70-uuid\n")
    env.load()
    assert env.require_key_and_issuer() == ("ABCD123456", "69a6de70-uuid")

    # The user edits .env and refreshes the page; the process is still running.
    write_env(tmp_path, "ASC_KEY_ID=ABCD123456\n")
    env.load()

    assert env.get(env.ISSUER_ID) == ""
    with pytest.raises(CredentialsError, match="ASC_ISSUER_ID"):
        env.require_key_and_issuer()


def test_deleting_the_whole_dotenv_clears_everything(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dotenv = write_env(tmp_path, "ASC_KEY_ID=ABCD123456\nASC_BUNDLE_ID=com.example.app\n")
    env.load()
    assert env.get(env.BUNDLE_ID) == "com.example.app"

    dotenv.unlink()
    env.load()
    assert env.get(env.BUNDLE_ID) == ""
    assert env.source() is None


class TestKeyPathResolution:
    """ASC_KEY_PATH should survive the checkout being renamed or moved.

    An absolute path is the one thing in .env that breaks when the
    folder moves, and the resulting "private key file not found" does
    not obviously point back at the rename.
    """

    def _dotenv(self, tmp_path, value):
        (tmp_path / ".env").write_text(f"ASC_KEY_PATH={value}\n", encoding="utf-8")
        (tmp_path / "AuthKey_TEST123.p8").write_text("not a real key", encoding="utf-8")

    def test_relative_path_resolves_next_to_the_env_file(self, tmp_path, monkeypatch):
        self._dotenv(tmp_path, "AuthKey_TEST123.p8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ASC_KEY_PATH", raising=False)
        env.load()

        resolved = env.key_path()
        assert resolved == (tmp_path / "AuthKey_TEST123.p8").resolve()
        assert resolved.is_file()

    def test_relative_path_still_resolves_after_the_folder_is_renamed(
        self, tmp_path, monkeypatch
    ):
        # The whole point: rename the directory and the key is still found.
        before = tmp_path / "appstore-snapshots"
        before.mkdir()
        self._dotenv(before, "AuthKey_TEST123.p8")
        after = tmp_path / "appstore-listing"
        before.rename(after)

        monkeypatch.chdir(after)
        monkeypatch.delenv("ASC_KEY_PATH", raising=False)
        env.load()

        assert env.key_path() == (after / "AuthKey_TEST123.p8").resolve()

    def test_absolute_path_is_left_alone(self, tmp_path, monkeypatch):
        absolute = tmp_path / "keys" / "AuthKey_TEST123.p8"
        absolute.parent.mkdir()
        absolute.write_text("not a real key", encoding="utf-8")
        self._dotenv(tmp_path, str(absolute))

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ASC_KEY_PATH", raising=False)
        env.load()

        assert env.key_path() == absolute

    def test_missing_setting_is_none_rather_than_a_bad_path(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("ASC_KEY_ID=ABC\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ASC_KEY_PATH", raising=False)
        env.load()

        assert env.key_path() is None
