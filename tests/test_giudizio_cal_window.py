"""The calibration window is derived from the eval records' own months.

No author date range is baked into tools/plaud/regole/giudizio.py: with the
SBK_CAL_* env vars unset, finestra_cal() must read the span and the train/test
split from the records it is given. Run alone:

    uv run pytest tests/test_giudizio_cal_window.py -q
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.plaud.regole import giudizio  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cal_env():
    """Simulate SBK_CAL_* unset regardless of the ambient environment."""
    saved = dict(giudizio._CAL_ENV)
    giudizio._CAL_ENV.update(start=None, train_end=None, test_start=None, end=None)
    try:
        yield
    finally:
        giudizio._CAL_ENV.update(saved)


def _rec(month: str, name: str = "alex") -> dict:
    """A minimal silver record (owner-labelled voice) dated in `month` (YYYY-MM)."""
    return {
        "id": f"r-{month}",
        "data": f"{month}-15T10:00:00",
        "voci": [
            {"slot": 0, "prov": "Plaud o il proprietario", "nome": name, "classe": "nome"},
        ],
    }


def test_mese_dopo_wraps_the_year():
    assert giudizio._mese_dopo("2026-08") == "2026-09"
    assert giudizio._mese_dopo("2026-12") == "2027-01"


def test_window_is_derived_from_the_record_months():
    regs = [_rec(f"2026-{m:02d}") for m in range(1, 9)]  # 8 consecutive months
    start, train_end, test_start, end = giudizio.finestra_cal(regs)
    assert (start, end) == ("2026-01", "2026-08")  # full span, no baked-in range
    assert train_end < test_start  # disjoint train / test
    # earlier ~60% of 8 distinct months -> train ends at the 5th month
    assert (train_end, test_start) == ("2026-05", "2026-06")


def test_window_follows_a_different_dataset():
    # A dataset entirely outside 2026 must still produce a valid, non-empty split.
    regs = [_rec(m) for m in ("2030-02", "2030-03", "2030-04", "2030-05")]
    start, train_end, test_start, end = giudizio.finestra_cal(regs)
    assert start == "2030-02" and end == "2030-05"
    assert train_end < test_start
    assert train_end in {"2030-02", "2030-03"} and test_start in {"2030-03", "2030-04"}


def test_single_month_keeps_everything_in_train_and_no_test():
    regs = [_rec("2026-03"), _rec("2026-03")]
    start, train_end, test_start, end = giudizio.finestra_cal(regs)
    assert (start, train_end, end) == ("2026-03", "2026-03", "2026-03")
    assert test_start == "2026-04"  # pushed past the data, so the test split is empty
    assert giudizio._test(regs) == {}


def test_empty_records_give_empty_bounds():
    assert giudizio.finestra_cal([]) == ("", "", "", "")


def test_env_overrides_a_single_bound():
    giudizio._CAL_ENV.update(start="2025-01")
    regs = [_rec(f"2026-{m:02d}") for m in range(1, 9)]
    start, _train_end, _test_start, end = giudizio.finestra_cal(regs)
    assert start == "2025-01"  # override honoured
    assert end == "2026-08"  # the rest still derived


def test_argento_and_test_use_the_derived_window():
    regs = [_rec(f"2026-{m:02d}") for m in range(1, 9)]
    # the window spans every month, so all 8 owner voices are silver examples
    assert len(giudizio.argento(regs)) == 8
    # test split = months >= 2026-06 -> Jun, Jul, Aug
    assert len(giudizio._test(regs)) == 3
