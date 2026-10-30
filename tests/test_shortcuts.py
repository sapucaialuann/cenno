"""Tests for recorded dictation shortcuts: the format, the migration of old
typed shortcuts, and the dispatcher's push-to-talk logic.  No key events are
sent; shortcuts.tap and shortcuts.hold are stubbed.  Run:

    python tests/test_shortcuts.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import shortcuts as sc                          # noqa: E402
import hand_desktop_switcher as core            # noqa: E402
from test_dispatcher_displays import PRIMARY, dispatcher_with   # noqa: E402

MAC, WIN = "Darwin", "Windows"


def test_make_puts_modifiers_in_order():
    s = sc.make(["shift", "ctrl", "cmd", "alt"], 2, "x")
    assert s["mods"] == ["cmd", "ctrl", "alt", "shift"]
    assert s["code"] == 2 and s["label"] == "x"


def test_is_valid():
    assert sc.is_valid({"mods": ["ctrl"], "code": 2, "label": "x"})
    assert sc.is_valid({"mods": [], "code": 96, "label": "F5"})
    assert sc.is_valid({"mods": ["fn"], "code": None, "label": "fn"})
    assert not sc.is_valid(None)
    assert not sc.is_valid("ctrl+d")
    assert not sc.is_valid({"mods": [], "code": None, "label": ""})
    assert not sc.is_valid({"mods": ["hyper"], "code": 2})
    assert not sc.is_valid({"mods": ["ctrl"], "code": "d"})
    assert not sc.is_valid({"mods": "ctrl", "code": 2})
    assert not sc.is_valid({"mods": ["ctrl"], "code": True})


def test_mac_legacy_with_aliases():
    s = sc.from_legacy("ctrl+option+d", MAC)
    assert s == {"mods": ["ctrl", "alt"], "code": 2, "label": "⌃⌥D"}
    assert sc.from_legacy("Control + Opt + D", MAC) == s
    assert sc.from_legacy("alt+ctrl+d", MAC) == s
    cmd = sc.from_legacy("command+shift+space", MAC)
    assert cmd["mods"] == ["cmd", "shift"] and cmd["code"] == 49
    assert cmd["label"] == "⇧⌘Space"
    assert sc.from_legacy("cmd+shift+space", MAC) == cmd
    assert sc.from_legacy("f5", MAC) == {"mods": [], "code": 96, "label": "F5"}


def test_mac_legacy_fn():
    assert sc.from_legacy("fn+space", MAC) == {"mods": ["fn"], "code": 49,
                                              "label": "fn Space"}
    assert sc.from_legacy("fn", MAC) == {"mods": ["fn"], "code": None, "label": "fn"}


def test_mac_legacy_modifier_only_combo():
    s = sc.from_legacy("ctrl+option", MAC)
    assert s["mods"] == ["ctrl", "alt"] and s["code"] is None
    assert s["label"] == "⌃⌥"


def test_legacy_rejects_unknown_parts():
    for spec in ("hyper+d", "ctrl+nonsense", "ctrl+", "", "  ", "ctrl+option+ö",
                 "win+d", None, 5):
        assert sc.from_legacy(spec, MAC) is None, spec
    for spec in ("meta+d", "ctrl+f25", "ctrl+nonsense", "fn+space", "", None):
        assert sc.from_legacy(spec, WIN) is None, spec


def test_windows_legacy():
    s = sc.from_legacy("ctrl+shift+d", WIN)
    assert s == {"mods": ["ctrl", "shift"], "code": 0x44, "label": "Ctrl+Shift+D"}
    s = sc.from_legacy("ctrl+win+space", WIN)
    assert s == {"mods": ["ctrl", "win"], "code": 0x20, "label": "Ctrl+Win+Space"}
    assert sc.from_legacy("Win+H", WIN)["code"] == 0x48
    assert sc.from_legacy("control+option+1", WIN)["mods"] == ["ctrl", "alt"]
    assert sc.from_legacy("f1", WIN)["code"] == 0x70
    assert sc.from_legacy("f24", WIN)["code"] == 0x87
    assert sc.from_legacy("alt+left", WIN)["code"] == 0x25
    assert sc.from_legacy("down", WIN) == {"mods": [], "code": 0x28, "label": "Down"}
    assert sc.from_legacy("esc", WIN)["code"] == 0x1B
    assert sc.from_legacy("return", WIN)["code"] == 0x0D
    ctrl_win = sc.from_legacy("ctrl+win", WIN)
    assert ctrl_win == {"mods": ["ctrl", "win"], "code": None, "label": "Ctrl+Win"}


def test_every_legacy_result_is_valid():
    for os_name in (MAC, WIN):
        for spec in ("ctrl+d", "shift+f5", "alt+space", "ctrl+alt+shift+9"):
            assert sc.is_valid(sc.from_legacy(spec, os_name)), (os_name, spec)


def test_labels():
    assert sc.label_for(["fn"], "space", MAC) == "fn Space"
    assert sc.label_for(["cmd", "ctrl", "alt", "shift"], "d", MAC) == \
        "⌃⌥⇧⌘D"
    assert sc.label_for(["ctrl", "alt"], "left", WIN) == "Ctrl+Alt+Left"
    assert sc.label_for(["alt", "ctrl", "shift", "win"], None, WIN) == \
        "Ctrl+Alt+Shift+Win"


def test_same():
    a = sc.make(["ctrl", "alt"], 2, "one label")
    assert sc.same(a, sc.make(["alt", "ctrl"], 2, "another label"))
    assert not sc.same(a, sc.make(["ctrl"], 2, "x"))
    assert not sc.same(a, sc.make(["ctrl", "alt"], 3, "x"))
    assert not sc.same(a, sc.make(["ctrl", "alt"], None, "x"))
    assert not sc.same(None, None)
    assert not sc.same(a, None)


def test_migration_never_gives_two_equal_shortcuts():
    s = sc.migrate_dictation(old(dictation="wispr", wispr_shortcut="ctrl+win"), WIN)
    assert s["dictation_toggle"]["code"] is None
    assert s["dictation_ptt"] is None


def test_windows_recorder_key_state():
    try:
        import recorder_win as rw
    except ImportError:         # no tkinter here
        return
    k = rw.KeyState()
    assert k.key_down(0x11)[0] == "preview"          # Ctrl
    assert k.key_down(0x5B)[0] == "preview"          # Win
    kind, got = k.key_down(0x48)                     # H
    assert kind == "keep"
    assert got == sc.make(["win", "ctrl"], 0x48, "Ctrl+Win+H")
    assert k.key_up(0x48) is None
    assert k.key_up(0x5B) is None
    assert k.key_up(0x11) == ("release", None)       # typed: keep what we had
    # Modifiers only: record them when the last one is let go.
    assert k.key_down(0x11)[0] == "preview"
    k.key_down(0x5B)
    assert k.key_up(0x5B) is None
    kind, got = k.key_up(0x11)
    assert kind == "keep" and got == sc.make(["ctrl", "win"], None, "Ctrl+Win")
    # Left and right Ctrl are one modifier: not let go until both are up.
    k.key_down(0xA2)
    k.key_down(0xA3)
    assert k.key_up(0xA2) is None
    assert k.key_up(0xA3)[0] == "keep"
    # Esc alone cancels; with a modifier it is a key.
    assert k.key_down(0x1B) == ("cancel", None)
    k.key_down(0x10)
    assert k.key_down(0x1B)[0] == "keep"


def test_tap_and_hold_refuse_invalid_shortcuts():
    assert sc.tap(None) is False
    assert sc.hold({"mods": [], "code": None}, True) is False


# --- migration ---------------------------------------------------------------

def old(**kw):
    return {"enabled": True, "dictation": "auto", "dictation_shortcut": "", **kw}


def test_mac_migration_wispr():
    s = sc.migrate_dictation(old(dictation="wispr"), MAC)
    assert s["dictation"] == "shortcut" and s["settings_version"] == 2
    assert s["dictation_toggle"] == {"mods": ["fn"], "code": 49, "label": "fn Space"}
    assert s["dictation_ptt"] == {"mods": ["fn"], "code": None, "label": "fn"}
    assert "dictation_shortcut" not in s and "wispr_shortcut" not in s
    assert s["enabled"] is True


def test_mac_migration_auto_depends_on_wispr_being_installed():
    s = sc.migrate_dictation(old(dictation="auto"), MAC, wispr_installed=True)
    assert s["dictation"] == "shortcut" and s["dictation_toggle"]["code"] == 49
    s = sc.migrate_dictation(old(dictation="auto"), MAC, wispr_installed=False)
    assert s["dictation"] == "apple"
    assert s["dictation_toggle"] is None and s["dictation_ptt"] is None


def test_mac_migration_custom():
    s = sc.migrate_dictation(
        old(dictation="custom", dictation_shortcut="ctrl+option+d"), MAC)
    assert s["dictation"] == "shortcut"
    assert s["dictation_toggle"]["label"] == "⌃⌥D"
    assert s["dictation_ptt"] is None
    bad = sc.migrate_dictation(
        old(dictation="custom", dictation_shortcut="hyper+d"), MAC)
    assert bad["dictation"] == "apple" and bad["dictation_toggle"] is None


def test_mac_migration_apple():
    s = sc.migrate_dictation(old(dictation="apple"), MAC, wispr_installed=True)
    assert s["dictation"] == "apple"


def test_windows_migration():
    s = sc.migrate_dictation(old(dictation="wispr", wispr_shortcut=""), WIN)
    assert s["dictation"] == "shortcut"
    assert s["dictation_toggle"]["mods"] == ["ctrl", "win"]
    assert s["dictation_toggle"]["code"] == 0x20
    assert s["dictation_ptt"] == {"mods": ["ctrl", "win"], "code": None,
                                  "label": "Ctrl+Win"}
    s = sc.migrate_dictation(old(dictation="wispr", wispr_shortcut="ctrl+alt+w"), WIN)
    assert s["dictation_toggle"]["label"] == "Ctrl+Alt+W"
    s = sc.migrate_dictation(old(dictation="auto", wispr_shortcut="ctrl+alt+w"), WIN)
    assert s["dictation"] == "shortcut"
    s = sc.migrate_dictation(old(dictation="auto"), WIN)
    assert s["dictation"] == "winvoice" and s["dictation_toggle"] is None
    s = sc.migrate_dictation(old(dictation="winvoice", wispr_shortcut="ctrl+w"), WIN)
    assert s["dictation"] == "winvoice"
    s = sc.migrate_dictation(
        old(dictation="custom", dictation_shortcut="ctrl+shift+d"), WIN)
    assert s["dictation"] == "shortcut" and s["dictation_toggle"]["code"] == 0x44
    assert s["dictation_ptt"] is None
    s = sc.migrate_dictation(old(dictation="custom", dictation_shortcut="nope"), WIN)
    assert s["dictation"] == "winvoice"
    s = sc.migrate_dictation(old(dictation="wispr", wispr_shortcut="nope"), WIN)
    assert s["dictation"] == "winvoice" and s["dictation_toggle"] is None


def test_migration_leaves_version_2_alone():
    now = {"settings_version": 2, "dictation": "shortcut",
           "dictation_toggle": None, "dictation_ptt": None}
    assert sc.migrate_dictation(now, MAC) == now
    assert sc.migrate_dictation(now, WIN) == now


def test_migration_does_not_change_its_input():
    before = old(dictation="wispr")
    sc.migrate_dictation(before, MAC)
    assert before == old(dictation="wispr")


# --- the dispatcher's dictation logic ------------------------------------------

class Recorder:
    """Stands in for shortcuts.tap and shortcuts.hold."""

    def __init__(self):
        self.calls = []

    def tap(self, s):
        self.calls.append(("tap", s["label"] if s else None))
        return True

    def hold(self, s, down):
        self.calls.append(("hold", s["label"], down))
        return True


class Patched:
    def __enter__(self):
        self.rec = Recorder()
        self.saved = (sc.tap, sc.hold)
        sc.tap, sc.hold = self.rec.tap, self.rec.hold
        return self.rec

    def __exit__(self, *exc):
        sc.tap, sc.hold = self.saved


TOGGLE = sc.make(["fn"], 49, "fn Space")
PTT = sc.make(["fn"], None, "fn")


def test_toggle_in_shortcut_mode_taps_the_toggle():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s), Patched() as rec:
        d.dictation_mode, d.dictation_toggle = "shortcut", TOGGLE
        d._toggle_dictation()
        assert rec.calls == [("tap", "fn Space")]


def test_toggle_without_a_shortcut_warns_and_sends_nothing():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s), Patched() as rec:
        d.dictation_mode, d.dictation_toggle = "shortcut", None
        sc.tap = lambda s: False        # what the real one says for None
        d._toggle_dictation()
        assert rec.calls == []


def test_hold_with_a_ptt_key_presses_and_releases_it():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s), Patched() as rec:
        d.dictation_mode, d.dictation_toggle, d.dictation_ptt = "shortcut", TOGGLE, PTT
        d._dictation_hold(True)
        d._dictation_hold(True)             # a repeat does nothing
        assert rec.calls == [("hold", "fn", True)]
        d._dictation_hold(False)
        d._dictation_hold(False)
        assert rec.calls == [("hold", "fn", True), ("hold", "fn", False)]


def test_hold_end_without_start_is_ignored():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s), Patched() as rec:
        d.dictation_mode, d.dictation_toggle, d.dictation_ptt = "shortcut", TOGGLE, PTT
        d._dictation_hold(False)
        assert rec.calls == []


def test_hold_without_a_ptt_key_toggles_on_then_off():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s), Patched() as rec:
        d.dictation_mode, d.dictation_toggle, d.dictation_ptt = "shortcut", TOGGLE, None
        d._dictation_hold(False)            # never started: ignored
        d._dictation_hold(True)
        d._dictation_hold(True)
        d._dictation_hold(False)
        assert rec.calls == [("tap", "fn Space"), ("tap", "fn Space")]


def test_hold_in_winvoice_mode_presses_win_h_twice():
    with dispatcher_with([PRIMARY]) as (d, pag, _s), Patched() as rec:
        presses = []
        pag.hotkey = lambda *keys, **kw: presses.append(keys)
        core_os = core.OS_NAME
        core.OS_NAME = "Windows"
        try:
            d.dictation_mode = "winvoice"
            d._dictation_hold(True)
            d._dictation_hold(False)
        finally:
            core.OS_NAME = core_os
        assert presses == [("win", "h"), ("win", "h")]
        assert rec.calls == []


def test_release_lets_go_of_a_held_key():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s), Patched() as rec:
        d.dictation_mode, d.dictation_toggle, d.dictation_ptt = "shortcut", TOGGLE, PTT
        d.release_dictation()               # nothing held: nothing sent
        assert rec.calls == []
        d._dictation_hold(True)
        d.release_dictation()
        assert rec.calls == [("hold", "fn", True), ("hold", "fn", False)]
        d.release_dictation()
        assert len(rec.calls) == 2


def test_release_works_even_if_the_ptt_key_was_cleared_meanwhile():
    with dispatcher_with([PRIMARY]) as (d, _pag, _s), Patched() as rec:
        d.dictation_mode, d.dictation_toggle, d.dictation_ptt = "shortcut", TOGGLE, PTT
        d._dictation_hold(True)
        d.dictation_ptt = None
        d.release_dictation()
        assert rec.calls == [("hold", "fn", True), ("hold", "fn", False)]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
    print("all good" if not failures else f"{failures} failed")
    sys.exit(1 if failures else 0)
