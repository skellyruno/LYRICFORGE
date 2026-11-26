"""Regression coverage for Windows cancellation and FFmpeg listing changes."""
import pytest
import server


def test_filter_listing_legacy_and_flagless():
    listing = """Filters:
  T.. = Timeline support
  ... scale V->V Resize
  TSC split V->N Split
  ass V->V Render subtitles
  abuffer |->A Input
  amix AA->A Mix
  buffersink V->| Output
  junk = Not a filter
"""
    assert server.parse_ffmpeg_filters(listing) == {"scale", "split", "ass", "abuffer", "amix", "buffersink"}


def test_remove_staging_retries_only_transient_windows_locks(tmp_path, monkeypatch):
    stage = tmp_path / 'render-private.mp4'
    stage.write_bytes(b'partial')
    original = type(stage).unlink
    attempts = []
    def unlink(path, **kwargs):
        attempts.append(path)
        if len(attempts) <= 2:
            exc = PermissionError('sharing violation')
            exc.winerror = 32
            raise exc
        return original(path, **kwargs)
    monkeypatch.setattr(type(stage), 'unlink', unlink)
    monkeypatch.setattr(server.time, 'sleep', lambda _: None)
    server.remove_render_staging(stage)
    assert len(attempts) == 3 and not stage.exists()


def test_remove_staging_surfaces_other_errors(monkeypatch, tmp_path):
    stage = tmp_path / 'render-private.mp4'
    def unlink(path, **kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr(type(stage), 'unlink', unlink)
    with pytest.raises(PermissionError):
        server.remove_render_staging(stage)
