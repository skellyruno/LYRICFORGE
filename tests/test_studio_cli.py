"""The headless command line: flags, presets and precedence map onto the same options the app uses."""
import pytest

import studio_cli
import studio_post as post


def parse(*argv):
    return studio_cli.build_parser().parse_args(list(argv))


def opts(*argv, preset=None):
    return studio_cli.build_options(parse(*argv), preset)


def test_defaults_match_the_app_defaults():
    assert opts("edit", "a.mp4", "--out", "o") == studio_cli.DEFAULTS
    assert studio_cli.DEFAULTS["fillers"] == "off" and studio_cli.DEFAULTS["voice_cleanup"] == "off"


def test_every_flag_changes_exactly_its_option():
    base = studio_cli.DEFAULTS
    cases = {("--no-trim",): {"trim_silence": False}, ("--no-loudness",): {"loudness": False}, ("--captions",): {"captions": True},
             ("--no-watermark",): {"watermark": False}, ("--no-endcard",): {"endcard": False}, ("--no-sfx",): {"sfx": False},
             ("--no-callouts",): {"callouts": False}, ("--no-chapter-titles",): {"chapter_titles": False},
             ("--no-music",): {"music": False}, ("--no-intro-outro",): {"intro_outro": False}, ("--no-broll",): {"broll": False},
             ("--intro-card",): {"intro_card": True}, ("--zoom", "strong"): {"zoom": "strong"}, ("--zoom-mode", "ui"): {"zoom_mode": "ui"},
             ("--voice-cleanup", "medium"): {"voice_cleanup": "medium"}, ("--remove-fillers", "more"): {"fillers": "more"},
             ("--resolution", "720p"): {"resolution": "720p"}, ("--min-gap", "1.5"): {"min_gap": 1.5}, ("--shorts", "4"): {"shorts": 4}}
    for flags, change in cases.items():
        assert opts("watch", "inbox", "--out", "o", *flags) == {**base, **change}, flags


def test_shorts_are_clamped_and_presets_sit_between_defaults_and_flags():
    assert opts("edit", "a.mp4", "--out", "o", "--shorts", "99")["shorts"] == 6
    assert opts("edit", "a.mp4", "--out", "o", "--shorts", "-3")["shorts"] == 0
    tutorial = post.with_preset({}, "Tutorial")
    got = opts("edit", "a.mp4", "--out", "o", preset=tutorial)
    assert got["fillers"] == "basic" and got["voice_cleanup"] == "light" and got["shorts"] == 3 and got["music"] is False
    over = opts("edit", "a.mp4", "--out", "o", "--remove-fillers", "more", "--shorts", "0", "--no-sfx", preset=tutorial)
    assert over["fillers"] == "more" and over["shorts"] == 0 and over["sfx"] is False and over["voice_cleanup"] == "light"
    showcase = opts("edit", "a.mp4", "--out", "o", preset=post.with_preset({}, "Plugin showcase"))
    assert showcase["zoom"] == "medium" and showcase["zoom_mode"] == "ui" and showcase["music"] is True
    assert opts("edit", "a.mp4", "--out", "o", preset={"title": "ignored", "evil": 1}) == studio_cli.DEFAULTS  # only known keys


def test_edit_calls_the_shared_pipeline_and_reports_errors(tmp_path, monkeypatch, capsys):
    import server
    monkeypatch.setattr(server, "DATA", tmp_path)
    seen = {}

    def fake(src, out, options, **kw):
        seen.update(src=src, out=out, opts=options, kw=kw)
        return out / "demo"
    monkeypatch.setattr(server, "process_video_file", fake)
    assert studio_cli.main(["edit", str(tmp_path / "demo.mp4"), "--out", str(tmp_path / "o"), "--shorts", "2", "--language", "es",
                            "--keep-project", "--preset", "Short-form focus", "--remove-fillers", "basic"]) == 0
    assert seen["opts"]["shorts"] == 2 and seen["opts"]["fillers"] == "basic" and seen["opts"]["captions"] is True  # preset + override
    assert seen["kw"]["language"] == "es" and seen["kw"]["keep_project"] is True
    assert str(tmp_path / "o" / "demo") in capsys.readouterr().out

    server.save_preset("Mine", server.PresetRequest(options={"zoom": "subtle"}))
    studio_cli.main(["edit", "x.mp4", "--out", str(tmp_path), "--preset", "Mine"])
    assert seen["opts"]["zoom"] == "subtle"  # saved presets work too

    assert studio_cli.main(["edit", "x.mp4", "--out", str(tmp_path), "--preset", "Nope"]) == 2
    assert "Available: Tutorial" in capsys.readouterr().err

    def boom(*a, **k):
        raise ValueError("Not a supported video file: x.txt")
    monkeypatch.setattr(server, "process_video_file", boom)
    assert studio_cli.main(["edit", "x.txt", "--out", str(tmp_path)]) == 1
    assert "Not a supported video file" in capsys.readouterr().err


def test_bad_flag_values_are_rejected():
    for bad in (("--zoom", "ludicrous"), ("--remove-fillers", "all"), ("--voice-cleanup", "max"), ("--zoom-mode", "mouse")):
        with pytest.raises(SystemExit):
            parse("edit", "a.mp4", "--out", "o", *bad)
    with pytest.raises(SystemExit):
        parse("edit", "a.mp4")  # --out is required
