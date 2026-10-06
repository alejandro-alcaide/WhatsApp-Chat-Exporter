import logging
import sqlite3

import pytest

from Whatsapp_Chat_Exporter import android_handler


@pytest.fixture
def media_db():
    """In-memory database with message_media rows referencing a standard layout."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE message_media (message_row_id INTEGER, file_path TEXT)")
    db.executemany(
        "INSERT INTO message_media (message_row_id, file_path) VALUES (?, ?)",
        [(1, "Media/WhatsApp Images/a.jpg"),
         (2, "Media/WhatsApp Images/b.jpg"),
         (3, "Media/WhatsApp Video/c.mp4"),
         (4, "Media/WhatsApp Voice Notes/d.ogg"),
         (5, None),
         (6, "")])
    return db


class TestCheckMediaFolderStructure:
    def test_correct_layout_is_silent(self, media_db, tmp_path, caplog):
        for folder in ("WhatsApp Images", "WhatsApp Video", "WhatsApp Voice Notes"):
            (tmp_path / "Media" / folder).mkdir(parents=True)
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(media_db.cursor(), str(tmp_path))
        assert caplog.text == ""

    def test_one_level_short_logs_error(self, media_db, tmp_path, caplog):
        # The phone's WhatsApp folder copied without its Media level
        for folder in ("WhatsApp Images", "WhatsApp Video", "WhatsApp Voice Notes"):
            (tmp_path / folder).mkdir(parents=True)
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(media_db.cursor(), str(tmp_path))
        assert "found 0 of 3 expected media items" in caplog.text
        assert "Media/WhatsApp Images" in caplog.text
        assert "All media will render as missing" in caplog.text

    def test_partial_layout_logs_warning(self, media_db, tmp_path, caplog):
        (tmp_path / "Media" / "WhatsApp Images").mkdir(parents=True)
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(media_db.cursor(), str(tmp_path))
        assert "found 1 of 3 expected media items" in caplog.text
        assert "WhatsApp Video" in caplog.text
        assert "ERROR" not in caplog.text

    def test_report_includes_a_status_table(self, media_db, tmp_path, caplog):
        (tmp_path / "Media" / "WhatsApp Images").mkdir(parents=True)
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(media_db.cursor(), str(tmp_path))
        lines = caplog.text.splitlines()
        table = [line for line in lines if line.lstrip().startswith(("Status", "missing", "found"))]
        assert f"  {'Status':<9}{'Type':<8}Expected item" in table
        assert "  missing  folder  Media/WhatsApp Video" in table
        assert "  found    folder  Media/WhatsApp Images" in table

    def test_file_references_are_checked_as_files(self, tmp_path, caplog):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE message_media (message_row_id INTEGER, file_path TEXT)")
        db.executemany(
            "INSERT INTO message_media (message_row_id, file_path) VALUES (?, ?)",
            [(1, "Media/WhatsApp Images/a.jpg"),
             (2, ".Shared/tralala.opus"),
             (3, "/data/user/0/com.whatsapp/files/.Shared/76ff49")])
        (tmp_path / "Media" / "WhatsApp Images").mkdir(parents=True)
        shared = tmp_path / ".Shared" / "tralala.opus"
        shared.parent.mkdir()
        shared.touch()
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(db.cursor(), str(tmp_path))
        # The present file and folder are found; the absolute phone path
        # can never resolve relative to the media folder.
        assert "found 2 of 3 expected media items" in caplog.text
        assert "  found    file    .Shared/tralala.opus" in caplog.text
        assert "  missing  file    /data/user/0/com.whatsapp/files/.Shared/76ff49" in caplog.text
        assert "folder" in caplog.text

    def test_absolute_file_paths_only_do_not_trigger_the_scan(self, tmp_path, caplog):
        # A database with nothing but absolute paths has no relative layout
        # expectation; the scan should stay quiet.
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE message_media (message_row_id INTEGER, file_path TEXT)")
        db.execute(
            "INSERT INTO message_media (message_row_id, file_path) "
            "VALUES (1, '/data/user/0/com.whatsapp/files/.Shared/76ff49')")
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(db.cursor(), str(tmp_path))
        assert caplog.text == ""

    def test_nonexistent_media_folder_logs_error(self, media_db, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(
                media_db.cursor(), str(tmp_path / "does-not-exist"))
        assert "found 0 of 3 expected media items" in caplog.text

    def test_no_message_media_table_is_silent(self, tmp_path, caplog):
        db = sqlite3.connect(":memory:")
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(db.cursor(), str(tmp_path))
        assert caplog.text == ""

    def test_none_media_folder_is_silent(self, media_db, caplog):
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(media_db.cursor(), None)
        assert caplog.text == ""

    def test_only_empty_file_paths_is_silent(self, tmp_path, caplog):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE message_media (message_row_id INTEGER, file_path TEXT)")
        db.execute("INSERT INTO message_media (message_row_id, file_path) VALUES (1, NULL)")
        with caplog.at_level(logging.WARNING):
            android_handler._check_media_folder_structure(db.cursor(), str(tmp_path))
        assert caplog.text == ""