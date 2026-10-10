"""Printability checks for FDM printed bodies.

Everything here works from the mesh the body is exported as, not from the solid it was modelled
as. That is the object the printer is actually given — the slicer never sees the model — so it is
the one whose printability means anything. It is also what makes slicing cheap: intersecting a
plane with a triangle list is arithmetic, where cutting the B-rep is a solid-modelling operation
per layer.

The mesh is sliced into layers along its print direction, the way a slicer does, and every
layer's cross-section is checked for three independent defects.

Overhangs: each cross-section is compared against the one below it. A region is supported
if material sits within ``layer_height * tan(max_overhang_angle)`` of it in the previous
layer; anything else is unsupported and must be explained either by the bed or by bridging.
This one works on the cross-sections as outlines rather than on a picture of them: growing a
layer by how far material may lean is an outward offset of its contour, what that fails to
cover is a polygon subtraction, and a bridge is smeared out from its own anchors rather than
counted in grid steps. Nothing is quantised along the way, so the span and the angle are
compared against the shape the slice actually has.

Sub-nozzle features: each cross-section is opened by a disc the width of the nozzle — shrunk by
half that width and pushed back out by the same, both on the outline. What
the opening removes is material the printer has nowhere to lay a full-width extrusion, so
the slicer either drops it or prints it as an under-filled sliver. Such a region is a defect
when either of two things is true of it:

  (A) the layer above puts material back on top of it, so a wall is being built on something
      the printer cannot actually lay down; or
  (B) nothing sits underneath it, making it a bridge narrower than a single bead — with no
      earlier layer to anchor to and no neighbouring bead to hold it straight, it is drawn
      through open air.

A sliver that is neither carried nor carrying is left alone: a knife edge or a cone tip that
rests on solid material and has nothing printed onto it is simply how a shape ends. The bed
counts as material underneath, so a part's first layer never trips (B).

Empty layers: a cross-section taken between a body's own top and bottom that contains no
material at all is a defect in its own right. There is nothing for the printer to lay down
on that pass, and anything above it is being printed into open air across the body's entire
width. It is reported where the gap is rather than being left to the overhang test, which
would blame the first layer above the gap for a hole that opened below it.

The mesh itself is checked too, since everything above presumes it is a sane one. A slicer can
only tell inside from outside if the mesh is a closed, consistently wound surface with its normals
facing outwards. One that is open, self-contradictory
or inside out leaves "inside" undefined and the slicer guessing. This is not a tautology that any
solid passes: welding rounds coincident corners together and then silently drops any triangle that
collapses to a line in the process, so a feature finer than that rounding leaves a hole behind it.

A body is also checked against the base it stands on. Its first-layer
cross-section is the footprint the slicer actually lays down, and a body may not stand taller
than ``MAX_BED_ASPECT_RATIO`` times the narrowest width of that footprint — past which it needs
a brim, a raft or a sacrificial stabiliser to survive being knocked by the nozzle.

This is deliberately geometry-agnostic. It knows nothing about faces, edges or wires, so
it cannot be fooled by topology accidents — notably the case where a cantilever's side
walls are coplanar with a wall that reaches the bed and get merged into one face by the
fusion, which makes purely topological "is this edge supported?" tests report the
cantilever as supported.

Known limitations:
  - Features thinner than the analysis layer height may be missed, so that height tracks
    the printer's layer height rather than being chosen for speed.
  - The sub-nozzle cutoff sits two mesh chord errors below the nozzle width rather than exactly
    on it, because a wall of exactly that width shrinks to a line of no width, which a polygon
    cannot hold. A 0.6 mm wall passes, a 0.597 mm one is flagged. This is the one check here that
    errs towards passing; the rest err towards flagging.
  - The overhang cutoff is not a band: the outlines are compared directly, so a surface at
    ``max_overhang_angle`` is covered by the layer below grown by the reach and one past it is
    not. What is left over is the mesh's own chord error, which can leave a surface sitting
    exactly on the cutoff a hair short of covered — a tenth of a square millimetre per layer on
    a 40 mm cone, against a MIN_UNSUPPORTED_AREA ten times that.
  - A layer counts as empty only when the section cuts nothing at all. One reduced to a speck of
    material is not caught here; it is left to the support test on the layer above, which finds
    that layer standing on next to nothing.
  - Bridge anchoring is sampled along four direction pairs, so a bridge anchored between
    those directions can read as slightly more cantilevered than it truly is.
  - A layer that repeats the one below it is taken as supported without further testing, and
    "repeats" allows the two outlines to disagree by as much as the integer grid they are carried
    on could have fabricated — see _repeats. On the bodies in this repo that allowance never
    exceeds a hundredth of a square millimetre, two orders of magnitude below anything the checks
    would report.
  - Bed contact is measured over the convex hull of the whole footprint, so a body standing on
    several disconnected patches is treated as braced across the span between them. That is
    right for a body on feet, but overstates the stability of one standing on slender towers
    that only join near the top, since each tower is independently tippy until they meet.
  - The layer and bed-contact checks only ever evaluate a body in its tagged print orientation;
    a wrong ``down_direction`` tag still yields a wrong answer. The mesh check does not depend on
    orientation.
  - Slicing the mesh inherits the mesh's own chord error, so a curved wall's cross-section can sit
    slightly off where the exact surface would put it. That is the error the printer prints, not
    an error introduced here, and at the deflections used it is a thousandth of a millimetre on a
    flat wall — but on a nearly-horizontal surface, where a small height error walks a long way
    sideways, it can reach a few tenths.
  - The mesh check is about the surface being closed, not about it being simple: a closed mesh
    that passes through itself is not detected.
"""

import ctypes
import inspect
import math
from typing import Sequence, cast

import numpy as np
import pyclipper
from build123d import Box, Compound, Mesher, Part, Vector
from lib3mf import Lib3MF, get_wrapper
from numpy.typing import NDArray
from scipy.spatial import ConvexHull, QhullError

from src.exporter import export_assembly_3mf
from src.part_tags import get_tags
from src.printer import BED_SIZE_X, BED_SIZE_Y, BUILD_HEIGHT, is_printable, orient_for_printing

# Printer settings
# The layer height matches the printer's own. Anything coarser steps straight over one-layer
# sacrificial bridges and reports the hole they were added to plug.
LAYER_HEIGHT = 0.2  # mm, spacing between analysis slices
NOZZLE_DIAMETER = 0.6  # mm, narrowest full-width extrusion the printer can lay down

# Layer analysis settings
MAX_BRIDGE_SPAN = 60.0  # mm, longest solid bridge printable without support
# The smallest area worth reporting is the one the printer cannot fill in the first place: lay a
# round bead of nozzle diameter into a nozzle-wide square corner and what is left over is the
# square less the disc inscribed in it. Nothing smaller than that can be the difference between a
# part that prints and one that does not, because the nozzle cannot place material at that scale
# whatever the model says. Stated in nozzle widths rather than picked, so a change of nozzle
# carries it.
MIN_UNSUPPORTED_AREA = NOZZLE_DIAMETER**2 - math.pi * (NOZZLE_DIAMETER / 2.0) ** 2  # mm^2

# The support test works on outlines, and Clipper — the polygon library it works them with — is
# integer arithmetic, so a millimetre is carried as this many units. One unit is then 10 nm, a
# hundredth of the mesh's own chord error, which puts the quantisation far below the error already
# in the contour; a body-sized coordinate and the area of one both still stay orders of magnitude
# inside the 64-bit integers Clipper multiplies them out in.
_CLIPPER_SCALE = 1e5

# Bed-contact settings
# The common FDM design rule is that a part standing more than ten times as tall as its base is
# wide will not survive an unassisted print: the nozzle's side loads grow with height while the
# base's resistance to tipping does not, so past that ratio the part needs a brim, a raft or a
# sacrificial stabiliser. That is a design defect in a body meant to print as modelled, so it is
# checked here rather than left to slicer settings.
MAX_BED_ASPECT_RATIO = 10.0

# Mesh settings
# The tolerances src.exporter.export_assembly_3mf tessellates at, read off that function rather
# than restated here. A curved solid is only ever as watertight as the mesh it is written out as,
# so the mesh checked here has to be the one the slicer is actually handed and not a coarser
# stand-in of it — and a second copy of these numbers would say so right up until the day the
# exporter's own were changed.
_EXPORT_TESSELLATION = inspect.signature(export_assembly_3mf).parameters
MESH_LINEAR_DEFLECTION: float = _EXPORT_TESSELLATION["linear_deflection"].default  # mm
MESH_ANGULAR_DEFLECTION: float = _EXPORT_TESSELLATION["angular_deflection"].default  # radians

# In-plane directions used to test whether a region is anchored on two opposing sides.
# Each entry is checked together with its opposite, giving four opposing pairs.
_BRIDGE_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))

# A closed outline in Clipper's integer units, and a set of them: outer boundaries and the holes
# in them, which together stand for one layer's material or any part of it.
_Path = list[list[int]]
_Paths = list[_Path]
_MeshData = tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]


def get_print_extents(part: Part | Compound, down_dir: Vector) -> tuple[float, float, float]:
    """Return (height, bed_dim1, bed_dim2) for a part given a print down-axis vector.

    The part is always rotated into the print frame before measuring, so an arbitrary
    down-axis is handled exactly like an axis-aligned one. There is deliberately no
    axis-aligned shortcut: one that triggers on "close enough to an axis" would measure a
    near-axis body's raw bounding box and quietly disagree with the general case.
    """
    rotated = orient_for_printing(part, down_dir.normalized())
    bb = rotated.bounding_box()
    return bb.max.Z - bb.min.Z, bb.max.X - bb.min.X, bb.max.Y - bb.min.Y


def _print_rotation(down_dir: Vector) -> NDArray[np.float64]:
    """Return the rotation matrix src.printer.orient_for_printing applies, as a 3x3 array.

    The matrix is read back out of orient_for_printing itself — a probe solid at the origin is
    handed to it and the transform it comes back carrying is taken — rather than by
    reimplementing the branches it chooses between. Which branch a down direction falls into, and
    the tolerance deciding when one counts as already parallel to the bed normal, then live in
    one place only; a copy of them here could disagree, and the mesh would be sliced in a frame
    the body is never printed in.

    The mesh is rotated into the print frame with numpy rather than by re-tessellating the
    rotated solid: meshing is the expensive step and its result must be the *same* mesh the
    exporter writes, which is taken from the body as modelled. Rotating the vertices afterwards
    is exact — a rigid transform of a triangle list is still the identical triangle list.
    """
    probe = orient_for_printing(Box(1, 1, 1), down_dir.normalized())
    assert probe.wrapped is not None
    transform = probe.wrapped.Location().Transformation()
    return np.array([[transform.Value(row, column) for column in range(1, 4)] for row in range(1, 4)])


class _MeshSlicer:
    """A body's exported mesh, rotated into its print frame and prepared for repeated slicing.

    This is what the checks section instead of the solid, for two reasons. It is what the printer
    actually receives — check_mesh already says the slicer never sees the model, only this mesh, so
    sectioning the solid was checking an object that is never printed. And it is far cheaper: a
    plane-triangle intersection is arithmetic over an array, where a boolean against the B-rep is a
    full solid-modelling operation per layer.

    Triangles are indexed by the layer range they span, so each slice touches only the triangles
    that actually cross it rather than the whole mesh (Minetto et al., "An optimal algorithm for
    3D triangle mesh slicing").
    """

    def __init__(
        self, vertices: list[tuple[float, float, float]], triangles: list[tuple[int, int, int]], down_dir: Vector
    ) -> None:
        super().__init__()
        self.vertices = np.asarray(vertices, dtype=np.float64) @ _print_rotation(down_dir).T
        self.triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        corner_z = self.vertices[:, 2][self.triangles]
        self._low, self._high = corner_z.min(axis=1), corner_z.max(axis=1)
        self._order = np.argsort(self._low)
        self._low_sorted = self._low[self._order]
        self._high_sorted = self._high[self._order]

    def _crossing_segments(self, z: float) -> NDArray[np.float64]:
        """Return the (n, 2, 2) line segments where the plane at ``z`` cuts the mesh.

        A vertex sitting exactly on the plane counts as below it, consistently for every edge. That
        is what makes the count of sign changes around a triangle even — 0 or 2, never 1 — so a
        triangle grazing the plane at one corner contributes nothing rather than half an edge.

        Each edge is interpolated from its lower-numbered vertex towards its higher-numbered one,
        whichever of the two triangles sharing it is being processed. Without that, the two
        traverse the shared edge in opposite directions and round its crossing point to two
        marginally different places, leaving the contour a hair open — and an open contour cannot
        be chained into the closed loop the outline is built from.
        """
        reachable = int(np.searchsorted(self._low_sorted, z, side="right"))
        candidates = self._order[:reachable][self._high_sorted[:reachable] > z]
        if candidates.size == 0:
            return np.empty((0, 2, 2))

        indices = self.triangles[candidates]
        next_indices = np.roll(indices, -1, axis=1)
        corners = self.vertices[indices]
        following = self.vertices[next_indices]
        height = corners[:, :, 2] - z
        next_height = following[:, :, 2] - z

        crosses = (height > 0.0) != (next_height > 0.0)
        keep = crosses.sum(axis=1) == 2
        if not keep.any():
            return np.empty((0, 2, 2))
        indices, next_indices = indices[keep], next_indices[keep]
        corners, following = corners[keep], following[keep]
        height, next_height, crosses = height[keep], next_height[keep], crosses[keep]

        # Traverse every edge from its lower-numbered vertex, so both triangles sharing it compute
        # the identical crossing point rather than two that differ in the last bit.
        flip = (indices > next_indices)[:, :, None]
        start = np.where(flip, following, corners)
        end = np.where(flip, corners, following)
        start_height = np.where(flip[:, :, 0], next_height, height)
        end_height = np.where(flip[:, :, 0], height, next_height)

        denominator = start_height - end_height
        fraction = np.divide(start_height, denominator, out=np.zeros_like(start_height), where=denominator != 0.0)
        points = start[:, :, :2] + fraction[:, :, None] * (end[:, :, :2] - start[:, :, :2])
        return points[crosses].reshape(-1, 2, 2)

    def contour_at(self, z: float) -> _Paths:
        """Return the cross-section at height ``z`` as outlines, in Clipper's integer units.

        The crossings come out of the mesh as loose segments in no particular order, so they are
        chained end to end into closed loops first — Clipper has no use for a bag of edges. The
        chaining is a lookup on the endpoint itself rather than a search for the nearest one,
        because _crossing_segments interpolates every shared edge from the same end and so puts
        the two triangles' copies of a point at exactly the same coordinates.

        Where more than two segments meet at one point, which is joined to which is arbitrary and
        does not matter: the loops are filled by the even-odd rule, which depends only on which
        edges a ray crosses and not at all on how those edges were grouped into loops.
        """
        segments = self._crossing_segments(z)
        if segments.shape[0] == 0:
            return []

        points = np.round(segments.reshape(-1, 2) * _CLIPPER_SCALE).astype(np.int64)
        corners, indices = np.unique(points, axis=0, return_inverse=True)
        ends = indices.ravel().reshape(-1, 2)

        meeting_at: dict[int, list[int]] = {}
        for segment, (start, end) in enumerate(ends.tolist()):
            meeting_at.setdefault(start, []).append(segment)
            meeting_at.setdefault(end, []).append(segment)

        walked = np.zeros(len(ends), dtype=bool)
        loops: _Paths = []
        for seed in range(len(ends)):
            if walked[seed]:
                continue
            walked[seed] = True
            first, point = int(ends[seed, 0]), int(ends[seed, 1])
            loop = [first]
            while point != first:
                loop.append(point)
                following = next((s for s in meeting_at[point] if not walked[s]), None)
                if following is None:
                    break
                walked[following] = True
                start, end = int(ends[following, 0]), int(ends[following, 1])
                point = end if start == point else start
            if len(loop) >= 3:
                loops.append([cast(list[int], corners[index].tolist()) for index in loop])

        if not loops:
            return []
        clipper = pyclipper.Pyclipper()
        clipper.AddPaths(loops, pyclipper.PT_SUBJECT, True)
        return clipper.Execute(pyclipper.CT_UNION, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)


def thin_regions(outline: _Paths, min_width: float = NOZZLE_DIAMETER) -> _Paths:
    """Return the parts of one layer's cross-section that are narrower than ``min_width``.

    This is a morphological opening: the outline is shrunk by half ``min_width`` and pushed back
    out by the same amount, which leaves exactly the material a disc of that width fits inside
    and can be rolled around — exactly where the nozzle can lay a full-width bead. Whatever the
    opening fails to bring back is sub-nozzle material.

    The disc is shrunk by the mesh's chord error first. Shrinking a wall of exactly ``min_width``
    by exactly half of it leaves a line of no width at all, which a polygon cannot hold and which
    is therefore dropped — so without this a wall at exactly the nozzle width, which is exactly
    printable, would come back as sub-nozzle along its whole length. The amount taken off is the
    accuracy the contour itself has, and it comes off each side, so the cutoff sits two chord
    errors below ``min_width`` — 0.598 mm against the 0.6 mm nozzle — rather than anywhere chosen.
    """
    radius = min_width / 2.0 - MESH_LINEAR_DEFLECTION
    if radius <= 0.0:
        return []
    opened = _offset(_offset(outline, -radius), radius)
    return _boolean(outline, opened, pyclipper.CT_DIFFERENCE)


def _boolean(subject: _Paths, clip: _Paths, operation: int) -> _Paths:
    """Combine two polygon sets — union, intersection or difference — into outlines and holes."""
    if not subject:
        return []
    clipper = pyclipper.Pyclipper()
    clipper.AddPaths(subject, pyclipper.PT_SUBJECT, True)
    if clip:
        clipper.AddPaths(clip, pyclipper.PT_CLIP, True)
    elif operation == pyclipper.CT_INTERSECTION:
        return []
    return clipper.Execute(operation, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def _offset(paths: _Paths, distance: float) -> _Paths:
    """Move a polygon set's boundary by ``distance`` mm — outwards if positive, inwards if not.

    Both directions are a disc of that radius rolled around the outline, on the inside or the
    outside of it, which is the shape the physics has: how far material may lean out per layer,
    and how wide a bead the nozzle can lay in. Corners therefore come back as arcs rather than as
    spikes, drawn to the mesh's own chord error, there being no point resolving a curve finer
    than the contour it is offset from is known to.
    """
    if not paths:
        return []
    offsetter = pyclipper.PyclipperOffset()
    offsetter.ArcTolerance = MESH_LINEAR_DEFLECTION * _CLIPPER_SCALE
    offsetter.AddPaths(paths, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    return offsetter.Execute(distance * _CLIPPER_SCALE)


def _polygon_area(paths: _Paths) -> float:
    """Return the area a polygon set encloses in mm², with its holes subtracted.

    Clipper winds holes the opposite way round from the outlines containing them, so their areas
    come out negative and the sum is the material area without any need to pair them up.
    """
    return sum(pyclipper.Area(path) for path in paths) / _CLIPPER_SCALE**2


def _regions(paths: _Paths) -> list[_Paths]:
    """Split a polygon set into its separate pieces, each an outline with its own holes.

    Clipper reports the nesting as a tree, so a piece is a top-level outline together with the
    holes directly inside it. Anything nested inside one of those holes is an island standing on
    its own and comes back as a piece of its own, which is what "separate" has to mean here: an
    island in a hole is not joined to the material around the hole.
    """
    if not paths:
        return []
    clipper = pyclipper.Pyclipper()
    clipper.AddPaths(paths, pyclipper.PT_SUBJECT, True)
    tree = clipper.Execute2(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
    pieces: list[_Paths] = []
    pending = list(tree.Childs)
    while pending:
        node = pending.pop()
        pieces.append([node.Contour] + [hole.Contour for hole in node.Childs])
        for hole in node.Childs:
            pending.extend(hole.Childs)
    return pieces


def _smear(paths: _Paths, dx: float, dy: float) -> _Paths:
    """Drag a polygon set along the vector (dx, dy) mm, covering everywhere it passes through."""
    step = [[0, 0], [int(round(dx * _CLIPPER_SCALE)), int(round(dy * _CLIPPER_SCALE))]]
    dragged: _Paths = []
    for path in paths:
        dragged.extend(pyclipper.MinkowskiSum(step, path, True))
    return _boolean(dragged, [], pyclipper.CT_UNION)


def _perimeter(paths: _Paths) -> float:
    """Return the total length of a polygon set's boundary, in mm."""
    total = 0.0
    for path in paths:
        corners = np.asarray(path, dtype=np.float64)
        steps = np.roll(corners, -1, axis=0) - corners
        total += float(np.hypot(steps[:, 0], steps[:, 1]).sum())
    return total / _CLIPPER_SCALE


def _repeats(outline: _Paths, previous: _Paths) -> bool:
    """Return whether two layers cover the same ground, to the precision the coordinates have.

    Two layers are compared as regions rather than corner by corner, because a wall built out of
    triangles is cut at a different point along each triangle's diagonal on every layer: the
    outline traces the same rectangle each time, but through a different set of corners, so
    matching corner lists would answer "no" for every body that is not axis-aligned and
    flat-walled.

    What is left after subtracting one region from the other, both ways round, is the ground only
    one of them covers. For a genuine repeat that is not quite nothing: each of those sliding
    corners is rounded onto the integer grid the outlines are carried on, so the two boundaries
    can part company by up to a unit along their whole length. The allowance is exactly that — a
    band one unit wide around the outline — so a repeat is a pair of layers whose disagreement
    could have been manufactured by the rounding alone.

    That does mean a layer that genuinely differs by less than the rounding is taken as a repeat
    and skipped: a wall leaning out by under 10 nm per layer, which is a hundredth of the mesh's
    own chord error and four orders of magnitude inside the reach an overhang is judged against.
    """
    disagreement = _boolean(outline, previous, pyclipper.CT_XOR)
    if not disagreement:
        return True
    return _polygon_area(disagreement) <= _perimeter(outline) / _CLIPPER_SCALE


def _bridgeable(supported: _Paths, material: _Paths, max_bridge_span: float) -> _Paths:
    """Mark material anchored on two opposing sides within the bridgeable span.

    A bridge is material the printer has something to string a bead between. For each direction,
    the layer's anchored material is dragged forwards half a span and backwards half a span, and
    what both sweeps reach is material with an anchor on either side of it no further apart than
    the span allows. A cantilever is anchored on one side only, so however short it is it never
    qualifies — this is what distinguishes a printable bridge from an unsupported shelf.

    Each piece of the layer is treated on its own, so anchors in a piece this material is not
    joined to cannot hold it up: two shelves reaching towards each other across a gap are not a
    bridge. A sweep that passes over a hole in its own piece is still counted, which is why holes
    through bridges are rejected separately — see _holes_in_bridges.
    """
    bridged: _Paths = []
    for piece in _regions(material):
        anchors = _boolean(supported, piece, pyclipper.CT_INTERSECTION)
        if not anchors:
            continue
        for dx, dy in _BRIDGE_DIRECTIONS:
            half_span = max_bridge_span / 2.0 / math.hypot(dx, dy)
            forward = _boolean(_smear(anchors, dx * half_span, dy * half_span), piece, pyclipper.CT_INTERSECTION)
            backward = _boolean(_smear(anchors, -dx * half_span, -dy * half_span), piece, pyclipper.CT_INTERSECTION)
            bridged.extend(_boolean(forward, backward, pyclipper.CT_INTERSECTION))
    return _boolean(bridged, [], pyclipper.CT_UNION)


def _largest_piece_area(paths: _Paths) -> float:
    """Return the area of the single largest separate piece of a polygon set.

    Pieces are measured one at a time rather than summed. A body with enough corners leaves a
    speck of material at each of them, and a part with enough corners can out-total a real defect
    on the sum alone while no single place is actually wrong.
    """
    return max((_polygon_area(piece) for piece in _regions(paths)), default=0.0)


def _holes_in_bridges(material: _Paths, unsupported: _Paths, ring_width: float) -> float:
    """Return the area of the largest hole whose surrounding material is mostly unsupported.

    A hole through a bridge is effectively unprintable at any span, unlike a solid bridge.
    Only the ring of material immediately around a hole is inspected, so a part's ordinary
    cavities — enclosed by supported walls — are not mistaken for holes through a bridge. The
    holes need no finding: Clipper already reports each piece of material as an outline plus the
    holes inside it, so they come straight off the layer's own structure.

    The largest such hole is returned rather than their total, for the same reason every other
    region here is measured one at a time: a bridge peppered with pinpricks the printer will
    simply skin over is not the same defect as one with a real opening through it, and summing
    them cannot tell the two apart.
    """
    area = 0.0
    for piece in _regions(material):
        for hole in piece[1:]:
            # Clipper winds a hole the opposite way from the outline containing it, and growing
            # such a path pushes it into the material rather than into the hole, so it is turned
            # round first and then read as an ordinary outline of the void.
            void = [pyclipper.ReversePath(hole)]
            ring = _boolean(
                _boolean(_offset(void, ring_width), void, pyclipper.CT_DIFFERENCE), material, pyclipper.CT_INTERSECTION
            )
            ring_area = _polygon_area(ring)
            if ring_area <= 0.0:
                continue
            if _polygon_area(_boolean(ring, unsupported, pyclipper.CT_INTERSECTION)) / ring_area > 0.5:
                area = max(area, _polygon_area(void))
    return area


def check_layers(
    part: Part | Compound,
    down_dir: Vector,
    max_overhang_angle: float = 45.0,
    max_bridge_span: float = MAX_BRIDGE_SPAN,
    layer_height: float = LAYER_HEIGHT,
    min_feature_width: float = NOZZLE_DIAMETER,
    slicer: _MeshSlicer | None = None,
) -> str | None:
    """Check a part's printed layers for unsupported material and for sub-nozzle features.

    Returns an error message for the first defect found, else None. Material is unprintable
    if it is neither supported from below (within ``max_overhang_angle``) nor a solid bridge
    anchored on two opposing sides no further than ``max_bridge_span`` apart; bridges pierced
    by a hole are rejected regardless of span. Material is also unprintable if its layer
    cross-section is narrower than ``min_feature_width`` either where the next layer up puts
    material back onto it, or where nothing sits underneath it at all. A layer with no
    material at all is unprintable outright: the printer has nothing to lay down on that
    pass, so whatever the body continues with above the gap starts in open air.

    Both checks are driven off the same slice, read as outlines: taking one costs a mesh
    intersection per layer and there is no reason to pay it twice.

    ``slicer`` is the body's mesh, already prepared for slicing. It is a parameter so a caller
    checking a whole body can mesh it once and share it with check_bed_contact and check_mesh
    rather than tessellating the same body three times over.
    """
    if slicer is None:
        slicer = _MeshSlicer(*mesh_body(part), down_dir)
    oriented = orient_for_printing(part, down_dir.normalized())
    bounds = oriented.bounding_box()

    # Material may lean outwards by this much per layer and still be self-supporting. Nothing is
    # added to it: the layers are compared as outlines, so a surface at exactly
    # max_overhang_angle is covered by the one below grown by the reach.
    reach = layer_height * math.tan(math.radians(max_overhang_angle))

    # The sub-nozzle test needs to know what the *next* layer does, so it runs one layer
    # behind: on each pass the previous layer's thin regions are checked against the material
    # now sitting on them, and reported at the previous layer's height.
    previous_thin: _Paths | None = None

    previous: _Paths | None = None
    z = bounds.min.Z + layer_height * 0.5
    while z < bounds.max.Z:
        outline = slicer.contour_at(z)
        height = z - bounds.min.Z

        # Every slice is taken strictly inside the body's own bounding box, so an empty one is
        # a gap running clean through it, not the tapering-away of a tip. Checked before
        # anything else, so the gap is reported where it is rather than as an unsupported
        # region on the first layer that lands above it.
        if not outline:
            return f"layer at {height:.1f} mm above the bed has no material at all to print"

        # A body of constant cross-section repeats the same layer for millimetres at a time, and
        # both passes below have known answers on such a layer: growing a layer always covers the
        # layer itself, so nothing in an identical layer can be unsupported, and an identical
        # layer has identical thin regions. Asking whether this layer repeats the last one is far
        # cheaper than either pass, so it is worth asking.
        repeats_previous = previous is not None and _repeats(outline, previous)

        # The first layer is held up by the bed itself, so it is supported by definition.
        # Every later layer has a non-empty layer beneath it, guaranteed by the check above.
        if previous is None or repeats_previous:
            supported = outline
        else:
            supported = _boolean(outline, _offset(previous, reach), pyclipper.CT_INTERSECTION)
        unsupported = _boolean(outline, supported, pyclipper.CT_DIFFERENCE)

        # (A) Sub-nozzle material the next layer builds on top of. Knowing that takes the layer
        # above, so this runs one layer behind and reports at the previous layer's height.
        if previous_thin is not None:
            thin_area = _largest_piece_area(_boolean(previous_thin, outline, pyclipper.CT_INTERSECTION))
            if thin_area > MIN_UNSUPPORTED_AREA:
                return (
                    f"region of {thin_area:.1f} mm² at {height - layer_height:.1f} mm above the bed is "
                    f"narrower than the {min_feature_width:.1f} mm nozzle and carries material on the "
                    f"layer above it"
                )

        thin = (
            previous_thin
            if repeats_previous and previous_thin is not None
            else thin_regions(outline, min_feature_width)
        )

        # (B) Sub-nozzle material with nothing beneath it: a bridge thinner than a single bead,
        # which has no earlier layer to anchor to and nothing alongside it to hold it straight.
        if previous is not None and thin and unsupported:
            thin_area = _largest_piece_area(_boolean(thin, unsupported, pyclipper.CT_INTERSECTION))
            if thin_area > MIN_UNSUPPORTED_AREA:
                return (
                    f"region of {thin_area:.1f} mm² at {height:.1f} mm above the bed is narrower than "
                    f"the {min_feature_width:.1f} mm nozzle and has nothing beneath it to print onto"
                )

        previous_thin = thin

        if previous is not None:
            if _polygon_area(unsupported) > MIN_UNSUPPORTED_AREA:
                # Bridge analysis is comparatively expensive, so it only runs on the rare layers
                # that actually contain unsupported material. The gate is on the total, which is
                # never less than the largest piece decided on below, so it cannot skip a layer
                # that would have been reported.
                bridged = _bridgeable(supported, outline, max_bridge_span)

                cantilever_area = _largest_piece_area(_boolean(unsupported, bridged, pyclipper.CT_DIFFERENCE))
                if cantilever_area > MIN_UNSUPPORTED_AREA:
                    return (
                        f"unsupported region of {cantilever_area:.1f} mm² at {height:.1f} mm above the bed "
                        f"is not held up from below and is not a bridge anchored within "
                        f"{max_bridge_span:.0f} mm on two sides"
                    )

                hole_area = _holes_in_bridges(outline, unsupported, reach)
                if hole_area > MIN_UNSUPPORTED_AREA:
                    return (
                        f"bridge at {height:.1f} mm above the bed is pierced by {hole_area:.1f} mm² of holes; "
                        f"holes cannot be bridged reliably at any span"
                    )

        previous = outline
        z += layer_height

    return None


def _min_footprint_width(footprint: _Paths) -> float:
    """Return the narrowest width of a bed-contact footprint, measured across all directions.

    The footprint's convex hull is measured, not the footprint itself: what holds a part upright
    is the outline it stands on, so a hollow tube is as hard to tip as the solid cylinder that
    circumscribes it, and a part standing on separate feet is braced by the span between them.

    A convex polygon's minimum width is always attained flush with one of its own edges, so
    measuring every edge in turn gives the exact width rather than a sampled approximation. The
    hull is taken over the outline's own corners, so what comes back is the width of the shape
    the body actually stands on rather than of a picture of it.
    """
    corners = [corner for path in footprint for corner in path]
    if not corners:
        return 0.0
    points = np.asarray(corners, dtype=np.float64) / _CLIPPER_SCALE
    try:
        hull = points[ConvexHull(points).vertices]
    except QhullError:
        # A footprint whose corners are all on one line encloses nothing to take a hull of, and
        # stands on nothing the body could balance on.
        return 0.0

    width = float("inf")
    for index in range(len(hull)):
        a, b = hull[index], hull[(index + 1) % len(hull)]
        edge = b - a
        length = math.hypot(float(edge[0]), float(edge[1]))
        if length < 1e-9:
            continue
        normal = np.array([-edge[1], edge[0]]) / length
        width = min(width, float(np.abs((hull - a) @ normal).max()))
    return width if math.isfinite(width) else 0.0


def check_bed_contact(
    part: Part | Compound,
    down_dir: Vector,
    max_aspect_ratio: float = MAX_BED_ASPECT_RATIO,
    slicer: _MeshSlicer | None = None,
) -> str | None:
    """Check that a body's bed contact is a wide enough base for how tall the body is.

    Returns an error message if it is not, else None. The base is the body's first-layer
    cross-section — what the slicer actually lays onto the plate — rather than its bounding box,
    so a body that flares outwards above the bed (a cone on its tip, a part standing on feet) is
    judged on what really touches the plate and not on how wide it eventually becomes.

    Height is compared against the *narrowest* width of that footprint rather than its area,
    because a part tips over its weakest axis: a tall fin is no more stable for being long, and a
    footprint with the area of a coin is useless if it is a sliver. See MAX_BED_ASPECT_RATIO for
    the limit itself. ``slicer`` is the body's prepared mesh, shared with the other checks — see
    check_layers.
    """
    if slicer is None:
        slicer = _MeshSlicer(*mesh_body(part), down_dir)
    oriented = orient_for_printing(part, down_dir.normalized())
    bounds = oriented.bounding_box()

    footprint = slicer.contour_at(bounds.min.Z + LAYER_HEIGHT * 0.5)
    if not footprint:
        return "nothing at all touches the bed on the first layer"

    height = bounds.max.Z - bounds.min.Z
    width = _min_footprint_width(footprint)
    if width <= 0.0:
        return "touches the bed along a line with no width to it at all"
    if height / width > max_aspect_ratio:
        return (
            f"stands {height:.1f} mm tall on a bed contact only {width:.1f} mm across at its narrowest, "
            f"an aspect ratio of {height / width:.0f}:1 — above the {max_aspect_ratio:.0f}:1 a part can "
            f"be printed at before it needs a brim, a raft or a sacrificial stabiliser"
        )
    return None


def _edge_defects(triangles: NDArray[np.int64], vertex_count: int) -> list[str]:
    """Describe how a triangle mesh fails to be a closed, consistently wound surface.

    In a closed one, every edge is shared by exactly two triangles and those two traverse it in
    opposite directions. Counting how each of those two conditions is broken is what turns a bare
    "not manifold" verdict into something that says where to look: a hole, a face meeting more
    than one neighbour along an edge, or a patch wound inside out relative to its neighbours.
    """
    directed = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    _, counts = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)

    # Encode each directed edge as a single integer so its reverse can be looked up in one pass.
    codes = directed[:, 0] * vertex_count + directed[:, 1]
    unpaired = int(np.isin(directed[:, 1] * vertex_count + directed[:, 0], codes, invert=True).sum())

    defects: list[str] = []
    boundary = int((counts == 1).sum())
    if boundary:
        defects.append(f"{boundary} edge(s) with only one triangle on them (holes in the surface)")
    over_shared = int((counts > 2).sum())
    if over_shared:
        defects.append(f"{over_shared} edge(s) shared by more than two triangles")
    # A boundary edge is unpaired for want of a second triangle, not for being wound wrongly; what
    # is left over is edges whose triangles both traverse them the same way, and each of those
    # leaves *both* its half-edges without a partner, hence the halving.
    if unpaired > boundary:
        defects.append(f"{(unpaired - boundary) // 2} edge(s) traversed the same way by both their triangles")
    return defects


def check_mesh_is_solid(
    vertices: Sequence[tuple[float, float, float]],
    triangles: Sequence[tuple[int, int, int]],
) -> str | None:
    """Check that a welded triangle mesh encloses a solid, and return an error message if not.

    A slicer does not see the model; it sees this mesh, and it can only decide what is inside the
    object if the mesh is a closed surface — every edge shared by exactly two triangles, wound
    consistently, with the normals pointing outwards. A mesh that is open, self-contradictory or
    inside out leaves "inside" undefined, and the slicer is left to guess: the usual results are
    dropped walls, inverted infill, or the repair pass silently reshaping the part.

    ``vertices`` must already be welded — coincident corners shared by index rather than repeated
    — since an unwelded mesh has no shared edges at all and would read as entirely open. This is
    what the exporter's own tessellation produces (see ``mesh_body``).

    Known limitations: a mesh may be closed and still self-intersect, which this does not detect;
    and a closed mesh made of several disjoint shells passes here, being left to
    tests.collisions.check_body_is_one_solid, which is the check about connectedness.
    """
    if not triangles:
        return "tessellates to no triangles at all"

    model = get_wrapper().CreateModel()
    assert model is not None
    mesh = model.AddMeshObject()
    positions = [Lib3MF.Position((ctypes.c_float * 3)(*vertex)) for vertex in vertices]
    faces = [Lib3MF.Triangle((ctypes.c_uint * 3)(*triangle)) for triangle in triangles]
    try:
        mesh.SetGeometry(positions, faces)
    except Lib3MF.ELib3MFException as error:
        # lib3mf rejects degenerate triangles and out-of-range indices outright, so a mesh it will
        # not even accept never reaches the manifold test below and has to be reported here.
        return f"tessellates to a mesh the 3MF writer rejects outright: {error}"

    indices = np.array([triangle.Indices[:] for triangle in faces], dtype=np.int64)
    if not mesh.IsManifoldAndOriented():
        defects = _edge_defects(indices, len(positions)) or ["no closed, consistently wound surface"]
        return "tessellates to a mesh that does not enclose a solid: " + "; ".join(defects)

    # A closed mesh wound entirely the other way is still manifold, but encloses its own outside:
    # the divergence theorem gives it a negative volume, which is the whole of the test.
    points = np.array([position.Coordinates[:] for position in positions], dtype=np.float64)
    corners = points[indices]
    volume = float(np.einsum("ij,ij->i", corners[:, 0], np.cross(corners[:, 1], corners[:, 2])).sum() / 6.0)
    if volume <= 0.0:
        return f"tessellates to an inside-out mesh: its triangle normals enclose a volume of {volume:.1f} mm^3"
    return None


def mesh_body(part: Part | Compound) -> _MeshData:
    """Tessellate a body exactly as the exporter does, and return its welded mesh.

    Meshing goes through build123d's Mesher rather than Shape.tessellate because Shape.tessellate
    returns each face's corners separately, and it is the Mesher that welds them into the shared
    vertices a 3MF holds — so it, and not the raw tessellation, is what decides whether the file
    handed to the slicer is watertight.
    """
    mesher = Mesher()
    mesher.add_shape(part, linear_deflection=MESH_LINEAR_DEFLECTION, angular_deflection=MESH_ANGULAR_DEFLECTION)
    assert mesher.model is not None
    iterator = mesher.model.GetMeshObjects()
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    while iterator.MoveNext():
        mesh = iterator.GetCurrentMeshObject()
        offset = len(vertices)
        vertices.extend(cast(tuple[float, float, float], tuple(v.Coordinates[:])) for v in mesh.GetVertices())
        triangles.extend(
            cast(tuple[int, int, int], tuple(index + offset for index in t.Indices[:]))
            for t in mesh.GetTriangleIndices()
        )
    return vertices, triangles


def check_mesh(part: Part | Compound, mesh: _MeshData | None = None) -> str | None:
    """Check that a body survives being turned into the mesh the printer is given.

    Returns an error message if it does not, else None. See check_mesh_is_solid for what makes a
    mesh printable and mesh_body for why it is tessellated this way. ``mesh`` is that body's
    already-tessellated mesh when the caller has one; the check is of the mesh itself, so it makes
    no difference whether it was built here or handed in.
    """
    try:
        vertices, triangles = mesh_body(part) if mesh is None else mesh
    except Exception as error:  # noqa: BLE001 — reported as a failure, not raised past the caller
        return f"cannot be tessellated for export at all: {error}"
    return check_mesh_is_solid(vertices, triangles)


def check_printable_parts_have_body_tags(parts: list[Part | Compound]) -> list[str]:
    """Verify every printable part carries a body tag (see src.part_tags.body/tag_body).

    This is the one printability question that belongs to the assembly rather than to a body: an
    untagged part has no body to be reported under, and the per-body checks never see it at all,
    so without this it would simply vanish from the suite instead of failing it.

    Returns a list of failure descriptions — empty if every printable part is tagged.
    """
    failures: list[str] = []
    for part in parts:
        if not is_printable(part):
            continue
        children = list(part.children) if type(part) is Compound else [part]
        for child in children:
            if get_tags(child).body is None:
                failures.append(f"{child.label!r} is printable but has no body tag")
    return failures


def check_body_printable(name: str, body_parts: list[Part | Compound], down_dir: Vector) -> list[str]:
    """Verify one printed body — the parts sharing a body tag, fused into the single object that
    comes off the plate — fits in the build volume, stands on enough bed contact for its height,
    has no unsupported overhangs, empty layers or sub-nozzle-width material in its own tagged
    print orientation, and tessellates to a mesh that encloses a solid.

    Returns a list of failure descriptions — empty if the body fits and prints cleanly.
    """
    fused_body = body_parts[0]
    for part in body_parts[1:]:
        fused_body = cast(Part | Compound, fused_body + part)

    # The exported mesh is what the printer is handed, so every check below works from it: the
    # layer checks slice it and check_mesh validates it. Tessellating is the expensive step, so it
    # happens once here rather than inside each check. A body too broken to tessellate has no mesh
    # to slice, so that is reported on its own and the layer checks are skipped rather than run
    # against nothing.
    failures: list[str] = []
    try:
        mesh = mesh_body(fused_body)
        slicer = _MeshSlicer(*mesh, down_dir)
    except Exception as error:  # noqa: BLE001 — reported as a failure, not raised past the caller
        return [f"{name!r}: cannot be tessellated for export at all: {error}"]

    height, bed1, bed2 = get_print_extents(fused_body, down_dir)
    if height > BUILD_HEIGHT:
        failures.append(f"{name!r} height {height:.1f} mm exceeds build height {BUILD_HEIGHT:.1f} mm (down={down_dir})")
    if bed1 > BED_SIZE_X:
        failures.append(f"{name!r} horizontal extent {bed1:.1f} mm exceeds bed X {BED_SIZE_X:.1f} mm")
    if bed2 > BED_SIZE_Y:
        failures.append(f"{name!r} horizontal extent {bed2:.1f} mm exceeds bed Y {BED_SIZE_Y:.1f} mm")

    contact_error = check_bed_contact(fused_body, down_dir, slicer=slicer)
    if contact_error:
        failures.append(f"{name!r}: {contact_error} (down={down_dir})")

    layer_error = check_layers(fused_body, down_dir, slicer=slicer)
    if layer_error:
        failures.append(f"{name!r}: {layer_error} (down={down_dir})")

    mesh_error = check_mesh(fused_body, mesh=mesh)
    if mesh_error:
        failures.append(f"{name!r}: {mesh_error}")

    return failures
