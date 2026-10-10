"""Unit tests for the printability checks themselves — overhangs, empty layers,
sub-nozzle-width material, whether a body's bed contact is a wide enough base for its height, and
whether it tessellates to a mesh that encloses a solid.

These build deliberately printable and deliberately unprintable shapes from primitives and
assert the checker's verdict on each, so that a regression in it shows up here rather than
as an assembly silently passing a check it should have failed.

The build-plate layout every assembly's export-3mf runs its parts through is tested here too, for
the same reason and in the same way: it is one shared piece of machinery, so it is exercised once
against a synthetic assembly rather than once per real one.
"""

import itertools
import math
import random
from typing import cast

import numpy as np
import pytest
from build123d import Align, Axis, Box, Compound, Cone, Cylinder, Location, Part, Vector

from src.part_tags import tag_body
from src.printer import DOWN_MINUS_Z, DOWN_X, build_print_plate, mark_non_printable
from tests.printability import (
    _CLIPPER_SCALE,  # noqa: PLC2701 — hand-built outlines have to be in the units the checks use
    BED_SIZE_X,
    LAYER_HEIGHT,
    MAX_BED_ASPECT_RATIO,
    MIN_UNSUPPORTED_AREA,
    NOZZLE_DIAMETER,
    _largest_piece_area,  # noqa: PLC2701 — see _CLIPPER_SCALE
    _MeshSlicer,  # noqa: PLC2701 — the invariant tested below is its own
    check_bed_contact,
    check_layers,
    check_mesh,
    check_mesh_is_solid,
    mesh_body,
    thin_regions,
)

_UP = (Align.CENTER, Align.CENTER, Align.MIN)


def _post() -> Part:
    """A 10x10 post standing 30 mm tall on the bed."""
    return Box(10, 10, 30, align=_UP)


def _post_with_wing(wing_depth: float) -> Part:
    """A post with a slab cantilevered out to both sides near its top.

    When the wing is as deep as the post, their side walls are coplanar and the fusion
    merges them into single faces running all the way to the bed. Face-adjacency tests read
    that as support even though nothing is underneath the wing, so this shape is the
    specific regression guard for that failure.
    """
    return cast(Part, _post() + Location((0, 0, 25)) * Box(40, wing_depth, 5, align=_UP))


def _bridge(gap: float, slab_length: float, pierced: bool = False, plugged: bool = False) -> Part:
    """Two pillars spanned by a slab, optionally with a hole through the span.

    ``plugged`` adds the sacrificial one-layer disc used elsewhere in this repo to close a
    hole across the first bridged layer, which makes an otherwise unprintable hole fine.
    """
    pillar = Box(10, 10, 20, align=_UP)
    slab = Box(slab_length, 10, 4, align=_UP)
    if pierced:
        slab -= Location((0, 0, -1)) * Cylinder(2, 10, align=_UP)
    part = (
        Location((-(gap / 2 + 5), 0, 0)) * pillar + Location((gap / 2 + 5, 0, 0)) * pillar + Location((0, 0, 20)) * slab
    )
    if plugged:
        part += Location((0, 0, 20)) * Cylinder(2, 0.2, align=_UP)
    return cast(Part, part)


def _rib(width: float) -> Part:
    """A wall of the given width standing 10 mm tall on the bed, buttressed by a solid block.

    Fully supported from below at every layer, so the only thing that can fail is its width.
    """
    return cast(
        Part,
        Box(6, 6, 10, align=_UP) + Location((3 + 10 / 2, 0, 0)) * Box(10, width, 10, align=_UP),
    )


def _post_with_sliver(capped: bool) -> Part:
    """A post interrupted by a single 0.2 mm layer that is only 0.3 mm wide in plan.

    With ``capped``, the post continues above the sliver, so the next layer lands material
    straight back onto material the nozzle cannot lay down. Without it the sliver is the last
    thing printed, which is merely how the part ends.
    """
    post = Box(8, 8, 10, align=_UP)
    sliver = Location((0, 0, 10)) * Box(8, 0.3, 0.2, align=_UP)
    part = post + sliver
    if capped:
        part += Location((0, 0, 10.2)) * Box(8, 8, 4, align=_UP)
    return cast(Part, part)


def _spanning_rib(width: float) -> Part:
    """Two pillars joined at their tops by a single 0.2 mm layer rib of the given width.

    Nothing is printed on top of the rib, so the "carries material above" condition cannot
    see it; the rib crosses open air between the pillars, so only the "nothing underneath"
    condition can. That makes it the shape that separates the two.
    """
    pillar = Box(6, 6, 10, align=_UP)
    return cast(
        Part,
        Location((-10, 0, 0)) * pillar
        + Location((10, 0, 0)) * pillar
        + Location((0, 0, 10)) * Box(26, width, 0.2, align=_UP),
    )


def _cone_at(overhang_degrees: float) -> Part:
    """A cone whose wall leans out at the given angle, standing on a nozzle-wide flat.

    The flat is what separates these from the apex-up cones below: a cone drawn to a true point
    stands the whole body on something the nozzle cannot lay down, which is a defect in its own
    right and would decide the verdict before the wall angle ever got a say. Truncating it to one
    bead across leaves the wall angle as the only thing under test. The tip that carries nothing
    is covered separately, by the cones that taper upwards.
    """
    base_radius = NOZZLE_DIAMETER / 2.0
    height = 20.0
    return Cone(base_radius, base_radius + height * math.tan(math.radians(overhang_degrees)), height, align=_UP)


def _island_over_a_gap() -> Part:
    """A slab on the bed and a second slab well above it, with nothing joining the two.

    Every layer across the gap is empty, so the printer is asked to lay the upper slab down
    onto nothing at all.
    """
    return cast(Part, Box(20, 20, 2, align=_UP) + Location((0, 0, 10)) * Box(20, 20, 2, align=_UP))


UNPRINTABLE = [
    pytest.param(_post_with_wing(10), id="cantilever wing flush with the post's side walls"),
    pytest.param(_post_with_wing(8), id="cantilever wing inset from the post's side walls"),
    pytest.param(
        _post() + Location((5, 0, 25)) * Box(30, 10, 5, align=(Align.MIN, Align.CENTER, Align.MIN)),
        id="cantilever anchored along a single edge",
    ),
    pytest.param(_island_over_a_gap(), id="island floating in mid air"),
    pytest.param(_bridge(gap=150, slab_length=170), id="bridge spanning far beyond the bridgeable limit"),
    pytest.param(_bridge(gap=10, slab_length=30, pierced=True), id="short bridge pierced by a hole"),
    pytest.param(_cone_at(55.0), id="cone overhanging at 55 degrees"),
    pytest.param(_cone_at(60.0), id="cone overhanging at 60 degrees"),
    pytest.param(_rib(0.2), id="rib a third of a nozzle wide"),
    pytest.param(_rib(0.4), id="rib narrower than the nozzle"),
    pytest.param(_post_with_sliver(capped=True), id="one sub-nozzle layer with the post continuing above it"),
    pytest.param(_spanning_rib(0.4), id="bridge narrower than one bead"),
]

PRINTABLE = [
    pytest.param(Box(20, 20, 20, align=_UP), id="plain box"),
    pytest.param(_bridge(gap=10, slab_length=30), id="short solid bridge"),
    pytest.param(Cone(20, 0, 20, align=_UP), id="cone widening towards the bed"),
    pytest.param(_cone_at(45.0), id="cone overhanging at 45 degrees"),
    pytest.param(_cone_at(40.0), id="cone overhanging at 40 degrees"),
    pytest.param(
        _bridge(gap=10, slab_length=30, pierced=True, plugged=True),
        id="pierced bridge closed by a sacrificial one-layer disc",
    ),
    pytest.param(_rib(NOZZLE_DIAMETER), id="rib exactly one nozzle wide"),
    pytest.param(_rib(0.8), id="rib wider than the nozzle"),
    pytest.param(_rib(2.0), id="rib several nozzles wide"),
    # The tip of every cone and dome is sub-nozzle for its last layer or two. That is how
    # such a shape ends, not a defect, so nothing is printed on top of it.
    pytest.param(Cone(20, 0, 20, align=_UP), id="cone tapering to a point"),
    pytest.param(_post_with_sliver(capped=False), id="sub-nozzle layer that is the last thing printed"),
    pytest.param(_spanning_rib(2.0), id="bridge several beads wide"),
]


@pytest.mark.parametrize("part", UNPRINTABLE)
def test_unprintable_geometry_is_flagged(part: Part) -> None:
    assert check_layers(part, DOWN_MINUS_Z) is not None


@pytest.mark.parametrize("part", PRINTABLE)
def test_printable_geometry_is_not_flagged(part: Part) -> None:
    assert check_layers(part, DOWN_MINUS_Z) is None


def test_bridge_is_allowed_up_to_the_span_limit_and_rejected_beyond_it() -> None:
    """The span limit, not merely the presence of a bridge, decides the verdict."""
    assert check_layers(_bridge(gap=20, slab_length=40), DOWN_MINUS_Z, max_bridge_span=60.0) is None
    assert check_layers(_bridge(gap=20, slab_length=40), DOWN_MINUS_Z, max_bridge_span=10.0) is not None


def test_a_rib_at_the_nozzle_width_passes_but_a_narrower_one_does_not() -> None:
    """The verdict turns on the nozzle width, not merely on the rib being narrow."""
    assert check_layers(_rib(0.4), DOWN_MINUS_Z, min_feature_width=0.3) is None
    assert check_layers(_rib(0.4), DOWN_MINUS_Z, min_feature_width=NOZZLE_DIAMETER) is not None


def test_thin_regions_marks_sub_nozzle_material_and_leaves_wide_material_alone() -> None:
    """The opening itself, on hand-built outlines, independent of any slicing.

    Measured the way the slice loop measures it — the largest connected piece, not the total.
    A rectangle's four corner tips are each sub-nozzle by definition, and they sum to very nearly
    the bead-corner area MIN_UNSUPPORTED_AREA is derived from, so a test summing them would sit on
    its own threshold whatever the strip's width.
    """

    def strip(width_mm: float) -> list[list[list[int]]]:
        """A 20 mm long wall of the given width, as one rectangular outline."""
        width, length = round(width_mm * _CLIPPER_SCALE), round(20.0 * _CLIPPER_SCALE)
        return [[[0, 0], [width, 0], [width, length], [0, length]]]

    assert _largest_piece_area(thin_regions(strip(0.4))) > MIN_UNSUPPORTED_AREA
    assert _largest_piece_area(thin_regions(strip(NOZZLE_DIAMETER))) < MIN_UNSUPPORTED_AREA
    assert _largest_piece_area(thin_regions(strip(2.0))) < MIN_UNSUPPORTED_AREA


def test_the_verdict_does_not_depend_on_how_the_body_is_oriented_in_its_own_frame() -> None:
    """An arbitrary down-direction must give the same answer as the axis-aligned equivalent.

    The tagged print direction is free — it is not restricted to the six axis directions —
    so a body modelled at an angle and tagged accordingly has to be judged identically to
    the same body modelled upright.
    """

    def tilt(shape: Part) -> Part:
        return cast(Part, shape.rotate(Axis.X, 37).rotate(Axis.Y, 53).rotate(Axis.Z, 19))

    # The same arbitrary rotation applied to the bed normal: the down-direction a body
    # tilted this way would be tagged with. It is nowhere near any of the six axes.
    skew = Vector(0, 0, -1).rotate(Axis.X, 37).rotate(Axis.Y, 53).rotate(Axis.Z, 19)
    assert max(abs(skew.X), abs(skew.Y), abs(skew.Z)) < 0.9

    for part, expected_flagged in ((_rib(0.4), True), (_rib(NOZZLE_DIAMETER), False), (_post_with_wing(10), True)):
        assert (check_layers(part, DOWN_MINUS_Z) is not None) == expected_flagged
        assert (check_layers(tilt(part), skew) is not None) == expected_flagged


def test_every_slice_contour_closes_on_itself() -> None:
    """A slice's contour must be a closed loop, or there is no outline to build from it.

    The mesh section comes back as loose segments, which are chained end to end into the closed
    loops every check downstream works on. That only works while each endpoint is met by an even
    number of segments — one arriving, one leaving. A single dangling endpoint leaves a chain that
    never returns to where it started, and the region it was supposed to enclose is lost.

    The way to lose one is subtle: every mesh edge is shared by two triangles, which traverse it in
    opposite directions, so interpolating the crossing point from whichever end comes first rounds
    it to two marginally different places and tears the contour open. That is why this asserts the
    invariant itself rather than waiting for a body unlucky enough to expose it.

    A curved, hollow body is used because it has thousands of shared edges at every angle, and two
    separate contours per slice — an outer and an inner — so a chaining that ran the two together
    would have nowhere to hide.
    """
    body = cast(Part, Cylinder(8, 12) - Cylinder(5, 12))
    slicer = _MeshSlicer(*mesh_body(body), DOWN_MINUS_Z)

    heights = [-6.0 + LAYER_HEIGHT * (index + 0.5) for index in range(60)]
    for height in heights:
        segments = slicer._crossing_segments(height)  # noqa: SLF001 — see the docstring
        assert len(segments) > 0, f"the slice at {height} mm should cut the body"
        endpoints = segments.reshape(-1, 2)
        _, counts = np.unique(endpoints, axis=0, return_counts=True)
        dangling = int((counts % 2 != 0).sum())
        assert dangling == 0, (
            f"the contour at {height} mm has {dangling} endpoint(s) meeting an odd number of "
            f"segments, so it is not a closed loop"
        )


def test_a_thin_layer_only_fails_when_the_layer_above_builds_on_it() -> None:
    """The load-bearing condition, isolated: the same sliver passes or fails on what is above it.

    This is the whole distinction the check rests on, so it is asserted on one pair of shapes
    that differ in nothing else.
    """
    assert check_layers(_post_with_sliver(capped=False), DOWN_MINUS_Z) is None
    assert check_layers(_post_with_sliver(capped=True), DOWN_MINUS_Z) is not None


def test_a_body_modelled_far_from_the_origin_is_still_checked() -> None:
    """Bodies are modelled where they sit in the assembly, not around the origin.

    The section cutter was once placed at the global origin rather than over the body, so a body
    modelled far away was sliced by a rectangle that missed it and read as empty on every layer.
    That passed every check in the module without examining any geometry, which is the one failure
    mode a checker must never have.
    """
    cases = ((_rib(0.4), True), (_post_with_wing(10), True), (Box(20, 20, 20, align=_UP), False))
    for part, expected_flagged in cases:
        far = cast(Part, Location((0, 300, -50)) * part)
        assert (check_layers(far, DOWN_MINUS_Z) is not None) == expected_flagged


def test_a_bridge_thinner_than_one_bead_fails_even_with_nothing_above_it() -> None:
    """Condition (B), isolated from (A) by a bridge that is the last thing printed.

    The rib is a single layer, so no material is ever laid on top of it and (A) can never
    fire; only the width of what it is drawn through open air decides the verdict.
    """
    assert check_layers(_spanning_rib(2.0), DOWN_MINUS_Z) is None
    failure = check_layers(_spanning_rib(0.4), DOWN_MINUS_Z)
    assert failure is not None
    assert "nothing beneath it" in failure, f"expected the unsupported-thin reason, got: {failure}"


def test_a_layer_with_no_material_at_all_is_flagged_where_the_gap_is() -> None:
    """An empty layer is not merely a layer with nothing to check — it is unprintable itself.

    The gap has to be reported at its own height rather than as an unsupported region on the
    first layer above it, since the layer above is only wrong because of the gap below.
    """
    failure = check_layers(_island_over_a_gap(), DOWN_MINUS_Z)
    assert failure is not None
    assert "no material at all" in failure, f"expected the empty-layer reason, got: {failure}"
    assert "at 2." in failure, f"expected the gap's own height, got: {failure}"


def test_a_tapering_tip_is_not_mistaken_for_an_empty_layer() -> None:
    """The layers of a cone's point are vanishingly small but never empty, at either end.

    This is the case an empty-layer check must not flag: a tip is how a shape ends, not a gap
    through it, and a cone printed apex-down has that tip on its very first layer.
    """
    for cone in (Cone(20, 0, 20, align=_UP), Cone(0, 20, 20, align=_UP)):
        assert check_layers(cone, DOWN_MINUS_Z) is None


def _tower(width: float, height: float) -> Part:
    """A square tower standing on the bed on its own full plan width."""
    return Box(width, width, height, align=_UP)


def test_a_tower_taller_than_its_base_is_wide_is_flagged() -> None:
    """The headline rule: past 10:1 a part needs a brim or a stabiliser to print at all."""
    assert check_bed_contact(_tower(5, 40), DOWN_MINUS_Z) is None  # 8:1
    assert check_bed_contact(_tower(5, 100), DOWN_MINUS_Z) is not None  # 20:1


def test_widening_the_base_is_what_rescues_a_tall_body() -> None:
    """The discriminator, isolated: the same tower passes once it is given a foot to stand on.

    Nothing about the tower changes — only what touches the bed — so this fails if the check is
    reading anything other than the body's bed contact.
    """
    tower = _tower(5, 100)
    assert check_bed_contact(tower, DOWN_MINUS_Z) is not None
    assert check_bed_contact(cast(Part, tower + Box(40, 40, 2, align=_UP)), DOWN_MINUS_Z) is None


def test_the_base_is_what_touches_the_bed_not_the_bounding_box() -> None:
    """A cone balanced on its tip is as wide as a stable part at the top and useless at the bed.

    Its bounding box says 40 mm across, so a check measuring the box would pass it.
    """
    assert check_bed_contact(Cone(0.5, 20, 60, align=_UP), DOWN_MINUS_Z) is not None


def test_a_long_thin_fin_is_flagged_even_though_its_contact_area_is_large() -> None:
    """A part tips over its weakest axis, so the narrowest width decides, not the area.

    This fin's footprint has ~90 mm² of contact — a characteristic width of ~9.5 mm, which would
    comfortably pass a check based on area — while being only 1.5 mm across the way it falls.
    """
    assert check_bed_contact(Box(60, 1.5, 40, align=_UP), DOWN_MINUS_Z) is not None


def test_a_hollow_tube_stands_on_the_outline_it_encloses() -> None:
    """The footprint's convex hull is the base: a tube is as stable as the cylinder it traces.

    The ring of contact is only 2 mm of wall, and its bare area (~180 mm²) would fail this tall a
    body outright, but a 30 mm tube 200 mm tall is an entirely ordinary print.
    """
    tube = cast(Part, Cylinder(15, 200, align=_UP) - Cylinder(13, 200, align=_UP))
    assert check_bed_contact(tube, DOWN_MINUS_Z) is None


def test_a_body_standing_on_separate_feet_is_braced_by_the_span_between_them() -> None:
    """Feet spread apart are one wide base, even though no single foot is wide.

    Their four 4 mm squares total only 64 mm² of contact — a characteristic width of 8 mm, which
    an area-based check would reject for a body this tall — while the 40 mm square they span is
    what the body actually tips over.
    """
    foot = Box(4, 4, 2, align=_UP)
    body = cast(Part, Location((0, 0, 2)) * Box(44, 44, 100, align=_UP))
    for x in (-18, 18):
        for y in (-18, 18):
            body = cast(Part, body + Location((x, y, 0)) * foot)
    assert check_bed_contact(body, DOWN_MINUS_Z) is None


def test_the_verdict_turns_on_the_aspect_ratio_and_not_merely_on_being_tall() -> None:
    """The limit itself decides, so a change of limit changes the answer for one fixed body."""
    tower = _tower(5, 100)  # 20:1
    assert check_bed_contact(tower, DOWN_MINUS_Z, max_aspect_ratio=30.0) is None
    assert check_bed_contact(tower, DOWN_MINUS_Z, max_aspect_ratio=MAX_BED_ASPECT_RATIO) is not None


def test_bed_contact_does_not_depend_on_how_the_body_is_oriented_in_its_own_frame() -> None:
    """Print orientation is a free direction, so a body modelled at an angle and tagged with the
    matching down-direction must be judged exactly like the upright equivalent."""

    def tilt(shape: Part) -> Part:
        return cast(Part, shape.rotate(Axis.X, 37).rotate(Axis.Y, 53).rotate(Axis.Z, 19))

    skew = Vector(0, 0, -1).rotate(Axis.X, 37).rotate(Axis.Y, 53).rotate(Axis.Z, 19)

    for part, expected_flagged in ((_tower(5, 100), True), (_tower(20, 100), False)):
        assert (check_bed_contact(part, DOWN_MINUS_Z) is not None) == expected_flagged
        assert (check_bed_contact(tilt(part), skew) is not None) == expected_flagged


def test_a_body_modelled_far_from_the_origin_is_still_measured() -> None:
    """Bodies sit where the assembly puts them, not around the origin; the section that samples
    the first layer has to follow the body there, or every footprint reads as empty and passes."""
    for part, expected_flagged in ((_tower(5, 100), True), (_tower(20, 100), False)):
        far = cast(Part, Location((0, 300, -50)) * part)
        assert (check_bed_contact(far, DOWN_MINUS_Z) is not None) == expected_flagged


# --- Exported mesh validity --------------------------------------------------------------------
# The mesh, not the model, is what a slicer is handed, so these work in mesh terms directly: a
# hand-written cube is broken in each of the ways a closed surface can be broken. Building such a
# mesh out of build123d primitives is not possible — a solid always tessellates to a closed
# surface — which is exactly why the verdict is factored out to take vertices and triangles.

# A unit cube, wound counter-clockwise seen from outside, and its six faces as triangle pairs.
_CUBE_VERTICES = [
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (1.0, 1.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 1.0),
    (1.0, 1.0, 1.0),
    (0.0, 1.0, 1.0),
]
_CUBE_TRIANGLES = [
    (0, 2, 1),
    (0, 3, 2),
    (4, 5, 6),
    (4, 6, 7),
    (0, 1, 5),
    (0, 5, 4),
    (1, 2, 6),
    (1, 6, 5),
    (2, 3, 7),
    (2, 7, 6),
    (3, 0, 4),
    (3, 4, 7),
]


def test_a_closed_mesh_encloses_a_solid() -> None:
    """The baseline the three failures below are departures from."""
    assert check_mesh_is_solid(_CUBE_VERTICES, _CUBE_TRIANGLES) is None


def test_a_mesh_with_a_hole_in_it_is_flagged() -> None:
    """Drop one face and the surface no longer separates inside from outside, so a slicer has
    nothing to decide what to fill."""
    failure = check_mesh_is_solid(_CUBE_VERTICES, _CUBE_TRIANGLES[:-2])
    assert failure is not None and "holes in the surface" in failure


def test_a_mesh_with_a_triangle_wound_the_wrong_way_is_flagged() -> None:
    """One flipped triangle contradicts its neighbours about which side is out — the defect a
    check that only counted triangles per edge would miss."""
    flipped = _CUBE_TRIANGLES[:-1] + [(3, 7, 4)]
    failure = check_mesh_is_solid(_CUBE_VERTICES, flipped)
    # Reversing one triangle contradicts its neighbours along each of its three edges, and the
    # count has to name those three edges rather than the six half-edges they are made of.
    assert failure is not None and "3 edge(s) traversed the same way" in failure


def test_a_mesh_the_3mf_writer_will_not_accept_is_flagged() -> None:
    """A degenerate triangle is rejected outright, before there is a surface to ask the manifold
    question of, so it has to come back as a verdict rather than escape as an exception."""
    failure = check_mesh_is_solid(_CUBE_VERTICES, _CUBE_TRIANGLES + [(0, 1, 1)])
    assert failure is not None and "rejects outright" in failure


def test_an_inside_out_mesh_is_flagged() -> None:
    """Reversing every triangle leaves a mesh that is still closed and still self-consistent, and
    means the exact opposite: the solid is everything outside the cube."""
    inverted = [(a, c, b) for a, b, c in _CUBE_TRIANGLES]
    failure = check_mesh_is_solid(_CUBE_VERTICES, inverted)
    assert failure is not None and "inside-out" in failure


def test_an_empty_mesh_is_flagged() -> None:
    """A body that tessellates to nothing exports a file with no object in it, which no other
    check here would notice."""
    assert check_mesh_is_solid([], []) is not None


def test_a_curved_solid_exports_as_a_closed_mesh() -> None:
    """End to end on a real shape, and on a curved one specifically: a flat-faced box tessellates
    to a closed mesh almost by construction, while a cylinder's walls are approximated, and it is
    the welding of those approximated facets that decides whether the file is watertight."""
    assert check_mesh(cast(Part, Cylinder(8, 20) - Cylinder(3, 20))) is None


# --- Build-plate layout ------------------------------------------------------------------------
# build_print_plate is shared machinery — every assembly's export-3mf runs the same code over its
# own parts — so it is tested once here against a synthetic assembly rather than through each real
# one. The synthetic assembly is deliberately awkward: one body already upright, one that only
# lies flat once rotated, one body made of two separate parts, and one non-printable part.


def _plate_assembly() -> list[Part]:
    """A synthetic assembly tagged the way a real one tags itself."""
    upright = Box(20, 20, 10)
    upright.label = "Upright"
    tag_body(upright, "Upright", DOWN_MINUS_Z)

    # 60 mm long along X and tagged to print on that end, so it is only 60 mm tall on the plate
    # if it was actually rotated.
    on_end = Box(60, 15, 15).translate((0, 200, 0))
    on_end.label = "On End"
    tag_body(on_end, "On End", DOWN_X)

    left = Box(10, 10, 10).translate((-25, 0, 300))
    left.label = "Left"
    tag_body(left, "Pair", DOWN_MINUS_Z)
    right = Box(10, 10, 10).translate((25, 0, 300))
    right.label = "Right"
    tag_body(right, "Pair", DOWN_MINUS_Z)

    fastener = Box(5, 5, 5)
    fastener.label = "Screw"
    mark_non_printable(fastener)

    return [upright, on_end, left, right, fastener]


@pytest.fixture
def plate() -> Compound:
    return build_print_plate(_plate_assembly(), "plate")


def test_the_plate_holds_every_printable_body_and_nothing_else(plate: Compound) -> None:
    """Each printable body arrives as its own named group; non-printable parts are left off."""
    assert {body.label for body in plate.children} == {"Upright", "On End", "Pair"}


def test_every_body_is_rotated_into_its_own_tagged_print_orientation(plate: Compound) -> None:
    """A body tagged to print on its end stands on its end, whatever pose it was modelled in."""
    bodies = {body.label: body.bounding_box() for body in plate.children}
    assert bodies["On End"].size.Z == pytest.approx(60.0)
    assert bodies["Upright"].size.Z == pytest.approx(10.0)


def test_every_body_rests_on_the_bed(plate: Compound) -> None:
    """Bodies modelled at any height come down onto the bed, so the plate slices as exported."""
    for body in plate.children:
        assert body.bounding_box().min.Z == pytest.approx(0.0), f"{body.label!r} is not on the bed"


def test_bodies_do_not_overlap_on_the_plate(plate: Compound) -> None:
    """Every body gets its own footprint, so they can all be printed in one go."""
    for first, second in itertools.combinations(plate.children, 2):
        a, b = first.bounding_box(), second.bounding_box()
        clear_x = min(a.max.X, b.max.X) <= max(a.min.X, b.min.X)
        clear_y = min(a.max.Y, b.max.Y) <= max(a.min.Y, b.min.Y)
        assert clear_x or clear_y, f"{first.label!r} and {second.label!r} overlap on the plate"


def test_parts_sharing_a_body_keep_their_positions_relative_to_each_other(plate: Compound) -> None:
    """A body made of several parts is moved as one, since it prints as the single solid it
    models — laying its parts out individually would pull it apart."""
    pair = next(body for body in plate.children if body.label == "Pair")
    left, right = sorted(pair.children, key=lambda p: p.bounding_box().center().X)
    assert right.bounding_box().center().X - left.bounding_box().center().X == pytest.approx(50.0)


def test_bodies_wrap_onto_a_new_row_once_a_row_fills_the_bed() -> None:
    """The plate packs across the bed and then back, rather than running off the side of it."""
    parts = []
    for index in range(6):
        block = Box(60, 60, 10)
        block.label = f"Block {index}"
        tag_body(block, f"Block {index}", DOWN_MINUS_Z)
        parts.append(block)

    bbox = build_print_plate(parts, "plate").bounding_box()
    assert bbox.size.X <= BED_SIZE_X
    assert bbox.size.Y > 60.0, "every body was placed in a single row wider than the bed"


def test_the_layout_does_not_depend_on_the_order_the_parts_arrive_in() -> None:
    """The same assembly always lays out the same way, so an unrelated reordering of
    create_assembly()'s list cannot silently move every body on the plate."""

    def placements(parts: list[Part]) -> list[tuple[str, tuple[float, ...]]]:
        plate = build_print_plate(parts, "plate")
        return sorted(
            (cast(str, body.label), tuple(round(v, 6) for v in tuple(body.bounding_box().min)))
            for body in plate.children
        )

    shuffled = _plate_assembly()
    random.Random(0).shuffle(shuffled)
    assert placements(shuffled) == placements(_plate_assembly())
