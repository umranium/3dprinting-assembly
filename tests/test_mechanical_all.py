"""Mechanical checks that run automatically for every assembly under src/, with no per-assembly
test code required. A new assembly gets covered the moment it exists, as long as it builds its
screws and nuts with src/hardware.py's factories (which tag hardware_kind and attach joints)."""

import warnings

from src.printer import is_printable
from tests.assemblies import Assembly
from tests.mechanical import (
    PryingWarning,
    check_body_rotationally_captured,
    check_hardware_clear_of_printable_material,
    check_nut_captured_by_printable_material,
    check_seams_not_pryable,
    pair_nuts_and_screws,
)


def test_nut_captured_by_printable_material(assembly: Assembly) -> None:
    """Assert every screw/nut pair in the assembly is auto-discovered (via hardware_kind and
    joints, not labels) and has printable material clamped between them."""
    printable = [p for p in assembly.parts if is_printable(p)]

    pairs, pairing_errors = pair_nuts_and_screws(assembly.parts)
    assert not pairing_errors, f"{assembly.name}: unpaired hardware:\n" + "\n".join(f"  {e}" for e in pairing_errors)

    failures = [
        f"{nut.label!r} <-> {screw.label!r}: {error}"
        for nut, screw in pairs
        if (error := check_nut_captured_by_printable_material(nut, screw, printable))
    ]
    assert not failures, f"{assembly.name}: nut/screw clamping checks failed:\n" + "\n".join(f"  {f}" for f in failures)


def test_body_rotationally_captured(assembly: Assembly) -> None:
    """Assert the printed body housing each screw's bearing face, and the printed body housing its
    nut, are each stopped from spinning about the screw's fastening axis by some other printable
    body — not merely held apart by it (that's check_nut_captured_by_printable_material's job)."""
    printable = [p for p in assembly.parts if is_printable(p)]

    pairs, pairing_errors = pair_nuts_and_screws(assembly.parts)
    assert not pairing_errors, f"{assembly.name}: unpaired hardware:\n" + "\n".join(f"  {e}" for e in pairing_errors)

    failures = [
        f"{nut.label!r} <-> {screw.label!r}: {error}"
        for nut, screw in pairs
        for error in check_body_rotationally_captured(nut, screw, printable)
    ]
    assert not failures, f"{assembly.name}: rotational capture checks failed:\n" + "\n".join(f"  {f}" for f in failures)


def test_hardware_has_clear_path(assembly: Assembly) -> None:
    """Assert every screw and nut in the assembly has an actual empty channel through the
    printable parts — being close enough and aligned enough to pair up isn't enough on its own;
    if the clearance hole is missing, too short, or otherwise blocked, the screw has nowhere to
    physically go even though check_nut_captured_by_printable_material would still see printable
    material nearby."""
    printable = [p for p in assembly.parts if is_printable(p)]

    pairs, pairing_errors = pair_nuts_and_screws(assembly.parts)
    assert not pairing_errors, f"{assembly.name}: unpaired hardware:\n" + "\n".join(f"  {e}" for e in pairing_errors)

    failures = []
    for nut, screw in pairs:
        for hardware_part in (nut, screw):
            error = check_hardware_clear_of_printable_material(hardware_part, printable)
            if error:
                failures.append(error)
    assert not failures, f"{assembly.name}: hardware clearance checks failed:\n" + "\n".join(f"  {f}" for f in failures)


def test_seams_cannot_be_pried_open(assembly: Assembly) -> None:
    """Assert no seam between two screwed-together bodies can be levered open at one end by
    pulling far from where it is held. Judged per pair of bodies, with all the screws between
    them counted together.

    A seam held worse than a single centred screw would hold it is the design target, not yet a
    defect, so it is raised as a PryingWarning rather than failing the test; only a seam past the
    hard ceiling in tests.mechanical fails. The warnings are the backlog of existing designs to
    bring up to the target, and pytest lists them in its warnings summary."""
    printable = [p for p in assembly.parts if is_printable(p)]

    pairs, pairing_errors = pair_nuts_and_screws(assembly.parts)
    assert not pairing_errors, f"{assembly.name}: unpaired hardware:\n" + "\n".join(f"  {e}" for e in pairing_errors)

    failures, advisories = check_seams_not_pryable(pairs, printable)
    for advisory in advisories:
        warnings.warn(f"{assembly.name}: {advisory}", PryingWarning, stacklevel=2)
    assert not failures, f"{assembly.name}: prying checks failed:\n" + "\n".join(f"  {f}" for f in failures)
