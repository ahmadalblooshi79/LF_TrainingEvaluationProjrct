from pathlib import Path

from app.exercise_workspace_images import save_workspace_image

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)
_MIN_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)


def test_save_workspace_image_png_and_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.exercise_workspace_images.EXERCISE_WORKSPACE_IMAGE_DIR", tmp_path
    )
    rel = save_workspace_image(7, "program", "chart.png", _MIN_PNG)
    assert rel == "7/program.png"
    assert (tmp_path / rel).is_file()
    rel2 = save_workspace_image(7, "program", "next.jpg", _MIN_JPEG)
    assert rel2 == "7/program.jpg"
    assert not (tmp_path / "7" / "program.png").exists()
    assert (tmp_path / rel2).is_file()


def test_save_workspace_image_rejects_non_image(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.exercise_workspace_images.EXERCISE_WORKSPACE_IMAGE_DIR", tmp_path
    )
    try:
        save_workspace_image(3, "map", "note.txt", b"hello")
        assert False, "expected ValueError"
    except ValueError:
        pass
