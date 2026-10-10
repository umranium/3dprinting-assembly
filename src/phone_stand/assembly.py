"""Desk phone stand: one printed body in two colours, holding a modelled phone."""

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
    extrude,
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


def _extrude_profile(points: list[tuple[float, float]], holes: tuple[list[tuple[float, float]], ...] = ()) -> Part:
    """Extrude a (Y, Z) side-view profile across the stand's full width, centred on X=0."""
    with BuildPart() as p:
        with BuildSketch(Plane.YZ) as s:
            Polygon(*points, align=None)
            for hole in holes:
                Polygon(*hole, align=None, mode=Mode.SUBTRACT)
        extrude(s.sketch, amount=config.stand_width / 2.0, both=True)
    assert p.part is not None
    return p.part


@body("Stand", STAND_DOWN)
def create_stand() -> Part:
    """Base, backrest and rear strut as one triangulated frame, with the groove the phone stands
    in. The lip in front of the groove is a separate part (see create_lip) only so it can take a
    second colour; it fuses into this same printed body."""
    outline = [
        (config.base_front_y, 0.0),
        (config.base_back_y, 0.0),
        config.STRUT_OUTER_BOTTOM,
        config.BACKREST_BACK_TOP,
        config.BACKREST_FRONT_TOP,
        config.BACKREST_FRONT_BOTTOM,
        (config.base_front_y, config.floor_z),
    ]
    return _extrude_profile(outline, holes=(config.WINDOW,))


@body("Stand", STAND_DOWN)
def create_lip() -> Part:
    """The front lip that stops the phone sliding off the groove: a contrasting-colour strip
    standing on the base's front edge."""
    top_z = config.floor_z + config.lip_height
    return _extrude_profile(
        [
            (config.base_front_y, config.floor_z),
            (config.lip_inner_y, config.floor_z),
            (config.lip_inner_y, top_z),
            (config.base_front_y, top_z),
        ]
    )


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
