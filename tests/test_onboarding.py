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


def test_skip_leaves_the_step():
    ob = onboarding.Onboarding("windows")
    ob.skip()
    assert ob.step == "camera"
    ob.skip()
    assert ob.step == "first_win"


def test_skip_all_finishes_the_tour():
    ob = onboarding.Onboarding("macos")
    ob.skip_all()
    assert ob.finished
    assert ob.step == "done"


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


def test_pause_needs_a_pause_and_then_a_resume():
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "pause")
    assert ob.on_event("pause_on") is False
    assert ob.on_event("pause_off") is True


def test_pause_does_not_finish_with_cenno_paused():
    # The step ends on a resume, so the tour cannot leave Cenno paused.
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "pause")
    assert ob.on_event("pause_off") is False
    assert ob.on_event("pause_on") is False


def test_pause_that_started_paused_needs_a_pause_first():
    # Cenno was paused before the step, so the first horns gesture only
    # resumes it: the step is not done until the user paused it again.
    ob = onboarding.Onboarding("macos")
    walk_to(ob, "pause")
    assert ob.on_event("pause_off") is False
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


def test_hints_exist_for_every_gesture_step():
    assert onboarding.HINTS["first_win"]
    assert onboarding.HINTS["pause"]
    for choice in onboarding.SECOND_GESTURE_CHOICES:
        assert onboarding.HINTS["second_gesture"][choice]


def test_hint_for_the_gesture_steps():
    assert onboarding.hint_for("first_win") == onboarding.HINTS["first_win"]
    assert onboarding.hint_for("pause") == onboarding.HINTS["pause"]
    for choice in onboarding.SECOND_GESTURE_CHOICES:
        hint = onboarding.hint_for("second_gesture", choice)
        assert hint == onboarding.HINTS["second_gesture"][choice]


def test_no_hint_for_the_other_steps():
    assert onboarding.hint_for("welcome") == ""
    assert onboarding.hint_for("camera") == ""
    assert onboarding.hint_for("second_gesture") == ""


def test_the_gesture_steps_are_the_ones_that_wait_for_a_gesture():
    assert onboarding.GESTURE_STEPS == ("first_win", "pause", "second_gesture")
    for step in onboarding.GESTURE_STEPS:
        assert onboarding.STEP_DONE.get(step) or step == "first_win"


def test_the_second_gesture_buttons_are_choices_the_tour_knows():
    keys = [key for key, _label in onboarding.SECOND_CHOICES]
    assert keys == list(onboarding.SECOND_GESTURE_CHOICES)
    ob = onboarding.Onboarding("macos")
    for key in keys:
        assert ob.choose_second(key) is True


def test_the_tour_watches_every_gesture_group():
    for name in onboarding.SPACE_EVENTS + onboarding.PAUSE_EVENTS + \
            onboarding.SCROLL_EVENTS + onboarding.PINCH_EVENTS:
        assert name in onboarding.ONBOARDING_EVENTS
    assert onboarding.EVENT_PLAY_PAUSE in onboarding.ONBOARDING_EVENTS


def test_the_hand_timer_waits_for_the_whole_time():
    timer = onboarding.HandTimer(4.0)
    assert timer.reached(100.0, True) is False     # the hand just arrived
    assert timer.reached(101.0, True) is False     # not long enough yet
    assert timer.reached(104.0, True) is True      # long enough now


def test_the_hand_timer_starts_over_when_the_hand_leaves():
    timer = onboarding.HandTimer(4.0)
    timer.reached(100.0, True)
    assert timer.reached(103.0, False) is False    # the hand left
    assert timer.reached(104.0, True) is False     # the count starts again
    assert timer.reached(108.0, True) is True


def test_the_hand_timer_counts_again_after_a_miss():
    timer = onboarding.HandTimer(4.0)
    timer.reached(100.0, True)
    assert timer.reached(104.0, True) is True
    assert timer.reached(105.0, True) is False     # the count starts again
    assert timer.reached(108.0, True) is True


def test_the_hand_timer_forgets_the_hand_on_reset():
    timer = onboarding.HandTimer(4.0)
    timer.reached(100.0, True)
    timer.reset()
    assert timer.reached(104.0, True) is False


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
