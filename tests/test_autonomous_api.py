"""HTTP-level checks for the autonomous endpoints: validation, auth and path safety."""
import base64
import io

from fastapi.testclient import TestClient

import server


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    return TestClient(server.app)


def test_new_routes_reject_bad_ids_and_numbers(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    for path in ("/api/projects/not-an-id/shorts/1", "/api/projects/not-an-id/clips/1",
                 "/api/projects/not-an-id/source", "/api/projects/not-an-id/bundle.zip",
                 "/api/projects/" + "0" * 32 + "/bundle.zip"):
        assert c.get(path).status_code == 404
    for path in ("/api/projects/not-an-id/shorts/suggestions", "/api/projects/not-an-id/autopilot",
                 "/api/projects/not-an-id/clips/render"):
        assert c.post(path, json={}).status_code in (404, 422)


def test_clip_source_upload_accepts_only_video_types(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    response = c.post("/api/clip-sources", files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")})
    assert response.status_code == 400
    assert not [d for d in tmp_path.iterdir() if d.is_dir()]  # nothing left behind


def test_capabilities_report_ai_only_when_a_key_exists(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert c.get("/api/clips/capabilities").json()["ai_rerank"] is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    body = c.get("/api/clips/capabilities").json()
    assert body["ai_rerank"] is True and "test-key" not in str(body)


def test_new_routes_sit_behind_owner_auth(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    monkeypatch.setenv("LYRICFORGE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("LYRICFORGE_AUTH_USER", "demo")
    monkeypatch.setenv("LYRICFORGE_AUTH_PASSWORD", "a-long-test-password")
    assert c.get("/api/clips/capabilities").status_code == 401
    token = base64.b64encode(b"demo:a-long-test-password").decode()
    ok = c.get("/api/clips/capabilities", headers={"Authorization": "Basic " + token})
    assert ok.status_code == 200
