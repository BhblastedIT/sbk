"""Google sign-in helper: your own OAuth client, one login per account, nothing else."""

import importlib
import json

import pytest


def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for var in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_SECRET_PATH"):
        monkeypatch.delenv(var, raising=False)
    import sbk_config

    importlib.reload(sbk_config)
    import google_oauth

    return importlib.reload(google_oauth)


def test_client_from_env(monkeypatch, tmp_path):
    g = _fresh(monkeypatch, tmp_path)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret-1")
    assert g.client_id_secret() == ("id-1", "secret-1")


def test_client_from_desktop_json(monkeypatch, tmp_path):
    g = _fresh(monkeypatch, tmp_path)
    f = tmp_path / "client.json"
    f.write_text(json.dumps({"installed": {"client_id": "id-2", "client_secret": "s-2"}}))
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET_PATH", str(f))
    assert g.client_file() == f
    assert g.client_id_secret() == ("id-2", "s-2")


def test_client_file_found_by_google_download_name(monkeypatch, tmp_path):
    g = _fresh(monkeypatch, tmp_path)
    folder = tmp_path / "home" / ".secrets" / "google-oauth"
    folder.mkdir(parents=True)
    f = folder / "client_secret_123-abc.apps.googleusercontent.com.json"
    f.write_text("{}")
    monkeypatch.setattr(g, "DEFAULT_CLIENT_DIR", folder)
    monkeypatch.setattr(g, "DEFAULT_CLIENT_FILE", folder / "client_secret.json")
    assert g.client_file() == f


def test_stored_value_formats(monkeypatch, tmp_path):
    g = _fresh(monkeypatch, tmp_path)
    assert g._parse_stored("1//bare") == ("1//bare", "", "")
    assert g._parse_stored(json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "s"})) == (
        "r",
        "c",
        "s",
    )
    assert g._parse_stored("") == ("", "", "")


def test_credentials_without_login_raise(monkeypatch, tmp_path):
    g = _fresh(monkeypatch, tmp_path)
    import secrets_adapter

    monkeypatch.setattr(secrets_adapter, "get_secret", lambda service, account: None)
    with pytest.raises(g.NoLogin):
        g.credentials("sbk-gsc", "main", ["scope"])


def test_credentials_from_keychain(monkeypatch, tmp_path):
    g = _fresh(monkeypatch, tmp_path)
    import secrets_adapter

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id-3")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "s-3")
    monkeypatch.setattr(secrets_adapter, "get_secret", lambda service, account: "1//refresh")
    creds = g.credentials("sbk-ga", "main", ["scope"])
    assert creds.refresh_token == "1//refresh" and creds.client_id == "id-3"


def test_gmail_label_by_label_or_address(monkeypatch, tmp_path):
    g = _fresh(monkeypatch, tmp_path)
    emails = tmp_path / "data" / "emails"
    emails.mkdir(parents=True)
    (emails / "accounts.json").write_text(json.dumps({"work": {"email": "alex@work.example"}}))
    assert g.gmail_label("work") == ("work", "alex@work.example")
    assert g.gmail_label("ALEX@work.example") == ("work", "alex@work.example")
    with pytest.raises(SystemExit):
        g.gmail_label("nobody@else.example")
