"""
Score Space switching (slaps) against recorded gesture checks.

Replays every step of every recording through the current engine and
prints, per recording: slaps that fired in the right direction, slaps that
fired the wrong way (usually the return stroke), Space switches that fired
in any other step (false triggers), and how many steps pass overall.

    python3 tools/slap_score.py                 # all recordings in checks/
    python3 tools/slap_score.py checks/a.json   # some of them
"""

import contextlib
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import gesture_check as gc          # noqa: E402

BY_ID = {s["id"]: s for s in gc.STEPS}
WANT = {"slap_right": "space_left", "slap_left": "space_right"}   # natural swipe


def score(path):
    with open(path) as f:
        rec = json.load(f)
    out = dict(hits={}, wrong=0, elsewhere={}, passed=0, steps=0)
    for sr in rec["steps"]:
        with contextlib.redirect_stdout(io.StringIO()):
            counts, _ = gc.replay_step(rec, sr)
        missing, stray = gc.judge(BY_ID[sr["id"]], counts)
        out["steps"] += 1
        out["passed"] += not missing and not stray
        spaces = {n: c for n, c in counts.items() if n.startswith("space_")}
        if sr["id"] in WANT:
            want = WANT[sr["id"]]
            out["hits"][sr["id"]] = spaces.get(want, 0)
            out["wrong"] += sum(c for n, c in spaces.items() if n != want)
        elif spaces:
            out["elsewhere"][sr["id"]] = sum(spaces.values())
    return out


def main(paths):
    paths = paths or sorted(glob.glob(os.path.join(ROOT, "checks", "check-*.json")))
    total_hits = total_wrong = total_else = 0
    for p in paths:
        s = score(p)
        hits = ", ".join(f"{k} {v}/3" for k, v in s["hits"].items()) or "no slap steps"
        print(f"{os.path.basename(p)}: {hits}   wrong-way {s['wrong']}   "
              f"elsewhere {sum(s['elsewhere'].values())} {s['elsewhere'] or ''}   "
              f"steps passing {s['passed']}/{s['steps']}")
        total_hits += sum(min(v, 3) for v in s["hits"].values())
        total_wrong += s["wrong"]
        total_else += sum(s["elsewhere"].values())
    print(f"TOTAL: right-way slaps {total_hits}, wrong-way {total_wrong}, "
          f"Space switches in other steps {total_else}")


if __name__ == "__main__":
    main(sys.argv[1:])
