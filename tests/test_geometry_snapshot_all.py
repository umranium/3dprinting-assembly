"""Geometry regression snapshot check that runs automatically for every printable body of every
assembly under src/, with no per-assembly test code required. Compares each body's exact shape
against a baseline attached to the latest GitHub release, using a boolean intersection volume
rather than mesh/tessellation comparison, so it isn't flaky. To accept an intentional geometry
change, run ./run-publish-snapshot.sh (see tests/geometry_snapshot.py) before committing, or set
SKIP_GEOMETRY_SNAPSHOT=1 to bypass the check for this run without publishing.

The three tests here sit at three levels, because a thing that has been *deleted* leaves no test
behind to notice it: the set of assemblies, the set of bodies within an assembly, and finally
each body's geometry.
"""

from tests.assemblies import Assembly, Body, discover_assemblies
from tests.geometry_snapshot import check_assembly_set, check_body_geometry, check_body_set


def test_assembly_set_matches_snapshot(snapshot_tag: str) -> None:
    """Assert the set of assemblies discovered under src/ matches the set covered by the latest
    GitHub release."""
    names = [name for name, _ in discover_assemblies()]
    failures = check_assembly_set(names, snapshot_tag)
    assert not failures, "assembly set mismatch:\n" + "\n".join(f"  {f}" for f in failures)


def test_body_set_matches_snapshot(assembly: Assembly, snapshot_tag: str) -> None:
    """Assert the assembly's printable bodies are exactly those with a baseline in the release —
    a body deleted from the model produces no per-body test, so only an assembly-level check can
    notice it has gone."""
    names = [body.name for body in assembly.bodies]
    failures = check_body_set(assembly.name, names, snapshot_tag)
    assert not failures, f"{assembly.name}: body set mismatch:\n" + "\n".join(f"  {f}" for f in failures)


def test_body_geometry_matches_snapshot(body: Body, snapshot_tag: str) -> None:
    """Assert this body's geometry matches the baseline in the latest GitHub release."""
    failures = check_body_geometry(body.assembly_name, body.name, body.parts, snapshot_tag)
    assert not failures, f"{body.id}: geometry snapshot mismatch:\n" + "\n".join(f"  {f}" for f in failures)
