import base64
from fastapi.testclient import TestClient
import server


def test_public_requires_auth(monkeypatch):
    monkeypatch.setenv("LYRICFORGE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("LYRICFORGE_AUTH_USER", "demo")
    monkeypatch.setenv("LYRICFORGE_AUTH_PASSWORD", "a-long-test-password")
    client = TestClient(server.app)
    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")
    credential = base64.b64encode(b"demo:a-long-test-password").decode()
    headers = {"Authorization": f"Basic {credential}"}
    assert client.get("/", headers=headers).status_code == 200
    assert client.post("/api/projects", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/projects", headers={**headers, "Origin": "http://testserver"}).status_code == 422
    assert client.get("/api/projects/not-a-project", headers=headers).status_code == 404


def test_web_fails_closed_without_password(monkeypatch):
    monkeypatch.setenv("LYRICFORGE_REQUIRE_AUTH", "1")
    monkeypatch.delenv("LYRICFORGE_AUTH_PASSWORD", raising=False)
    assert TestClient(server.app).get("/").status_code == 503
