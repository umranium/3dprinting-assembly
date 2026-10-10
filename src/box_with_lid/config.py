"""Box with lid dimensions.

Datum: origin at the centre of the box's underside, on the desk. +X along the box's length, +Y
along its width, +Z up. The lid sits on top of the box's walls at Z = wall_height.
"""

from src import hardware
from src.hardware import ScrewSize

# --- Box -------------------------------------------------------------------------------------
length = 70.0  # mm, outside, X
width = 50.0  # mm, outside, Y
wall_height = 35.0  # mm, floor of the box to the top of its walls
wall = 3.6  # mm, six 0.6 mm perimeters
floor = 2.4  # mm
outer_fillet_r = 3.0  # mm, the vertical outside corners of box and lid

# A locating lip stands up from the inner half of the wall's top and drops into a matching groove
# under the lid. It is what stops the lid sliding or twisting on the box, so the screws only ever
# have to pull it down.
lip_height = 3.0  # mm above the wall top
lip_thickness = 1.8  # mm, the wall's inner half
lip_clearance = 0.2  # mm each side of the lip, in the lid's groove and above it

# --- Lid -------------------------------------------------------------------------------------
lid_thickness = 6.0  # mm
groove_depth = lip_height + lip_clearance

# --- Corner screws ---------------------------------------------------------------------------
# A square boss in each inside corner carries a captive M3 square nut; the screw goes down
# through the lid into it. Everything is driven from the top.
boss_size = 10.0  # mm square
screw_inset = wall + boss_size / 2.0  # from each outside face to the screw axis
screw_x = length / 2.0 - screw_inset
screw_y = width / 2.0 - screw_inset

_M3 = hardware._SCREW_DIMENSIONS[ScrewSize.M3]
head_bearing_z = wall_height + lid_thickness - _M3.socket_head_height  # head sits flush in the lid
screw_length = 12.0  # mm, under the head to the tip
nut_side_length = 5.5  # mm, M3 square nut across the flats
nut_depth = 2.0  # mm
nut_offset = 9.0  # mm, head bearing face down to the nut's centre — 6 mm into the boss
screw_clearance_below = 1.0  # mm of hole past the screw tip

# The nut is pushed into its pocket sideways from inside the box, along a slot that breaks out of
# the boss's inner face. The slot length is added beyond the pocket's own far edge, so this takes
# the slot from there to a millimetre past the boss's inner face.
nut_slot_length = boss_size / 2.0 + 1.0 - (nut_side_length + hardware._SQUARE_NUT_POCKET_MARGIN) / 2.0

# The slot's roof is a bridge, and the screw's own shank hole goes up through the middle of it. A
# bridge cannot span a void with a hole taken out of its middle, so a one-layer disc plugs the
# hole for exactly that layer; the screw pushes through it on first assembly.
nut_bridge_thickness = 0.2  # mm, one layer
nut_pocket_top_z = head_bearing_z - nut_offset + (nut_depth + hardware._SQUARE_NUT_POCKET_MARGIN) / 2.0
shank_clearance_r = _M3.shank_clearance_r
