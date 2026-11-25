"""Name matching ships no specific people: personal aliases come only from sbk.config.json
("nickname_aliases"), and the built-in rules are generic nicknames (bob -> robert)."""

from __future__ import annotations

import importlib
import json

import pandas as pd
import pytest


def _ricarica(monkeypatch, tmp_path, cfg: dict):
    path = tmp_path / "sbk.config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("SBK_CONFIG", str(path))
    monkeypatch.setenv("SBK_DATA_ROOT", str(tmp_path / "data"))
    import sbk_config

    importlib.reload(sbk_config)
    import rq_name_matching

    importlib.reload(rq_name_matching)
    return sbk_config, rq_name_matching


@pytest.fixture(autouse=True)
def _rimetti(monkeypatch):
    yield
    monkeypatch.undo()
    import sbk_config

    importlib.reload(sbk_config)


def test_no_people_built_in(monkeypatch, tmp_path):
    cfg, rq = _ricarica(monkeypatch, tmp_path, {"owner": "Alex Demo"})
    assert cfg.NICKNAME_ALIASES == {}
    assert rq.KNOWN_NICKNAMES == {}
    # Generic rules map a nickname to a given name, never to a person.
    assert all(" " not in v for v in cfg.GENERIC_NICKNAMES.values())
    # The example owner's first name is not captured by any built-in rule.
    assert "alex" not in cfg.GENERIC_NICKNAMES


def test_aliases_come_from_the_config(monkeypatch, tmp_path):
    cfg, rq = _ricarica(
        monkeypatch,
        tmp_path,
        {"nickname_aliases": {"_help": "note", "Sammy": "Sam  Demo", "": "x", "bad": ""}},
    )
    assert cfg.NICKNAME_ALIASES == {"sammy": "sam demo"}
    m = rq.NameMatcher(df=pd.DataFrame({"person_id": ["p_1"], "name": ["Sam Demo"]}))
    r = m.match("Sammy")
    assert (r.person_id, r.method) == ("p_1", "nickname")


def test_generic_rules_match_known_full_names(monkeypatch, tmp_path):
    _, rq = _ricarica(monkeypatch, tmp_path, {})
    df = pd.DataFrame(
        {
            "person_id": ["p_1", "p_2", "p_3"],
            "name": ["Robert Smith", "Giuseppe Verdi", "Alex Rossi"],
        }
    )
    m = rq.NameMatcher(df=df)
    assert m.match("Bob Smith").person_id == "p_1"
    assert m.match("Beppe Verdi").person_id == "p_2"
    # A bare first name or a demo nickname resolves to nobody.
    assert m.match("Alex").person_id is None
    assert m.match("Bob").person_id is None


def test_generic_rule_left_out_when_ambiguous(monkeypatch, tmp_path):
    _, rq = _ricarica(monkeypatch, tmp_path, {})
    # Two different people whose names both turn into "bob smith": the form is not indexed.
    df = pd.DataFrame({"person_id": ["p_1", "p_2"], "name": ["Robert Smith", "Robert  Smith"]})
    m = rq.NameMatcher(df=df)
    assert "bob smith" not in m._nickname_index
