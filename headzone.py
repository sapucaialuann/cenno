"""Is the hand beside the head?  Used for push-to-talk: a hang-loose held by
the ear (like a phone call) holds the dictation key, anywhere else it toggles.

The geometry is pure Python so it can be tested without a camera.  Only
FaceTracker touches mediapipe, and only when it is first used.
"""

# --- Head zone (all relative to the detected face box) ---
HEAD_SIDE_REACH = 1.0         # hand centre at most this far (face widths) beyond the face's side edge
HEAD_MIN_SIDE_OFFSET = 0.35   # ...and at least this far (face widths) from the face centre
HEAD_TOP_MARGIN = 0.3         # zone starts this far above the face top (face heights)
HEAD_BOTTOM_MARGIN = 0.6      # ...and ends this far below the chin (face heights)
HEAD_PALM_RATIO_MIN = 0.35    # palm / face width; smaller = hand far behind the head
HEAD_PALM_RATIO_MAX = 1.6     # larger = hand much closer to the camera than the head
FACE_MEMORY_SECONDS = 0.6     # keep the last face box this long when detection drops out
FACE_MIN_CONFIDENCE = 0.5

PALM_POINTS = (0, 5, 9, 13, 17)     # wrist + knuckles: the hand centre


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


def near_head(pts, palm, face):
    """True when the hand (21 landmarks in px, palm size in px) is beside the
    head: at ear or cheek height, off to one side, and about as far from the
    camera as the face."""
    if face is None:
        return False
    x0, y0, x1, y1 = face
    fw, fh = x1 - x0, y1 - y0
    if fw <= 0 or fh <= 0:
        return False
    hx = sum(pts[i][0] for i in PALM_POINTS) / len(PALM_POINTS)
    hy = sum(pts[i][1] for i in PALM_POINTS) / len(PALM_POINTS)
    offset = abs(hx - (x0 + x1) / 2)
    if offset < HEAD_MIN_SIDE_OFFSET * fw:
        return False                         # in front of the face
    if offset - fw / 2 > HEAD_SIDE_REACH * fw:
        return False                         # too far out to the side
    if not (y0 - HEAD_TOP_MARGIN * fh <= hy <= y1 + HEAD_BOTTOM_MARGIN * fh):
        return False
    return HEAD_PALM_RATIO_MIN <= palm / fw <= HEAD_PALM_RATIO_MAX


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
