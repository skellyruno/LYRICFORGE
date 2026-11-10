"""Regression for the native WebView2 object-graph recursion at startup."""
from desktop_launcher import DesktopFilePicker


class FakeWindow:
    def __init__(self):
        self.closed = False

    def destroy(self):
        self.closed = True


def test_bridge_never_exposes_native_window_as_public_state():
    api = DesktopFilePicker()
    fake = FakeWindow()
    api._window = fake
    # pywebview walks non-underscore API members. A public `window` led it
    # into .native.AccessibilityObject.Bounds.Empty... until RecursionError.
    exposed = {key: value for key, value in vars(api).items()
               if not key.startswith("_")}
    assert exposed == {"active_project": False, "allow_close": False}
    assert fake not in exposed.values()
    assert "window" not in vars(api)
    assert "window" not in dir(api)


def test_close_action_still_uses_private_native_window():
    api = DesktopFilePicker()
    fake = FakeWindow()
    api._window = fake
    assert api.session_active(True) == {"active": True}
    assert api.approve_close() is True
    assert fake.closed
    assert api.allow_close


def test_bridge_methods_remain_callable_after_internal_state_hiding():
    api = DesktopFilePicker()
    for name in ("save_video", "choose_audio", "pick_audio_file",
                 "import_picked_audio", "choose_background",
                 "session_active", "approve_close"):
        assert callable(getattr(api, name))
