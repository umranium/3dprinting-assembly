import math
from dataclasses import dataclass
from enum import Enum
from typing import cast

from build123d import (
    Align,
    Axis,
    BuildPart,
    BuildSketch,
    Circle,
    Compound,
    Cone,
    Location,
    Locations,
    Mode,
    Part,
    Plane,
    Polygon,
    Rectangle,
    RigidJoint,
    Sketch,
    Vector,
    add,
    extrude,
    loft,
)

from src.part_tags import HardwareType, get_tags, nut, screw
from src.printer import mark_non_printable


class ScrewSize(Enum):
    """Which screw thread size create_screw()/create_screw_joint() build for. Only M3 is
    implemented today; adding another size means adding another _SCREW_DIMENSIONS entry, not
    changing create_screw()/create_screw_joint() themselves."""

    M3 = "M3"


class ScrewHeadType(Enum):
    """Which head shape a screw (or its clearance hole) has."""

    SOCKET = "socket"
    COUNTERSUNK = "countersunk"


class PrintOrientation(Enum):
    """Which way a clearance hole's cross-section is shaped for self-supporting FDM printing:
    HORIZONTAL for a teardrop cross-section (the hole's own axis prints sideways, so it needs a
    self-supporting point rather than an unsupported round overhang), VERTICAL for a plain round
    cross-section (the hole's axis prints straight up, where a round hole prints fine on its own)."""

    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class NutType(Enum):
    """Which nut shape create_screw_joint() builds. Only SQUARE is implemented today."""

    SQUARE = "square"


@dataclass(frozen=True)
class _ScrewDimensions:
    """Real screw geometry and its clearance-hole equivalents for one screw size. Clearance radii
    add ~0.3mm over the real screw's own radii, standard margin for a 3D-printed clearance fit;
    clearance head depths match the real screw's own head heights exactly, so a hole built with
    head_depth == socket_head_height (or == countersunk_cone_height) recesses the head flush."""

    shank_r: float
    shank_clearance_r: float
    socket_head_r: float
    socket_head_clearance_r: float
    socket_head_height: float
    countersunk_head_r: float
    countersunk_head_clearance_r: float
    countersunk_cone_height: float


_SCREW_DIMENSIONS: dict[ScrewSize, _ScrewDimensions] = {
    ScrewSize.M3: _ScrewDimensions(
        shank_r=1.5,
        shank_clearance_r=1.8,
        socket_head_r=2.75,
        socket_head_clearance_r=2.9,
        socket_head_height=3.0,
        countersunk_head_r=3.0,
        countersunk_head_clearance_r=3.25,
        countersunk_cone_height=1.65,
    ),
}


def hardware_kind(part: Part | Compound) -> HardwareType | None:
    """Return the hardware role tagged by @screw/@nut, or None if untagged."""
    return get_tags(part).hardware_kind


def is_sacrificial(part: Part | Compound) -> bool:
    """Return whether a part was tagged sacrificial by @sacrificial."""
    return get_tags(part).sacrificial


def is_set_screw(part: Part | Compound) -> bool:
    """Return whether a screw instance was tagged as a set-screw by part_tags.mark_set_screw()."""
    return get_tags(part).set_screw


@screw
def create_screw(size: ScrewSize, length: float, head_type: ScrewHeadType) -> Part:
    """Screw factory (single contiguous body, no internal overlaps): a cylindrical shank plus
    either a cylindrical socket head or a tapered countersunk head, sized from `size`'s real
    dimensions (see _SCREW_DIMENSIONS — only ScrewSize.M3 is implemented today).

    `length`'s meaning follows standard hardware convention, which differs by head type since a
    socket head sits proud of the surface while a countersunk head sits flush/recessed into it:
    - SOCKET: the shank length only, measured from under the head to the tip — the head adds its
      own height on top of this.
    - COUNTERSUNK: the overall length from the head's flush top face to the tip — the head's own
      cone height counts toward this total rather than adding to it.
    """
    dims = _SCREW_DIMENSIONS[size]
    with BuildPart() as p:
        if head_type == ScrewHeadType.SOCKET:
            # Shank
            with BuildSketch(Plane.XY):
                Circle(radius=dims.shank_r)
            extrude(amount=length, dir=(0, 0, -1))

            # Head
            with BuildSketch(Plane.XY):
                Circle(radius=dims.socket_head_r)
            extrude(amount=dims.socket_head_height)

            head_z = 0.0
        else:
            # Shank
            with BuildSketch(Plane.XY):
                Circle(radius=dims.shank_r)
            extrude(amount=length - dims.countersunk_cone_height, dir=(0, 0, -1))

            # Conical head
            Cone(
                bottom_radius=dims.shank_r,
                top_radius=dims.countersunk_head_r,
                height=dims.countersunk_cone_height,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
            )

            head_z = dims.countersunk_cone_height
    assert p.part is not None
    # "head" marks the bearing face — where the head meets the shank for a socket head (the local
    # origin), or the cone's wide top for a countersunk head (which sits flush with the printable
    # material's outer surface once seated in a countersink) — with its local Z pointing down
    # through the shank into the tip, i.e. the direction the screw penetrates the material.
    RigidJoint(label="head", to_part=p.part, joint_location=Location(Plane(origin=(0, 0, head_z), z_dir=(0, 0, -1))))
    return p.part


def teardrop_sketch(r_clear: float) -> Sketch:
    """2D teardrop profile for horizontal holes."""
    with BuildSketch() as s:
        Circle(radius=r_clear)
        # 45 degree taper up to apex
        # apex is at [0, r_clear * sqrt(2)]
        # base points are [r_clear*cos(45), r_clear*sin(45)] and [-r_clear*cos(45), r_clear*sin(45)]
        pts = [
            (0, r_clear * math.sqrt(2)),
            (r_clear * math.cos(math.radians(45)), r_clear * math.sin(math.radians(45))),
            (-r_clear * math.cos(math.radians(45)), r_clear * math.sin(math.radians(45))),
        ]
        Polygon(*pts)
    return s.sketch


class _HoleAxis(Enum):
    """Which native axis a hole-building segment's "increasing d" direction runs along — separate
    from PrintOrientation, which only picks the cross-section shape (teardrop vs round).
    create_screw_joint() needs a teardrop cross-section that still runs along Z, to share
    create_screw()'s own Z-axis frame regardless of print orientation, so the two are threaded
    through separately here rather than being tied together."""

    Y = "Y"
    Z = "Z"


def _segment_plane(axis: _HoleAxis, d: float) -> Plane:
    """The sketch plane for a cross-section at depth `d` along a hole's shared "increasing d"
    axis, for the given native axis."""
    if axis == _HoleAxis.Y:
        return Plane.XZ.offset(d)
    return Plane.XY.offset(-d)


def _segment_extrude_dir(axis: _HoleAxis) -> tuple[float, float, float]:
    """The extrude direction that advances a sketch built by _segment_plane() further along a
    hole's shared "increasing d" axis, for the given native axis."""
    if axis == _HoleAxis.Y:
        return (0, -1, 0)
    return (0, 0, -1)


def _segment_profile(orientation: PrintOrientation, radius: float) -> Sketch:
    """The cross-section shape at the given clearance radius: a self-supporting teardrop for
    horizontal printing, or a plain circle for vertical printing."""
    if orientation == PrintOrientation.HORIZONTAL:
        return teardrop_sketch(radius)
    with BuildSketch() as s:
        Circle(radius=radius)
    return s.sketch


def _straight_hole_segment(
    orientation: PrintOrientation, radius: float, d_start: float, d_end: float, axis: _HoleAxis
) -> Part:
    """A constant-radius clearance segment spanning [d_start, d_end] along a hole's shared depth
    axis. `axis` is independent of `orientation` (which only picks the cross-section shape) —
    create_screw_joint() always passes Z, regardless of orientation, to share create_screw()'s own
    frame."""
    with BuildPart() as p:
        with BuildSketch(_segment_plane(axis, d_start)):
            add(_segment_profile(orientation, radius))
        extrude(amount=d_end - d_start, dir=_segment_extrude_dir(axis))
    assert p.part is not None
    return p.part


def _tapered_hole_segment(
    orientation: PrintOrientation,
    r_start: float,
    r_end: float,
    d_start: float,
    d_end: float,
    axis: _HoleAxis,
) -> Part:
    """A lofted clearance segment tapering from r_start (at d_start) to r_end (at d_end) along a
    hole's shared depth axis — the countersunk head's conical clearance. See
    _straight_hole_segment() for `axis`."""
    with BuildPart() as p:
        with BuildSketch(_segment_plane(axis, d_start)):
            add(_segment_profile(orientation, r_start))
        with BuildSketch(_segment_plane(axis, d_end)):
            add(_segment_profile(orientation, r_end))
        loft()
    assert p.part is not None
    return p.part


# Margin added to a nut's own side_length/depth to get its pocket's, split evenly as 0.25mm
# clearance on each side/face.
_SQUARE_NUT_POCKET_MARGIN = 0.5


@nut
def _square_nut(bore_r: float, side_length: float, depth: float) -> Part:
    """A square nut with a threaded bore, centered on its own local origin (bore axis = Z),
    symmetric front-to-back — create_screw_joint()'s own nut factory, sized from the given screw's
    own shank radius (`bore_r`) rather than hardcoded to one screw size."""
    with BuildPart() as p:
        with BuildSketch(Plane.XY):
            Rectangle(side_length, side_length)
            Circle(radius=bore_r, mode=Mode.SUBTRACT)
        extrude(amount=depth / 2.0, both=True)
    assert p.part is not None
    RigidJoint(label="bore", to_part=p.part, joint_location=Location(Plane(origin=(0, 0, 0), z_dir=(0, 0, 1))))
    return p.part


def _square_nut_pocket(
    side_length: float,
    depth: float,
    slide_length: float = 0.0,
    slide_angle_deg: float = 0.0,
    tip_extension: float = 0.0,
) -> Part:
    """A square pocket (no bore) sized to snugly fit a _square_nut() of the same side_length/depth
    plus _SQUARE_NUT_POCKET_MARGIN, centered on its own local origin by default —
    create_screw_joint()'s own nut-pocket factory.

    slide_length optionally elongates it into a sideways sliding-insertion slot: the pocket's near
    edge (at its own local origin, matching the nut's own resting position) stays fixed, and it
    extends slide_length further in local +X before slide_angle_deg rotates the whole elongated
    shape about the screw's own axis (local Z) — for a nut that must be dropped in at an offset
    point and slid into its final resting position rather than reached directly. The default
    slide_length=0 reduces to the plain, non-elongated pocket.

    tip_extension optionally instead elongates the pocket along local -Z (the screw's own tip
    direction) beyond its plain depth, leaving the head-side face where it is — for a nut that
    slides in along the screw's own axis from the tip/bottom opening of the screw hole rather than
    sideways. It is independent of slide_length/slide_angle_deg (a real nut only slides in from one
    direction, but nothing here enforces that); the default tip_extension=0 leaves the pocket's
    Z-extent unchanged."""
    pocket_width = side_length + _SQUARE_NUT_POCKET_MARGIN
    pocket_length = pocket_width + slide_length
    half_depth = (depth + _SQUARE_NUT_POCKET_MARGIN) / 2.0
    with BuildPart() as p:
        with BuildSketch(Plane.XY):
            with Locations((slide_length / 2.0, 0)):
                Rectangle(pocket_length, pocket_width)
        extrude(amount=half_depth, both=True)
        if tip_extension > 1e-9:
            with BuildSketch(Plane.XY.offset(-half_depth)):
                with Locations((slide_length / 2.0, 0)):
                    Rectangle(pocket_length, pocket_width)
            extrude(amount=tip_extension, dir=(0, 0, -1))
    assert p.part is not None
    return p.part.rotate(Axis.Z, slide_angle_deg)


def create_screw_joint(
    size: ScrewSize,
    length: float,
    head_type: ScrewHeadType,
    orientation: PrintOrientation,
    nut_type: NutType | None = None,
    nut_side_length: float | None = None,
    nut_depth: float | None = None,
    nut_offset: float | None = None,
    nut_slide_length: float = 0.0,
    nut_slide_angle_deg: float = 0.0,
    nut_slide_to_tip: bool = False,
    clearance_above_head: float = 0.0,
    clearance_below_screw: float = 0.0,
) -> tuple[Part, Part | None, Part]:
    """Coordinated screw+nut+clearance factory: builds a create_screw() screw, optionally a
    captive nut, and the single clearance void for both, all sharing create_screw()'s own frame
    (head bearing at local Z=0, tip at Z=-length) — no separate alignment/rotation bookkeeping
    needed between the three; place all of them with the same Location.

    Returns (screw, nut, clearance) — nut is None if no nut_type was given.

    Parameters:
        size, length, head_type: passed straight through to create_screw() — see its own
            docstring for `length`'s head-type-dependent meaning.
        orientation: shapes the clearance's cross-section (teardrop for horizontal printing,
            round for vertical) — the clearance itself always runs along create_screw()'s own Z
            axis regardless, so orientation only affects print-supportability, not alignment.
        nut_type, nut_side_length, nut_depth, nut_offset: a captive square nut, given all
            together (or all omitted for no nut). nut_offset is the distance from the screw's own
            head/shank transition (local Z=0, the same reference for both head types) down to the
            nut's own center, along the screw's axis — i.e. how far below the head the nut sits.
        nut_slide_length, nut_slide_angle_deg, nut_slide_to_tip: pick at most one of two ways a
            captive nut can be inserted, or leave both at their defaults for a print-in-place nut
            with no insertion slot at all (dropped in mid-print and fully enclosed):
              - nut_slide_length/nut_slide_angle_deg elongate the nut's own pocket sideways, into a
                slot in the plane perpendicular to the screw, for a nut that must be dropped in at
                an offset point and slid into its final resting position — see
                _square_nut_pocket()'s own docstring for exactly how the elongation and rotation
                are applied. The nut itself still sits only at its final resting position
                (nut_offset along the screw's own axis); only its pocket is widened.
              - nut_slide_to_tip instead opens the pocket along the screw's own axis, all the way
                to the tip end of the clearance, for a nut slid in from the bottom/tip opening of
                the screw hole itself rather than sideways.
        clearance_above_head: extra clearance length beyond the head's own natural recess depth,
            between the true opening face and where the head actually sits — lets a shorter screw's
            head sit recessed deeper in the body instead of flush (0 = flush).
        clearance_below_screw: extra clearance length beyond the screw's own tip, for margin/
            tolerance past where the screw physically ends (0 = clearance ends exactly at the tip).
    """
    nut_params = (nut_type, nut_side_length, nut_depth, nut_offset)
    if any(p is not None for p in nut_params):
        assert all(p is not None for p in nut_params), (
            "nut_type/nut_side_length/nut_depth/nut_offset must all be given together, or all omitted"
        )

    dims = _SCREW_DIMENSIONS[size]
    screw = create_screw(size, length, head_type)

    natural_head_depth = dims.socket_head_height if head_type == ScrewHeadType.SOCKET else dims.countersunk_cone_height
    head_depth = natural_head_depth + clearance_above_head
    hole_length = head_depth + length + clearance_below_screw

    nut_part: Part | None = None
    nut_pocket: Part | None = None
    excl_start: float | None = None
    excl_end: float | None = None
    if nut_type is not None:
        assert nut_side_length is not None and nut_depth is not None and nut_offset is not None
        assert not (nut_slide_length > 0.0 and nut_slide_to_tip), (
            "nut_slide_length and nut_slide_to_tip are two different insertion directions for the "
            "same nut — pick at most one"
        )
        d_nut_center = head_depth + nut_offset
        excl_start = d_nut_center - nut_depth / 2.0
        excl_end = d_nut_center + nut_depth / 2.0
        tip_extension = max(0.0, hole_length - excl_end) if nut_slide_to_tip else 0.0
        match nut_type:
            case NutType.SQUARE:
                # The nut is rotated by the same nut_slide_angle_deg as its pocket so the two
                # stay aligned at any angle — a square's own 4-fold symmetry means this doesn't
                # constrain which way its flat faces end up facing (any desired orientation is
                # reachable by choosing nut_slide_angle_deg mod 90° accordingly), but leaving the
                # nut unrotated while only the pocket turns would let the nut's own corners poke
                # out of the pocket at most angles.
                nut_part = (
                    _square_nut(dims.shank_r, nut_side_length, nut_depth)
                    .rotate(Axis.Z, nut_slide_angle_deg)
                    .moved(Location((0, 0, -nut_offset)))
                )
                nut_pocket = _square_nut_pocket(
                    nut_side_length, nut_depth, nut_slide_length, nut_slide_angle_deg, tip_extension
                ).moved(Location((0, 0, -nut_offset)))
        if nut_slide_to_tip:
            excl_end = hole_length

    hole_segments: list[Part] = []
    if head_type == ScrewHeadType.SOCKET:
        hole_segments.append(
            _straight_hole_segment(orientation, dims.socket_head_clearance_r, 0.0, head_depth, axis=_HoleAxis.Z)
        )
    else:
        cone_start = head_depth - dims.countersunk_cone_height
        if cone_start > 1e-9:
            hole_segments.append(
                _straight_hole_segment(
                    orientation, dims.countersunk_head_clearance_r, 0.0, cone_start, axis=_HoleAxis.Z
                )
            )
        hole_segments.append(
            _tapered_hole_segment(
                orientation,
                dims.countersunk_head_clearance_r,
                dims.shank_clearance_r,
                cone_start,
                head_depth,
                axis=_HoleAxis.Z,
            )
        )

    shank_ranges = [(head_depth, hole_length)]
    if excl_start is not None and excl_end is not None:
        clipped_start = max(excl_start, head_depth)
        clipped_end = min(excl_end, hole_length)
        if clipped_start < clipped_end:
            clipped: list[tuple[float, float]] = []
            for a, b in shank_ranges:
                if clipped_end <= a or clipped_start >= b:
                    clipped.append((a, b))
                    continue
                if a < clipped_start:
                    clipped.append((a, clipped_start))
                if clipped_end < b:
                    clipped.append((clipped_end, b))
            shank_ranges = clipped

    for a, b in shank_ranges:
        if b - a > 1e-9:
            hole_segments.append(_straight_hole_segment(orientation, dims.shank_clearance_r, a, b, axis=_HoleAxis.Z))

    screw_hole = hole_segments[0]
    for seg in hole_segments[1:]:
        screw_hole = cast(Part, screw_hole + seg)
    screw_hole = screw_hole.moved(Location((0, 0, head_depth)))

    clearance = screw_hole
    if nut_pocket is not None:
        clearance = cast(Part, clearance + nut_pocket)
    mark_non_printable(clearance)

    return screw, nut_part, clearance


def screw_joint_location(
    origin: tuple[float, float, float], tip_dir: Vector, print_up_dir: Vector | None = None
) -> Location:
    """The Location that positions create_screw_joint()'s (screw, nut, clearance) outputs so the
    screw's head sits at `origin`, its shank points along `tip_dir` (the direction the screw
    penetrates the material — i.e. head-to-tip, matching create_screw()'s own local -Z), and, for
    a PrintOrientation.HORIZONTAL clearance, its teardrop's self-supporting apex points along
    `print_up_dir` (the print-up direction of whichever body the clearance is being subtracted
    from — perpendicular to `tip_dir`; omit for PrintOrientation.VERTICAL, where there's no apex
    to align).

    Apply the same Location, via .located(), to all three of create_screw_joint()'s outputs so
    they land consistently positioned relative to each other, exactly as they were built."""
    tip_dir = tip_dir.normalized()
    z_dir = -tip_dir
    if print_up_dir is not None:
        y_dir = print_up_dir.normalized()
        x_dir = y_dir.cross(z_dir)
    else:
        x_dir = z_dir.cross(Vector(1, 0, 0)) if abs(z_dir.X) < 0.9 else z_dir.cross(Vector(0, 1, 0))
    return Location(Plane(origin=origin, x_dir=x_dir, z_dir=z_dir))
