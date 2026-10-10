"""Shared assembly/body discovery for the project-wide test suites (tests/test_*_all.py).

Discovery happens at two levels, matching the two units those suites are parametrized over:

  - the **assembly**, for checks about how parts relate to each other — unexpected intersections,
    overlapping clearances, hardware capture, whether the set of bodies is the expected one;
  - the **printable body**, for checks about one printed object on its own — printability and
    geometry snapshots. A body is what actually comes off the printer, so a failure in one body
    should name that body and leave its siblings' verdicts alone.

See tests/conftest.py for how these become test parameters.
"""

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType

from build123d import Compound, Part, Vector

import src as src_package
from src.part_tags import get_tags
from src.printer import is_printable


@dataclass(frozen=True)
class Body:
    """One printable body of one assembly: the parts sharing a body tag, which fuse into a single
    physical object on the plate (see src.part_tags.body/tag_body)."""

    assembly_name: str
    name: str
    parts: list[Part | Compound]
    down_direction: Vector

    @property
    def id(self) -> str:
        """Test id fragment, giving the "assembly then body" nesting the suites report under."""
        return f"{self.assembly_name}-{self.name}"


@dataclass(frozen=True)
class Assembly:
    """One assembly, already built. ``error`` is set instead of ``parts``/``bodies`` when
    create_assembly() raised: a broken assembly must fail its own tests rather than abort
    collection and take every other assembly's tests down with it."""

    name: str
    module: ModuleType
    parts: list[Part | Compound]
    bodies: list[Body]
    error: BaseException | None = None


def discover_assemblies() -> list[tuple[str, ModuleType]]:
    """Every subpackage of src/ that has an assembly.py module. Imports the modules but builds
    nothing, so this stays cheap enough to call before deciding what to build."""
    assemblies = []
    for module_info in pkgutil.iter_modules(src_package.__path__):
        if not module_info.ispkg:
            continue
        try:
            assembly = importlib.import_module(f"src.{module_info.name}.assembly")
        except ModuleNotFoundError:
            continue
        assemblies.append((module_info.name, assembly))
    return assemblies


def _group_bodies(assembly_name: str, parts: list[Part | Compound]) -> list[Body]:
    """Group an assembly's printable parts into bodies, mirroring src.printer.group_by_body but
    tolerating a printable part with no body tag rather than asserting on it. Such a part is a
    real defect, but it is one the assembly-level suites report by name
    (tests.printability.check_printable_parts_have_body_tags); raising here would turn it into a
    collection error instead, with no test left to explain it."""
    flattened: list[Part | Compound] = []
    for part in parts:
        if not is_printable(part):
            continue
        if type(part) is Compound:
            for child in part.children:
                flattened.append(child.moved(part.location))
        else:
            flattened.append(part)

    grouped: dict[str, list[Part | Compound]] = {}
    directions: dict[str, Vector] = {}
    for part in flattened:
        tagged_body = get_tags(part).body
        if tagged_body is None:
            continue
        grouped.setdefault(tagged_body.name, []).append(part)
        directions[tagged_body.name] = tagged_body.down_direction

    return [
        Body(assembly_name=assembly_name, name=name, parts=body_parts, down_direction=directions[name])
        for name, body_parts in grouped.items()
    ]


# create_assembly() is the expensive step, and the body names it yields are needed at *collection*
# time to parametrize one test per body — before any fixture exists to hold them. This is the one
# cache in the test suite for that reason: it is consulted from pytest_generate_tests, which runs
# once per test function, so without it every assembly would be rebuilt a dozen times over. Tests
# themselves never rebuild; they receive these already-built objects as their parameter.
_BUILT: dict[str, Assembly] = {}


def build_assembly(name: str, module: ModuleType) -> Assembly:
    """Build one assembly (once per process) and group its printable parts into bodies."""
    if name not in _BUILT:
        try:
            parts = module.create_assembly()
            _BUILT[name] = Assembly(name=name, module=module, parts=parts, bodies=_group_bodies(name, parts))
        except Exception as error:  # noqa: BLE001 — re-raised per-test, see Assembly.error
            _BUILT[name] = Assembly(name=name, module=module, parts=[], bodies=[], error=error)
    return _BUILT[name]


def built_assembly(name: str) -> Assembly | None:
    """The already-built assembly of that name, or None if it was never built this process."""
    return _BUILT.get(name)


def assembly_parts(name: str, module: ModuleType) -> list[Part | Compound]:
    """An assembly's parts, built once per process and shared with the project-wide suites.
    Re-raises a build failure rather than handing back the empty part list Assembly.error stands
    for — only the parametrized suites have a use for a failure they can attach to one test."""
    built = build_assembly(name, module)
    if built.error is not None:
        raise built.error
    return built.parts
