"""A small storage box with a screw-down lid: two printed bodies joined by four M3 screws into
captive square nuts."""

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Color,
    Compound,
    Cylinder,
    Location,
    Locations,
    Mode,
    Part,
    Rectangle,
    add,
    extrude,
    fillet,
)

from src import hardware
from src.exporter import part_choices
from src.hardware import NutType, PrintOrientation, ScrewHeadType, ScrewSize
from src.part_tags import body, sacrificial
from src.printer import DOWN_MINUS_Z, group_by_body

from . import config

# Corner name -> (x sign, y sign).
CORNERS: dict[str, tuple[int, int]] = {
    "Front Left": (-1, -1),
    "Front Right": (1, -1),
    "Back Left": (-1, 1),
    "Back Right": (1, 1),
}

PART_NAMES = {"Box", "Lid"} | {
    f"{corner} {suffix}"
    for corner in CORNERS
    for suffix in ("M3 Screw", "M3 Square Nut", "Screw Clearance", "Nut Bridge")
}


def create_screw_joint(corner: str) -> tuple[Part, Part, Part]:
    """One corner's screw, its captive nut and the single void that clears both.

    The screw runs straight down the print direction of both bodies — each prints with its
    underside on the bed — so its hole is round rather than teardropped. The nut's pocket is
    stretched into a slot towards the middle of the box, so the nut is pushed in from inside it:
    the pocket must not open on the lid side, or lifting the lid would leave nothing holding it.
    """
    sx, sy = CORNERS[corner]
    screw, nut, clearance = hardware.create_screw_joint(
        ScrewSize.M3,
        config.screw_length,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=config.nut_side_length,
        nut_depth=config.nut_depth,
        nut_offset=config.nut_offset,
        nut_slide_length=config.nut_slot_length,
        nut_slide_angle_deg=180.0 if sx > 0 else 0.0,
        clearance_below_screw=config.screw_clearance_below,
    )
    assert nut is not None
    loc = Location((sx * config.screw_x, sy * config.screw_y, config.head_bearing_z))
    return screw.moved(loc), nut.moved(loc), clearance.moved(loc)


def _clearances() -> list[Part]:
    """All four screw voids. Each body subtracts all of them; whatever part of a void falls
    outside a body's own material simply removes nothing."""
    return [create_screw_joint(corner)[2] for corner in CORNERS]


@body("Box", DOWN_MINUS_Z)
def create_box() -> Part:
    """The open box: floor, walls, a corner boss for each nut, and the locating lip on top of the
    walls. Prints floor-down, so the cavity, the lip and the bosses all build straight up."""
    inner_length = config.length - 2 * config.wall
    inner_width = config.width - 2 * config.wall
    with BuildPart() as p:
        Box(config.length, config.width, config.wall_height, align=(Align.CENTER, Align.CENTER, Align.MIN))
        fillet(p.edges().filter_by(Axis.Z), radius=config.outer_fillet_r)
        with Locations((0, 0, config.floor)):
            Box(
                inner_length,
                inner_width,
                config.wall_height,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
                mode=Mode.SUBTRACT,
            )

        # Bosses fill each inside corner from the floor to the wall top.
        for sx, sy in CORNERS.values():
            corner_x = sx * (inner_length - config.boss_size) / 2.0
            corner_y = sy * (inner_width - config.boss_size) / 2.0
            with Locations((corner_x, corner_y, config.floor)):
                Box(
                    config.boss_size,
                    config.boss_size,
                    config.wall_height - config.floor,
                    align=(Align.CENTER, Align.CENTER, Align.MIN),
                )

        # The lip: the inner part of the wall, carried on above the wall top.
        lip_length = inner_length + 2 * config.lip_thickness
        lip_width = inner_width + 2 * config.lip_thickness
        with BuildSketch(Location((0, 0, config.wall_height))):
            Rectangle(lip_length, lip_width)
            Rectangle(inner_length, inner_width, mode=Mode.SUBTRACT)
        extrude(amount=config.lip_height)

        for clearance in _clearances():
            add(clearance, mode=Mode.SUBTRACT)
    assert p.part is not None
    return p.part


@body("Lid", DOWN_MINUS_Z)
def create_lid() -> Part:
    """The lid: a plate with a groove underneath that the box's lip drops into, and a counterbore
    at each corner so the screw heads finish flush with the top. Prints underside-down, which puts
    the groove on the bed and leaves the counterbores opening upward."""
    groove_outer_length = config.length - 2 * config.wall + 2 * (config.lip_thickness + config.lip_clearance)
    groove_outer_width = config.width - 2 * config.wall + 2 * (config.lip_thickness + config.lip_clearance)
    groove_inner_length = config.length - 2 * config.wall - 2 * config.lip_clearance
    groove_inner_width = config.width - 2 * config.wall - 2 * config.lip_clearance
    with BuildPart() as p:
        with Locations((0, 0, config.wall_height)):
            Box(config.length, config.width, config.lid_thickness, align=(Align.CENTER, Align.CENTER, Align.MIN))
        fillet(p.edges().filter_by(Axis.Z), radius=config.outer_fillet_r)
        with BuildSketch(Location((0, 0, config.wall_height))):
            Rectangle(groove_outer_length, groove_outer_width)
            Rectangle(groove_inner_length, groove_inner_width, mode=Mode.SUBTRACT)
        extrude(amount=config.groove_depth, mode=Mode.SUBTRACT)

        for clearance in _clearances():
            add(clearance, mode=Mode.SUBTRACT)
    assert p.part is not None
    return p.part


@body("Box", DOWN_MINUS_Z)
@sacrificial
def create_nut_bridge(corner: str) -> Part:
    """A one-layer disc plugging the screw's shank hole where it crosses the roof of the nut slot.
    The screw pushes through it on first assembly, which is why it is tagged sacrificial rather
    than modelled as part of the box itself. See config.nut_bridge_thickness."""
    sx, sy = CORNERS[corner]
    return Cylinder(
        config.shank_clearance_r,
        config.nut_bridge_thickness,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    ).moved(Location((sx * config.screw_x, sy * config.screw_y, config.nut_pocket_top_z)))


def create_assembly() -> list[Part | Compound]:
    """Create all box parts and return them as a list."""
    box = create_box()
    box.label = "Box"
    box.color = Color("steelblue")

    lid = create_lid()
    lid.label = "Lid"
    lid.color = Color("orange")

    hardware_parts: list[Part] = []
    for corner in CORNERS:
        screw, nut, clearance = create_screw_joint(corner)
        bridge = create_nut_bridge(corner)
        screw.label = f"{corner} M3 Screw"
        screw.color = Color("darkgray")
        nut.label = f"{corner} M3 Square Nut"
        nut.color = Color("darkgray")
        clearance.label = f"{corner} Screw Clearance"
        clearance.color = Color("red", 0.5)
        bridge.label = f"{corner} Nut Bridge"
        bridge.color = Color("steelblue")
        hardware_parts += [screw, nut, clearance, bridge]

    parts: list[Part | Compound] = [box, lid, *hardware_parts]
    assert {p.label for p in parts} == PART_NAMES
    return parts


def _derive_part_choices() -> dict[str, set[str]]:
    """The standard per-part choices, plus one per printed body (the Box with its nut bridges),
    derived from an actual build so they cannot go stale."""
    choices = part_choices(PART_NAMES)
    for body_name, group in group_by_body(create_assembly()).items():
        choices[f"{body_name} Body"] = {p.label for p in group}
    return choices


PART_CHOICES: dict[str, set[str]] = _derive_part_choices()
