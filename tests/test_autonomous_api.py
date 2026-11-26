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


def png_bytes(color=(10, 200, 90, 255), size=(300, 120)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def test_brand_kit_over_http_including_logo_upload(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.get("/api/brand").json()["brand"]["has_logo"] is False
    assert not (tmp_path / "_brand").exists(), "Reading settings must not create storage"
    saved = c.put("/api/brand", json={"brand": {"name": "Skelly", "accent": "#112233", "font": "Bad,Font"}}).json()["brand"]
    assert saved["name"] == "Skelly" and saved["accent"] == "#112233" and saved["font"] == "Arial"
    assert c.get("/api/brand/logo").status_code == 404
    ok = c.post("/api/brand/logo", files={"file": ("logo.png", io.BytesIO(png_bytes()), "image/png")})
    assert ok.status_code == 200 and ok.json()["brand"]["has_logo"] is True
    old_logo = (tmp_path / "_brand" / "logo.png").read_bytes()
    assert c.get("/api/brand/logo").headers["content-type"] == "image/png"
    assert c.post("/api/brand/logo", files={"file": ("x.txt", io.BytesIO(b"hi"), "text/plain")}).status_code == 400
    assert c.post("/api/brand/logo", files={"file": ("fake.png", io.BytesIO(b"not a png"), "image/png")}).status_code == 400
    assert (tmp_path / "_brand" / "logo.png").read_bytes() == old_logo
    assert c.get("/api/brand").json()["brand"]["has_logo"] is True  # a rejected upload leaves the good logo alone
    assert c.delete("/api/brand/logo").json()["brand"]["has_logo"] is False
    assert not [p for p in (tmp_path / "_brand").iterdir() if p.suffix == ".tmp"]


def test_generated_file_route_only_serves_known_names(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    pid = "d" * 32
    (tmp_path / pid).mkdir()
    (tmp_path / pid / "project.json").write_text("{}", encoding="utf-8")
    (tmp_path / pid / "captions.srt").write_text("1\n", encoding="utf-8")
    assert c.get(f"/api/projects/{pid}/files/captions.srt").status_code == 200
    for name in ("project.json", "source.mp4", "captions.EN.srt", "..%2Fproject.json"):
        assert c.get(f"/api/projects/{pid}/files/{name}").status_code == 404
    assert c.get(f"/api/projects/{'e' * 32}/files/captions.srt").status_code == 404


def test_autoedit_translate_and_watch_guard_rails(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    pid = "f" * 32
    (tmp_path / pid).mkdir()
    (tmp_path / pid / "project.json").write_text('{"id": "%s", "kind": "song", "status": "editor", "duration": 30}' % pid,
                                                 encoding="utf-8")
    assert c.post(f"/api/projects/{pid}/autoedit", json={}).status_code == 409  # songs are not video sources
    assert c.post(f"/api/projects/{pid}/translate", json={"languages": ["es"]}).status_code == 409
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert c.post(f"/api/projects/{pid}/clips/variants", json={"text": "hello"}).status_code == 409
    monkeypatch.delenv("SKELLYMOTION_WATCH", raising=False)
    assert c.post("/api/watch/start", json={"folder": str(tmp_path), "out": str(tmp_path / "o")}).status_code == 403
    assert c.post("/api/watch/stop", json={}).status_code == 403
    assert c.get("/api/watch/status").json()["enabled"] is False
    assert c.post(f"/api/projects/{pid}/autoedit", json={"min_gap": 99}).status_code == 422  # out-of-range option


def test_new_routes_sit_behind_owner_auth_too(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    monkeypatch.setenv("LYRICFORGE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("LYRICFORGE_AUTH_USER", "demo")
    monkeypatch.setenv("LYRICFORGE_AUTH_PASSWORD", "a-long-test-password")
    for method, path in (("get", "/api/brand"), ("put", "/api/brand"), ("get", "/api/watch/status"),
                         ("get", "/api/brand/logo"), ("post", "/api/watch/start")):
        assert getattr(c, method)(path).status_code == 401, path


def test_brand_asset_routes_validate_kind_type_and_content(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/brand/asset/virus", files={"file": ("a.mp3", io.BytesIO(b"x"), "audio/mpeg")}).status_code == 404
    assert c.delete("/api/brand/asset/virus").status_code == 404
    assert c.post("/api/brand/asset/music", files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 400
    bad = c.post("/api/brand/asset/intro", files={"file": ("a.mp4", io.BytesIO(b"not a video"), "video/mp4")})
    assert bad.status_code == 400 and "no video" in bad.json()["detail"]
    assert c.get("/api/brand").json()["brand"]["has_intro"] is False
    assert not [p for p in (tmp_path / "_brand").iterdir() if p.name.startswith("upload-")]  # temp files cleaned up
    assert c.delete("/api/brand/asset/music").json()["brand"]["has_music"] is False


def test_autoedit_options_validate_and_new_flags_are_accepted(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    pid = "a" * 32
    (tmp_path / pid).mkdir()
    (tmp_path / pid / "project.json").write_text('{"id": "%s", "kind": "song", "status": "editor", "duration": 9}' % pid,
                                                 encoding="utf-8")
    body = {"sfx": False, "callouts": False, "chapter_titles": False, "music": False, "intro_outro": False, "intro_card": True}
    assert c.post(f"/api/projects/{pid}/autoedit", json=body).status_code == 409  # valid options, wrong project kind
    assert c.post(f"/api/projects/{pid}/autoedit", json={"sfx": "maybe"}).status_code == 422


def test_missing_brand_assets_are_read_only(tmp_path, monkeypatch):
    """Actual Brand Kit read endpoints must not create storage for missing assets."""
    c = client(tmp_path, monkeypatch)
    assert c.get("/api/brand").status_code == 200
    assert c.get("/api/brand/logo").status_code == 404
    assert server.brand_asset("music") is None
    assert server.brand_asset("intro") is None
    assert server.brand_asset("outro") is None
    assert not (tmp_path / "_brand").exists()
