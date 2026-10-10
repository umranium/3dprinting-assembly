"""Phone stand dimensions.

Datum: origin on the desk surface, centred across the stand's width. +X runs across the stand,
+Y runs from the front lip towards the back, +Z is up. Every profile point below is a (Y, Z) pair
in the stand's side view, which is extruded across X.
"""

import math

# --- The phone it holds (reference part, see REQUIREMENTS.md Assumptions) --------------------
# A large phone in a case, the worst case of the range in REQUIREMENTS.md: a smaller phone sits
# in the same groove with room to spare, a larger one would foul the lip.
phone_length = 165.0  # mm, long edge, standing up the backrest
phone_width = 80.0  # mm, across the stand
phone_thickness = 12.0  # mm, front to back, case included

# How far the phone leans back from vertical. Steep enough to read on a desk, shallow enough that
# a tap on the screen pushes it into the backrest rather than over the lip.
lean_deg = 25.0
lean_rad = math.radians(lean_deg)
_sin = math.sin(lean_rad)
_cos = math.cos(lean_rad)

# --- Stand -----------------------------------------------------------------------------------
stand_width = 70.0  # mm, across X; the phone overhangs it on both sides, so buttons stay clear
base_thickness = 5.0  # mm, the plate that sits on the desk
wall = 6.0  # mm, backrest and rear strut thickness
lip_thickness = 5.0  # mm, front lip, Y
lip_height = 10.0  # mm, how far the lip stands above the groove floor
base_back_y = 50.0  # mm, rear edge of the base, behind the phone's centre of gravity
backrest_length = 80.0  # mm, along the lean, from the groove floor up

# Gap between the phone's front-bottom corner and the lip's inner face, so the phone drops in
# without binding on a slightly over-thick case.
lip_clearance = 1.0  # mm

# Where the phone's back-bottom corner meets the groove floor. The backrest's front face starts
# here and runs up the lean.
groove_back_y = -20.0  # mm
floor_z = base_thickness

# Unit vectors in the side view: up the backrest, and out of its back face.
up_lean = (_sin, _cos)
out_back = (_cos, -_sin)


def _along(p: tuple[float, float], d: tuple[float, float], t: float) -> tuple[float, float]:
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def _line_at_z(p: tuple[float, float], d: tuple[float, float], z: float) -> tuple[float, float]:
    """Where the line through p along d crosses height z."""
    return _along(p, d, (z - p[1]) / d[1])


def _intersect(
    p: tuple[float, float], d: tuple[float, float], q: tuple[float, float], e: tuple[float, float]
) -> tuple[float, float]:
    """Where the line through p along d crosses the line through q along e."""
    det = d[0] * -e[1] - d[1] * -e[0]
    t = ((q[0] - p[0]) * -e[1] - (q[1] - p[1]) * -e[0]) / det
    return _along(p, d, t)


# Backrest: front face from the groove floor up the lean, back face one wall further out.
BACKREST_FRONT_BOTTOM = (groove_back_y, floor_z)
BACKREST_FRONT_TOP = _along(BACKREST_FRONT_BOTTOM, up_lean, backrest_length)
BACKREST_BACK_TOP = _along(BACKREST_FRONT_TOP, out_back, wall)
_backrest_back_bottom = _along(BACKREST_FRONT_BOTTOM, out_back, wall)

# Phone's front-bottom corner, and the lip just in front of it.
PHONE_FRONT_BOTTOM = _along(BACKREST_FRONT_BOTTOM, out_back, -phone_thickness)
lip_inner_y = PHONE_FRONT_BOTTOM[0] - lip_clearance
base_front_y = lip_inner_y - lip_thickness  # the lip's outer face and the base's front edge are flush

# Rear strut: its outer face runs from the base's back top corner to the backrest's back top
# corner; its inner face is one wall inside that.
STRUT_OUTER_BOTTOM = (base_back_y, base_thickness + 1.0)
_strut_dir = (BACKREST_BACK_TOP[0] - STRUT_OUTER_BOTTOM[0], BACKREST_BACK_TOP[1] - STRUT_OUTER_BOTTOM[1])
_strut_len = math.hypot(*_strut_dir)
strut_dir = (_strut_dir[0] / _strut_len, _strut_dir[1] / _strut_len)
_strut_inward = (-strut_dir[1], strut_dir[0])  # rotate +90°: forward, towards the window
assert _strut_inward[0] < 0, "strut inward normal should point forward, into the window"
_strut_inner_point = _along(STRUT_OUTER_BOTTOM, _strut_inward, wall)

# The window between base, backrest and strut, saving material without weakening the triangle.
WINDOW = [
    _line_at_z(_backrest_back_bottom, up_lean, floor_z),
    _line_at_z(_strut_inner_point, strut_dir, floor_z),
    _intersect(_strut_inner_point, strut_dir, _backrest_back_bottom, up_lean),
]

# Centre of the phone, in the side view: the stand must reach behind it or it tips over.
PHONE_CENTRE = _along(_along(BACKREST_FRONT_BOTTOM, up_lean, phone_length / 2.0), out_back, -phone_thickness / 2.0)
assert base_back_y > PHONE_CENTRE[0], "base does not reach behind the phone's centre of gravity"
