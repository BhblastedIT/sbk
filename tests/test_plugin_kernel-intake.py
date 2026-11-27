"""Generic plugin intake in the kernel: loader, L2 merge, knowledge extraction.

Everything runs on tiny synthetic parquet files under a temporary SBK_DATA_ROOT.
No network, no real account, no real data.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# The data root must point to a temp folder BEFORE sbk_config is imported.
_ROOT_TMP = Path(tempfile.mkdtemp(prefix="sbk-intake-test-"))
_CFG = _ROOT_TMP / "sbk.config.test.json"
# The owner comes only from sbk.config.json (no built-in default): the test owner is the
# demo person the fixtures below treat as "you".
_CFG.write_text(
    json.dumps(
        {
            "owner": "Jordan Blake",
            "own_names": ["jordan blake"],
            "own_emails": ["jordan@acme.example"],
        }
    ),
    encoding="utf-8",
)
os.environ["SBK_DATA_ROOT"] = str(_ROOT_TMP / "data")
os.environ["SBK_CONFIG"] = str(_CFG)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
XS = REPO / "tools" / "cross-source"

import plugin_intake  # noqa: E402

import sbk_config  # noqa: E402

# If another test module imported sbk_config first, DATA_ROOT is frozen to that
# module's root (or to ~/.sbk-data). The in-process merge and knowledge tests
# would then read a data root that is not this temp folder: skip them instead.
_ISOLATED = Path(sbk_config.DATA_ROOT) == _ROOT_TMP / "data"
_NOT_ISOLATED_REASON = (
    "sbk_config was imported earlier with another data root; run this file alone: "
    "uv run pytest tests/test_plugin_kernel-intake.py"
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, XS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _contacts(root: Path, plugin: str, rows: list[dict]) -> Path:
    p = root / plugin / "processed" / plugin_intake.CONTACTS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(p, index=False)
    return p


def _events(root: Path, plugin: str, rows: list[dict]) -> Path:
    p = root / plugin / "processed" / plugin_intake.INTERACTIONS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(p, index=False)
    return p


def _c(**kw) -> dict:
    base = {
        "source": "",
        "name": "",
        "email": "",
        "phone": "",
        "company": "",
        "title": "",
        "first_seen": "",
        "last_seen": "",
        "interactions": 0,
        "url": "",
    }
    base.update(kw)
    return base


def _e(**kw) -> dict:
    base = {
        "source": "",
        "ts": "2026-10-01T09:00:00Z",
        "kind": "issue",
        "title": "",
        "text": "",
        "participants": "",
        "owner_role": "other",
        "due": "",
        "url": "",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------- loader


def test_missing_files_are_a_no_op(tmp_path):
    assert plugin_intake.contact_files(tmp_path) == []
    assert plugin_intake.interaction_files(tmp_path / "does-not-exist") == []
    assert plugin_intake.load_contacts(tmp_path) is None
    assert plugin_intake.load_interactions(tmp_path) is None
    assert plugin_intake.load_people(tmp_path) is None
    assert plugin_intake.participant_contacts(None) is None


def test_contacts_are_normalised(tmp_path):
    _contacts(
        tmp_path,
        "demo-tracker",
        [
            _c(
                name=" Ada Demo ",
                email="ADA@Fabrikam.example",
                interactions="7",
                first_seen="2026-01-02",
                last_seen="2026-03-04T10:00:00+01:00",
            ),
            _c(name="", email="", phone="", interactions="0"),  # empty row: dropped
        ],
    )
    df = plugin_intake.load_contacts(tmp_path)
    assert len(df) == 1
    r = df.iloc[0]
    assert r["source"] == "demo-tracker"  # empty source = folder name
    assert r["name"] == "Ada Demo" and r["email"] == "ada@fabrikam.example"
    assert int(r["interactions"]) == 7
    assert r["first_seen"].startswith("2026-01-02T00:00:00")
    assert r["last_seen"].startswith("2026-03-04T09:00:00")  # UTC
    assert bool(r[plugin_intake.FROM_PARTICIPANTS]) is False


def test_optional_columns_may_be_missing(tmp_path):
    p = tmp_path / "mini" / "processed" / plugin_intake.CONTACTS_FILE
    p.parent.mkdir(parents=True)
    pd.DataFrame([{"name": "Bo Sample", "email": "bo@fabrikam.example"}]).to_parquet(p)
    df = plugin_intake.load_contacts(tmp_path)
    assert list(df["name"]) == ["Bo Sample"]
    assert int(df.iloc[0]["interactions"]) == 0 and df.iloc[0]["phone"] == ""


def test_file_without_required_column_is_skipped(tmp_path, caplog):
    p = tmp_path / "broken" / "processed" / plugin_intake.CONTACTS_FILE
    p.parent.mkdir(parents=True)
    pd.DataFrame([{"who": "x"}]).to_parquet(p)
    with caplog.at_level("WARNING"):
        assert plugin_intake.load_contacts(tmp_path) is None
    assert "has no column" in caplog.text


def test_unknown_kind_and_role_fall_back(tmp_path):
    _events(tmp_path, "demo-tracker", [_e(kind="Ticket", owner_role="boss", title="X")])
    ev = plugin_intake.load_interactions(tmp_path)
    assert ev.iloc[0]["kind"] == "record" and ev.iloc[0]["owner_role"] == "other"
    assert ev.iloc[0]["status"] == ""


def test_participants_fill_only_what_contacts_lack(tmp_path):
    _contacts(
        tmp_path,
        "demo-tracker",
        [_c(name="Ada Demo", email="ada@fabrikam.example", interactions=3)],
    )
    _events(
        tmp_path,
        "demo-tracker",
        [
            _e(
                title="A",
                participants="ada@fabrikam.example|||Cy Example",
                ts="2026-10-01T09:00:00Z",
            ),
            _e(title="B", participants="Cy Example", ts="2026-10-05T09:00:00Z"),
        ],
    )
    people = plugin_intake.load_people(tmp_path)
    assert len(people) == 2
    cy = people[people["name"] == "Cy Example"].iloc[0]
    assert bool(cy[plugin_intake.FROM_PARTICIPANTS]) is True
    assert int(cy["interactions"]) == 2
    assert cy["first_seen"].startswith("2026-10-01") and cy["last_seen"].startswith("2026-10-05")
    ada = people[people["email"] == "ada@fabrikam.example"].iloc[0]
    assert int(ada["interactions"]) == 3  # the contacts file wins, no double count


def test_enabled_sources_is_honoured(tmp_path, monkeypatch):
    import sbk_config

    _contacts(tmp_path, "on", [_c(name="Ada Demo", email="ada@fabrikam.example")])
    _contacts(tmp_path, "off", [_c(name="Bo Sample", email="bo@fabrikam.example")])
    monkeypatch.setattr(sbk_config, "source_enabled", lambda n: n == "on")
    df = plugin_intake.load_contacts(tmp_path)
    assert set(df["source"]) == {"on"}


def test_parse_person():
    assert plugin_intake.parse_person("Bo Demo <BO@Fabrikam.example>") == (
        "Bo Demo",
        "bo@fabrikam.example",
    )
    assert plugin_intake.parse_person('"Bo Demo" <bo@fabrikam.example>') == (
        "Bo Demo",
        "bo@fabrikam.example",
    )
    assert plugin_intake.parse_person(" bo@fabrikam.example ") == ("", "bo@fabrikam.example")
    assert plugin_intake.parse_person("Bo Demo") == ("Bo Demo", "")
    assert plugin_intake.parse_person("octocat") == ("octocat", "")
    assert plugin_intake.parse_person("") == ("", "")
    assert plugin_intake.valid_email("octocat") == ""


def test_non_address_in_email_field_is_blanked(tmp_path, caplog):
    # review: a login or handle in the email column used to become a merged
    # contact keyed by that string (e.g. email == "octocat").
    _contacts(
        tmp_path,
        "demo-tracker",
        [
            _c(name="", email="octocat"),  # nothing left: dropped
            _c(name="Lu Demo", email="ludemo"),  # kept by name, email blanked
            _c(name="", email="Mo Demo <MO@Fabrikam.example>"),  # both recovered
        ],
    )
    with caplog.at_level("WARNING"):
        df = plugin_intake.load_contacts(tmp_path)
    assert "not addresses" in caplog.text
    assert df[["name", "email"]].to_dict("records") == [
        {"name": "Lu Demo", "email": ""},
        {"name": "Mo Demo", "email": "mo@fabrikam.example"},
    ]


def test_named_and_list_participants(tmp_path):
    # review: "Name <address>" participants used to be stored whole as an email,
    # and a list column was stringified ("['a' 'b']") and stored as one email.
    _events(
        tmp_path,
        "tracker-a",
        [_e(title="A", participants="Mo Demo <MO@Fabrikam.example>|||Ol Demo")],
    )
    _events(tmp_path, "tracker-b", [_e(title="B", participants=["ny@fabrikam.example", "Ol Demo"])])
    ev = plugin_intake.load_interactions(tmp_path)
    assert sorted(ev["participants"]) == sorted(
        ["Mo Demo <MO@Fabrikam.example>|||Ol Demo", "ny@fabrikam.example|||Ol Demo"]
    )
    people = plugin_intake.load_people(tmp_path)
    got = sorted((r.source, r.name, r.email) for r in people.itertuples(index=False))
    assert got == [
        ("tracker-a", "Mo Demo", "mo@fabrikam.example"),
        ("tracker-a", "Ol Demo", ""),
        ("tracker-b", "", "ny@fabrikam.example"),
        ("tracker-b", "Ol Demo", ""),
    ]
    assert all("@" in e and "<" not in e for e in people["email"] if e)


def test_missing_status_column_warns_about_open_commitments(tmp_path, caplog):
    _events(tmp_path, "demo-tracker", [_e(title="A", owner_role="assignee"), _e(title="B")])
    with caplog.at_level("WARNING"):
        plugin_intake.load_interactions(tmp_path)
    assert "no status column: 1 assigned or dated items" in caplog.text


def test_commitment_rule():
    from collections import namedtuple

    R = namedtuple("R", "owner_role due status")
    assert plugin_intake.is_commitment(R("assignee", "", ""))
    assert plugin_intake.is_commitment(R("author", "2026-12-01T00:00:00+00:00", "open"))
    assert not plugin_intake.is_commitment(R("author", "", ""))
    assert not plugin_intake.is_commitment(R("assignee", "", "merged"))


# --------------------------------------------------------------- L2 merge


@pytest.fixture(scope="module")
def merge_mod():
    if not _ISOLATED:
        pytest.skip(_NOT_ISOLATED_REASON)
    return _load("xs_l2_merge_under_test", "xs-l2-merge.py")


def _phase1(merge_mod):
    cal = pd.DataFrame(
        [
            {
                "email": "ada@fabrikam.example",
                "name": "Ada Demo",
                "total_events": 4,
                "as_organizer": 1,
                "first_seen": "2025-01-01",
                "last_seen": "2026-01-01",
            },
            {
                "email": "bo@fabrikam.example",
                "name": "Bo Sample",
                "total_events": 2,
                "as_organizer": 0,
                "first_seen": "2025-02-01",
                "last_seen": "2026-02-01",
            },
            {
                "email": "cy@fabrikam.example",
                "name": "Cy Example",
                "total_events": 1,
                "as_organizer": 0,
                "first_seen": "2025-03-01",
                "last_seen": "2026-03-01",
            },
        ]
    )
    merged = merge_mod.merge_contacts_phase1(None, None, cal, None)
    # a phone known for Bo (as WhatsApp / iPhone would have set it)
    bo = merged.index[merged["email"] == "bo@fabrikam.example"][0]
    merged.at[bo, "phone_primary"] = "+1 202 555 0101"
    return merged


def _phase2(merge_mod, merged, plugin_df, da_verificare=None):
    return merge_mod.merge_contacts_phase2(
        merged,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        da_verificare=da_verificare,
        verifiche={},
        plugin_df=plugin_df,
    )


def test_merge_without_plugins_adds_neutral_columns(merge_mod):
    merged, _ = _phase2(merge_mod, _phase1(merge_mod), None)
    assert not merged["has_plugin"].any()
    assert (merged["plugin_interactions"] == 0).all()
    assert len(merged) == 3


def test_merge_email_phone_name_and_new(merge_mod, tmp_path):
    _contacts(
        tmp_path,
        "demo-tracker",
        [
            # 1. email match
            _c(
                name="Ada D.",
                email="ADA@fabrikam.example",
                company="Fabrikam",
                title="CTO",
                interactions=5,
                last_seen="2026-11-01T10:00:00Z",
                url="https://tracker.example/u/ada",
            ),
            # 2. phone match (no email)
            _c(name="Bobby", phone="+12025550101", interactions=2),
            # 3. name match (no email, no phone)
            _c(name="Cy Example", interactions=1),
            # 4. unknown email -> new email-keyed row
            _c(
                name="Dee Newcomer",
                email="dee@contoso.example",
                interactions=4,
                first_seen="2026-05-01",
                last_seen="2026-06-01",
            ),
            # 5. no email, nothing matches -> counted, not added
            _c(name="Eve Unmatched Person", interactions=1),
            # 6. your own address -> ignored
            _c(name="Jordan Blake", email="jordan@acme.example", interactions=9),
        ],
    )
    plugin_df = plugin_intake.load_people(tmp_path)
    merged, stats = _phase2(merge_mod, _phase1(merge_mod), plugin_df)

    by = merged.set_index("email")
    ada = by.loc["ada@fabrikam.example"]
    assert ada["has_plugin"] and ada["plugin_sources"] == "demo-tracker"
    assert int(ada["plugin_interactions"]) == 5
    assert ada["organization"] == "Fabrikam" and ada["plugin_title"] == "CTO"
    assert ada["plugin_url"] == "https://tracker.example/u/ada"
    assert ada["last_contact"] == pd.Timestamp("2026-11-01T10:00:00Z")
    assert ada["last_contact_source"] == "demo-tracker"

    assert by.loc["bo@fabrikam.example"]["has_plugin"]  # via phone
    assert by.loc["cy@fabrikam.example"]["has_plugin"]  # via name

    dee = by.loc["dee@contoso.example"]
    assert dee["has_plugin"] and dee["name"] == "Dee Newcomer"
    assert int(dee["plugin_interactions"]) == 4 and not dee["has_email"]
    assert dee["plugin_first_seen"] == pd.Timestamp("2026-05-01T00:00:00Z")

    assert "Eve Unmatched Person" not in set(merged["name"])
    assert "jordan@acme.example" not in set(merged["email"])
    assert len(merged) == 4
    s = stats["demo-tracker"]
    assert s["matched"] == 3 and s["added"] == 1 and s["unmatched"] == 1
    assert int(merged["source_count"].max()) >= 2
    # the score sees the plugin interactions
    assert merge_mod.compute_cross_source_score(dee) > 0


def test_merge_same_new_email_from_two_plugins_is_one_row(merge_mod, tmp_path):
    _contacts(
        tmp_path,
        "tracker-a",
        [_c(name="Dee Newcomer", email="dee@contoso.example", interactions=1)],
    )
    _contacts(
        tmp_path,
        "tracker-b",
        [_c(name="Dee Newcomer", email="dee@contoso.example", interactions=2)],
    )
    merged, _ = _phase2(merge_mod, _phase1(merge_mod), plugin_intake.load_people(tmp_path))
    dee = merged[merged["email"] == "dee@contoso.example"]
    assert len(dee) == 1
    assert int(dee.iloc[0]["plugin_interactions"]) == 3
    assert dee.iloc[0]["plugin_sources"] == "tracker-a|||tracker-b"


def test_merge_never_keys_a_row_on_a_non_address(merge_mod, tmp_path):
    _contacts(
        tmp_path, "demo-tracker", [_c(name="", email="octocat"), _c(name="Lu Demo", email="ludemo")]
    )
    _events(
        tmp_path,
        "demo-tracker",
        [
            _e(
                title="A",
                participants="Ada Demo <ADA@fabrikam.example>|||Mo Demo <mo@contoso.example>",
            )
        ],
    )
    merged, _ = _phase2(merge_mod, _phase1(merge_mod), plugin_intake.load_people(tmp_path))
    emails = [e for e in merged["email"] if e]
    assert all(plugin_intake.valid_email(e) == e for e in emails), emails
    by = merged.set_index("email")
    assert by.loc["ada@fabrikam.example"]["has_plugin"]  # the named participant matched by address
    assert by.loc["mo@contoso.example"]["name"] == "Mo Demo"


def test_merge_ambiguous_name_goes_to_verification(merge_mod, tmp_path):
    merged = _phase1(merge_mod)
    # a namesake: two "Cy Example" with different emails
    extra = merged[merged["email"] == "cy@fabrikam.example"].copy()
    extra["email"] = "cy.other@contoso.example"
    merged = pd.concat([merged, extra], ignore_index=True)
    _contacts(tmp_path, "demo-tracker", [_c(name="Cy Example", interactions=1)])
    casi: list = []
    out, stats = _phase2(merge_mod, merged, plugin_intake.load_people(tmp_path), da_verificare=casi)
    assert not out["has_plugin"].any()
    assert len(casi) == 1 and casi[0]["fonte"] == "demo-tracker"
    assert stats["demo-tracker"]["da_verificare"] == 1


def _run(script: str, args: list[str], data_root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, SBK_DATA_ROOT=str(data_root), SBK_CONFIG=str(_CFG))
    return subprocess.run(
        [sys.executable, str(XS / script), *args],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_merge_cli_with_only_plugin_data(tmp_path):
    root = tmp_path / "data"
    _contacts(
        root,
        "demo-tracker",
        [
            _c(
                name="Ada Demo",
                email="ada@fabrikam.example",
                interactions=3,
                last_seen="2026-11-01",
            ),
            _c(
                name="Bo Sample", email="bo@contoso.example", interactions=1, last_seen="2026-10-01"
            ),
        ],
    )
    res = _run("xs-l2-merge.py", [], root)
    assert res.returncode == 0, res.stderr[-3000:]
    out = pd.read_parquet(root / "enriched" / "contacts-merged.parquet")
    assert set(out["email"]) == {"ada@fabrikam.example", "bo@contoso.example"}
    assert out["has_plugin"].all()
    summary = json.loads((root / "exports" / "contacts-summary.json").read_text())
    assert summary["sources"]["plugin_contacts"] == 2


def test_merge_cli_with_no_data_says_so(tmp_path):
    (tmp_path / "empty").mkdir()
    res = _run("xs-l2-merge.py", [], tmp_path / "empty")
    # D26: a first install with no data is "nothing to merge yet" (exit 0), naming what starts a
    # contact; with an earlier merged book it still refuses (tests/test_kit_first_ingest.py).
    assert res.returncode == 0, res.stderr[-3000:]
    assert "Nothing to merge yet" in res.stderr and "plugin" in res.stderr
    assert not (tmp_path / "empty" / "enriched" / "contacts-merged.parquet").exists()


# --------------------------------------------------------------- knowledge


@pytest.fixture(scope="module")
def ke_mod():
    if not _ISOLATED:
        pytest.skip(_NOT_ISOLATED_REASON)
    return _load("xs_l2_knowledge_extract_under_test", "xs-l2-knowledge-extract.py")


def test_knowledge_no_files_no_facts(ke_mod, tmp_path):
    assert ke_mod.extract_from_plugins(tmp_path) == []
    assert (
        "plugins" in ke_mod.ALL_SOURCES
        and ke_mod.EXTRACTORS["plugins"] is ke_mod.extract_from_plugins
    )


def test_knowledge_facts_and_commitments(ke_mod, tmp_path):
    _contacts(
        tmp_path,
        "demo-tracker",
        [
            _c(
                name="Ada Demo",
                email="ada@fabrikam.example",
                phone="+12025550101",
                company="Fabrikam",
                title="CTO",
                interactions=5,
                first_seen="2026-01-02",
                last_seen="2026-11-01",
                url="https://tracker.example/u/ada",
            ),
            _c(name="Jordan Blake", email="jordan@acme.example", interactions=2),  # you: skipped
        ],
    )
    _events(
        tmp_path,
        "demo-tracker",
        [
            _e(
                kind="issue",
                title="Fix the login page",
                owner_role="assignee",
                participants="ada@fabrikam.example|||Cy Example",
                url="https://tracker.example/i/1",
            ),
            _e(
                kind="pr",
                title="Ship docs",
                owner_role="author",
                due="2026-12-01",
                participants="Cy Example",
                url="https://tracker.example/p/2",
            ),
            _e(
                kind="issue",
                title="Closed one",
                owner_role="assignee",
                url="https://tracker.example/i/3",
            ),
            _e(
                kind="meeting",
                title="Weekly sync",
                owner_role="attendee",
                participants="Cy Example",
            ),
        ],
    )
    # the closed one carries a status column
    ev = pd.read_parquet(tmp_path / "demo-tracker" / "processed" / plugin_intake.INTERACTIONS_FILE)
    ev["status"] = ["open", "", "done", ""]
    ev.to_parquet(tmp_path / "demo-tracker" / "processed" / plugin_intake.INTERACTIONS_FILE)

    facts = ke_mod.extract_from_plugins(tmp_path)
    person = [f for f in facts if f.entity_type == "person"]
    commit = [f for f in facts if f.entity_type == "commitment"]

    attrs = {(f.attribute, str(f.value)) for f in person}
    assert ("identity.name", "Ada Demo") in attrs
    assert ("contact.email", "ada@fabrikam.example") in attrs
    assert ("contact.phone", "+12025550101") in attrs
    assert ("employment.company", "Fabrikam") in attrs
    assert ("identity.headline", "CTO") in attrs
    assert ("contact.demo_tracker_url", "https://tracker.example/u/ada") in attrs
    assert ("communication.demo_tracker_interactions", "5") in attrs
    assert ("communication.demo_tracker_last_contact", "2026-11-01") in attrs
    assert not any("jordan" in str(f.value).lower() for f in person)
    # a bare participant never gets identity.name (it only enriches known people)
    assert ("identity.name", "Cy Example") not in attrs
    assert all(f.source.source_type == "demo-tracker" for f in facts)

    names = {str(f.value) for f in commit if f.attribute == "identity.name"}
    assert names == {"Fix the login page", "Ship docs"}
    cattrs = {(f.attribute, str(f.value)) for f in commit}
    assert ("commitment.due_date", "2026-12-01") in cattrs
    assert ("commitment.where", "demo-tracker / issue") in cattrs
    assert ("commitment.owner", "Jordan Blake") in cattrs
    assert ("commitment.status", "open") in cattrs
    rel = [f for f in person if f.attribute == "relationship.commitment"]
    assert {str(f.value) for f in rel} == {"Fix the login page", "Ship docs"}
    # stable ids: same input, same commitment id
    again = ke_mod.extract_from_plugins(tmp_path)
    assert {f.entity_id for f in commit} == {
        f.entity_id for f in again if f.entity_type == "commitment"
    }


def test_knowledge_named_participant_lands_on_the_known_person(ke_mod, tmp_path):
    _contacts(
        tmp_path,
        "demo-tracker",
        [_c(name="Ada Demo", email="ada@fabrikam.example", interactions=1)],
    )
    _events(
        tmp_path,
        "demo-tracker",
        [
            _e(
                title="Fix the login page",
                owner_role="assignee",
                participants="Ada Demo <ADA@fabrikam.example>",
                url="https://tracker.example/i/9",
            ),
        ],
    )
    facts = ke_mod.extract_from_plugins(tmp_path)
    ada_ids = {
        f.entity_id for f in facts if f.attribute == "identity.name" and f.value == "Ada Demo"
    }
    rel = [f for f in facts if f.attribute == "relationship.commitment"]
    assert len(ada_ids) == 1 and rel and {f.entity_id for f in rel} == ada_ids
    assert not any("<" in str(f.value) for f in facts if f.attribute == "contact.email")


def test_knowledge_cli_writes_profiles(tmp_path):
    root = tmp_path / "data"
    _contacts(
        root, "demo-tracker", [_c(name="Ada Demo", email="ada@fabrikam.example", interactions=5)]
    )
    _events(
        root,
        "demo-tracker",
        [
            _e(
                title="Fix the login page",
                owner_role="assignee",
                participants="ada@fabrikam.example",
                url="https://tracker.example/i/1",
            ),
        ],
    )
    res = _run("xs-l2-knowledge-extract.py", ["--source", "plugins"], root)
    # exit 0, or 1 only for the coining gate (not expected with one clean person)
    assert res.returncode == 0, res.stderr[-3000:]
    ents = root / "knowledge" / "entities"
    people = [json.loads(p.read_text()) for p in (ents / "person").glob("*.json")]
    commits = [json.loads(p.read_text()) for p in (ents / "commitment").glob("*.json")]
    assert any(p.get("canonical_name") == "Ada Demo" for p in people)
    assert any(c.get("canonical_name") == "Fix the login page" for c in commits)
