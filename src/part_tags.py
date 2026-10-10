"""Custom metadata attached to build123d parts, consolidated into a single dynamic attribute
(rather than one attribute per tag) so every part carries at most one extra field."""

from dataclasses import dataclass, replace
from enum import Enum
from functools import wraps
from typing import Callable, TypeVar, cast

from build123d import Compound, Part, Plane, Vector
from build123d import mirror as _build123d_mirror

_CUSTOM_TAGS_ATTR = "custom_tags"

PartT = TypeVar("PartT", bound=Part | Compound)


class HardwareType(Enum):
    """The mechanical role of a hardware part produced by src/hardware.py's factories."""

    SCREW = "screw"
    NUT = "nut"


@dataclass
class Body:
    """Which printed body a part belongs to, and that body's print orientation. Several parts can
    share the same Body (they get fused together for the bed-fit/overhang check and print with the
    same orientation), or a body can be exactly one part — e.g. box_with_lid prints its Box and
    Lid as two separately-oriented bodies, while phone_stand fuses its stand and its contrasting
    lip into one "Stand" body."""

    name: str
    down_direction: Vector


@dataclass
class CustomTags:
    """Custom metadata for a part. Every field defaults to "not tagged", so a part with no
    metadata at all never needs a tagging call."""

    hardware_kind: HardwareType | None = None
    sacrificial: bool = False
    non_printable: bool = False
    body: Body | None = None
    set_screw: bool = False


def get_tags(part: Part | Compound) -> CustomTags:
    """Return a part's CustomTags, attaching a fresh (all-default) one first if it has none yet."""
    tags = getattr(part, _CUSTOM_TAGS_ATTR, None)
    if tags is None:
        tags = CustomTags()
        setattr(part, _CUSTOM_TAGS_ATTR, tags)
    return tags


def _copy_tags(source: Part | Compound, dest: Part | Compound) -> None:
    """Copy source's CustomTags onto dest as an independent copy (not an alias), if source has
    any. A no-op if source was never tagged, leaving dest untagged (printable by default) too."""
    tags = getattr(source, _CUSTOM_TAGS_ATTR, None)
    if tags is not None:
        setattr(dest, _CUSTOM_TAGS_ATTR, replace(tags))


def mirror(part: PartT, plane: Plane) -> PartT:
    """Tag-preserving drop-in replacement for build123d's mirror(): the mirrored copy inherits
    part's CustomTags, since build123d's own mirror() (like its boolean operators) doesn't carry
    custom attributes over on its own. Import this instead of build123d.mirror wherever the part
    being mirrored might be tagged, so a future tagged part mirrored here can't silently lose its
    tag the way a bare build123d.mirror() call would."""
    mirrored = cast(PartT, _build123d_mirror(part, plane))
    _copy_tags(part, mirrored)
    return mirrored


def tag_body(part: PartT, name: str, down_direction: Vector) -> PartT:
    """Tag a part with which printed body it belongs to and that body's print orientation.
    Plain-function form of @body(), for cases where the name/orientation vary per call (e.g. a
    loop producing several differently-oriented instances) rather than being fixed for a whole
    factory function."""
    get_tags(part).body = Body(name=name, down_direction=down_direction)
    return part


def mark_set_screw(part: PartT) -> PartT:
    """Tag a screw instance as a set-screw: one whose clamping force comes from its own tip
    pressing into a separate body as it's tightened, rather than from its head-to-nut span
    drawing two different bodies together. Unlike @screw, this isn't a factory decorator, since
    the same shared factory (e.g. hardware.create_screw_joint) is used for both ordinary draw-together
    joints and, occasionally, a set-screw — only the specific instance used as a set-screw should
    be tagged, not every screw the factory ever produces."""
    get_tags(part).set_screw = True
    return part


def body(name: str, down_direction: Vector) -> Callable[[Callable[..., PartT]], Callable[..., PartT]]:
    """Decorator factory for a part factory function whose body membership and print orientation
    are fixed at definition time: tags its returned part accordingly. See tag_body() for the
    per-call form when they vary."""

    def decorator(factory: Callable[..., PartT]) -> Callable[..., PartT]:
        @wraps(factory)
        def wrapper(*args: object, **kwargs: object) -> PartT:
            return tag_body(factory(*args, **kwargs), name, down_direction)

        return wrapper

    return decorator


def non_printable(factory: Callable[..., PartT]) -> Callable[..., PartT]:
    """Decorator for a part factory function: tags its returned part as not meant to be printed.
    See CustomTags.non_printable — printable is the default, so only this exception needs tagging."""

    @wraps(factory)
    def wrapper(*args: object, **kwargs: object) -> PartT:
        part = factory(*args, **kwargs)
        get_tags(part).non_printable = True
        return part

    return wrapper


def sacrificial(factory: Callable[..., PartT]) -> Callable[..., PartT]:
    """Decorator for a part factory function: tags its returned part as an intentional sacrificial
    feature. See CustomTags.sacrificial."""

    @wraps(factory)
    def wrapper(*args: object, **kwargs: object) -> PartT:
        part = factory(*args, **kwargs)
        get_tags(part).sacrificial = True
        return part

    return wrapper


def screw(factory: Callable[..., PartT]) -> Callable[..., PartT]:
    """Decorator for a part factory function: tags its returned part as a screw (hardware_kind)
    and as non-printable, since a screw is never a printed body."""

    @wraps(factory)
    def wrapper(*args: object, **kwargs: object) -> PartT:
        part = factory(*args, **kwargs)
        tags = get_tags(part)
        tags.hardware_kind = HardwareType.SCREW
        tags.non_printable = True
        return part

    return wrapper


def nut(factory: Callable[..., PartT]) -> Callable[..., PartT]:
    """Decorator for a part factory function: tags its returned part as a nut (hardware_kind) and
    as non-printable, since a nut is never a printed body."""

    @wraps(factory)
    def wrapper(*args: object, **kwargs: object) -> PartT:
        part = factory(*args, **kwargs)
        tags = get_tags(part)
        tags.hardware_kind = HardwareType.NUT
        tags.non_printable = True
        return part

    return wrapper
