from build123d import Location

from src import hardware
from src.hardware import NutType, PrintOrientation, ScrewHeadType, ScrewSize


def test_create_screw_is_single_body():
    """Both head types must produce one contiguous solid with no internal overlaps (shank and
    head are fused, not just touching or overlapping)."""
    for head_type in ScrewHeadType:
        part = hardware.create_screw(ScrewSize.M3, 20.0, head_type)
        assert len(part.solids()) == 1, head_type


def _screw_joint_cases():
    return [
        dict(head_type=ScrewHeadType.SOCKET, orientation=PrintOrientation.VERTICAL, length=20.0),
        dict(head_type=ScrewHeadType.COUNTERSUNK, orientation=PrintOrientation.HORIZONTAL, length=15.0),
        dict(
            head_type=ScrewHeadType.SOCKET,
            orientation=PrintOrientation.VERTICAL,
            length=20.0,
            clearance_above_head=2.0,
            clearance_below_screw=3.0,
        ),
        dict(
            head_type=ScrewHeadType.COUNTERSUNK,
            orientation=PrintOrientation.VERTICAL,
            length=20.0,
            clearance_above_head=1.0,
            clearance_below_screw=1.0,
        ),
        dict(
            head_type=ScrewHeadType.SOCKET,
            orientation=PrintOrientation.VERTICAL,
            length=20.0,
            nut_type=NutType.SQUARE,
            nut_side_length=5.5,
            nut_depth=2.0,
            nut_offset=10.0,
        ),
        dict(
            head_type=ScrewHeadType.COUNTERSUNK,
            orientation=PrintOrientation.HORIZONTAL,
            length=20.0,
            nut_type=NutType.SQUARE,
            nut_side_length=5.5,
            nut_depth=2.0,
            nut_offset=10.0,
            clearance_above_head=1.0,
            clearance_below_screw=2.0,
        ),
        dict(
            head_type=ScrewHeadType.SOCKET,
            orientation=PrintOrientation.VERTICAL,
            length=20.0,
            nut_type=NutType.SQUARE,
            nut_side_length=6.0,
            nut_depth=2.5,
            nut_offset=3.5,  # nut close to head
        ),
    ]


def test_create_screw_joint_fully_covers_screw_and_nut():
    """For every combination, the screw and (if present) the nut must be entirely enclosed by the
    single clearance void — zero volume of either left uncovered."""
    for case in _screw_joint_cases():
        screw, nut, clearance = hardware.create_screw_joint(ScrewSize.M3, **case)
        uncovered_screw = screw - clearance
        us = sum(s.volume for s in uncovered_screw.solids()) if uncovered_screw is not None else 0.0
        assert us < 1e-6, case
        if nut is not None:
            uncovered_nut = nut - clearance
            un = sum(s.volume for s in uncovered_nut.solids()) if uncovered_nut is not None else 0.0
            assert un < 1e-6, case


def test_create_screw_joint_clearance_is_a_single_body():
    """The clearance void — screw hole and (if present) nut pocket together — must always be one
    contiguous solid, whether or not a nut is requested."""
    for case in _screw_joint_cases():
        _, _, clearance = hardware.create_screw_joint(ScrewSize.M3, **case)
        assert len(clearance.solids()) == 1, case


def test_create_screw_joint_nut_requires_all_params_together():
    """Partial nut parameters (some given, some omitted) must be rejected — a nut is either fully
    specified or not requested at all."""
    import pytest

    with pytest.raises(AssertionError):
        hardware.create_screw_joint(
            ScrewSize.M3,
            20.0,
            ScrewHeadType.SOCKET,
            PrintOrientation.VERTICAL,
            nut_type=NutType.SQUARE,
            nut_side_length=5.5,  # nut_depth/nut_offset missing
        )


def test_create_screw_joint_without_nut_returns_none():
    """No nut params given must return None for the nut slot of the tuple."""
    _, nut, _ = hardware.create_screw_joint(ScrewSize.M3, 20.0, ScrewHeadType.SOCKET, PrintOrientation.VERTICAL)
    assert nut is None


def test_create_screw_joint_clearance_excludes_no_more_than_the_nut_pocket_itself():
    """The clearance's screw-hole-vs-nut-pocket exclusion must not double-count: the fused
    clearance volume must be strictly less than the naive (non-exclusion-aware) sum of a
    continuous screw hole plus the nut pocket alone, by exactly the overlap that would otherwise
    be double-counted."""
    size, length, head_type, orientation = ScrewSize.M3, 20.0, ScrewHeadType.COUNTERSUNK, PrintOrientation.HORIZONTAL
    nut_side, nut_depth, nut_offset = 5.5, 2.0, 10.0

    _, _, gapped_clearance = hardware.create_screw_joint(
        size,
        length,
        head_type,
        orientation,
        nut_type=NutType.SQUARE,
        nut_side_length=nut_side,
        nut_depth=nut_depth,
        nut_offset=nut_offset,
    )
    _, _, continuous_clearance = hardware.create_screw_joint(size, length, head_type, orientation)
    nut_pocket = hardware._square_nut_pocket(nut_side, nut_depth).moved(Location((0, 0, -nut_offset)))

    naive_sum = continuous_clearance.volume + nut_pocket.volume
    assert gapped_clearance.volume < naive_sum - 1e-6


def test_create_screw_joint_tags_are_correct():
    """screw must be tagged @screw (hardware_kind=SCREW, non_printable), nut must be tagged @nut
    (hardware_kind=NUT, non_printable), and clearance must be non_printable but carry no
    hardware_kind (it's a void, not a physical part)."""
    from src.part_tags import HardwareType, get_tags

    screw, nut, clearance = hardware.create_screw_joint(
        ScrewSize.M3,
        20.0,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=10.0,
    )
    assert get_tags(screw).hardware_kind == HardwareType.SCREW
    assert get_tags(screw).non_printable
    assert nut is not None
    assert get_tags(nut).hardware_kind == HardwareType.NUT
    assert get_tags(nut).non_printable
    assert get_tags(clearance).hardware_kind is None
    assert get_tags(clearance).non_printable


def test_create_screw_joint_screw_tags_correct_without_nut():
    """The screw's tags must be correct even when no nut is requested."""
    from src.part_tags import HardwareType, get_tags

    screw, _, clearance = hardware.create_screw_joint(
        ScrewSize.M3, 20.0, ScrewHeadType.SOCKET, PrintOrientation.VERTICAL
    )
    assert get_tags(screw).hardware_kind == HardwareType.SCREW
    assert get_tags(screw).non_printable
    assert get_tags(clearance).non_printable


def test_create_screw_joint_sliding_nut_slot_fully_covers_screw_and_nut_at_any_angle():
    """A sliding-insertion nut slot (nut_slide_length > 0) must still fully cover both the screw
    and the nut, at arbitrary slide angles — not just angles that happen to align with the
    nut's own 90°-rotational symmetry."""
    for angle in [0.0, 30.0, -45.0, 90.0, 123.5]:
        screw, nut, clearance = hardware.create_screw_joint(
            ScrewSize.M3,
            14.0,
            ScrewHeadType.COUNTERSUNK,
            PrintOrientation.VERTICAL,
            nut_type=NutType.SQUARE,
            nut_side_length=5.5,
            nut_depth=2.0,
            nut_offset=8.0,
            nut_slide_length=10.0,
            nut_slide_angle_deg=angle,
        )
        assert nut is not None
        uncovered_screw = screw - clearance
        us = sum(s.volume for s in uncovered_screw.solids()) if uncovered_screw is not None else 0.0
        assert us < 1e-6, angle
        uncovered_nut = nut - clearance
        un = sum(s.volume for s in uncovered_nut.solids()) if uncovered_nut is not None else 0.0
        assert un < 1e-6, angle


def test_create_screw_joint_zero_slide_length_matches_plain_pocket():
    """nut_slide_length=0 (the default) must produce exactly the same geometry as not passing it
    at all — a plain, non-elongated pocket."""
    _, nut_a, clearance_a = hardware.create_screw_joint(
        ScrewSize.M3,
        20.0,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=10.0,
    )
    _, nut_b, clearance_b = hardware.create_screw_joint(
        ScrewSize.M3,
        20.0,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=10.0,
        nut_slide_length=0.0,
        nut_slide_angle_deg=0.0,
    )
    assert clearance_a.volume == clearance_b.volume
    assert nut_a is not None and nut_b is not None
    assert nut_a.volume == nut_b.volume


def test_create_screw_joint_nut_slide_to_tip_fully_covers_screw_and_nut():
    """nut_slide_to_tip=True opens the nut's pocket along the screw's own axis, all the way to the
    tip end of the clearance, for a nut slid in from the bottom of the screw hole rather than
    sideways — the fused clearance must still fully cover both the screw and the nut, with no gap
    between the plain shank hole and the widened pocket."""
    screw, nut, clearance = hardware.create_screw_joint(
        ScrewSize.M3,
        20.0,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=15.0,
        nut_slide_to_tip=True,
    )
    assert nut is not None
    assert len(clearance.solids()) == 1
    uncovered_screw = screw - clearance
    us = sum(s.volume for s in uncovered_screw.solids()) if uncovered_screw is not None else 0.0
    assert us < 1e-6
    uncovered_nut = nut - clearance
    un = sum(s.volume for s in uncovered_nut.solids()) if uncovered_nut is not None else 0.0
    assert un < 1e-6


def test_create_screw_joint_nut_slide_to_tip_near_tip_still_single_body():
    """A nut positioned close enough to the tip that its own resting pocket already reaches (or
    exceeds) the clearance's natural end must not produce a negative/zero-length extension — the
    clearance must still come out as a single fused body."""
    screw, nut, clearance = hardware.create_screw_joint(
        ScrewSize.M3,
        20.0,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=20.9,
        nut_slide_to_tip=True,
    )
    assert nut is not None
    assert len(clearance.solids()) == 1
    uncovered_screw = screw - clearance
    us = sum(s.volume for s in uncovered_screw.solids()) if uncovered_screw is not None else 0.0
    assert us < 1e-6


def test_create_screw_joint_nut_slide_length_and_slide_to_tip_are_mutually_exclusive():
    """A nut can only slide in from one direction at a time — combining a sideways slide length
    with a to-the-tip axial slide must be rejected rather than silently picking one."""
    import pytest

    with pytest.raises(AssertionError):
        hardware.create_screw_joint(
            ScrewSize.M3,
            20.0,
            ScrewHeadType.SOCKET,
            PrintOrientation.VERTICAL,
            nut_type=NutType.SQUARE,
            nut_side_length=5.5,
            nut_depth=2.0,
            nut_offset=15.0,
            nut_slide_length=5.0,
            nut_slide_to_tip=True,
        )


def test_create_screw_joint_nut_slide_to_tip_false_matches_plain_pocket():
    """nut_slide_to_tip=False (the default) must produce exactly the same geometry as not passing
    it at all — a plain, non-elongated, print-in-place pocket."""
    _, nut_a, clearance_a = hardware.create_screw_joint(
        ScrewSize.M3,
        20.0,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=10.0,
    )
    _, nut_b, clearance_b = hardware.create_screw_joint(
        ScrewSize.M3,
        20.0,
        ScrewHeadType.SOCKET,
        PrintOrientation.VERTICAL,
        nut_type=NutType.SQUARE,
        nut_side_length=5.5,
        nut_depth=2.0,
        nut_offset=10.0,
        nut_slide_to_tip=False,
    )
    assert clearance_a.volume == clearance_b.volume
    assert nut_a is not None and nut_b is not None
    assert nut_a.volume == nut_b.volume
