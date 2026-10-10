"""Project-wide mechanical assembly checks, shared across all assemblies' test suites.

These checks verify hardware is actually doing its mechanical job (e.g. a screw clamping
printed parts together), as opposed to tests/printability.py's checks that a part can physically
be printed.
"""

import math
from dataclasses import dataclass
from typing import cast

from build123d import Axis, BoundBox, Compound, Face, Location, Part, Plane, Solid, Vector

from src import hardware
from src.part_tags import HardwareType, get_tags
from tests.printability import NOZZLE_DIAMETER


def _support(bb: BoundBox, direction: Vector) -> tuple[float, float]:
    """Min/max projection of a bounding box's 8 corners onto an arbitrary direction vector."""
    corners = [
        Vector(x, y, z) for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y) for z in (bb.min.Z, bb.max.Z)
    ]
    projections = [c.dot(direction) for c in corners]
    return min(projections), max(projections)


def _fuse_printable_bodies(printable_parts: list[Part | Compound]) -> dict[str, Part | Compound]:
    """Group printable parts by their shared tag.body.name (see src.part_tags.body/tag_body) and
    fuse each group into one shape, the same "body" grouping tests/collisions.py's
    check_no_body_overlaps_another_body uses to reason about which parts print as one physical
    object. Parts with no body tag are dropped — they're reported elsewhere (check_bodies_printable)
    and can't be attributed to a body here."""
    flattened: list[Part | Compound] = []
    for p in printable_parts:
        if type(p) is Compound:
            for child in p.children:
                flattened.append(child.moved(p.location))
        else:
            flattened.append(p)

    bodies: dict[str, list[Part | Compound]] = {}
    for p in flattened:
        tagged_body = get_tags(p).body
        if tagged_body is not None:
            bodies.setdefault(tagged_body.name, []).append(p)

    fused: dict[str, Part | Compound] = {}
    for name, group in bodies.items():
        combined = group[0]
        for p in group[1:]:
            combined = cast(Part | Compound, combined + p)
        fused[name] = combined
    return fused


@dataclass
class _BodyAttribution:
    """Which printed body houses a screw's bearing face and which houses its mating nut (see
    _attribute_bodies), plus the geometry needed to reason about either: every fused printable
    body in the assembly, the screw's fastening axis direction, and a point on that axis at the
    screw's head and at the nut's bore respectively. `error` is set instead of the *_body_name
    fields when attribution couldn't be performed at all (misaligned or touching hardware)."""

    fused_bodies: dict[str, Part | Compound]
    axis_dir: Vector
    head_origin: Vector
    bore_origin: Vector
    screw_body_name: str | None
    nut_body_name: str | None
    error: str | None


def _attribute_bodies(
    nut: Part | Compound,
    screw: Part | Compound,
    printable_parts: list[Part | Compound],
) -> _BodyAttribution:
    """Work out which printed body (see src.part_tags.body/tag_body) houses a screw's bearing face
    and which houses its mating nut, by finding whichever body's material comes closest to each
    end of the gap between them along the screw's fastening axis — the body closest to the head
    end "owns" the screw, the body closest to the nut end "owns" the nut. A recessed screw head
    sitting in a counterbore, for instance, has an air gap before reaching its own body's material,
    but that body is still the closest one to the head, so this doesn't require contact exactly at
    the bearing/bore face itself.

    Unlike a plain bounding-box comparison, this uses the "head" RigidJoint that hardware.py's
    screw factories attach (marking the screw's bearing face and the direction it penetrates the
    material) and the "bore" RigidJoint on the nut (marking its threaded axis), so it works for
    hardware at any orientation, not just ones aligned to a world X/Y/Z axis.

    Either *_body_name comes back None (with `error` set) if the nut's bore isn't aligned with the
    screw's fastening axis, if they touch with no gap between them, or if no printable material
    was found anywhere in that gap.
    """
    head_plane = Plane(screw.joints["head"].location)
    bore_plane = Plane(nut.joints["bore"].location)

    axis_dir = head_plane.z_dir  # direction the screw penetrates, from its bearing face onward
    x_dir = head_plane.x_dir
    y_dir = head_plane.y_dir

    fused_bodies = _fuse_printable_bodies(printable_parts)

    def attribution_error(message: str) -> _BodyAttribution:
        return _BodyAttribution(fused_bodies, axis_dir, head_plane.origin, bore_plane.origin, None, None, message)

    alignment = abs(bore_plane.z_dir.dot(axis_dir))
    if alignment < 0.9:
        return attribution_error(
            f"Nut's bore axis is not aligned with the screw's fastening axis (alignment={alignment:.2f} of 1.0)"
        )

    nut_bb = nut.bounding_box()
    screw_bb = screw.bounding_box()

    head_pos = head_plane.origin.dot(axis_dir)
    nut_axis_lo, nut_axis_hi = _support(nut_bb, axis_dir)

    # The nut's near face is whichever end of its bounding box (along the fastening axis) is
    # closer to the screw's bearing face; the gap to check runs from there to the bearing face.
    nut_near = nut_axis_lo if abs(nut_axis_lo - head_pos) < abs(nut_axis_hi - head_pos) else nut_axis_hi
    gap_lo, gap_hi = min(head_pos, nut_near), max(head_pos, nut_near)

    if gap_hi - gap_lo <= 1e-6:
        return attribution_error(
            "Nut and screw touch directly along the screw's fastening axis with no gap between them"
        )

    def perpendicular_range(direction: Vector) -> tuple[float, float]:
        n_lo, n_hi = _support(nut_bb, direction)
        s_lo, s_hi = _support(screw_bb, direction)
        lo, hi = max(n_lo, s_lo), min(n_hi, s_hi)
        if hi <= lo:
            # Footprints don't overlap (unusual); fall back to the smaller of the two footprints.
            lo, hi = (n_lo, n_hi) if (n_hi - n_lo) < (s_hi - s_lo) else (s_lo, s_hi)
        return lo, hi

    x_lo, x_hi = perpendicular_range(x_dir)
    y_lo, y_hi = perpendicular_range(y_dir)

    probe_origin = x_lo * x_dir + y_lo * y_dir + gap_lo * axis_dir
    probe = Solid.make_box(
        x_hi - x_lo,
        y_hi - y_lo,
        gap_hi - gap_lo,
        Plane(origin=probe_origin, x_dir=x_dir, z_dir=axis_dir),
    )

    # For each body with any material in the gap, find how close that material comes to each end
    # of the gap — the body closest to the head end "owns" the screw, the body closest to the nut
    # end "owns" the nut.
    screw_body_name, screw_body_dist = None, float("inf")
    nut_body_name, nut_body_dist = None, float("inf")
    for name, body in fused_bodies.items():
        overlap = probe.intersect(body)
        if overlap is None:
            continue
        # Normalize overlap: might be a single Solid or a ShapeList of multiple solids
        solids = [overlap] if isinstance(overlap, Solid) else list(overlap)
        volume = sum(s.volume for s in solids)
        if volume <= 1e-6:
            continue
        extents = [_support(s.bounding_box(), axis_dir) for s in solids]
        mat_lo = min(lo for lo, _ in extents)
        mat_hi = max(hi for _, hi in extents)
        dist_to_head = mat_lo - gap_lo
        if dist_to_head < screw_body_dist:
            screw_body_dist, screw_body_name = dist_to_head, name
        dist_to_nut = gap_hi - mat_hi
        if dist_to_nut < nut_body_dist:
            nut_body_dist, nut_body_name = dist_to_nut, name

    if screw_body_name is None or nut_body_name is None:
        return attribution_error(
            "No printable material found between nut and screw along the screw's fastening axis "
            + f"(gap {gap_lo:.2f}..{gap_hi:.2f} mm) — the screw would drive straight into the nut "
            + "through open air instead of clamping printed parts together"
        )

    return _BodyAttribution(
        fused_bodies, axis_dir, head_plane.origin, bore_plane.origin, screw_body_name, nut_body_name, None
    )


def check_nut_captured_by_printable_material(
    nut: Part | Compound,
    screw: Part | Compound,
    printable_parts: list[Part | Compound],
) -> str | None:
    """Verify a screw actually clamps two separate printed bodies together at a nut, rather than
    just threading into open air or into material that's all part of the same body as the screw
    itself.

    A screw threads into a nut to draw two mating bodies together, squeezing whichever one the
    screw's own head bears against toward whichever one houses the nut. That only works if:
    - the nut and screw sit in two different printed bodies (see src.part_tags.body/tag_body) —
      if the "nut's body" and the "screw's body" are the same body, there's nothing to clamp
      together;
    - some of the nut's body's material lies in the gap between nut and screw — otherwise the
      nut's pocket isn't actually backed by that body there;
    - some of the screw's body's material lies in that same gap — otherwise the screw's head has
      nothing to bear against and pull tight.

    Body attribution (which printed body "owns" the nut, which owns the screw) is done by
    _attribute_bodies; see there for how a body is matched to each end of the gap.

    A screw tagged with part_tags.mark_set_screw() flips that first rule: a set-screw's nut and
    threaded shank must anchor in the *same* body, since its clamping force comes from its own
    tip pressing into a separate body further along its length — not from its head-to-nut span —
    so a set-screw whose nut ends up in a different body than its own shank is mistagged or
    mismodeled just as surely as an ordinary screw sharing a body with its nut is.

    Returns an error message describing the problem if the nut's bore isn't aligned with the
    screw, no printable material bridges the gap between them, or the nut and screw are both
    captured by the same body, else None.
    """
    attr = _attribute_bodies(nut, screw, printable_parts)
    if attr.error is not None:
        return attr.error

    screw_body_name, nut_body_name = attr.screw_body_name, attr.nut_body_name
    assert screw_body_name is not None and nut_body_name is not None  # error is None, so both are set

    is_set_screw = hardware.is_set_screw(screw)
    same_body = screw_body_name == nut_body_name

    if same_body and not is_set_screw:
        return (
            f"Nut and screw are both captured by the same printed body ({screw_body_name!r}) — "
            + "the screw has nothing separate to clamp it against (if this is a set-screw whose tip "
            + "presses a separate body rather than a head-to-nut span, tag it with "
            + "part_tags.mark_set_screw())"
        )

    if is_set_screw and not same_body:
        return (
            "Screw is tagged as a set-screw but its nut is captured by a different printed body "
            + f"({nut_body_name!r}) than its own shank ({screw_body_name!r}) — a set-screw's nut and "
            + "shank must anchor in the same body, since its clamping force comes from its tip "
            + "pressing into a separate body, not from a head-to-nut span between two bodies"
        )

    return None


# How far a fastened body is rotated, about the screw's fastening axis, to probe whether anything
# else in the assembly actually stops it from spinning. Small enough that a real capturing feature
# (a hex pocket, a boss, a second fastener, an adjacent wall) will already show a collision well
# within it, so it stands in for the rotational slop a body has before something else engages.
_ROTATION_CAPTURE_PROBE_DEG = 5.0


def check_body_rotationally_captured(
    nut: Part | Compound,
    screw: Part | Compound,
    printable_parts: list[Part | Compound],
) -> list[str]:
    """Verify the printed body housing the screw's bearing face, and the printed body housing the
    nut, are each rotationally captured about the screw's fastening axis by some other printable
    body — not free to spin in place around the one axis the screw/nut pair itself constrains.

    A screw and nut only constrain their two bodies along and around a single axis: the fastening
    axis. Nothing about threading a screw into a nut stops either body from rotating about that
    axis on its own — that has to come from something else: a hex nut pocket keying the nut
    against its own body, a boss, an alignment key, a second fastener, or any other geometry
    belonging to a *different* printable body that the rotating body would run into. Without such
    a feature, tightening the screw can just spin the nut (or the whole part) instead of clamping
    anything.

    This is tested by rotating each body a small amount (_ROTATION_CAPTURE_PROBE_DEG) about the
    screw's fastening axis and checking whether it then collides with any *other* printable body.
    A real capturing feature produces a collision well within this small a rotation; a body with
    nothing constraining its spin rotates freely with no collision at all. Bodies whose attribution
    is ambiguous (see _attribute_bodies) are skipped here — check_nut_captured_by_printable_material
    already reports that problem.

    Returns a list of failure descriptions, one per body that isn't captured — empty if both are
    (or if there's only one body to check, as for a set-screw's shared screw/nut body).
    """
    attr = _attribute_bodies(nut, screw, printable_parts)
    if attr.error is not None or attr.screw_body_name is None or attr.nut_body_name is None:
        return []

    # A set-screw's nut and screw share one body (see check_nut_captured_by_printable_material);
    # dict.setdefault keeps that body checked only once, pivoting at the screw's own head.
    bodies_to_check: dict[str, Vector] = {attr.screw_body_name: attr.head_origin}
    bodies_to_check.setdefault(attr.nut_body_name, attr.bore_origin)

    failures = []
    for body_name, pivot in bodies_to_check.items():
        rotated = attr.fused_bodies[body_name].rotate(Axis(pivot, attr.axis_dir), _ROTATION_CAPTURE_PROBE_DEG)

        collided = False
        for other_name, other_body in attr.fused_bodies.items():
            if other_name == body_name:
                continue
            overlap = rotated.intersect(other_body)
            volume = sum(s.volume for s in overlap) if overlap is not None else 0.0
            if volume > 1e-6:
                collided = True
                break

        if not collided:
            failures.append(
                f"body {body_name!r} can rotate {_ROTATION_CAPTURE_PROBE_DEG:g}\N{DEGREE SIGN} about the "
                + "screw's fastening axis without colliding with any other printable body — nothing "
                + "captures it against rotation, so tightening the screw could just spin it in place "
                + "instead of clamping"
            )

    return failures


def _screw_reach(screw: Part | Compound, head_plane: Plane) -> float:
    """Distance from a screw's head-bearing face to the far end of its own bounding box, along
    its fastening axis — the farthest away a nut could possibly be and still be reachable by it."""
    _, hi = _support(screw.bounding_box(), head_plane.z_dir)
    return hi - head_plane.origin.dot(head_plane.z_dir)


def pair_nuts_and_screws(
    parts: list[Part | Compound],
) -> tuple[list[tuple[Part | Compound, Part | Compound]], list[str]]:
    """Automatically pair up every screw and nut in an assembly's parts, using each part's
    hardware_kind tag and joint geometry rather than labels — no per-assembly wiring required.

    A nut is a valid candidate for a screw if its bore is aligned with the screw's fastening axis
    and lies ahead of the screw's head within the screw's own reach (a screw can't thread into a
    nut farther away than the screw itself is long). Candidates are matched nearest-first so each
    screw and nut is used in at most one pair.

    Returns (pairs, errors) as a list of (nut, screw) tuples and a list of problem descriptions.
    Every screw and nut must end up in exactly one pair; any left unmatched is reported in errors
    rather than silently dropped, since a screw or nut nobody checked is a false pass waiting to
    happen.
    """
    screws = [p for p in parts if hardware.hardware_kind(p) == HardwareType.SCREW]
    nuts = [p for p in parts if hardware.hardware_kind(p) == HardwareType.NUT]

    candidates: list[tuple[float, int, int]] = []
    for si, screw in enumerate(screws):
        head_plane = Plane(screw.joints["head"].location)
        axis_dir = head_plane.z_dir
        head_pos = head_plane.origin.dot(axis_dir)
        reach = _screw_reach(screw, head_plane)

        for ni, nut in enumerate(nuts):
            bore_plane = Plane(nut.joints["bore"].location)
            if abs(bore_plane.z_dir.dot(axis_dir)) < 0.9:
                continue
            distance = nut.bounding_box().center().dot(axis_dir) - head_pos
            if 0 < distance <= reach:
                candidates.append((distance, si, ni))

    candidates.sort(key=lambda c: c[0])

    matched_screw: dict[int, int] = {}
    matched_nut: dict[int, int] = {}
    for _, si, ni in candidates:
        if si in matched_screw or ni in matched_nut:
            continue
        matched_screw[si] = ni
        matched_nut[ni] = si

    pairs = [(nuts[ni], screws[si]) for si, ni in matched_screw.items()]

    errors = [
        f"Screw {screw.label!r} has no matching nut within reach"
        for si, screw in enumerate(screws)
        if si not in matched_screw
    ]
    errors += [
        f"Nut {nut.label!r} has no matching screw within reach" for ni, nut in enumerate(nuts) if ni not in matched_nut
    ]

    return pairs, errors


# CAD boolean operations between a hardware part's clearance hole and its own hardware body can
# leave a hairline mismatch (e.g. two hole/head radii chosen a fraction of a millimeter too close)
# even in a correct design. This caps how much overlap counts as that kind of rounding noise, as
# opposed to a real blockage: a tiny linear thickness across the hardware part's own cross-section,
# scaled to the part rather than a single fixed volume for every part size. It is NOT meant to
# cover deliberate sacrificial bridges — those must be tagged with hardware.mark_sacrificial()
# instead, so they're recognized explicitly rather than by how much material happens to overlap.
_MAX_MODELING_TOLERANCE_THICKNESS = 0.02  # mm


def check_hardware_clear_of_printable_material(
    hardware_part: Part | Compound,
    printable_parts: list[Part | Compound],
) -> str | None:
    """Verify a hardware part (a screw or nut) has a clear path through the printable parts.

    check_nut_captured_by_printable_material only confirms printable material exists somewhere
    between a nut and screw — it would still pass if that material completely fills the gap with
    no clearance hole at all, since the screw has nowhere to go. A screw/nut's own solid occupies
    exactly the channel it needs to travel through, so any substantial overlap with a printable
    part means that channel isn't actually open — there's no empty space for the screw to be
    driven into the nut, even though the two are close enough and aligned enough to look like a
    valid pair.

    Parts tagged sacrificial (hardware.mark_sacrificial()) are skipped entirely — contact with
    those is by design. Any other printable part is allowed only a hairline of rounding-noise
    overlap (see _MAX_MODELING_TOLERANCE_THICKNESS); anything more is treated as a real blockage.

    Returns an error message naming the colliding printable part(s) if a real blockage is found,
    else None.
    """
    bb = hardware_part.bounding_box()
    dims = sorted([bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z])
    cross_section_area = dims[0] * dims[1]  # perpendicular to the part's own longest dimension
    max_tolerated_volume = cross_section_area * _MAX_MODELING_TOLERANCE_THICKNESS

    colliding = []
    for part in printable_parts:
        if hardware.is_sacrificial(part):
            continue
        overlap = hardware_part.intersect(part)
        volume = sum(s.volume for s in overlap) if overlap is not None else 0.0
        if volume > max_tolerated_volume:
            colliding.append(f"{part.label!r} ({volume:.3f} mm³)")

    if colliding:
        return f"{hardware_part.label!r} has no clear path — it collides with " + ", ".join(colliding)
    return None


# How far a fastened body is pulled away from its mate, along the seam normal, to find what would
# stop the two coming apart — a hook, a tab under a ledge, a snap lip — for check_seams_not_pryable.
# A probe distance, not a tolerance, and one extrusion width for the same reason the printability
# checks measure everything against the nozzle: a retaining feature is modelled with running
# clearance, so it only engages once the seam has already opened by that clearance, and a feature
# that lets the seam open by more than one bead's width before it engages is play, not retention.
_PRYING_PROBE_MM = NOZZLE_DIAMETER

# How finely each edge of a contact or overlap region is sampled when projecting it onto the seam
# plane. Its straight edges contribute their ends whatever this is; it only has to be fine enough
# that a curved edge (a round lid's rim, a circular boss) projects to something close to its true
# outline rather than to a chord between its two ends.
_SEAM_EDGE_SAMPLES = 16

# The leverage a seam is meant to concede at most: that of a single screw centred on its seam,
# which reaches exactly halfway across from every edge. It is a boundary the geometry itself
# supplies rather than a tuned number — the best one screw can ever do — so no seam need be held
# better than a centred screw would hold it. A seam that does worse is reported as a warning: it
# is the target to design to, not a defect on its own.
_CENTRED_SCREW_LEVERAGE = 2.0

# The leverage at which a seam is a hard failure. Unlike the figure above this one is not derived
# from anything — bolted-joint guidance caps the overhang a designer may *credit* to a bolt but
# publishes no maximum lever ratio, and estimating one from forces (a hand can pinch 50–100 N
# against an M3's 500–1000 N of preload) lands nearer 5:1. It is an interim ceiling set
# deliberately high, so that only grossly levered seams fail while the existing designs that sit
# between the two figures surface as warnings and get fixed in their own time.
_MAX_PRYING_LEVERAGE = 8.0


class PryingWarning(UserWarning):
    """A seam held worse than a single centred screw would hold it, but not yet past the hard
    ceiling. Its own category so these can be listed, counted or promoted to errors on their own,
    separately from any other warning a test run produces."""


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """2D convex hull (Andrew's monotone chain), returned counter-clockwise with no repeated
    end point. Fewer than three distinct non-collinear points come back as-is, degenerate."""
    unique = sorted(set(points))
    if len(unique) < 3:
        return unique

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _projected_points(shape: Part | Compound | Solid | Face, plane: Plane) -> list[tuple[float, float]]:
    """Every vertex of a shape, plus points sampled along each of its edges, projected onto a
    plane's own (x, y) coordinates — the footprint of a contact or overlap region as seen looking
    straight down the seam normal."""
    points: list[Vector] = [v.center() for v in shape.vertices()]
    fractions = [i / _SEAM_EDGE_SAMPLES for i in range(_SEAM_EDGE_SAMPLES + 1)]
    for edge in shape.edges():
        points.extend(edge.positions(fractions))
    return [(p.dot(plane.x_dir), p.dot(plane.y_dir)) for p in points]


def _contact_faces(a: Part | Compound, b: Part | Compound) -> list[Face]:
    """The faces along which two bodies touch without overlapping — build123d's own boundary
    contact search, applied to each solid of one body against each solid of the other."""
    faces: list[Face] = []
    for solid_a in a.solids():
        for solid_b in b.solids():
            faces.extend(f for f in solid_a.touch(solid_b) if isinstance(f, Face))
    return faces


def _overlap_solids(a: Part | Compound, b: Part | Compound) -> list[Solid]:
    """The solid pieces two shapes have in common, dropping rounding-noise slivers."""
    overlap = a.intersect(b)
    if overlap is None:
        return []
    solids = [overlap] if isinstance(overlap, Solid) else list(overlap.solids())
    return [s for s in solids if s.volume > 1e-6]


@dataclass
class _Seam:
    """One seam between two printed bodies: the pair, the direction that separates them, and the
    screws that clamp them across it."""

    body_a: str
    body_b: str
    normal: Vector  # unit, pointing from body_a into body_b
    plane: Plane  # normal along `normal`; its x/y are the coordinates the seam is analysed in
    screw_anchors: list[tuple[float, float]]  # where each clamping screw's axis crosses the plane


def _seams(
    pairs: list[tuple[Part | Compound, Part | Compound]],
    printable_parts: list[Part | Compound],
) -> tuple[list[_Seam], dict[str, Part | Compound]]:
    """Group an assembly's screw/nut pairs by the pair of bodies each clamps together, so a seam
    held by several screws is analysed once with all of them counted as anchors. Pairs whose
    bodies can't be attributed, and set-screws (whose nut shares the screw's own body, so there is
    no seam between two bodies to speak of), are left out: check_nut_captured_by_printable_material
    reports the former, and the latter clamp by pressing rather than by drawing a seam shut."""
    seams: dict[frozenset[str], _Seam] = {}
    fused: dict[str, Part | Compound] = {}
    for nut, screw in pairs:
        attr = _attribute_bodies(nut, screw, printable_parts)
        fused = attr.fused_bodies
        if attr.error is not None or attr.screw_body_name is None or attr.nut_body_name is None:
            continue
        if attr.screw_body_name == attr.nut_body_name:
            continue

        key = frozenset((attr.screw_body_name, attr.nut_body_name))
        seam = seams.get(key)
        if seam is None:
            # The first screw found fixes which body is "a" and which is "b", and the seam normal
            # as its own fastening axis: a screw is set square to the seam it clamps.
            plane = Plane(screw.joints["head"].location)
            seam = _Seam(attr.screw_body_name, attr.nut_body_name, plane.z_dir, plane, [])
            seams[key] = seam
        # Every screw across this seam pins the point where its axis crosses it, whichever way it
        # is driven — an anchor against the two bodies being levered apart there.
        seam.screw_anchors.append((attr.head_origin.dot(seam.plane.x_dir), attr.head_origin.dot(seam.plane.y_dir)))
    return list(seams.values()), fused


def check_seams_not_pryable(
    pairs: list[tuple[Part | Compound, Part | Compound]],
    printable_parts: list[Part | Compound],
) -> tuple[list[str], list[str]]:
    """Verify no seam between two screwed-together bodies can be levered open at one end by
    pulling far from where it is held.

    Two bodies drawn together by a screw meet along a seam. Pull one body away at some point on
    that seam and it does not lift off evenly: it pivots about the seam's opposite edge, like a
    crowbar on a fulcrum, and everything holding the seam shut has to resist with whatever
    leverage its own distance from that fulcrum gives it. A screw close to the fulcrum edge, with
    the seam running a long way past it, is a short hand on a long handle — a modest tug at the
    far end multiplies into a force the screw's clamp cannot match, and the far end gaps open
    while the screw is still tight. That is the fault this looks for: a single screw at one end of
    a long seam, or all of a seam's screws bunched on one side of it.

    What holds a seam shut ("anchors") is every screw clamping across it, plus any geometry that
    stops one body pulling away from the other along the seam normal — a hook, a tab under a
    ledge, a snap lip. Those are found rather than declared: the body is nudged away from its
    mate along the normal, and wherever it then overlaps another printed body is somewhere a
    real feature is engaged across the seam. The seam itself is the set of faces the two bodies
    share: where they actually bear on each other across the normal, which is where a fulcrum can
    form.

    Both are projected onto the seam plane and the seam's convex hull taken (a rigid body can only
    pivot about one of the hull's supporting edges). For each edge of that hull, the farthest the
    seam reaches from it is the longest handle a person can pull on; the farthest any anchor
    reaches from it is the longest hand holding on, and their ratio is the lever advantage a
    person has from that edge. A seam with anchors at both ends, or a screw at one end and a hook
    at the other, comes out near 1:1. Screws are only checked against the seam they clamp, so a
    body held to one neighbour and merely resting on another is judged on the first seam alone.

    The worst edge's ratio is judged against two figures: a seam worse than a single centred
    screw's _CENTRED_SCREW_LEVERAGE is reported as a warning, and one past the
    _MAX_PRYING_LEVERAGE ceiling as a failure.

    Returns (failures, warnings): descriptions of the seams that can be pried, naming the pair of
    bodies and how far the seam outruns its anchors — both empty if every seam is held well.
    """
    seams, fused = _seams(pairs, printable_parts)
    failures: list[str] = []
    advisories: list[str] = []
    for seam in seams:
        a, b = fused[seam.body_a], fused[seam.body_b]

        seam_points: list[tuple[float, float]] = []
        for face in _contact_faces(b, a):
            # A face the two bodies share edge-on to the seam normal — a rail, a rim wall — can
            # only guide the bodies sideways; only a face they bear on across the normal can
            # take the fulcrum's push.
            if abs(face.normal_at().dot(seam.normal)) > 1e-6:
                seam_points.extend(_projected_points(face, seam.plane))
        hull = _convex_hull(seam_points)
        if len(hull) < 3:
            continue  # no face-to-face contact to pry against — nothing here forms a fulcrum

        anchors = list(seam.screw_anchors)
        pulled_apart = b.moved(Location(seam.normal * _PRYING_PROBE_MM))
        for name, other in fused.items():
            if name == seam.body_b:
                continue
            for solid in _overlap_solids(pulled_apart, other):
                anchors.extend(_projected_points(solid, seam.plane))

        worst: tuple[float, float, float] | None = None  # (ratio, seam reach, anchor reach)
        for i, p in enumerate(hull):
            q = hull[(i + 1) % len(hull)]
            ex, ey = q[0] - p[0], q[1] - p[1]
            length = math.hypot(ex, ey)
            if length < 1e-9:
                continue
            # Inward normal of a counter-clockwise hull edge: the direction "across the seam" from
            # this edge, which is the fulcrum being considered.
            nx, ny = -ey / length, ex / length
            seam_reach = max((s[0] - p[0]) * nx + (s[1] - p[1]) * ny for s in hull)
            anchor_reach = max((s[0] - p[0]) * nx + (s[1] - p[1]) * ny for s in anchors)
            if anchor_reach <= 1e-9:
                ratio = math.inf
            else:
                ratio = seam_reach / anchor_reach
            if worst is None or ratio > worst[0]:
                worst = (ratio, seam_reach, anchor_reach)

        if worst is None or worst[0] <= _CENTRED_SCREW_LEVERAGE:
            continue
        ratio, seam_reach, anchor_reach = worst
        description = (
            f"seam between {seam.body_a!r} and {seam.body_b!r} can be pried open: from one edge of "
            + f"the seam it reaches {seam_reach:.1f} mm but the farthest screw or retaining feature "
            + f"holding it only reaches {anchor_reach:.1f} mm, a {ratio:.1f}:1 lever advantage for "
            + "anyone pulling at the far end — add a screw, hook or lip at the far end, or move the "
            + "screw toward the middle of the seam"
        )
        if ratio > _MAX_PRYING_LEVERAGE:
            failures.append(description + f" (past the {_MAX_PRYING_LEVERAGE:g}:1 ceiling)")
        else:
            advisories.append(description + f" (worse than a single centred screw's {_CENTRED_SCREW_LEVERAGE:g}:1)")
    return failures, advisories
