""
import importlib
import os
from pathlib import Path


def test_config_imports_and_has_constants(monkeypatch, tmp_path):
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text('{"owner":"Alex Demo","own_emails":["alex@demo.example"]}', encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    c = importlib.import_module("sbk_config")
    importlib.reload(c)
    assert hasattr(c, "DATA_ROOT")
    assert hasattr(c, "OWN_EMAILS") and isinstance(c.OWN_EMAILS, set)
    assert hasattr(c, "EMAIL_ACCOUNTS") and isinstance(c.EMAIL_ACCOUNTS, tuple)
    assert hasattr(c, "OWNER_NAME") and c.OWNER_NAME == "Alex Demo"


def test_data_root_follows_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path / "x"))
    import sbk_config
    importlib.reload(sbk_config)
    assert str(sbk_config.DATA_ROOT).endswith("x")


def test_user_config_override(monkeypatch, tmp_path):
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text('{"owner":"Test Owner","email_accounts":["a","b"]}', encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    import sbk_config
    importlib.reload(sbk_config)
    assert sbk_config.OWNER_NAME == "Test Owner"
    assert sbk_config.EMAIL_ACCOUNTS == ("a", "b")


def test_sorgenti_registry_loads():
    s = importlib.import_module("sorgenti")

    assert any(k for k in dir(s) if "VIVE" in k.upper() or "sorgent" in k.lower())


def test_example_config_is_valid_json():
    import json
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "sbk.config.example.json").read_text(encoding="utf-8"))
    assert "owner" in data and "email_accounts" in data


def test_source_settings_defaults_without_config(monkeypatch, tmp_path):
    for var in ("SBK_PLAUD_API_BASE", "SBK_VOICE_MEMOS_LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path / "data"))
    import sbk_config
    importlib.reload(sbk_config)
    assert not hasattr(sbk_config, "GOOGLE_SA_FILE")  # Google: personal OAuth login only
    assert not hasattr(sbk_config, "SLACK_WORKSPACES")  # Slack: the token's own workspace only
    assert sbk_config.SLACK_EXCLUDE_CHANNEL_PATTERNS == []
    assert not sbk_config.SLACK_EXCLUDE_CHANNEL_IDS
    assert sbk_config.SLACK_USER_NAMES == {}
    assert sbk_config.ATTIO_EXTRA_WORKSPACES == {} and list(sbk_config.ATTIO_WORKSPACE_DIRS) == ["acme"]
    assert sbk_config.CLICKUP_TEAMS == {}
    assert sbk_config.PLAUD_API_BASE == "https://api-euc1.plaud.ai"
    assert sbk_config.VOICE_MEMOS_LANGUAGE == "auto"
    assert frozenset() == sbk_config.ENABLED_SOURCES and sbk_config.source_enabled("anything")


def test_source_settings_from_config(monkeypatch, tmp_path):
    import json
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text(json.dumps({
        "enabled_sources": ["voice-memos", "email"],
        "slack": {"exclude_channel_patterns": ["^client-"], "exclude_channel_ids": ["C1"],
                  "user_names": {"U1": "Sam Demo"}, "_help": "ignored"},
        "attio": {"extra_workspaces": {"second": "Second"}},
        "clickup": {"teams": {"42": "Team"}},
        "voice_memos": {"language": "en"},
    }), encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    import sbk_config
    importlib.reload(sbk_config)
    assert sbk_config.SLACK_EXCLUDE_CHANNEL_PATTERNS == ["^client-"]
    assert {"C1"} == set(sbk_config.SLACK_EXCLUDE_CHANNEL_IDS)
    assert sbk_config.SLACK_USER_NAMES == {"U1": "Sam Demo"}
    assert "second" in sbk_config.ATTIO_WORKSPACE_DIRS
    assert sbk_config.CLICKUP_TEAMS == {"42": "Team"}
    assert sbk_config.VOICE_MEMOS_LANGUAGE == "en"
    assert sbk_config.source_enabled("voicememos") and sbk_config.source_enabled("email")
    assert not sbk_config.source_enabled("slack")


def test_empty_data_root_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv("SBK_DATA_ROOT", "")  # an empty line in .env
    import sbk_config
    importlib.reload(sbk_config)
    assert Path.home() / ".sbk-data" == sbk_config.DATA_ROOT


def test_slack_exclusions_from_config(monkeypatch, tmp_path):
    """Channels flagged in the index and ids listed in sbk.config.json are both excluded."""
    import json
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text(json.dumps({"slack": {"exclude_channel_ids": ["D9"]}}), encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    import sbk_config
    importlib.reload(sbk_config)
    import slack_esclusi
    importlib.reload(slack_esclusi)
    index = tmp_path / "channel-index.json"
    index.write_text(json.dumps({"channels": [
        {"id": "C1", "name": "client-x", "is_excluded": True},
        {"id": "C2", "name": "general", "is_excluded": False},
    ]}), encoding="utf-8")
    ids = slack_esclusi.esclusi(index)
    assert ids == frozenset({"C1", "D9"})
    assert slack_esclusi.e_escluso({"channel_id": "D9"}, ids)
    assert not slack_esclusi.e_escluso({"channel_id": "C2"}, ids)


def test_owner_has_no_builtin_default(monkeypatch, tmp_path, caplog):
    """D3: who you are comes only from sbk.config.json; missing = empty plus one warning."""
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path / "data"))
    import sbk_config
    with caplog.at_level("WARNING", logger="sbk.config"):
        importlib.reload(sbk_config)
    assert sbk_config.OWNER_NAME == "" and sbk_config.OWNER_FIRST_NAME == ""
    assert set() == sbk_config.OWN_EMAILS and set() == sbk_config.OWN_NAMES_NORMALIZED
    assert sbk_config.OWN_PERSON_ID == "" and sbk_config.OWNER_SUBJECT == ""
    assert frozenset() == sbk_config.OWNER_SPEAKER_LABELS
    assert sbk_config.OWNER_GRAPH_ID == "p_owner" and sbk_config.OWNER_LABEL == "the owner"
    assert not sbk_config.is_owner_speaker("anyone") and not sbk_config.is_own_email("a@b.example")
    import re
    assert re.search(sbk_config.owner_name_regex(), "any text at all") is None
    warnings = [r for r in caplog.records if "sbk.config.json has no" in r.getMessage()]
    assert len(warnings) == 1


def test_owner_identity_from_config(monkeypatch, tmp_path):
    import json
    import re
    cfg = tmp_path / "sbk.config.json"
    cfg.write_text(json.dumps({
        "owner": "Alex Demo",
        "own_names": ["alex demo", "AD"],
        "own_emails": ["Alex@Demo.example"],
        "own_person_id": "p_1234abcd",
    }), encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(cfg))
    import sbk_config
    importlib.reload(sbk_config)
    assert {"alex@demo.example"} == sbk_config.OWN_EMAILS
    assert {"alex demo", "ad"} == sbk_config.OWN_NAMES_NORMALIZED
    assert frozenset({"alex demo", "ad", "alex"}) == sbk_config.OWNER_SPEAKER_LABELS
    assert sbk_config.OWN_PERSON_ID == "p_1234abcd" == sbk_config.OWNER_GRAPH_ID
    assert sbk_config.OWNER_SUBJECT == "alex demo" and sbk_config.OWNER_LABEL == "Alex Demo"
    assert sbk_config.is_owner_speaker(" Alex ") and not sbk_config.is_own_name("alex")
    assert re.search(rf"\b{sbk_config.owner_name_regex()}\b", "ciao alex, come va")


def test_example_config_documents_the_owner_keys():
    import json
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "sbk.config.example.json").read_text(encoding="utf-8"))
    for key in ("owner", "own_names", "own_emails", "own_person_id"):
        assert key in data and f"_help_{key}" in data


def test_no_demo_owner_literal_in_code():
    """No demo owner name in code, prompts or defaults (tests may set one through config)."""
    import re
    root = Path(__file__).resolve().parents[1]
    pat = re.compile(r"jordan|p_jordan|jblake", re.IGNORECASE)
    allowed = {
        # a name in a first-name dictionary (gender), not the owner
        ("tools/plaud/regole/nomi.py", '"jordan",'),
    }
    hits = []
    for base in ("tools", "dashboard"):
        for f in (root / base).rglob("*"):
            if not f.is_file() or f.suffix not in {".py", ".js", ".html", ".json", ".swift"}:
                continue
            rel = f.relative_to(root).as_posix()
            if "/tests/" in rel or rel.startswith("tools/util/sb-identita-collaudo.py"):
                continue
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                if pat.search(line) and (rel, line.strip()) not in allowed:
                    hits.append(f"{rel}: {line.strip()[:80]}")
    assert not hits, hits
