"""Unit tests for tests/mechanical.py's prying check against synthetic two-body joints: a long
flat lid screwed to a base, held in the different ways a designer might hold it. The real
assemblies are covered by tests/test_mechanical_all.py; these pin down what the check itself
says about geometry whose answer is known."""

from build123d import Box, Compound, Location, Part, Vector

from src import hardware
from src.hardware import NutType, PrintOrientation, ScrewHeadType, ScrewSize
from src.part_tags import tag_body
from src.printer import DOWN_MINUS_Z
from tests.mechanical import check_seams_not_pryable, pair_nuts_and_screws

# A base slab under a lid of the same footprint, both long in X, meeting on the plane Z=0.
_LENGTH = 100.0
_WIDTH = 20.0
_THICKNESS = 8.0

_SCREW_LENGTH = 12.0  # long enough to reach through the lid into a nut buried in the base
_NUT_OFFSET = 10.0  # head bearing face (top of lid) down to the nut's centre, inside the base


def _joint(x: float) -> tuple[Part, Part, Part]:
    """A vertical M3 socket screw driven down through the lid at (x, 0), with its nut in the
    base, plus the one clearance void for both."""
    screw, nut, clearance = hardware.create_screw_joint(
        ScrewSize.M3,
        _SCREW_LENGTH,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=_NUT_OFFSET,
    )
    assert nut is not None
    loc = hardware.screw_joint_location((x, 0.0, _THICKNESS), Vector(0, 0, -1))
    return screw.moved(loc), nut.moved(loc), clearance.moved(loc)


def _slab(z_bottom: float) -> Part:
    return Box(_LENGTH, _WIDTH, _THICKNESS).moved(Location((0, 0, z_bottom + _THICKNESS / 2.0)))


def _lid_on_base(screw_xs: list[float], hook_at_x: float | None = None) -> list[Part | Compound]:
    """A base and a lid screwed together at the given X positions, optionally with a hook at
    one end: a tab on the lid reaching down past the seam and under a ledge of the base, so the
    lid cannot be lifted there without pulling the tab up into the ledge."""
    joints = [_joint(x) for x in screw_xs]

    base = _slab(-_THICKNESS)
    lid = _slab(0.0)
    if hook_at_x is not None:
        # A tab drops from the lid's end into a channel in the base and turns inward as a toe;
        # the base has an undercut for the toe under a ledge of its own material, cut 0.3 mm
        # larger all round so nothing touches until the lid is pulled up into the ledge.
        inward = -1.0 if hook_at_x > 0 else 1.0
        tab = Box(2.0, _WIDTH, 4.0).moved(Location((hook_at_x + inward * 1.5, 0, -2.0)))
        toe = Box(3.0, _WIDTH, 1.5).moved(Location((hook_at_x + inward * 4.0, 0, -3.25)))
        lid = Part(lid + tab + toe)
        channel = Box(2.6, _WIDTH + 2.0, 4.3).moved(Location((hook_at_x + inward * 1.5, 0, -2.15)))
        undercut = Box(3.3, _WIDTH + 2.0, 2.1).moved(Location((hook_at_x + inward * 4.15, 0, -3.25)))
        base = Part(base - channel - undercut)
    for _, _, clearance in joints:
        base = Part(base - clearance)
        lid = Part(lid - clearance)

    base = tag_body(base, "Base", DOWN_MINUS_Z)
    lid = tag_body(lid, "Lid", DOWN_MINUS_Z)
    base.label, lid.label = "Base", "Lid"

    parts: list[Part | Compound] = [base, lid]
    for i, (screw, nut, clearance) in enumerate(joints):
        screw.label, nut.label, clearance.label = f"Screw {i}", f"Nut {i}", f"Clearance {i}"
        parts += [screw, nut, clearance]
    return parts


def _prying(parts: list[Part | Compound]) -> tuple[list[str], list[str]]:
    """The (failures, warnings) the check reports for a base-and-lid built by _lid_on_base."""
    printable = [parts[0], parts[1]]
    pairs, errors = pair_nuts_and_screws(parts)
    assert not errors, errors
    return check_seams_not_pryable(pairs, printable)


def test_a_single_screw_at_one_end_of_a_long_seam_fails() -> None:
    """The fault this check exists for: nearly the whole seam hangs off one screw, so the far end
    is levered open far past the hard ceiling rather than merely worse than a centred screw."""
    failures, warnings = _prying(_lid_on_base([-_LENGTH / 2.0 + 8.0]))
    assert len(failures) == 1 and "'Lid'" in failures[0] and "'Base'" in failures[0], failures
    assert warnings == []


def test_a_single_screw_centred_on_the_seam_passes() -> None:
    """A screw in the middle of its seam is the standard the advisory level is drawn from, so it
    sits exactly on that boundary and must come back clean — neither failed nor warned about."""
    assert _prying(_lid_on_base([0.0])) == ([], [])


def test_a_screw_at_each_end_passes() -> None:
    assert _prying(_lid_on_base([-_LENGTH / 2.0 + 8.0, _LENGTH / 2.0 - 8.0])) == ([], [])


def test_two_screws_bunched_at_one_end_are_warned_about() -> None:
    """Two screws close together at one end hold the seam better than one does, but still worse
    than a single centred screw would — between the two levels, so warned rather than failed."""
    failures, warnings = _prying(_lid_on_base([-_LENGTH / 2.0 + 8.0, -_LENGTH / 2.0 + 16.0]))
    assert failures == []
    assert len(warnings) == 1 and "'Lid'" in warnings[0] and "'Base'" in warnings[0], warnings


def test_a_hook_at_the_far_end_holds_what_a_single_screw_cannot() -> None:
    screw_x = -_LENGTH / 2.0 + 8.0
    assert _prying(_lid_on_base([screw_x]))[0], "the bare single-screw lid should fail first"
    assert _prying(_lid_on_base([screw_x], hook_at_x=_LENGTH / 2.0)) == ([], [])


def test_a_hook_at_the_same_end_as_the_screw_does_not_help() -> None:
    screw_x = -_LENGTH / 2.0 + 8.0
    failures, _ = _prying(_lid_on_base([screw_x], hook_at_x=-_LENGTH / 2.0))
    assert len(failures) == 1, failures


def test_a_lid_that_only_touches_its_base_edge_on_is_not_judged() -> None:
    """A body screwed to another it only meets along faces parallel to the screw — a peg in a
    socket, say — has no seam across the screw to pry; there is nothing for the check to say."""
    parts = _lid_on_base([0.0])
    base, lid = parts[0], parts[1]
    # Lift the lid clear of the base so the two share no face at all.
    lifted = tag_body(lid.moved(Location((0, 0, 1.0))), "Lid", DOWN_MINUS_Z)
    lifted.label = "Lid"
    pairs, _ = pair_nuts_and_screws(parts)
    assert check_seams_not_pryable(pairs, [base, lifted]) == ([], [])
