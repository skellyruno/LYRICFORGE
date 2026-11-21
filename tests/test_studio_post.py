"""Platform post text (limits, hashtags, AI fallback) and preset rules."""
import json

import pytest

import studio_post as post

BRAND = {"name": "Skelly Audio", "endcard": {"url": "skelly.example"}}
TAGS = ["mixing", "eq tips", "plugin", "vocal chain", "drive", "tone"]
SUMMARY = "Here is how the plugin works. First open the main window. Then turn the drive knob. That is all."


def test_every_platform_stays_inside_its_limits():
    posts = post.build_posts("How to set up the signal chain in a vocal session", SUMMARY, TAGS, BRAND)
    assert set(posts) == set(post.PLATFORMS)
    assert posts["x"]["chars"] <= 280 and "skelly.example" in posts["x"]["text"]
    assert len(posts["tiktok"]["text"]) <= 150 and posts["tiktok"]["text"].count("#") <= 5
    assert len(posts["instagram"]["text"]) <= 2200 and posts["instagram"]["text"].count("#") <= 8
    assert "Skelly Audio | skelly.example" in posts["instagram"]["text"]
    yt = posts["youtube_shorts"]
    assert yt["title"].endswith("#Shorts") and len(yt["title"]) <= 100 and "#Shorts" in yt["description"]


def test_long_titles_are_shortened_cleanly_and_a_hook_wins():
    long_title = "word " * 120
    posts = post.build_posts(long_title, SUMMARY, TAGS, BRAND, link="https://example.com/very/long/link")
    assert posts["x"]["chars"] <= 280 and posts["tiktok"]["text"].count("…") <= 1
    assert all(len(p["text"]) > 0 for p in posts.values())
    assert posts["x"]["text"].count("https://example.com/very/long/link") == 1
    hooked = post.build_posts("Title", SUMMARY, TAGS, BRAND, hook="Stop doing this to your vocals")
    assert hooked["tiktok"]["text"].startswith("Stop doing this to your vocals")
    bare = post.build_posts("", "", [], {})
    assert bare["x"]["text"] and "#" not in bare["tiktok"]["text"]


def test_hashtags_are_clean_unique_and_capped():
    assert post.hashtag("eq tips") == "#EqTips" and post.hashtag("a-b!c") == "#ABC" and post.hashtag("???") == ""
    assert post.hashtags(["Mixing", "mixing", "MIXING", "x" * 40, "tone"], 5) == ["#Mixing", "#Tone"]
    assert post.hashtags(TAGS, 2) == ["#Mixing", "#EqTips"] and post.hashtags(TAGS, 2, extra=["Shorts"])[0] == "#Shorts"
    assert post.fit("a b c d e f", 5) == "a b…" and post.fit("short", 50) == "short"


def fake(reply):
    calls = []

    def llm(prompt, key, model, post_fn=None, max_tokens=2000):
        calls.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply
    llm.calls = calls
    return llm


def test_ai_text_is_used_when_valid_and_templates_when_not(monkeypatch):
    good = {"youtube_shorts_title": "Fix your vocal chain", "youtube_shorts_description": "Quick tour.",
            "tiktok": "Fix your vocal chain in 30s #mixing", "instagram": "Fix it. #mixing", "x": "Fix your vocal chain."}
    monkeypatch.setattr(post.edit, "llm_text", fake(json.dumps(good)))
    out = post.llm_posts("T", SUMMARY, TAGS, BRAND, "key", "model")
    assert out["tiktok"]["text"] == good["tiktok"] and out["youtube_shorts"]["title"] == "Fix your vocal chain #Shorts"
    assert out["x"]["text"].endswith("skelly.example") and out["x"]["chars"] <= 280
    too_long = dict(good, tiktok="x" * 400, x="y" * 300)
    monkeypatch.setattr(post.edit, "llm_text", fake(json.dumps(too_long)))
    out = post.llm_posts("T", SUMMARY, TAGS, BRAND, "key", "model")
    template = post.build_posts("T", SUMMARY, TAGS, BRAND)
    assert out["tiktok"] == template["tiktok"] and out["x"] == template["x"]  # over-limit AI text is rejected
    for bad in (OSError("offline"), "not json", "[1, 2]"):
        monkeypatch.setattr(post.edit, "llm_text", fake(bad))
        assert post.llm_posts("T", SUMMARY, TAGS, BRAND, "key", "model") == template
    no_key = fake("{}")
    monkeypatch.setattr(post.edit, "llm_text", no_key)
    assert post.llm_posts("T", SUMMARY, TAGS, BRAND, "", "m") == template and no_key.calls == []


def test_posts_text_block_lists_each_platform():
    text = post.posts_text(post.build_posts("Title here", SUMMARY, TAGS, BRAND))
    for label in post.LABELS.values():
        assert f"=== {label} ===" in text


def test_presets_names_and_listing():
    assert [r["name"] for r in post.list_presets({})] == ["Tutorial", "Plugin showcase", "Short-form focus", "Minimal"]
    rows = post.list_presets({"Mine": {"sfx": False}, "Tutorial": {"sfx": False}})
    assert [r["name"] for r in rows][-1] == "Mine" and sum(r["name"] == "Tutorial" for r in rows) == 1  # built-ins win
    assert all(r["builtin"] for r in rows[:4]) and not rows[-1]["builtin"]
    for good in ("My preset", "A", "Tutorial 2", "R&D-style"):
        assert post.valid_preset_name(good)
    for bad in ("", " lead", "trail ", "x" * 31, "../etc", "a/b", "<b>", "emoji🙂"):
        assert not post.valid_preset_name(bad)
    assert post.with_preset({}, "Minimal")["trim_silence"] is False and post.with_preset({}, "nope") is None
    assert post.with_preset({"Mine": {"sfx": True}}, "Mine") == {"sfx": True}
    mine = post.with_preset({}, "Tutorial")
    mine["sfx"] = "changed"
    assert post.BUILTIN_PRESETS["Tutorial"]["sfx"] is True  # callers cannot corrupt the built-ins
