import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from Whatsapp_Chat_Exporter import android_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection, Timing
from Whatsapp_Chat_Exporter.utility import PersonFilter, get_person_chat_condition

REPO_ROOT = Path(__file__).parent.parent


def make_new_schema_db():
    """Build an in-memory database with the new schema's identity tables."""
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, raw_string TEXT UNIQUE, type INTEGER);
        CREATE TABLE jid_map (_id INTEGER PRIMARY KEY, lid_row_id INTEGER, jid_row_id INTEGER, sort_id INTEGER);
        CREATE TABLE group_participant_user (
            _id INTEGER PRIMARY KEY, group_jid_row_id INTEGER, user_jid_row_id INTEGER, pending INTEGER);
    """)
    return db


def add_jid(db, raw_string, jid_type=0):
    cursor = db.execute(
        "INSERT INTO jid (raw_string, type) VALUES (?, ?)", (raw_string, jid_type))
    return cursor.lastrowid


def add_participant(db, group_row_id, user_row_id):
    db.execute(
        "INSERT INTO group_participant_user (group_jid_row_id, user_jid_row_id) VALUES (?, ?)",
        (group_row_id, user_row_id))


def make_legacy_schema_db():
    """Build an in-memory database with only the legacy membership table."""
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, raw_string TEXT UNIQUE, type INTEGER);
        CREATE TABLE group_participants (_id INTEGER PRIMARY KEY, gjid TEXT, jid TEXT);
    """)
    return db


class TestResolvePersonFilter:
    def test_none_and_empty(self):
        assert android_handler.resolve_person_filter(None, None) is None
        assert android_handler.resolve_person_filter(None, []) is None

    def test_direct_and_created_need_no_membership(self):
        result = android_handler.resolve_person_filter(None, ["direct:111", "created:222"])
        assert result == PersonFilter(["111"], ["222"], [])

    def test_is_on_chat_new_schema(self):
        db = make_new_schema_db()
        person = add_jid(db, "111@s.whatsapp.net")
        group1 = add_jid(db, "111-1@g.us", 1)
        group2 = add_jid(db, "222-9@g.us", 1)
        add_participant(db, group1, person)
        add_participant(db, group2, person)

        result = android_handler.resolve_person_filter(db, ["is-on-chat:111"])
        assert result.member_chats == sorted([
            "111@s.whatsapp.net", "111-1@g.us", "222-9@g.us"])

    def test_is_on_chat_matches_lid_identity(self):
        """Participant rows keyed by a LID identity resolve via jid_map."""
        db = make_new_schema_db()
        person = add_jid(db, "111@s.whatsapp.net")
        lid = add_jid(db, "25280227881093@lid")
        group = add_jid(db, "111-1@g.us", 1)
        db.execute(
            "INSERT INTO jid_map (lid_row_id, jid_row_id) VALUES (?, ?)", (lid, person))
        add_participant(db, group, lid)

        result = android_handler.resolve_person_filter(db, ["is-on-chat:111"])
        assert result.member_chats == sorted(["111@s.whatsapp.net", "111-1@g.us"])

    def test_is_on_chat_coalesces_group_lid(self):
        """A group chat stored as a LID resolves to its phone-form JID."""
        db = make_new_schema_db()
        person = add_jid(db, "111@s.whatsapp.net")
        group_lid = add_jid(db, "9999-1@lid", 1)
        group_real = add_jid(db, "9999-1@g.us", 1)
        db.execute(
            "INSERT INTO jid_map (lid_row_id, jid_row_id) VALUES (?, ?)",
            (group_lid, group_real))
        add_participant(db, group_lid, person)

        result = android_handler.resolve_person_filter(db, ["is-on-chat:111"])
        assert result.member_chats == sorted(["111@s.whatsapp.net", "9999-1@g.us"])

    def test_is_on_chat_legacy_schema(self):
        db = make_legacy_schema_db()
        add_jid(db, "111@s.whatsapp.net")
        db.execute(
            "INSERT INTO group_participants (gjid, jid) VALUES ('111-1@g.us', '111@s.whatsapp.net')")

        result = android_handler.resolve_person_filter(db, ["is-on-chat:111"])
        assert result.member_chats == sorted(["111@s.whatsapp.net", "111-1@g.us"])

    def test_new_membership_table_preferred(self):
        """When both membership tables exist, group_participant_user wins."""
        db = make_new_schema_db()
        db.execute("CREATE TABLE group_participants (_id INTEGER PRIMARY KEY, gjid TEXT, jid TEXT)")
        person = add_jid(db, "111@s.whatsapp.net")
        group = add_jid(db, "111-1@g.us", 1)
        db.execute(
            "INSERT INTO group_participants (gjid, jid) VALUES ('old@g.us', '111@s.whatsapp.net')")
        add_participant(db, group, person)

        result = android_handler.resolve_person_filter(db, ["is-on-chat:111"])
        assert result.member_chats == sorted(["111@s.whatsapp.net", "111-1@g.us"])

    def test_unknown_number_warns_but_keeps_direct_chat(self, caplog):
        db = make_new_schema_db()
        with caplog.at_level(logging.WARNING):
            result = android_handler.resolve_person_filter(db, ["is-on-chat:111"])
        assert result.member_chats == ["111@s.whatsapp.net"]
        assert "is-on-chat:111" in caplog.text

    def test_known_person_without_groups_does_not_warn(self, caplog):
        db = make_new_schema_db()
        add_jid(db, "111@s.whatsapp.net")
        with caplog.at_level(logging.WARNING):
            result = android_handler.resolve_person_filter(db, ["is-on-chat:111"])
        assert "is-on-chat:111" not in caplog.text
        assert result.member_chats == ["111@s.whatsapp.net"]

    def test_invalid_mode_raises(self):
        db = make_new_schema_db()
        with pytest.raises(ValueError):
            android_handler.resolve_person_filter(db, ["bogus:111"])

    def test_multiple_values_union(self):
        db = make_new_schema_db()
        person = add_jid(db, "111@s.whatsapp.net")
        other = add_jid(db, "222@s.whatsapp.net")
        group = add_jid(db, "111-1@g.us", 1)
        add_participant(db, group, person)
        add_participant(db, group, other)

        result = android_handler.resolve_person_filter(
            db, ["is-on-chat:111", "is-on-chat:222", "direct:333", "created:444"])
        assert result.direct == ["333"]
        assert result.created == ["444"]
        assert result.member_chats == sorted([
            "111@s.whatsapp.net", "222@s.whatsapp.net", "111-1@g.us"])


def make_legacy_msgstore():
    """Build a minimal legacy-schema message database for integration tests."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE jid (_id INTEGER PRIMARY KEY, raw_string TEXT UNIQUE, type INTEGER);
        CREATE TABLE chat (_id INTEGER PRIMARY KEY, jid_row_id INTEGER UNIQUE, subject TEXT, hidden INTEGER);
        CREATE TABLE messages (
            _id INTEGER PRIMARY KEY, key_remote_jid TEXT, key_from_me INTEGER,
            timestamp INTEGER, data TEXT, status INTEGER, edit_version INTEGER,
            thumb_image BLOB, media_wa_type INTEGER, latitude REAL, longitude REAL,
            remote_resource TEXT, key_id TEXT, quoted_row_id INTEGER,
            media_caption TEXT, needs_push INTEGER,
            received_timestamp INTEGER, read_device_timestamp INTEGER);
        CREATE TABLE messages_quotes (_id INTEGER PRIMARY KEY, key_id TEXT, data TEXT);
        CREATE TABLE missed_call_logs (message_row_id INTEGER, video_call INTEGER);
        CREATE TABLE message_system (message_row_id INTEGER, action_type INTEGER);
        CREATE TABLE message_system_group (message_row_id INTEGER, is_me_joined INTEGER);
        CREATE TABLE message_system_number_change (message_row_id INTEGER, old_jid_row_id INTEGER, new_jid_row_id INTEGER);
        CREATE TABLE receipt_user (message_row_id INTEGER, receipt_timestamp INTEGER, read_timestamp INTEGER, played_timestamp INTEGER);
        CREATE TABLE message_media (message_row_id INTEGER, file_path TEXT);
        CREATE TABLE jid_map (_id INTEGER PRIMARY KEY, lid_row_id INTEGER, jid_row_id INTEGER, sort_id INTEGER);
        CREATE TABLE group_participants (_id INTEGER PRIMARY KEY, gjid TEXT, jid TEXT);

        -- Person's direct chat
        INSERT INTO jid (raw_string, type) VALUES ('111@s.whatsapp.net', 0);
        INSERT INTO chat (jid_row_id, subject, hidden) VALUES (1, NULL, 0);
        INSERT INTO messages (_id, key_remote_jid, key_from_me, timestamp, data, status, media_wa_type, needs_push)
            VALUES (1, '111@s.whatsapp.net', 0, 1000, 'hello from person', 1, 0, 0);

        -- Group the person is a member of, with a message from someone else
        INSERT INTO jid (raw_string, type) VALUES ('222-1@g.us', 1);
        INSERT INTO chat (jid_row_id, subject, hidden) VALUES (2, 'The Group', 0);
        INSERT INTO messages (_id, key_remote_jid, key_from_me, timestamp, data, status, media_wa_type, needs_push, remote_resource)
            VALUES (2, '222-1@g.us', 0, 2000, 'hello from someone else', 1, 0, 0, '333@s.whatsapp.net');
        INSERT INTO messages (_id, key_remote_jid, key_from_me, timestamp, data, status, media_wa_type, needs_push)
            VALUES (3, '222-1@g.us', 1, 3000, 'hello from me', 1, 0, 0);
        INSERT INTO group_participants (gjid, jid) VALUES ('222-1@g.us', '111@s.whatsapp.net');

        -- Unrelated chat
        INSERT INTO jid (raw_string, type) VALUES ('999@s.whatsapp.net', 0);
        INSERT INTO chat (jid_row_id, subject, hidden) VALUES (3, NULL, 0);
        INSERT INTO messages (_id, key_remote_jid, key_from_me, timestamp, data, status, media_wa_type, needs_push)
            VALUES (4, '999@s.whatsapp.net', 0, 4000, 'unrelated', 1, 0, 0);

        -- Media rows: one in the group, one in the unrelated chat
        INSERT INTO message_media (message_row_id, file_path) VALUES (2, 'Media/group.jpg');
        INSERT INTO message_media (message_row_id, file_path) VALUES (4, 'Media/unrelated.jpg');
    """)
    return db


class TestPersonFilterIntegration:
    def test_is_on_chat_keeps_full_context(self):
        """is-on-chat selects whole chats, keeping other participants' messages."""
        db = make_legacy_msgstore()
        data = ChatCollection()
        person_filter = android_handler.resolve_person_filter(db, ["is-on-chat:111"])

        android_handler.messages(db, data, None, Timing(0), None, (None, None, person_filter), True, False)

        assert "111@s.whatsapp.net" in data
        assert "222-1@g.us" in data
        assert "999@s.whatsapp.net" not in data
        group_chat = data["222-1@g.us"]
        assert group_chat.get_message(2) is not None, "the other participant's message must be kept"
        assert group_chat.get_message(3) is not None, "my own message must be kept"

    def test_direct_selects_only_the_direct_chat(self):
        db = make_legacy_msgstore()
        data = ChatCollection()
        person_filter = android_handler.resolve_person_filter(db, ["direct:111"])

        android_handler.messages(db, data, None, Timing(0), None, (None, None, person_filter), True, False)

        assert "111@s.whatsapp.net" in data
        assert "222-1@g.us" not in data
        assert "999@s.whatsapp.net" not in data

    def test_created_selects_created_groups(self):
        db = make_legacy_msgstore()
        data = ChatCollection()
        person_filter = android_handler.resolve_person_filter(db, ["created:222"])

        android_handler.messages(db, data, None, Timing(0), None, (None, None, person_filter), True, False)

        assert "222-1@g.us" in data
        assert "111@s.whatsapp.net" not in data

    def test_calls_respect_person_filter(self):
        db = make_legacy_msgstore()
        db.executescript("""
            CREATE TABLE call_log (
                _id INTEGER PRIMARY KEY, jid_row_id INTEGER, from_me INTEGER,
                call_id TEXT, timestamp INTEGER, video_call INTEGER, duration INTEGER,
                call_result INTEGER, bytes_transferred INTEGER);
            INSERT INTO call_log (jid_row_id, timestamp) VALUES (1, 5000);
            INSERT INTO call_log (jid_row_id, timestamp) VALUES (3, 6000);
        """)
        data = ChatCollection()
        person_filter = android_handler.resolve_person_filter(db, ["direct:111"])

        android_handler.calls(db, data, Timing(0), (None, None, person_filter))

        assert "000000000000000" in data
        call_chat = data["000000000000000"]
        assert call_chat.get_message(1) is not None, "the call with the filtered person must be kept"
        assert call_chat.get_message(2) is None, "the unrelated call must be filtered out"

    def test_person_condition_applies_to_media_count(self):
        """The media count query splices the person condition and filters."""
        db = make_legacy_msgstore()
        cursor = db.cursor()
        person_filter = PersonFilter([], [], ["111@s.whatsapp.net", "222-1@g.us"])
        count = android_handler._get_media_count(cursor, True, None, (None, None, person_filter))
        assert count == 1  # only the group's media row; the unrelated one is filtered out


def run_cli(args):
    """Run the exporter CLI from the repository root."""
    return subprocess.run(
        [sys.executable, "-m", "Whatsapp_Chat_Exporter"] + args,
        capture_output=True, text=True, cwd=REPO_ROOT, check=False)


class TestPersonCliValidation:
    def test_invalid_mode(self):
        result = run_cli(["-a", "--person", "bogus:123"])
        assert result.returncode == 2
        assert "Invalid --person value 'bogus:123'" in result.stderr

    def test_invalid_number(self):
        result = run_cli(["-a", "--person", "direct:notanumber"])
        assert result.returncode == 2
        assert "Expected MODE:phone number" in result.stderr

    def test_missing_separator(self):
        result = run_cli(["-a", "--person", "direct"])
        assert result.returncode == 2
        assert "Invalid --person value 'direct'" in result.stderr

    def test_mutual_exclusion_with_include(self):
        result = run_cli(["-a", "--person", "direct:123", "--include", "456"])
        assert result.returncode == 2
        assert "cannot be used together with --include or --exclude" in result.stderr

    def test_mutual_exclusion_with_exclude(self):
        result = run_cli(["-a", "--person", "direct:123", "--exclude", "456"])
        assert result.returncode == 2
        assert "cannot be used together with --include or --exclude" in result.stderr

    def test_ios_not_supported(self):
        result = run_cli(["-i", "--person", "direct:123"])
        assert result.returncode == 2
        assert "not yet supported on iOS" in result.stderr

    def test_exported_not_supported(self):
        result = run_cli(["-e", "some.txt", "--person", "direct:123"])
        assert result.returncode == 2
        assert "cannot be used with --exported or --import" in result.stderr

    def test_import_not_supported(self):
        result = run_cli(["--import", "--person", "direct:123"])
        assert result.returncode == 2
        assert "cannot be used with --exported or --import" in result.stderr