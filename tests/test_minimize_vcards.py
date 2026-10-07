import importlib.util
import os
import sqlite3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "minimize_vcards", os.path.join(REPO_ROOT, "scripts", "minimize_vcards.py"))
minimize_vcards = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(minimize_vcards)


VCF = """\
BEGIN:VCARD
VERSION:3.0
FN:Needed Person
TEL;TYPE=CELL:+85288888888
EMAIL:secret@example.com
ADR:;;Private St;City;;00000;Country
NOTE:private note
BDAY:19800101
END:VCARD

BEGIN:VCARD
VERSION:3.0
FN:Not In Whatsapp
TEL;TYPE=CELL:+85299999999
EMAIL:other@example.com
END:VCARD
"""


def _make_db(tmp_path, numbers):
    db = tmp_path / "msgstore.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE jid (_id INTEGER PRIMARY KEY, user TEXT, server TEXT, raw_string TEXT)")
    for i, number in enumerate(numbers, 1):
        con.execute(
            "INSERT INTO jid (_id, user, server, raw_string) VALUES (?, ?, ?, ?)",
            (i, number, "s.whatsapp.net", f"{number}@s.whatsapp.net"))
    con.commit()
    con.close()
    return str(db)


def test_needed_numbers_reads_phone_jids(tmp_path):
    db = _make_db(tmp_path, ["85288888888", "85299999999"])
    assert minimize_vcards.needed_numbers(db) == {"85288888888", "85299999999"}


def test_minimize_keeps_only_present_and_strips_other_fields(tmp_path):
    db = _make_db(tmp_path, ["85288888888"])
    vcf = tmp_path / "full.vcf"
    vcf.write_text(VCF, encoding="utf-8")

    out, total, kept_c, kept_n = minimize_vcards.minimize(
        str(vcf), minimize_vcards.needed_numbers(db), "852")

    assert (total, kept_c, kept_n) == (2, 1, 1)
    assert "Needed Person" in out
    assert "+85288888888" in out
    assert "Not In Whatsapp" not in out
    for stripped in ("EMAIL", "ADR", "NOTE", "BDAY"):
        assert stripped not in out
