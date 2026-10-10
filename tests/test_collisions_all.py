"""No-unexpected-intersections check that runs automatically for every assembly under src/, with
no per-assembly test code required. A new assembly gets covered the moment it exists; a part with
a deliberate overlap (e.g. a sacrificial bridge) just needs hardware.mark_sacrificial().

Most of these are relational — they ask how an assembly's parts sit against each other — so the
assembly is the right unit for them. The one question that is genuinely about a single printed
object, whether a body holds together as one solid, is parametrized per body instead (see
tests/conftest.py).
"""

from tests.assemblies import Assembly, Body
from tests.collisions import (
    check_body_is_one_solid,
    check_no_body_overlaps_another_body,
    check_no_overlapping_clearances,
    check_no_unexpected_intersections,
    check_parts_are_single_solids,
    check_sacrificial_parts_connected,
    check_sacrificial_parts_survive_hardware,
)


def test_body_is_one_solid(body: Body) -> None:
    """Assert the parts sharing this body's tag fuse into exactly one connected solid — a body
    that splits into several has a part floating free of the siblings it prints as one object
    with."""
    failure = check_body_is_one_solid(body.name, body.parts)
    assert failure is None, f"{body.id}: {failure}"


def test_no_intersections(assembly: Assembly) -> None:
    """Assert no two physical (non-clearance) parts in the assembly intersect, other than a
    sacrificial part meeting the hardware that pierces it."""
    failures = check_no_unexpected_intersections(assembly.parts, assembly.module.PART_NAMES)
    assert not failures, f"{assembly.name}: intersecting parts found:\n" + "\n".join(f"  {f}" for f in failures)


def test_no_overlapping_clearances(assembly: Assembly) -> None:
    """Assert no two distinct clearance/hole parts in the assembly overlap each other — each
    joint must expose one fused clearance part, so any overlap found here is between two
    different joints and always a modeling defect."""
    failures = check_no_overlapping_clearances(assembly.parts, assembly.module.PART_NAMES)
    assert not failures, f"{assembly.name}: overlapping clearance parts found:\n" + "\n".join(
        f"  {f}" for f in failures
    )


def test_sacrificial_parts_are_connected(assembly: Assembly) -> None:
    """Assert every sacrificial-tagged part is actually fused into a printable part, not floating
    disconnected — test_no_intersections only rules out overlap, which a part adrift in mid-air
    satisfies trivially, so this is the only thing that catches that kind of positioning bug."""
    failures = check_sacrificial_parts_connected(assembly.parts)
    assert not failures, f"{assembly.name}: disconnected sacrificial parts found:\n" + "\n".join(
        f"  {f}" for f in failures
    )


def test_sacrificial_parts_survive_their_hardware(assembly: Assembly) -> None:
    """Assert the hardware that pierces a sacrificial part leaves some of it behind — the one
    overlap test_no_intersections exempts is otherwise unbounded, so a sacrificial part modeled
    entirely inside a screw would pass every other check while printing as nothing at all."""
    failures = check_sacrificial_parts_survive_hardware(assembly.parts)
    assert not failures, f"{assembly.name}: sacrificial parts fully consumed:\n" + "\n".join(f"  {f}" for f in failures)


def test_bodies_do_not_overlap(assembly: Assembly) -> None:
    """Assert the assembly produces at least one printed body (one with none has nothing to print
    and would otherwise pass vacuously) and that no two of them share volume — two different
    bodies are two different physical printed objects, even where their individual constituent
    parts happen to pass pairwise checks."""
    failures = check_no_body_overlaps_another_body({b.name: b.parts for b in assembly.bodies})
    assert not failures, f"{assembly.name}: body checks failed:\n" + "\n".join(f"  {f}" for f in failures)


def test_parts_are_single_solids(assembly: Assembly) -> None:
    """Assert every part in the assembly — printable, hardware or clearance alike — is a single
    connected solid, with Compound groups checked child by child. Stays at assembly level because
    hardware and clearance parts belong to no body, so a per-body test would not reach them."""
    failures = check_parts_are_single_solids(assembly.parts)
    assert not failures, f"{assembly.name}: multi-solid parts found:\n" + "\n".join(f"  {f}" for f in failures)
