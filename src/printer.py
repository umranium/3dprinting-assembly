from dataclasses import dataclass
from typing import Sequence

from build123d import BoundBox, Compound, Part, Vector

from src.part_tags import get_tags

# Bambu Lab X1C build volume (mm). Lives here with the rest of what is known about the printer,
# because both the build-plate layout below and the printability checks that test against it need
# the same numbers.
BED_SIZE_X = 256.0  # mm
BED_SIZE_Y = 256.0  # mm
BUILD_HEIGHT = 256.0  # mm

# Print orientation constants
DOWN_X = Vector(1, 0, 0)
DOWN_MINUS_X = Vector(-1, 0, 0)
DOWN_Y = Vector(0, 1, 0)
DOWN_MINUS_Y = Vector(0, -1, 0)
DOWN_Z = Vector(0, 0, 1)
DOWN_MINUS_Z = Vector(0, 0, -1)


def mark_non_printable(part: Part | Compound) -> None:
    """Tag a part as not meant to be printed — a hardware fastener, a clearance/pocket cutout, or
    a reference part modeling a real off-the-shelf component. Printable is the default for every
    part, so only these exceptions need tagging. Applying this once at the source — e.g. in each
    of hardware.py's shared factories — means every instance created from it is automatically
    covered, no matter how many times or where it's called."""
    get_tags(part).non_printable = True


def is_printable(part: Part | Compound) -> bool:
    """Return whether a part is printable — true for any part, unless it was tagged otherwise via
    mark_non_printable()."""
    return not get_tags(part).non_printable


def orient_for_printing(part: Part | Compound, down_dir: Vector) -> Part | Compound:
    """Rotate a part so its down_dir points to (0, 0, -1) which is the bed surface."""
    down_dir = down_dir.normalized()
    from build123d import Axis

    target = Vector(0, 0, -1)
    rot_axis = down_dir.cross(target)
    if rot_axis.length < 1e-5:
        if down_dir.dot(target) < 0:
            return part.rotate(Axis.X, 180)
        else:
            return part
    else:
        return part.rotate(Axis((0, 0, 0), rot_axis.normalized()), down_dir.get_angle(target))


def body_down_direction(part: Part | Compound) -> Vector:
    """Return the tagged print-down direction for a printable part's body (see
    src.part_tags.body/tag_body)."""
    tagged_body = get_tags(part).body
    assert tagged_body is not None, f"{part.label!r} is printable but has no body tag"
    return tagged_body.down_direction


def group_by_body(parts: Sequence[Part | Compound]) -> dict[str, list[Part | Compound]]:
    """Group printable parts by their tagged body name (see src.part_tags.body/tag_body),
    flattening Compound wrappers (e.g. a group of individually-tagged legs) into their child
    parts first. Non-printable parts are excluded."""
    flattened: list[Part | Compound] = []
    for p in parts:
        if not is_printable(p):
            continue
        if type(p) is Compound:
            for child in p.children:
                flattened.append(child.moved(p.location))
        else:
            flattened.append(p)

    bodies: dict[str, list[Part | Compound]] = {}
    for p in flattened:
        tagged_body = get_tags(p).body
        assert tagged_body is not None, f"{p.label!r} is printable but has no body tag"
        bodies.setdefault(tagged_body.name, []).append(p)
    return bodies


# Gap left between neighbouring bodies once they are laid out on the build plate, so each body's
# skirt/brim and the nozzle's travel between them have room.
PLATE_BODY_GAP = 10.0


@dataclass
class _PlateRow:
    """A row of bodies on the build plate: where it starts in Y, how deep it is (set by the
    deepest body in it, which is the first one placed there), and how far along X it has been
    filled."""

    y: float
    depth: float
    cursor_x: float = 0.0


def build_print_plate(parts: Sequence[Part | Compound], label: str) -> Compound:
    """Arrange an assembly's printable parts on the build plate, ready to slice.

    Every printable part is grouped into its tagged body (see src.part_tags.body/tag_body) and each
    body is rotated so its own tagged down direction faces the bed, then dropped until it rests on
    the bed. The oriented bodies are packed into rows across the bed by first-fit decreasing
    height: deepest body first, each one going into the first row it still fits in and opening a
    new row behind the others when none has room. Packing the deepest first is what stops a shallow
    body from claiming a row of its own and leaving the space above it empty, and choosing the row
    by footprint rather than by the order create_assembly() happened to return the parts in means
    the same assembly always lays out the same way. The finished plate is centred on the origin.

    Parts sharing a body keep their positions relative to each other, since they are all moved by
    the same offset — that is what makes a multi-part body print as the one solid it models.

    Returns a Compound of one Compound per body, which is the structure the 3MF exporter turns
    into a named, grouped object per body in the slicer.

    This is the one place print orientation happens, so that no assembly can export a .3mf that
    was never oriented for the bed, and none has to hand-roll its own build-plate offsets.
    """
    oriented_bodies: list[tuple[str, list[Part | Compound], BoundBox]] = []
    for name, body_parts in group_by_body(parts).items():
        down_dir = body_down_direction(body_parts[0])
        oriented = [orient_for_printing(p, down_dir) for p in body_parts]
        bbox = oriented[0].bounding_box()
        for p in oriented[1:]:
            bbox = bbox.add(p.bounding_box())
        oriented_bodies.append((name, oriented, bbox))

    # Deepest first, with the wider body and then the name breaking ties, so the packing depends
    # only on the shapes themselves and never on the order the parts arrived in.
    oriented_bodies.sort(key=lambda entry: (-entry[2].size.Y, -entry[2].size.X, entry[0]))

    plate: list[Part | Compound] = []
    rows: list[_PlateRow] = []
    for name, oriented, bbox in oriented_bodies:
        row = next((r for r in rows if r.cursor_x + bbox.size.X <= BED_SIZE_X), None)
        if row is None:
            # A body wider than the whole bed still opens a row of its own; that it doesn't fit is
            # the printability check's business, not the layout's.
            back = rows[-1] if rows else None
            row = _PlateRow(y=back.y + back.depth + PLATE_BODY_GAP if back else 0.0, depth=bbox.size.Y)
            rows.append(row)

        offset = (row.cursor_x - bbox.min.X, row.y - bbox.min.Y, -bbox.min.Z)
        plate.append(Compound(label=name, children=[p.translate(offset) for p in oriented]))
        row.cursor_x += bbox.size.X + PLATE_BODY_GAP

    if not plate:
        return Compound(label=label, children=[])

    plate_bbox = plate[0].bounding_box()
    for body in plate[1:]:
        plate_bbox = plate_bbox.add(body.bounding_box())
    centred = (-plate_bbox.center().X, -plate_bbox.center().Y, 0.0)

    return Compound(label=label, children=[body.translate(centred) for body in plate])
