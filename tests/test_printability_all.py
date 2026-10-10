"""Printability check (bed-fit, bed contact vs. height, overhangs, empty layers, sub-nozzle
material, exported mesh validity) that runs automatically for every printable body of every
assembly under src/, with no per-assembly test code required. Driven entirely by each part's
body tag (see src.part_tags.body/tag_body) — a new assembly needs no PRINT_ORIENTATIONS/PART_CHOICES
declarations for this, just to tag its printable parts' bodies as it creates them.

A body is what actually comes off the printer, so it is also the unit these tests are
parametrized over (see tests/conftest.py): one failing body names itself and leaves its siblings'
verdicts alone.
"""

from tests.assemblies import Assembly, Body
from tests.printability import check_body_printable, check_printable_parts_have_body_tags


def test_body_is_printable(body: Body) -> None:
    """Assert this printed body fits in the build volume, stands on enough bed contact for its
    height, has no unsupported overhangs, empty layers or sub-nozzle-width material, and
    tessellates to a mesh that encloses a solid."""
    failures = check_body_printable(body.name, body.parts, body.down_direction)
    assert not failures, f"{body.id}: printability checks failed:\n" + "\n".join(f"  {f}" for f in failures)


def test_printable_parts_have_body_tags(assembly: Assembly) -> None:
    """Assert every printable part belongs to a body. An untagged part has no body to be reported
    under, so the per-body tests above never see it — this is what stops it disappearing from the
    suite rather than failing it."""
    failures = check_printable_parts_have_body_tags(assembly.parts)
    assert not failures, f"{assembly.name}: untagged printable parts:\n" + "\n".join(f"  {f}" for f in failures)
