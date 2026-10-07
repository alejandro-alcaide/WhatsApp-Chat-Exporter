#!/usr/bin/env python3
"""Reduce a full vCard export to only the contacts referenced by a msgstore.db.

Why: WhatsApp's encrypted backup (wa.db.cryptNN) does not include the address
book, so `--enrich-from-vcards` is the only way to recover names. A Google/phone
vCard export, however, carries every contact (most of them not on WhatsApp) and
every field (email, address, notes, birthday, photo, ...). This script keeps
only {name, matching TEL(s)} for the numbers that actually appear in the given
WhatsApp database, and drops everything else.

It reuses the exporter's own vCard parsing/number normalization
(process_vcard_entry / map_number_to_name) so the kept numbers match exactly
how `wtsexporter --enrich-from-vcards` compares them.

The message/media databases are only read; nothing is written to them.
"""
import argparse
import os
import sqlite3
import sys
from typing import Iterable, List, Set, Tuple

from Whatsapp_Chat_Exporter.vcards_contacts import (
    process_vcard_entry,
    map_number_to_name,
)


def _digits(value: str) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def needed_numbers(db_path: str) -> Set[str]:
    """Collect the phone numbers (JID user parts) the database knows about.

    Enrichment in the exporter matches a vCard number `v` against chats whose
    JID starts with `v`; the chat JID is `<digits>@s.whatsapp.net`. So the set
    of chat digits is the superset of what can be matched. We read every phone
    JID from `jid`, falling back to legacy columns if the schema is older.
    """
    numbers: Set[str] = set()
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jid'")
        if cur.fetchone():
            for (user,) in cur.execute(
                    "SELECT user FROM jid WHERE server='s.whatsapp.net'"):
                d = _digits(user)
                if d:
                    numbers.add(d)
            # jid_map: the phone side of every LID mapping
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='jid_map'")
            if cur.fetchone():
                for row in cur.execute(
                        "SELECT j.raw_string FROM jid_map m "
                        "JOIN jid j ON j._id = m.jid_row_id"):
                    d = _digits(row[0].split("@")[0])
                    if d:
                        numbers.add(d)
        else:
            # Legacy schema: scrape JIDs out of the message tables.
            for table, col in (("messages", "key_remote_jid"),
                               ("message", "key_remote_jid"),
                               ("messages", "remote_resource"),
                               ("message", "remote_resource")):
                try:
                    for (raw,) in cur.execute(
                            f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL"):
                        d = _digits(raw.split("@")[0])
                        if d:
                            numbers.add(d)
                except sqlite3.OperationalError:
                    continue
    finally:
        con.close()
    return numbers


def _matches(normalized: str, needed: Set[str]) -> bool:
    # Mirror `filter_chats_by_prefix`: the chat JID (`<digits>@s.whatsapp.net`)
    # starts with the vCard number, i.e. digits.startswith(normalized).
    return any(n == normalized or n.startswith(normalized) for n in needed)


def _escape_name(name: str) -> str:
    # Minimal: keep it on one line. The exporter reads FN verbatim.
    return " ".join(name.split())


def minimize(vcf_path: str, needed: Set[str], country_code: str
             ) -> Tuple[str, int, int, int]:
    with open(vcf_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    blocks = []
    total = 0
    kept_contacts = 0
    kept_numbers = 0

    for part in content.split("BEGIN:VCARD"):
        if "END:VCARD" not in part:
            continue
        total += 1
        contact = process_vcard_entry(part)
        if not contact:
            continue

        numbers = contact["numbers"]
        mapping = list(map_number_to_name([contact], country_code))
        kept = []
        for i, item in enumerate(numbers):
            if i >= len(mapping):
                break
            # Older exporter versions return plain TEL strings; newer ones
            # return (value, waid) tuples.
            value, waid = item if isinstance(item, tuple) else (item, None)
            if _matches(mapping[i][0], needed):
                kept.append((value, waid, mapping[i][0]))
        if not kept:
            continue

        name = _escape_name(contact["full_name"])
        block = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{name}"]
        for value, waid, normalized in kept:
            if waid:
                block.append(f"TEL;WAID={_digits(waid)}:{value}")
            else:
                block.append(f"TEL:{value}")
            kept_numbers += 1
        block.append("END:VCARD")
        blocks.append("\n".join(block))
        kept_contacts += 1

    return "\n\n".join(blocks) + "\n", total, kept_contacts, kept_numbers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="Path to msgstore.db")
    ap.add_argument("--vcards", required=True, help="Path to the full .vcf export")
    ap.add_argument("--output", required=True, help="Path for the minimized .vcf")
    ap.add_argument("--country-code", default="",
                    help="Country code used for numbers without one (same value you pass to wtsexporter --default-country-code)")
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.vcards):
        print(f"error: vCard file not found: {args.vcards}", file=sys.stderr)
        return 2

    needed = needed_numbers(args.db)
    out, total, kept_c, kept_n = minimize(args.vcards, needed, args.country_code)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(out)

    def size(p):
        return os.path.getsize(p)
    print(f"DB numbers known:        {len(needed)}")
    print(f"Contacts in vCard:       {total}")
    print(f"Contacts kept:           {kept_c}")
    print(f"Numbers (TEL) kept:      {kept_n}")
    print(f"Input size:              {size(args.vcards)} bytes")
    print(f"Output size:             {size(args.output)} bytes")
    print(f"Written:                 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
