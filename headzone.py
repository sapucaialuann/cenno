"""Is the hand beside the head?  Used for push-to-talk: a hang-loose held by
the ear (like a phone call) holds the dictation key, anywhere else it toggles.

The geometry is pure Python so it can be tested without a camera.  Only
FaceTracker touches mediapipe, and only when it is first used.
"""

# --- Head zone (all relative to the detected face box) ---
# Held like a phone: the thumb tip at the ear, the pinky below it towards the
# mouth.  A hang loose shown to the camera has the pinky up and the thumb out
# to the side, so the thumb-above-pinky test is what tells the two apart.
HEAD_EAR_INSIDE = 0.25        # thumb tip at most this far (face widths) inside the face's side edge
HEAD_EAR_OUTSIDE = 0.6        # ...or this far outside it
HEAD_EAR_TOP = 0.15           # ear band starts this far above the face top (face heights)
HEAD_EAR_BOTTOM = 0.75        # ...and ends this far down the face (face heights)
HEAD_UPRIGHT = 0.5            # pinky tip below the thumb tip by this share of their distance
HEAD_PALM_RATIO_MIN = 0.35    # palm / face width; smaller = hand far behind the head
HEAD_PALM_RATIO_MAX = 1.6     # larger = hand much closer to the camera than the head
FACE_MEMORY_SECONDS = 0.6     # keep the last face box this long when detection drops out
FACE_MIN_CONFIDENCE = 0.5

def face_box_from_detection(detection, w, h):
    """Pixel box (x0, y0, x1, y1) of a mediapipe face detection, or None."""
    try:
        r = detection.location_data.relative_bounding_box
        x0, y0 = r.xmin * w, r.ymin * h
        x1, y1 = x0 + r.width * w, y0 + r.height * h
    except AttributeError:
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def head_check(pts, palm, face):
    """(near, why): is the hand (21 landmarks in px, palm size in px) held
    like a phone by the ear?  `why` names the first test that failed, with
    the measurement, so the log shows what to tune."""
    if face is None:
        return False, "no face"
    x0, y0, x1, y1 = face
    fw, fh = x1 - x0, y1 - y0
    if fw <= 0 or fh <= 0:
        return False, "no face"
    (tx, ty), (px, py) = pts[4], pts[20]
    span = ((px - tx) ** 2 + (py - ty) ** 2) ** 0.5 or 1.0
    upright = (py - ty) / span
    if upright < HEAD_UPRIGHT:
        return False, f"not held like a phone (upright {upright:+.2f})"
    right = tx > (x0 + x1) / 2
    out = (tx - x1 if right else x0 - tx) / fw    # beyond the side edge
    if not -HEAD_EAR_INSIDE <= out <= HEAD_EAR_OUTSIDE:
        return False, f"thumb not at the ear (side {out:+.2f})"
    down = (ty - y0) / fh                          # from the face top
    if not -HEAD_EAR_TOP <= down <= HEAD_EAR_BOTTOM:
        return False, f"thumb not at ear height (height {down:+.2f})"
    ratio = palm / fw
    if not HEAD_PALM_RATIO_MIN <= ratio <= HEAD_PALM_RATIO_MAX:
        return False, f"hand not beside the head (palm/face {ratio:.2f})"
    return True, f"by the ear (upright {upright:+.2f}, side {out:+.2f}, height {down:+.2f})"


def near_head(pts, palm, face):
    """True when the hand is held like a phone by the ear."""
    return head_check(pts, palm, face)[0]


class FaceTracker:
    """Lazy mediapipe face detector that returns the largest face box and
    bridges short dropouts (a hand at the cheek can hide part of the face)."""

    def __init__(self):
        self._detector = None
        self._last = None
        self._last_t = -1e9

    def update(self, rgb, w, h, now):
        if self._detector is None:
            import mediapipe as mp
            self._detector = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=FACE_MIN_CONFIDENCE)
        res = self._detector.process(rgb)
        best, area = None, 0.0
        for det in res.detections or []:
            box = face_box_from_detection(det, w, h)
            if box and (box[2] - box[0]) * (box[3] - box[1]) > area:
                best, area = box, (box[2] - box[0]) * (box[3] - box[1])
        if best is not None:
            self._last, self._last_t = best, now
            return best
        return self._last if now - self._last_t <= FACE_MEMORY_SECONDS else None

    def close(self):
        if self._detector is not None:
            self._detector.close()
            self._detector = None
