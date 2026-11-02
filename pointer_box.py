"""Pointer box styling for the camera preview in Cenno."""


def pointer_box_style(pose, mouse_on, pointer_mode, pinched):
    """Drawing style for the pointer box in the camera preview.

    Draws the box whenever the pose is "point" and mouse control is on:
    - absolute ("Aim"): box maps to the screen, 2 px, ember if pinched, trace otherwise.
    - relative ("Trackpad"): the same box as a guide to where the hand is
      tracked comfortably.  Also 2 px: the preview is scaled down, and a
      1 px line fades to almost nothing in the small size.

    Returns (thickness, color_name) or None if the box should not be drawn.
    """
    if pose != "point" or not mouse_on:
        return None
    if pointer_mode not in ("absolute", "relative"):
        return None
    return (2, "ember" if pinched else "trace")
