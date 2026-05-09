"""ROI metadata endpoint."""


def test_roi_returns_inserted_rows(client, stub_processor):
    upload = client.post(
        "/upload",
        files={"file": ("clip.mp4", b"\x00\x00\x00fake", "video/mp4")},
    )
    video_id = upload.json()["video_id"]

    resp = client.get(f"/roi/{video_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"] == video_id
    assert body["fps"] == 30.0
    assert body["frame_count"] == 3
    assert len(body["rois"]) == 2

    # Returned in frame order with the documented field shape.
    first = body["rois"][0]
    assert first["frame_number"] == 0
    assert first["timestamp"] == 0.0
    for key in ("x", "y", "width", "height"):
        assert isinstance(first[key], int)


def test_roi_unknown_id_404s(client):
    resp = client.get("/roi/does-not-exist")
    assert resp.status_code == 404
