from fastapi.testclient import TestClient

from app import main


client = TestClient(main.app)


def test_ping():
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "msg": "pong"}


def test_describe_request_keeps_public_response_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "classify_intent", lambda _prompt: ("describe", None, False))
    monkeypatch.setattr(main.history_service, "add", lambda _prompt: None)
    monkeypatch.setattr(main.vision_service, "detect_objects", lambda _path: [])
    monkeypatch.setattr(main.vision_service, "caption_image", lambda _path: "a table")
    monkeypatch.setattr(main.vision_service, "describe", lambda _caption, _items: "một cái bàn")
    monkeypatch.setattr(main.groq_service, "summarize", lambda caption, _counts: caption)
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)

    response = client.post(
        "/analyze",
        files={"file": ("capture.jpg", b"fake-image", "image/jpeg")},
        data={"prompt": "mô tả ảnh", "language": "vi"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "intent": "describe",
        "file": "capture.jpg",
        "text": "Một cái bàn.",
        "data": {"counts": {}},
    }
    assert list(tmp_path.iterdir()) == []

