"""Tests for the onboarding step logic (#40).  Run:

    python tests/test_onboarding.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import onboarding                     # noqa: E402


def walk_to(ob, step):
    """Advance until the given step is on screen."""
    while ob.step != step:
        assert not ob.finished, (step, ob.steps)
        ob.advance()


def test_steps_per_os():
    assert onboarding.STEPS_MACOS == ["welcome", "camera", "accessibility",
                                      "first_win", "pause", "second_gesture",
                                      "done"]
    assert onboarding.STEPS_WINDOWS == ["welcome", "camera", "first_win",
                                        "pause", "second_gesture", "done"]
    assert onboarding.steps_for("macos") == onboarding.STEPS_MACOS
    assert onboarding.steps_for("windows") == onboarding.STEPS_WINDOWS
    # The list is a copy: the app cannot change the steps for everyone.
    onboarding.steps_for("windows").append("extra")
    assert onboarding.steps_for("windows") == onboarding.STEPS_WINDOWS


def test_advance_walks_the_steps():
    ob = onboarding.Onboarding("macos")
    assert ob.step == "welcome"
    assert not ob.finished
    ob.advance()
    assert ob.step == "camera"
    for _ in onboarding.STEPS_MACOS:
        ob.advance()
    assert ob.finished
    assert ob.step == "done"


def test_skip_records_the_step():
    ob = onboarding.Onboarding("windows")
    ob.skip()
    assert ob.step == "camera"
    assert ob.skipped == ["welcome"]
    ob.skip()
    assert ob.step == "first_win"
    assert ob.skipped == ["welcome", "camera"]


def test_skip_all_finishes_and_records_the_rest():
    ob = onboarding.Onboarding("macos")
    ob.skip_all()
    assert ob.finished
    assert ob.skipped == onboarding.STEPS_MACOS


def test_first_win_completes_on_a_slap():
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "first_win")
    assert ob.on_event("pointer_move") is False
    assert ob.on_event("scroll_drag") is False
    assert ob.on_event("pause_on") is False
    assert ob.on_event("space_left") is True


def test_first_win_on_windows_uses_the_same_event():
    # Windows drives Alt+Tab from the same slap events.
    ob = onboarding.Onboarding("windows")
    walk_to(ob, "first_win")
    assert ob.on_event("space_right") is True


def test_pause_needs_two_toggles():
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "pause")
    assert ob.on_event("pause_on") is False
    assert ob.on_event("pause_off") is True


def test_second_gesture_needs_the_chosen_one():
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "second_gesture")
    assert ob.choose_second("scroll") is True
    assert ob.on_event("click") is False
    assert ob.on_event("play_pause") is False
    assert ob.on_event("scroll_drag") is True


def test_second_gesture_pointer_and_play_pause():
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "second_gesture")
    assert ob.choose_second("pointer") is True
    assert ob.on_event("click") is True

    ob = onboarding.Onboarding("macos")
    walk_to(ob, "second_gesture")
    assert ob.choose_second("play_pause") is True
    assert ob.on_event("scroll_drag") is False
    assert ob.on_event("play_pause") is True


def test_second_gesture_ignores_an_unknown_choice():
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "second_gesture")
    assert ob.choose_second("scroll") is True
    assert ob.choose_second("nonsense") is False
    assert ob.second_gesture == "scroll"
    assert ob.on_event("scroll_drag") is True


def test_events_outside_the_step_are_ignored():
    ob = onboarding.Onboarding("macos")
    assert ob.on_event("space_left") is False
    assert ob.on_event("pause_on") is False
    assert ob.step == "welcome"


def test_note_miss_hints_on_the_third_miss_only():
    ob = onboarding.Onboarding("macos")
    assert ob.note_miss() is False
    assert ob.note_miss() is False
    assert ob.note_miss() is True
    assert ob.note_miss() is False


def test_miss_counter_resets_on_advance():
    ob = onboarding.Onboarding("macos")
    ob.note_miss()
    ob.note_miss()
    ob.advance()
    assert ob.note_miss() is False


def test_needs_onboarding_for_a_new_user():
    assert onboarding.needs_onboarding({}, False) is True


def test_needs_onboarding_is_false_for_existing_users():
    assert onboarding.needs_onboarding({}, True) is False
    assert onboarding.needs_onboarding({"onboarding_done": True}, False) is False


def test_needs_onboarding_keeps_the_windows_legacy_user_new():
    # Windows wrote first_run before the tour existed.
    assert onboarding.needs_onboarding({"first_run": True}, True) is True
    assert onboarding.needs_onboarding({"first_run": False}, True) is False


def test_mark_onboarding_done():
    settings = {"first_run": True}
    onboarding.mark_onboarding_done(settings)
    assert settings["onboarding_done"] is True
    assert settings["first_run"] is False
    assert onboarding.needs_onboarding(settings, False) is False


def test_record_gesture_used_dedupes():
    settings = {}
    onboarding.record_gesture_used(settings, "scroll")
    onboarding.record_gesture_used(settings, "scroll")
    assert settings["gestures_used"] == ["scroll"]
    onboarding.record_gesture_used(settings, "pointer")
    assert settings["gestures_used"] == ["scroll", "pointer"]


def test_next_gesture_to_teach():
    settings = {}
    assert onboarding.next_gesture_to_teach(settings) == onboarding.TEACH_ORDER[0]
    onboarding.record_gesture_used(settings, onboarding.TEACH_ORDER[0])
    assert onboarding.next_gesture_to_teach(settings) == onboarding.TEACH_ORDER[1]
    for name in onboarding.TEACH_ORDER:
        onboarding.record_gesture_used(settings, name)
    assert onboarding.next_gesture_to_teach(settings) is None


def test_teach_order_leaves_the_lock_wave_out():
    assert "wave" not in onboarding.TEACH_ORDER
    assert "lock" not in onboarding.TEACH_ORDER


def test_hints_exist_for_every_gesture_step():
    assert onboarding.HINTS["first_win"]
    assert onboarding.HINTS["pause"]
    for choice in onboarding.SECOND_GESTURE_CHOICES:
        assert onboarding.HINTS["second_gesture"][choice]


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
