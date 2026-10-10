"""Project-wide geometry sanity checks — unexpected intersections between parts, and the
solidity/connectivity of the parts and printed bodies themselves — shared across all
assemblies' test suites."""

from typing import cast

from build123d import Compound, Part

from src import hardware
from src.printer import is_printable


def _physical_parts(parts: list[Part | Compound], part_names: set[str]) -> list[Part | Compound]:
    """Flatten Compound children into individual parts and drop clearance-only (visualization)
    parts, identified by the "Clearance" suffix convention every assembly's PART_NAMES already
    follows for those parts."""
    clearance_labels = {name for name in part_names if "Clearance" in name}
    physical: list[Part | Compound] = []
    for part in parts:
        if part.label in clearance_labels:
            continue
        if type(part) is Compound:
            for child in part.children:
                physical.append(child.moved(part.location))
        else:
            physical.append(part)
    return physical


def _is_sacrificial_hardware_pair(p1: Part | Compound, p2: Part | Compound) -> bool:
    """Whether a pair is a sacrificial part meeting the hardware that destroys it — the one
    combination whose overlap is intentional (see check_no_unexpected_intersections)."""
    return (hardware.is_sacrificial(p1) and hardware.hardware_kind(p2) is not None) or (
        hardware.is_sacrificial(p2) and hardware.hardware_kind(p1) is not None
    )


def check_no_unexpected_intersections(parts: list[Part | Compound], part_names: set[str]) -> list[str]:
    """Verify no two physical (non-clearance) parts in an assembly intersect, except where a part
    tagged sacrificial (@sacrificial) meets a hardware part — e.g. a thin bridge meant to be
    pierced by a screw during assembly — where overlap is by design rather than a defect.

    The exemption is deliberately no wider than that. A sacrificial part is still printed
    material fused into a body, so it must sit alongside the assembly's other parts as cleanly as
    any of them: overlapping printable geometry (or a non-printable reference part like a modeled
    phone) is a modeling defect whether the part is sacrificial or not, and only the hardware
    that destroys it during assembly is allowed to share its volume.

    Returns a list of failure descriptions — empty if every non-exempt pair is clear.
    """
    physical = _physical_parts(parts, part_names)

    def overlap_vol(p1: Part | Compound, p2: Part | Compound) -> float:
        shape = p1.intersect(p2)
        return sum(s.volume for s in shape) if shape is not None else 0.0

    failures: list[str] = []
    for i, p1 in enumerate(physical):
        for p2 in physical[i + 1 :]:
            if _is_sacrificial_hardware_pair(p1, p2):
                continue
            v = overlap_vol(p1, p2)
            if v > 1e-6:
                failures.append(f"{p1.label!r} ∩ {p2.label!r} = {v:.3f} mm³")
    return failures


def check_no_overlapping_clearances(parts: list[Part | Compound], part_names: set[str]) -> list[str]:
    """Verify no two distinct clearance/hole parts (identified by the "Clearance" label
    convention every assembly's PART_NAMES already follows) overlap each other.

    A single mechanical joint's own clearance pieces (e.g. a screw's shank tunnel, head
    clearance, and countersink cone) are expected to overlap heavily — they're deliberately
    layered subtractions that union into one continuous void for that joint — so each joint must
    expose exactly one fused clearance part (as hardware.create_screw_joint() returns) rather
    than its individual pieces. Given that, any overlap this finds is between two different
    joints' clearance geometry, which is always a modeling defect: either their positions
    genuinely collide, or one of them is oversized for what it actually needs to clear.

    Returns a list of failure descriptions — empty if every clearance pair is clear.
    """
    clearance_labels = {name for name in part_names if "Clearance" in name}
    clearances: list[Part | Compound] = []
    for part in parts:
        if part.label not in clearance_labels:
            continue
        if type(part) is Compound:
            for child in part.children:
                clearances.append(child.moved(part.location))
        else:
            clearances.append(part)

    def overlap_vol(p1: Part | Compound, p2: Part | Compound) -> float:
        shape = p1.intersect(p2)
        return sum(s.volume for s in shape) if shape is not None else 0.0

    failures: list[str] = []
    for i, c1 in enumerate(clearances):
        for c2 in clearances[i + 1 :]:
            v = overlap_vol(c1, c2)
            if v > 1e-6:
                failures.append(f"{c1.label!r} ∩ {c2.label!r} = {v:.3f} mm³")
    return failures


def check_sacrificial_parts_connected(parts: list[Part | Compound]) -> list[str]:
    """Verify every part tagged sacrificial (hardware.mark_sacrificial()) actually fuses into at
    least one printable part, rather than floating disconnected from the body it's meant to be a
    piece of. Nothing else establishes that: check_no_unexpected_intersections only rules out
    overlap, which a part adrift in mid-air satisfies trivially, and its hardware pair is exempt
    there by design.

    Connectivity is tested by fusing the sacrificial part with each printable part in turn and
    checking whether the result is a single solid — two shapes that only touch or overlap collapse
    into one solid on union, while genuinely separate ones remain two.

    Returns a list of failure descriptions — empty if every sacrificial part is connected.
    """
    sacrificial = [p for p in parts if hardware.is_sacrificial(p)]
    printable = [p for p in parts if is_printable(p)]

    failures: list[str] = []
    for s in sacrificial:
        # A sacrificial part is often itself printable (fused into the print body elsewhere), so
        # comparing it against itself would trivially "connect" regardless of its real position.
        others = [p for p in printable if p is not s]
        if not any(len((s + p).solids()) == 1 for p in others):
            failures.append(f"{s.label!r} is tagged sacrificial but doesn't connect to any printable part")
    return failures


def check_sacrificial_parts_survive_hardware(parts: list[Part | Compound]) -> list[str]:
    """Verify the hardware allowed to pierce a sacrificial part (@sacrificial) doesn't swallow the
    whole of it. The sacrificial/hardware pair is the one overlap
    check_no_unexpected_intersections deliberately ignores, so without this the exemption is
    unbounded: a bridge modeled entirely inside the screw's own volume would pass every other
    check here — check_sacrificial_parts_connected included, since it still fuses to the body it
    was cut from — while printing as material the screw simply occupies.

    The bound comes from the geometry rather than a tuned constant: the overlap must be strictly
    less than the sacrificial part's own volume, so some rim of it survives as real material
    attached to the body. How much should survive is assembly-specific and belongs in that
    assembly's own tests.

    Returns a list of failure descriptions — empty if every sacrificial part outlives its hardware.
    """
    sacrificial = [p for p in parts if hardware.is_sacrificial(p)]
    hardware_parts = [p for p in parts if hardware.hardware_kind(p) is not None]

    def overlap_vol(a: Part | Compound, b: Part | Compound) -> float:
        shape = a.intersect(b)
        return sum(s.volume for s in shape) if shape is not None else 0.0

    failures: list[str] = []
    for s in sacrificial:
        for h in hardware_parts:
            v = overlap_vol(s, h)
            if v >= s.volume - 1e-6:
                failures.append(
                    f"{h.label!r} consumes all of sacrificial {s.label!r} "
                    + f"({v:.3f} mm³ of {s.volume:.3f} mm³) — nothing of it is left to print"
                )
    return failures


def check_parts_are_single_solids(parts: list[Part | Compound]) -> list[str]:
    """Verify every part in an assembly is a single connected solid, rather than several disjoint
    ones. A part is the unit an assembly models and reasons about, so one that has quietly split
    into several solids is a defect whatever its role: a printable part that no longer touches
    the rest of its own geometry, or a clearance part whose pieces failed to union into the one
    continuous void per joint that check_no_overlapping_clearances relies on.

    Compound wrappers (e.g. a group of legs, or a strip of connector modules) are flattened into
    their children first and each child checked on its own — a Compound is a container of several
    parts, not a part that happens to be multi-solid. Only a Compound that actually has children
    counts as such a wrapper: build123d returns a childless Compound from a boolean whose result
    fell apart into disjoint pieces, which is exactly the defect this looks for, so those are
    checked as parts rather than flattened away into nothing.

    Returns a list of failure descriptions — empty if every part is one solid.
    """
    flattened: list[Part | Compound] = []
    for part in parts:
        if type(part) is Compound and part.children:
            for child in part.children:
                flattened.append(child.moved(part.location))
        else:
            flattened.append(part)

    failures: list[str] = []
    for part in flattened:
        n = len(part.solids())
        if n != 1:
            failures.append(f"{part.label!r}: {n} solids, not one")
    return failures


def fuse_body(body_parts: list[Part | Compound]) -> Part | Compound:
    """Fuse the parts sharing a body tag into the single object the printer lays down."""
    combined = body_parts[0]
    for part in body_parts[1:]:
        combined = cast(Part | Compound, combined + part)
    return combined


def check_body_is_one_solid(name: str, body_parts: list[Part | Compound]) -> str | None:
    """Verify one printed body fuses into exactly one connected solid.

    The parts sharing a body name are printed as a single object, so they must all actually
    touch: a body that comes out as two or more solids has a part floating free of its siblings,
    which the printer would lay down as separate pieces — or drop entirely, if the stray piece
    never reaches the bed.

    Returns a failure description, or None if the body is one solid.
    """
    solids = fuse_body(body_parts).solids()
    if len(solids) == 1:
        return None
    volumes = ", ".join(f"{s.volume:.3f} mm³" for s in sorted(solids, key=lambda s: -s.volume))
    return f"body {name!r} is {len(solids)} disconnected solids ({volumes}), not one"


def check_no_body_overlaps_another_body(bodies: dict[str, list[Part | Compound]]) -> list[str]:
    """Verify an assembly's printed bodies don't share volume, and that it produces any at all —
    where a "body" is the group of parts sharing the same tag.body.name
    (src.part_tags.body/tag_body), fused together for printing.

    Parts within the same body are expected to touch and fuse; parts in different bodies are
    different physical printed objects and must never share volume. Both questions here are
    relational or about the assembly as a whole, so neither can be asked of a single body: an
    assembly with no bodies is broken — there is nothing to print — and would otherwise pass
    vacuously, since no bodies means no overlapping pairs. Whether each individual body holds
    together is check_body_is_one_solid's job, and whether every printable part made it into a
    body at all is tests.printability.check_printable_parts_have_body_tags's.

    Returns a list of failure descriptions — empty if the assembly has at least one body and no
    pair of bodies overlaps.
    """
    if not bodies:
        return ["assembly produces no printable bodies at all"]

    fused = {name: fuse_body(group) for name, group in bodies.items()}

    def overlap_vol(a: Part | Compound, b: Part | Compound) -> float:
        shape = a.intersect(b)
        return sum(s.volume for s in shape) if shape is not None else 0.0

    failures: list[str] = []
    names = list(fused.keys())
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            v = overlap_vol(fused[name_a], fused[name_b])
            if v > 1e-6:
                failures.append(f"body {name_a!r} ∩ body {name_b!r} = {v:.3f} mm³")
    return failures
