import os
from argparse import Namespace

from Whatsapp_Chat_Exporter.__main__ import (
    get_output_media_folder,
    handle_media_directory,
)


def make_media_tree(tmp_path, monkeypatch):
    """Create a fake media folder with original and generated content, and
    run from tmp_path so the media path stays relative, like the real CLI."""
    monkeypatch.chdir(tmp_path)
    media_dir = tmp_path / "media"
    (media_dir / "Media").mkdir(parents=True)
    (media_dir / "Media" / "a.jpg").write_text("original media")
    (media_dir / "Media" / "Profile").mkdir()
    (media_dir / "Media" / "Profile" / "avatar.jpg").write_text("avatar")
    (media_dir / "Message" / "vCards").mkdir(parents=True)
    (media_dir / "Message" / "vCards" / "c.vcf").write_text("ios vcard")
    (media_dir / "separated" / "chat").mkdir(parents=True)
    (media_dir / "separated" / "chat" / "a.jpg").write_text("separated media")
    (media_dir / "thumbnails").mkdir()
    (media_dir / "thumbnails" / "t.png").write_text("thumbnail")
    (media_dir / "vCards").mkdir()
    (media_dir / "vCards" / "c.vcf").write_text("vcard")
    return media_dir


def make_args(tmp_path, **overrides):
    output_dir = tmp_path / "result"
    os.makedirs(output_dir, exist_ok=True)
    args = Namespace(
        media="media",
        output="result",
        move_media=False,
        separate_media=False,
        android=False,
        ios=False
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args, output_dir / "media"


def test_default_copies_whole_media_tree(tmp_path, monkeypatch):
    media_dir = make_media_tree(tmp_path, monkeypatch)
    args, media_path = make_args(tmp_path)

    handle_media_directory(args)

    assert (media_path / "Media" / "a.jpg").is_file()
    assert (media_path / "separated" / "chat" / "a.jpg").is_file()
    assert (media_path / "thumbnails" / "t.png").is_file()
    assert (media_path / "vCards" / "c.vcf").is_file()
    assert media_dir.is_dir(), "Original media folder must not be removed by a copy"


def test_separated_mode_copies_only_referenced_folders(tmp_path, monkeypatch):
    make_media_tree(tmp_path, monkeypatch)
    args, media_path = make_args(tmp_path, separate_media=True)

    handle_media_directory(args)

    assert not (media_path / "Media").exists(), \
        "The original media tree is not referenced in separated mode and must not be copied"
    assert (media_path / "separated" / "chat" / "a.jpg").is_file()
    assert (media_path / "thumbnails" / "t.png").is_file()
    assert (media_path / "vCards" / "c.vcf").is_file()


def test_separated_mode_ios_includes_avatars_and_vcards(tmp_path, monkeypatch):
    make_media_tree(tmp_path, monkeypatch)
    args, media_path = make_args(tmp_path, separate_media=True, ios=True)

    handle_media_directory(args)

    assert (media_path / "separated" / "chat" / "a.jpg").is_file()
    assert (media_path / "Media" / "Profile" / "avatar.jpg").is_file(), \
        "iOS avatars are referenced from Media/Profile and must be copied"
    assert (media_path / "Message" / "vCards" / "c.vcf").is_file(), \
        "iOS vCards are referenced from Message/vCards and must be copied"
    assert not (media_path / "Media" / "a.jpg").exists(), \
        "iOS original media must still not be copied in separated mode"
    assert not (media_path / "thumbnails").exists(), \
        "iOS does not generate thumbnails"


def test_separated_mode_refreshes_generated_folders_on_rerun(tmp_path, monkeypatch):
    media_dir = make_media_tree(tmp_path, monkeypatch)
    args, media_path = make_args(tmp_path, separate_media=True)

    handle_media_directory(args)
    (media_dir / "separated" / "chat" / "b.jpg").write_text("new separated media")
    handle_media_directory(args)

    assert (media_path / "separated" / "chat" / "b.jpg").is_file(), \
        "A re-run must copy media added to separated/ since the last run"


def test_move_media_moves_whole_tree(tmp_path, monkeypatch):
    media_dir = make_media_tree(tmp_path, monkeypatch)
    args, media_path = make_args(tmp_path, move_media=True)

    handle_media_directory(args)

    assert not media_dir.exists(), "The media folder must be moved away"
    assert (media_path / "Media" / "a.jpg").is_file()
    assert (media_path / "separated" / "chat" / "a.jpg").is_file()


def test_move_media_takes_precedence_over_separated_mode(tmp_path, monkeypatch):
    make_media_tree(tmp_path, monkeypatch)
    args, media_path = make_args(tmp_path, move_media=True, separate_media=True)

    handle_media_directory(args)

    assert not (tmp_path / "media").exists(), \
        "-c moves the whole folder regardless of separated mode"
    assert (media_path / "Media" / "a.jpg").is_file()


def test_separated_mode_android_copies_nothing(tmp_path, monkeypatch):
    # On Android the generated copies were already written directly into
    # the output directory during processing; the copy step must not
    # duplicate them or re-copy leftovers from the media folder.
    make_media_tree(tmp_path, monkeypatch)
    args, media_path = make_args(tmp_path, separate_media=True, android=True)

    handle_media_directory(args)

    assert not media_path.exists(), \
        "On Android in separated mode nothing must be copied after processing"


def test_output_media_folder_is_in_the_output_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args, _ = make_args(tmp_path, separate_media=True, android=True)

    assert get_output_media_folder(args) == os.path.join("result", "media")


def test_output_media_folder_requires_android(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args, _ = make_args(tmp_path, separate_media=True, android=False)

    assert get_output_media_folder(args) is None


def test_output_media_folder_not_with_move_media(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args, _ = make_args(tmp_path, separate_media=True, android=True, move_media=True)

    assert get_output_media_folder(args) is None


def test_output_media_folder_none_for_absolute_media(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args, _ = make_args(tmp_path, separate_media=True, android=True,
                        media=str(tmp_path / "media"))

    assert get_output_media_folder(args) is None


def test_output_media_folder_none_without_media(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args, _ = make_args(tmp_path, separate_media=True, android=True, media=None)

    assert get_output_media_folder(args) is None