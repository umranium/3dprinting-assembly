"""Desk phone stand: one printed body in two colours, holding a modelled phone."""

import math

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Color,
    Compound,
    Location,
    Mode,
    Part,
    Plane,
    Polygon,
    add,
    chamfer,
    extrude,
    fillet,
)

from src.exporter import part_choices
from src.part_tags import body, non_printable
from src.printer import DOWN_MINUS_X

from . import config

PART_NAMES = {"Stand", "Lip", "Phone"}

PART_CHOICES: dict[str, set[str]] = part_choices(PART_NAMES)

# The stand prints lying on one end face. Its side profile then runs straight up the print as a
# constant cross-section: no overhangs anywhere, and the layers lie across the backrest so the
# phone's weight bends the part across its layer lines rather than peeling them apart.
STAND_DOWN = DOWN_MINUS_X


def _top_z() -> float:
    return config.floor_z + config.lip_height


def _stand_with_lip() -> Part:
    """The whole printed body, stand and lip together, with its edges treated.

    The edges are treated on the combined shape and only then split into stand and lip, so the
    rounding runs unbroken across the colour seam on the front face."""
    top_z = _top_z()
    outline = [
        (config.base_front_y, 0.0),
        (config.base_back_y, 0.0),
        config.STRUT_OUTER_BOTTOM,
        config.BACKREST_BACK_TOP,
        config.BACKREST_FRONT_TOP,
        config.BACKREST_FRONT_BOTTOM,
        (config.lip_inner_y, config.floor_z),
        (config.lip_inner_y, top_z),
        (config.base_front_y, top_z),
    ]
    # The two corners the phone sits in stay sharp; see config.edge_fillet_r. Sketch vertices are
    # in the sketch plane's own frame, where (X, Y) is the profile's (Y, Z).
    sharp = (config.BACKREST_FRONT_BOTTOM, (config.lip_inner_y, config.floor_z))
    with BuildPart() as p:
        with BuildSketch(Plane.YZ) as s:
            Polygon(*outline, align=None)
            Polygon(*config.WINDOW, align=None, mode=Mode.SUBTRACT)
            fillet(
                [v for v in s.vertices() if all(math.dist((v.X, v.Y), c) > 1e-6 for c in sharp)],
                radius=config.edge_fillet_r,
            )
        extrude(s.sketch, amount=config.stand_width / 2.0, both=True)
        fillet(p.faces().sort_by(Axis.X)[-1].edges(), radius=config.edge_fillet_r)
        chamfer(p.faces().sort_by(Axis.X)[0].edges(), length=config.bed_chamfer)
    assert p.part is not None
    return p.part


def _split(mode: Mode) -> Part:
    """The treated body with the lip region subtracted (the stand) or intersected (the lip)."""
    # Both shapes are made before entering the builder: a Box made inside one adds itself to it.
    whole, region = _stand_with_lip(), _lip_region()
    with BuildPart() as p:
        add(whole)
        add(region, mode=mode)
    assert p.part is not None
    return p.part


def _lip_region() -> Part:
    """A block enclosing the lip and nothing else, used to split it from the stand."""
    margin = 1.0
    front_y = config.base_front_y - margin
    return Box(
        config.stand_width + 2 * margin,
        config.lip_inner_y - front_y,
        _top_z() + margin - config.floor_z,
        align=(Align.CENTER, Align.MIN, Align.MIN),
    ).moved(Location((0, front_y, config.floor_z)))


@body("Stand", STAND_DOWN)
def create_stand() -> Part:
    """Base, backrest and rear strut as one triangulated frame, with the groove the phone stands
    in. The lip in front of the groove is a separate part (see create_lip) only so it can take a
    second colour; it fuses into this same printed body."""
    return _split(Mode.SUBTRACT)


@body("Stand", STAND_DOWN)
def create_lip() -> Part:
    """The front lip that stops the phone sliding off the groove: a contrasting-colour strip
    standing on the base's front edge."""
    return _split(Mode.INTERSECT)


@non_printable
def create_phone() -> Part:
    """The phone, as a plain slab at its worst-case size, leaning back against the backrest with
    its back-bottom edge on the groove floor. Drawn whole and never trimmed, so if the groove or
    lip were too tight the collision suite would see the overlap."""
    phone = Box(
        config.phone_width,
        config.phone_thickness,
        config.phone_length,
        align=(Align.CENTER, Align.MAX, Align.MIN),
    )
    y, z = config.BACKREST_FRONT_BOTTOM
    return phone.rotate(Axis.X, -config.lean_deg).moved(Location((0, y, z)))


def create_assembly() -> list[Part | Compound]:
    """Create all phone stand parts and return them as a list."""
    stand = create_stand()
    stand.label = "Stand"
    stand.color = Color("steelblue")

    lip = create_lip()
    lip.label = "Lip"
    lip.color = Color("orange")

    phone = create_phone()
    phone.label = "Phone"
    phone.color = Color("black", 0.6)

    parts: list[Part | Compound] = [stand, lip, phone]
    assert {p.label for p in parts} == PART_NAMES
    return parts
