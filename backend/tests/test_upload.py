"""Upload happy path + processed-video download."""


def test_upload_returns_video_id(client, stub_processor):
    resp = client.post(
        "/upload",
        files={"file": ("clip.mp4", b"\x00\x00\x00fake", "video/mp4")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"]
    assert body["original_filename"] == "clip.mp4"
    assert body["frame_count"] == 3
    assert body["roi_count"] == 2
    assert body["warning"] is None


def test_get_video_returns_mp4(client, stub_processor):
    resp = client.post(
        "/upload",
        files={"file": ("clip.mp4", b"\x00\x00\x00fake", "video/mp4")},
    )
    video_id = resp.json()["video_id"]

    download = client.get(f"/video/{video_id}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "video/mp4"
    assert download.content == b"\x00fake-mp4"


def test_get_video_unknown_id_404s(client):
    resp = client.get("/video/does-not-exist")
    assert resp.status_code == 404
