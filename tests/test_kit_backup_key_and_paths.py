"""The backup keeps its key only in the Keychain, has no credentials-folder source, and finds the repo
and the Claude Code project folder from where the scripts sit (wherever you cloned it)."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "tools" / "infrastructure" / "sb-backup.py"
LIVELLI = ROOT / "tools" / "infrastructure" / "sb_livelli.py"
SKILL = ROOT / ".claude" / "skills" / "backup" / "SKILL.md"


def _load(name: str, path: Path, monkeypatch, tmp_path: Path, claude_dir: Path | None = None):
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path / "data"))
    if claude_dir is None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


def _project_folder_name(repo: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(repo))


def test_backup_paths_come_from_the_script_location(monkeypatch, tmp_path):
    b = _load("sb_backup_paths", BACKUP, monkeypatch, tmp_path)
    assert b.REPO_DIR == ROOT
    assert b.REPO_SBK_DIR == ROOT / "sbk"
    assert (
        Path.home() / ".claude" / "projects" / _project_folder_name(ROOT) == b._CLAUDE_PROJECT_DIR
    )
    assert b._CLAUDE_MEMORY_DIR == b._CLAUDE_PROJECT_DIR / "memory"
    assert [p for p, _ in b.SOURCES] == ["sbk-data", "repo-sbk", "claude-memory"]


def test_backup_honours_claude_config_dir(monkeypatch, tmp_path):
    b = _load("sb_backup_cfgdir", BACKUP, monkeypatch, tmp_path, claude_dir=tmp_path / "cc")
    assert tmp_path / "cc" / "projects" / _project_folder_name(ROOT) == b._CLAUDE_PROJECT_DIR


def test_no_author_paths_or_credentials_folder_in_the_backup_code():
    for f in (BACKUP, LIVELLI):
        text = f.read_text(encoding="utf-8")
        assert '"Projects"' not in text, f
        assert "-Users-" not in text, f
        assert ".sbk-credentials" not in text, f
        assert "vault" not in text.lower(), f


def _fake_keychain(b, monkeypatch, store: dict, stores: bool = True):
    monkeypatch.setattr(b, "get_secret", lambda s, a: store.get((s, a)))

    def _set(s, a, v):
        if stores:
            store[(s, a)] = v

    monkeypatch.setattr(b, "set_secret", _set)


def test_first_key_goes_only_to_the_keychain(monkeypatch, tmp_path):
    b = _load("sb_backup_key1", BACKUP, monkeypatch, tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    store: dict = {}
    _fake_keychain(b, monkeypatch, store)
    dest = tmp_path / "dest"
    key = b._ensure_encryption_key(dest)
    assert store == {(b.ENC_SERVICE, b.ENC_ACCOUNT): key}
    assert list(home.rglob("*")) == []  # no copy of the key anywhere under HOME
    assert not dest.exists()
    assert b._ensure_encryption_key(dest) == key  # read back, not regenerated


def test_no_new_key_when_it_cannot_be_stored(monkeypatch, tmp_path):
    b = _load("sb_backup_key2", BACKUP, monkeypatch, tmp_path)
    store: dict = {}
    _fake_keychain(b, monkeypatch, store, stores=False)  # container mode: set_secret stores nothing
    with pytest.raises(b.ChiaveNonDisponibile, match="SBK_BACKUP_ENC_KEY"):
        b._ensure_encryption_key(tmp_path / "dest")


def test_no_new_key_when_encrypted_archives_exist(monkeypatch, tmp_path):
    b = _load("sb_backup_key3", BACKUP, monkeypatch, tmp_path)
    store: dict = {}
    _fake_keychain(b, monkeypatch, store)
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "sbk-l1-20260101-0000.tar.gz.enc").write_bytes(b"x")
    with pytest.raises(b.ChiaveNonDisponibile, match="offline copy"):
        b._ensure_encryption_key(dest)
    assert store == {}


def test_levels_paths_come_from_the_file_location(monkeypatch, tmp_path):
    lv = _load("sb_livelli_paths", LIVELLI, monkeypatch, tmp_path, claude_dir=tmp_path / "cc")
    assert lv.REPO == ROOT
    assert tmp_path / "cc" / "projects" / _project_folder_name(ROOT) == lv.PROGETTO_CLAUDE
    fuori = {f.nome: f for f in lv.FUORI}
    assert "vault" not in fuori
    assert fuori["repo-sbk"].base == ROOT / "sbk"
    assert fuori["memoria-claude"].base == lv.PROGETTO_CLAUDE / "memory"
    assert fuori["regole-claude"].base == tmp_path / "cc"


def test_backup_skill_says_how_to_keep_and_restore_the_key():
    text = SKILL.read_text(encoding="utf-8")
    assert "keyring.get_password('sbk-backup', 'enc-key')" in text
    assert "keyring.set_password('sbk-backup', 'enc-key'" in text
    assert "--key-from-stdin" in text
    assert "SBK_BACKUP_ENC_KEY" in text
    assert "vault" not in text.lower()
