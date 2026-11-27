"""Documented CLIs answer to English names; the older Italian names still work as hidden aliases.
Only argument parsing runs: parse_args is wrapped so main() stops right after it."""

import argparse
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class _Parsed(Exception):
    def __init__(self, ns):
        self.ns = ns


def _load(rel: str):
    path = ROOT / rel
    name = "cli_" + re.sub(r"\W", "_", path.stem)
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def parse(monkeypatch):
    original = argparse.ArgumentParser.parse_args

    def stop_after_parse(self, args=None, namespace=None):
        raise _Parsed(original(self, args, namespace))

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", stop_after_parse)

    def run(mod, argv):
        monkeypatch.setattr(sys, "argv", ["x", *argv])
        with pytest.raises(_Parsed) as got:
            mod.main()
        return vars(got.value.ns)

    return run


def _help(mod, monkeypatch, capsys, argv=("--help",)) -> str:
    monkeypatch.setattr(sys, "argv", ["x", *argv])
    with pytest.raises(SystemExit):
        mod.main()
    return capsys.readouterr().out


ITALIAN = re.compile(
    r"(?<![\w-])(stato|elenco|sposta|applica|pulizia|annulla|piano|carica|controlla|tutte|"
    r"--esegui|--perche|--casella|--principale|--solo-build|--chiudi|--apri|--aggiorna|--torna-a|"
    r"--nuovo|--quante|--risposta|--stampa|--minuti|--aspetta|--senza-cache|--da-zero|"
    r"CASELLA|PERCHE|QUANTE|MINUTI|REGISTRO)(?![\w-])"
)


INBOX_ZERO = {
    "stato": "status",
    "elenco": "list",
    "sposta": "move",
    "applica": "apply",
    "pulizia": "cleanup",
    "annulla": "undo",
}


@pytest.mark.parametrize(
    "english, italian",
    [
        (["status"], ["stato"]),
        (["list", "--mailbox", "work"], ["elenco", "--casella", "work"]),
        (
            ["move", "work", "a@b.example", "NEWS", "--reason", "r", "--main"],
            ["sposta", "work", "a@b.example", "NEWS", "--perche", "r", "--principale"],
        ),
        (["apply", "--execute"], ["applica", "--esegui"]),
        (
            ["cleanup", "--mailbox", "work", "--execute"],
            ["pulizia", "--casella", "work", "--esegui"],
        ),
        (["undo", "log.jsonl", "--execute"], ["annulla", "log.jsonl", "--esegui"]),
    ],
)
def test_inbox_zero_english_and_italian_parse_alike(parse, english, italian):
    mod = _load("tools/email/em-util-inbox-zero.py")
    en, it = parse(mod, english), parse(mod, italian)
    it["cmd"] = INBOX_ZERO[it["cmd"]]
    assert en == it


def test_inbox_zero_help_is_english(monkeypatch, capsys):
    mod = _load("tools/email/em-util-inbox-zero.py")
    for argv in (["--help"], *[[c, "--help"] for c in INBOX_ZERO.values()]):
        assert not ITALIAN.findall(_help(mod, monkeypatch, capsys, argv)), argv


@pytest.mark.parametrize(
    "rel, english, italian",
    [
        (
            "tools/secondbrain/installa.py",
            ["--build-only", "--close", "--open", "--update", "--roll-back-to", "1.2.3"],
            ["--solo-build", "--chiudi", "--apri", "--aggiorna", "--torna-a", "1.2.3"],
        ),
        (
            "tools/plaud/pl_lotto.py",
            ["--new", "--count", "7", "--answer", "3", "yes"],
            ["--nuovo", "--quante", "7", "--risposta", "3", "yes"],
        ),
        ("tools/plaud/pl_lunghe.py", ["list"], ["elenco"]),
        ("tools/plaud/pl_lunghe.py", ["plan", "rec1"], ["piano", "rec1"]),
        ("tools/plaud/pl_lunghe.py", ["upload", "rec1"], ["carica", "rec1"]),
        (
            "tools/plaud/pl_lunghe.py",
            ["check", "rec1", "--wait"],
            ["controlla", "rec1", "--aspetta"],
        ),
        ("tools/plaud/pl_lunghe.py", ["all", "--minutes", "30"], ["tutte", "--minuti", "30"]),
        ("tools/plaud/pl_quadro.py", ["--print-only"], ["--stampa"]),
        ("tools/plaud/regole/r1_fonti.py", ["--no-cache"], ["--senza-cache"]),
        ("tools/plaud/regole/r2_testo.py", ["--from-scratch"], ["--da-zero"]),
        ("tools/plaud/regole/r3_incroci.py", ["--print-only"], ["--stampa"]),
    ],
)
def test_flags_english_and_italian_parse_alike(parse, rel, english, italian):
    mod = _load(rel)
    assert parse(mod, english) == parse(mod, italian)


@pytest.mark.parametrize(
    "rel",
    [
        "tools/secondbrain/installa.py",
        "tools/plaud/pl_lotto.py",
        "tools/plaud/pl_lunghe.py",
        "tools/plaud/pl_quadro.py",
        "tools/plaud/regole/r1_fonti.py",
        "tools/plaud/regole/r2_testo.py",
        "tools/plaud/regole/r3_incroci.py",
    ],
)
def test_help_shows_no_italian_names(monkeypatch, capsys, rel):
    assert not ITALIAN.findall(_help(_load(rel), monkeypatch, capsys))


def test_pl_lotto_keeps_its_default_batch_size(parse):
    assert parse(_load("tools/plaud/pl_lotto.py"), ["--new"])["quante"] == 50


def test_app_calls_the_installer_with_english_flags():
    text = (ROOT / "tools/secondbrain/sb-app.py").read_text(encoding="utf-8")
    assert '"tools/secondbrain/installa.py", "--update"' in text
    assert '"tools/secondbrain/installa.py", "--roll-back-to"' in text


def test_overlap_lock_lines_are_english():
    for rel in (
        "tools/cross-source/xs-l3-graph.py",
        "tools/cross-source/rq-05-backfill-events.py",
        "tools/cross-source/xs-l3-shadow-extract.py",
        "tools/cross-source/xs-l2-person-deep-context.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "lock tenuto" not in text, rel
        assert "lock held by another instance, exit 75" in text, rel


def test_drift_report_missing_section_is_english(tmp_path):
    mod = _load("tools/security/drift_report.py")
    p = tmp_path / "classification.yaml"
    p.write_text("classes: {}\n", encoding="utf-8")
    with pytest.raises(
        mod.ClassificationError, match="classification: missing section: backup_policy"
    ):
        mod.load_classification(p)


@pytest.mark.parametrize("key", ["funds", "fondi"])
def test_inspiration_funds_group_accepts_the_english_key(monkeypatch, key):
    sys.path.insert(0, str(ROOT / "tools"))
    import sbk_config

    monkeypatch.setattr(
        sbk_config, "_USER_CFG", {"inspiration": {"clickup_lists": {"groups": {key: "L-42"}}}}
    )
    smista = _load("tools/secondbrain/sb_inspiration_smista.py")
    assert smista.DEL_GRUPPO["fondi"]["lista_id"] == "L-42"
