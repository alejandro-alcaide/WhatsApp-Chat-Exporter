"""Tests for vCard processing.

Regression tests for a crash found on real data (WhatsApp Business 2026,
hybrid schema): vCard rows keyed by raw LIDs while the ChatCollection is
keyed by phone JIDs resolved through jid_map, plus the resulting guard in
_process_vcard_row.
"""
import sqlite3

from Whatsapp_Chat_Exporter import android_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message
from Whatsapp_Chat_Exporter.utility import Device

PHONE_JID = "1234567890@s.whatsapp.net"
LID_JID = "987654321098765@lid"


def _row(**overrides):
    row = {
        "message_row_id": 1,
        "key_remote_jid": PHONE_JID,
        "vcard": "BEGIN:VCARD\nEND:VCARD",
        "media_name": "Someone",
        "group_sender_jid": None,
    }
    row.update(overrides)
    return row


def _collection_with_message():
    data = ChatCollection()
    chat = ChatStore(Device.ANDROID, name=None)
    chat = ChatStore(Device.ANDROID, name=None)
    # the real flow keys messages by the raw int message._id
    chat.add_message(1, Message(
        from_me=False, timestamp=1700000000, time=1700000000, key_id=1))
    data.add_chat(PHONE_JID, chat)
    return data


class TestProcessVcardRow:
    def test_happy_path_attaches_message_and_writes_file(self, tmp_path):
        data = _collection_with_message()
        result = android_handler._process_vcard_row(
            _row(), str(tmp_path), str(tmp_path), data)
        assert result is True
        message = data.get_chat(PHONE_JID).get_message(1)
        assert message.meta is True
        assert message.mime == "text/x-vcard"
        assert "Someone" in message.data
        assert list(tmp_path.iterdir()) != []

    def test_skips_when_chat_missing(self, tmp_path):
        data = ChatCollection()  # no chats at all
        result = android_handler._process_vcard_row(
            _row(), str(tmp_path), str(tmp_path), data)
        assert result is False
        assert list(tmp_path.iterdir()) == []

    def test_skips_when_message_missing(self, tmp_path):
        data = ChatCollection()
        data.add_chat(PHONE_JID, ChatStore(Device.ANDROID, name=None))  # chat exists, message does not
        result = android_handler._process_vcard_row(
            _row(), str(tmp_path), str(tmp_path), data)
        assert result is False
        assert list(tmp_path.iterdir()) == []


def _legacy_vcard_db():
    """In-memory DB with the legacy table naming (message, message_vcard)
    but jid_map-era LID data, like the WhatsApp Business schema."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    c = db.cursor()
    c.executescript("""
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, raw_string TEXT);
        CREATE TABLE jid_map (lid_row_id INTEGER, jid_row_id INTEGER);
        CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER);
        CREATE TABLE message (_id INTEGER PRIMARY KEY,
                              key_remote_jid TEXT,
                              chat_row_id INTEGER,
                              timestamp INTEGER,
                              text_data TEXT,
                              sender_jid_row_id INTEGER);
        CREATE TABLE message_vcard (message_row_id INTEGER, vcard TEXT);
    """)
    c.execute("INSERT INTO jid VALUES (1, ?)", (PHONE_JID,))
    c.execute("INSERT INTO jid VALUES (2, ?)", (LID_JID,))
    c.execute("INSERT INTO jid VALUES (3, '111222333444555@lid')")  # unmapped LID
    c.execute("INSERT INTO jid_map VALUES (2, 1)")
    c.execute("INSERT INTO chat VALUES (1, 2)")
    c.execute("INSERT INTO chat VALUES (2, 3)")
    c.execute('INSERT INTO message VALUES (1, ?, 1, 1700000000, "Contact", NULL)',
              (LID_JID,))
    c.execute('INSERT INTO message VALUES (2, ?, 2, 1700000001, "Other", NULL)',
              ("111222333444555@lid",))
    c.execute('INSERT INTO message_vcard VALUES (1, "BEGIN:VCARD")')
    c.execute('INSERT INTO message_vcard VALUES (2, "BEGIN:VCARD")')
    db.commit()
    return db


class TestLegacyVcardQueryLidCoalescing:
    def test_lid_is_resolved_to_phone_jid_when_jid_map_exists(self):
        db = _legacy_vcard_db()
        rows = android_handler._execute_vcard_query_legacy(
            db.cursor(), None, (None, None, None), False, True)
        assert {r["key_remote_jid"] for r in rows} == {
            PHONE_JID, "111222333444555@lid"}

    def test_raw_jid_returned_when_jid_map_absent(self):
        db = _legacy_vcard_db()
        rows = android_handler._execute_vcard_query_legacy(
            db.cursor(), None, (None, None, None), False, False)
        assert {r["key_remote_jid"] for r in rows} == {
            LID_JID, "111222333444555@lid"}


class TestVcardSummary:
    def test_skipped_rows_are_counted_and_warned(self, caplog):
        import logging
        db = _legacy_vcard_db()
        data = _collection_with_message()  # chat exists, but keyed by phone jid
        with caplog.at_level(logging.WARNING):
            android_handler.vcard(
                db, data, media_folder=".", filter_date=None,
                filter_chat=(None, None, None), filter_empty=False)
        message = data.get_chat(PHONE_JID).get_message(1)
        assert message.meta is True
        assert any("1 of 2 vCards" in r.message for r in caplog.records)