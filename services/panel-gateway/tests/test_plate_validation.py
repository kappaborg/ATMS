"""Per-country plate validation + OCR-confusion disambiguation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import plate_validation as pv


def test_generic_rejects_garble_and_accepts_plates(monkeypatch):
    monkeypatch.setenv("PANEL_PLATE_COUNTRY", "generic")
    assert pv.is_valid("EFODZL")
    assert pv.is_valid("AB12CD")
    assert not pv.is_valid("DAKELANEMIOR")  # 12 chars — garbled OCR
    assert not pv.is_valid("AB")            # too short
    assert not pv.is_valid("")


def test_default_is_bosnia(monkeypatch):
    monkeypatch.delenv("PANEL_PLATE_COUNTRY", raising=False)
    assert pv.country() == "ba"


def test_bosnia_format(monkeypatch):
    monkeypatch.setenv("PANEL_PLATE_COUNTRY", "ba")
    assert pv.is_valid("A12K345")   # L DD L DDD (unified BiH letters)
    assert pv.is_valid("E01M234")
    assert pv.is_valid("GX15OGJ")   # EU fallback -> mixed/UK test footage still validates
    assert not pv.is_valid("AB")    # too short
    assert not pv.is_valid("DAKELANEMIOR")  # garbled OCR


def test_uk_format(monkeypatch):
    monkeypatch.setenv("PANEL_PLATE_COUNTRY", "uk")
    assert pv.is_valid("AB12CDE")           # current LL DD LLL
    assert not pv.is_valid("123456")        # all digits
    assert not pv.is_valid("ABCDEFG")       # all letters


def test_turkey_format(monkeypatch):
    monkeypatch.setenv("PANEL_PLATE_COUNTRY", "tr")
    assert pv.is_valid("34ABC123")
    assert pv.is_valid("06A1234")
    assert not pv.is_valid("ABCDEF")        # needs a 2-digit province prefix


def test_disambiguation_fixes_digit_positions(monkeypatch):
    monkeypatch.setenv("PANEL_PLATE_COUNTRY", "uk")
    # OCR misreads in the DD digit block: I->1, O->0, S->5, B->8
    assert pv.disambiguate("ABI2CDE") == "AB12CDE"
    assert pv.disambiguate("ABO2CDE") == "AB02CDE"
    assert pv.disambiguate("ABS2CDE") == "AB52CDE"


def test_disambiguation_leaves_valid_untouched(monkeypatch):
    monkeypatch.setenv("PANEL_PLATE_COUNTRY", "uk")
    assert pv.disambiguate("AB12CDE") == "AB12CDE"


def test_clean_strips_symbols_and_spaces():
    assert pv.clean("ab-12 cd.e") == "AB12CDE"


def test_class_string_expands_pattern():
    # LL DD LLL over 7 chars -> letters, digits, letters
    assert pv._class_string(r"[A-Z]{2}[0-9]{2}[A-Z]{3}", 7) == "LLDDLLL"
    assert pv._class_string(r"[A-Z]{2}[0-9]{2}[A-Z]{3}", 6) is None  # wrong length
