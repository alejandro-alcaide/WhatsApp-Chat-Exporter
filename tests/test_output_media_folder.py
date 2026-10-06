import os
from base64 import b64encode
from mimetypes import MimeTypes

import pytest

from Whatsapp_Chat_Exporter import android_handler
from Whatsapp_Chat_Exporter.data_model import ChatCollection, ChatStore, Message
from Whatsapp_Chat_Exporter.utility import Device

JID = "1234567890@s.whatsapp.net"
THUMB_NAME = b"hash".hex() + ".png"


@pytest.fixture
def media_data(tmp_path, monkeypatch):
    """Chat collection with one message whose media file exists, run from
    tmp_path with a relative media folder, like the real CLI."""
    monkeypatch.chdir(tmp_path)
    media = tmp_path / "media"
    (media / "Media").mkdir(parents=True)
    (media / "Media" / "a.jpg").write_bytes(b"original media")
    data = ChatCollection()
    chat = ChatStore(Device.ANDROID, name="Test Chat")
    chat.add_message(1, Message(from_me=False, timestamp=0, time="00:00", key_id=1))
    data[JID] = chat
    content = {
        "file_path": "Media/a.jpg",
        "key_remote_jid": JID,
        "message_row_id": 1,
        "mime_type": "image/jpeg",
        "thumbnail": b"thumbnail bytes",
        "file_hash": b64encode(b"hash"),
    }
    return data, content


class TestProcessSingleMedia:
    def test_copies_are_written_to_output_folder(self, media_data):
        data, content = media_data
        output_media = os.path.join("result", "media")
        os.makedirs(os.path.join(output_media, "thumbnails"))

        android_handler._process_single_media(
            data, content, "media", MimeTypes(), True, False, output_media)

        message = data[JID].get_message(1)
        assert os.path.isfile(os.path.join(output_media, "separated", "Test-Chat", "a.jpg"))
        assert message.data == os.path.join("media", "separated", "Test-Chat", "a.jpg"), \
            "The message must reference the copy relative to the media folder"
        assert os.path.isfile(os.path.join(output_media, "thumbnails", THUMB_NAME))
        assert message.thumb == os.path.join("media", "thumbnails", THUMB_NAME)
        assert not os.path.exists("media/separated")
        assert not os.path.exists("media/thumbnails"), \
            "The media folder must stay untouched when copies go to the output"

    def test_without_output_folder_copies_stay_in_media_folder(self, media_data):
        data, content = media_data
        os.makedirs("media/thumbnails")

        android_handler._process_single_media(
            data, content, "media", MimeTypes(), True, False)

        message = data[JID].get_message(1)
        assert os.path.isfile(os.path.join("media", "separated", "Test-Chat", "a.jpg"))
        assert message.data == os.path.join("media", "separated", "Test-Chat", "a.jpg")
        assert os.path.isfile(os.path.join("media", "thumbnails", THUMB_NAME))
        assert message.thumb == os.path.join("media", "thumbnails", THUMB_NAME)


class TestProcessVcardRow:
    def test_vcard_written_to_output_folder(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = ChatCollection()
        chat = ChatStore(Device.ANDROID, name="Test Chat")
        chat.add_message(1, Message(from_me=False, timestamp=0, time="00:00", key_id=1))
        data[JID] = chat
        row = {"media_name": "Contact", "vcard": "BEGIN:VCARD",
               "key_remote_jid": JID, "message_row_id": 1}
        os.makedirs(os.path.join("result", "media", "vCards"))

        android_handler._process_vcard_row(
            row, os.path.join("result", "media", "vCards"),
            os.path.join("media", "vCards"), data)

        message = data[JID].get_message(1)
        assert os.path.isfile(os.path.join("result", "media", "vCards", "Contact.vcf"))
        assert f'href="{os.path.join("media", "vCards", "Contact.vcf")}"' in message.data
        assert not os.path.exists("media/vCards"), \
            "The media folder must stay untouched when copies go to the output"