import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from caption.server import create_app
from test_stream import VOICE, SILENCE
import numpy as np


def receive_until(ws, kind, status=None, text=False):
    for _ in range(100):
        event = ws.receive_json()
        if event["type"] == kind and (status is None or event.get("segment", {}).get("status") == status):
            if not text or event.get("segment", {}).get("text"):
                return event
    raise AssertionError("Expected WebSocket event was not received")


class FakeEngine:
    name = "fixture"
    device = "cpu"
    model = True

    def load(self):
        pass

    def transcribe(self, audio):
        return "今天練習繁體中文聽打。"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "api.db", FakeEngine())) as c:
        yield c


def open_audio(client, sid):
    return client.websocket_connect(f"/api/sessions/{sid}/audio")


def test_real_websocket_protocol_edit_during_capture_and_export(client):
    sid = client.post("/api/sessions", json={"title":"課堂"}).json()["id"]
    with open_audio(client, sid) as ws:
        assert ws.receive_json()["type"] == "loading"
        assert ws.receive_json()["type"] == "ready"
        for _ in range(12):
            ws.send_bytes(VOICE)
        preview = receive_until(ws, "segment", "provisional", text=True)["segment"]
        assert preview["status"] == "provisional"
        assert client.patch(f"/api/sessions/{sid}/segments/{preview['id']}", json={"text":"修改","revision":preview["revision"]}).status_code == 409
        for _ in range(8):
            ws.send_bytes(SILENCE)
        final = receive_until(ws, "segment", "committed")["segment"]
        assert final["status"] == "committed"
        # Capture stays connected while HTTP saves a correction.
        saved = client.patch(f"/api/sessions/{sid}/segments/{final['id']}", json={"text":"人工校正的繁體中文","revision":final["revision"]}).json()
        assert saved["locked"]
        for _ in range(4):
            ws.send_bytes(VOICE)
        ws.send_json({"type":"stop"})
        assert receive_until(ws, "segment", "committed")["segment"]["status"] == "committed"
        assert receive_until(ws, "stopped")["type"] == "stopped"
    rows = client.get(f"/api/sessions/{sid}").json()["segments"]
    assert len(rows) == 2 and rows[0]["text"] == "人工校正的繁體中文"
    assert rows[0]["status"] == "human_corrected"
    for fmt in ("txt", "json", "srt"):
        response = client.get(f"/api/sessions/{sid}/export/{fmt}")
        assert response.status_code == 200
        assert "人工校正的繁體中文" in response.text
        assert "attachment" in response.headers["content-disposition"]


def test_cross_origin_denied_and_missing_sessions(client):
    assert client.post("/api/sessions", json={}, headers={"Origin":"https://malicious.example"}).status_code == 403
    assert client.get("/api/sessions/missing").status_code == 404
    assert client.get("/", headers={"Host":"malicious.example"}).status_code == 400
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/sessions/missing/audio", headers={"Origin":"https://malicious.example"}):
            pass


def test_bad_audio_and_second_capture_are_rejected(client):
    sid = client.post("/api/sessions", json={}).json()["id"]
    with open_audio(client, sid) as first:
        first.receive_json(); first.receive_json()
        with open_audio(client, sid) as second:
            assert second.receive_json()["type"] == "error"
        first.send_bytes(b"bad")
        assert first.receive_json()["type"] == "error"
        assert first.receive_json()["type"] == "stopped"
    assert client.get("/api/health").json()["busy"] is False


def test_model_failure_retains_provisional_and_releases_capture(tmp_path):
    class Broken(FakeEngine):
        def transcribe(self, audio):
            raise RuntimeError("fixture failure")
    with TestClient(create_app(tmp_path / "broken.db", Broken())) as client:
        sid = client.post("/api/sessions", json={}).json()["id"]
        with open_audio(client, sid) as ws:
            ws.receive_json(); ws.receive_json()
            for _ in range(12):
                ws.send_bytes(VOICE)
            while ws.receive_json()["type"] != "stopped":
                pass
        assert client.get("/api/health").json()["busy"] is False
        assert client.get(f"/api/sessions/{sid}").json()["segments"][0]["status"] == "provisional"


def test_quiet_microphone_receipt_and_live_sensitivity(client):
    sid = client.post("/api/sessions", json={}).json()["id"]
    quiet = (np.ones(1600, dtype="<i2") * 50).tobytes()
    with open_audio(client, sid) as ws:
        ws.receive_json(); ws.receive_json()
        for _ in range(10):
            ws.send_bytes(quiet)
        stats = receive_until(ws, "audio")
        assert stats["received_seconds"] == 1
        assert stats["speech_frames"] == 0
        assert 0 < stats["rms"] < stats["threshold"]
        ws.send_json({"type":"configure", "threshold":0.001})
        assert receive_until(ws, "configured")["threshold"] == .001
        for _ in range(12):
            ws.send_bytes(quiet)
        row = receive_until(ws, "segment", "provisional", text=True)["segment"]
        assert row["text"]
        capture = client.get("/api/health").json()["capture"]
        assert capture["speech_frames"] == 12 and capture["received_seconds"] == 2.2
        ws.send_json({"type":"stop"})
        receive_until(ws, "stopped")


@pytest.mark.parametrize("threshold", [0, -1, 1, "NaN"])
def test_invalid_sensitivity_rejected(client, threshold):
    sid = client.post("/api/sessions", json={}).json()["id"]
    with open_audio(client, sid) as ws:
        ws.receive_json(); ws.receive_json()
        ws.send_json({"type":"configure", "threshold":threshold})
        assert ws.receive_json()["type"] == "error"
        assert ws.receive_json()["type"] == "stopped"
