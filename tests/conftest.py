"""Parametrization for the project-wide suites (tests/test_*_all.py), and the options that scope
them.

A test in those suites declares what it is about by the parameter it takes: ``assembly`` for a
check about how an assembly's parts relate to each other, ``body`` for a check about one printed
object on its own. Both are parametrized here rather than by a decorator in each suite, because
the parameter list depends on --assembly/--body, and a decorator's arguments are evaluated at
import time — before pytest options can be read, which would mean building every assembly even
when only one was asked for.
"""

import pytest
from build123d import Vector

from tests.assemblies import Assembly, Body, build_assembly, built_assembly, discover_assemblies
from tests.geometry_snapshot import is_skip_mode, latest_release_tag

# Stand-in body for an assembly whose create_assembly() raised: without it, a broken assembly
# would contribute no per-body tests at all and its failure would go unreported by them.
BUILD_FAILED = "<build failed>"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--assembly",
        default=None,
        metavar="NAME",
        help="restrict the project-wide suites to one assembly (as named under src/)",
    )
    parser.addoption(
        "--body",
        default=None,
        metavar="NAME",
        help="restrict the per-body tests to one printable body, e.g. --body 'Lid'",
    )


def _selected_assemblies(config: pytest.Config) -> list[Assembly]:
    """Build and return the assemblies --assembly selects — only those, so scoping a run to one
    assembly doesn't pay to model the others."""
    only = config.getoption("--assembly")
    modules = [(name, module) for name, module in discover_assemblies() if only in (None, name)]
    return [build_assembly(name, module) for name, module in modules]


def _selected_bodies(config: pytest.Config) -> list[Body]:
    only = config.getoption("--body")
    bodies: list[Body] = []
    for assembly in _selected_assemblies(config):
        if assembly.error is not None:
            bodies.append(Body(assembly.name, BUILD_FAILED, [], Vector(0, 0, -1)))
            continue
        bodies.extend(body for body in assembly.bodies if only in (None, body.name))
    return bodies


def pytest_configure(config: pytest.Config) -> None:
    """Reject a --assembly/--body that selects nothing, once, before collection. A typo would
    otherwise quietly run zero of the tests it was meant to narrow down to, and report success."""
    only_assembly = config.getoption("--assembly")
    if only_assembly is not None and not _selected_assemblies(config):
        available = ", ".join(sorted(name for name, _ in discover_assemblies()))
        raise pytest.UsageError(f"--assembly={only_assembly!r} matches no assembly under src/; available: {available}")

    only_body = config.getoption("--body")
    if only_body is not None and not _selected_bodies(config):
        available = ", ".join(sorted(body.name for a in _selected_assemblies(config) for body in a.bodies))
        raise pytest.UsageError(f"--body={only_body!r} matches no printable body; available: {available}")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "assembly" in metafunc.fixturenames:
        assemblies = _selected_assemblies(metafunc.config)
        metafunc.parametrize("assembly", assemblies, ids=[a.name for a in assemblies], indirect=True)
    if "body" in metafunc.fixturenames:
        bodies = _selected_bodies(metafunc.config)
        metafunc.parametrize("body", bodies, ids=[b.id for b in bodies], indirect=True)


@pytest.fixture
def assembly(request: pytest.FixtureRequest) -> Assembly:
    """The built assembly for this test's parameter. Re-raises a build failure here so it is
    reported as this test failing, not as an error collecting the whole session."""
    selected: Assembly = request.param
    if selected.error is not None:
        raise selected.error
    return selected


@pytest.fixture
def body(request: pytest.FixtureRequest) -> Body:
    """The printable body for this test's parameter (see the assembly fixture on build errors)."""
    selected: Body = request.param
    parent = built_assembly(selected.assembly_name)
    if parent is not None and parent.error is not None:
        raise parent.error
    return selected


@pytest.fixture(scope="session")
def snapshot_tag() -> str:
    """The GitHub release tag the geometry snapshot suite compares against, or a skip when there
    is nothing to compare against. Session-scoped because resolving it shells out to `gh`, and
    every body's snapshot test wants the same answer."""
    if is_skip_mode():
        pytest.skip("SKIP_GEOMETRY_SNAPSHOT is set")
    tag = latest_release_tag()
    if tag is None:
        pytest.skip("no GitHub release available to compare against (no release, gh auth or network)")
    return tag
