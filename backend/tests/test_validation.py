"""Validation: filename sanitization and upload rejection paths."""

from app.utils.filenames import sanitize_filename


def test_sanitize_strips_path_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_replaces_unsafe_chars():
    assert sanitize_filename("hello world!.mp4") == "hello_world_.mp4"


def test_sanitize_collapses_dot_runs():
    # Multiple dots collapse to a single dot so `..` can't sneak through.
    assert sanitize_filename("a..b.mp4") == "a.b.mp4"


def test_sanitize_falls_back_when_empty():
    assert sanitize_filename("") == "upload.mp4"
    assert sanitize_filename(None) == "upload.mp4"
    assert sanitize_filename("...") == "upload.mp4"


def test_upload_rejects_wrong_extension(client):
    resp = client.post(
        "/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
    assert "mp4" in resp.json()["detail"].lower()


def test_upload_rejects_missing_file(client):
    resp = client.post("/upload")
    # FastAPI returns 422 when a required body field is missing.
    assert resp.status_code == 422


def test_upload_rejects_oversize_body(client, stub_processor, monkeypatch):
    # Lower the limit so we don't have to actually generate 100 MB.
    monkeypatch.setattr("app.routes.videos.MAX_UPLOAD_BYTES", 1024)
    big = b"x" * 4096
    resp = client.post(
        "/upload",
        files={"file": ("big.mp4", big, "video/mp4")},
    )
    assert resp.status_code == 413
