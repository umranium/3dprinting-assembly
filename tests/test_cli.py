"""Unit tests for the base CLI layer shared by every assembly: the Click option decorators in
src.exporter (and the parse_vector/parse_color callbacks they install) wired up to the exporter
functions they feed.

Each assembly's own main.py only wraps this layer — it selects parts and hands them over — so the
wrappers are not tested per assembly. They are exercised here once against a generic assembly of
plain boxes, tagged exactly the way a real assembly tags its parts, and driven through a CLI wired
up exactly the way a real assembly's main.py wires up its own. That covers the naming, grouping
and print-orientation behaviour of the shared export path without any real assembly geometry.
"""

import os
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import click
import pytest
from build123d import Box, Color, Compound, Part
from click.testing import CliRunner
from lib3mf import Lib3MF

from src.exporter import (
    export_3mf_options,
    export_printable_3mf,
    export_shaded_jpg,
    export_shaded_jpg_options,
    export_wireframe_jpg,
    export_wireframe_jpg_options,
)
from src.part_tags import tag_body
from src.printer import DOWN_MINUS_Z, DOWN_X, mark_non_printable

DEFAULT_OUTDIR = "export/generic"


def _generic_assembly() -> list[Part]:
    """A generic assembly of plain boxes, standing in for a real create_assembly(): a flat list of
    parts, each tagged with the body it belongs to and how that body prints.

    The boxes are deliberately tiny (wireframe projection costs per projected edge) but the
    structure is deliberately complete — two bodies so the grouping path is taken, two parts
    sharing a colour and one differing so extruder assignment is exercised, one part left
    unlabelled so label inheritance from its body is exercised, a body tagged to print on its end
    so the orientation path is exercised, and one non-printable part that must be left out.
    """
    part_one = Box(10, 10, 10)
    part_one.label = "Part One"
    part_one.color = Color("cyan")
    tag_body(part_one, "Body A", DOWN_MINUS_Z)

    part_two = Box(6, 6, 6).translate((20, 0, 0))
    part_two.label = "Part Two"
    part_two.color = Color("orange")
    tag_body(part_two, "Body A", DOWN_MINUS_Z)

    # Deliberately unlabelled: it should inherit "Body B" from its parent. Modelled lying along X
    # and well above the bed, but tagged to print on that end, so it only comes out 20 mm tall and
    # standing on the bed if the export actually oriented it.
    unlabelled_part = Box(20, 4, 4).translate((0, 20, 50))
    unlabelled_part.color = Color("cyan")
    tag_body(unlabelled_part, "Body B", DOWN_X)

    fastener = Box(5, 5, 5)
    fastener.label = "Screw"
    mark_non_printable(fastener)

    return [part_one, part_two, unlabelled_part, fastener]


def _mesh_object_names(path: str) -> list[str]:
    """Every mesh object name in a 3MF file, after asserting the file declares millimetres."""
    wrapper = Lib3MF.Wrapper()
    model: Any = wrapper.CreateModel()
    assert model is not None
    reader = model.QueryReader("3mf")
    assert reader is not None
    reader.ReadFromFile(path)

    assert model.GetUnit() == 1, "3MF model unit is not millimetres"

    iterator = model.GetMeshObjects()
    assert iterator is not None
    names = []
    for _ in range(iterator.Count()):
        iterator.MoveNext()
        mesh = iterator.GetCurrentMeshObject()
        assert mesh is not None
        names.append(mesh.GetName())
    return names


def _mesh_object_bounds(path: str) -> dict[str, tuple[tuple[float, float, float], float]]:
    """Every mesh object in a 3MF file, read back as name -> (size, lowest z), so that where a
    part ended up in the exported file can be checked without trusting the code that put it
    there."""
    wrapper = Lib3MF.Wrapper()
    model: Any = wrapper.CreateModel()
    reader = model.QueryReader("3mf")
    reader.ReadFromFile(path)

    iterator = model.GetMeshObjects()
    bounds = {}
    for _ in range(iterator.Count()):
        iterator.MoveNext()
        mesh = iterator.GetCurrentMeshObject()
        xs, ys, zs = zip(*(mesh.GetVertex(i).Coordinates for i in range(mesh.GetVertexCount())))
        size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        bounds[mesh.GetName()] = (size, min(zs))
    return bounds


def _slicer_object_config(path: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """The Metadata/model_settings.config that export_assembly_3mf injects for Bambu Studio,
    read back as [(body name, [(part name, extruder index), ...]), ...]."""

    def metadata(element: ET.Element, key: str) -> str:
        found = element.find(f"metadata[@key='{key}']")
        assert found is not None, f"missing {key!r} metadata"
        value = found.get("value")
        assert value is not None, f"{key!r} metadata has no value"
        return value

    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("Metadata/model_settings.config"))

    return [
        (metadata(obj, "name"), [(metadata(part, "name"), metadata(part, "extruder")) for part in obj.findall("part")])
        for obj in root.findall("object")
    ]


@click.group()
def cli():
    """Generic assembly CLI, wired up exactly as each assembly's main.py wires up its own."""


@cli.command("export-3mf")
@export_3mf_options(default_outdir=DEFAULT_OUTDIR)
def export_3mf_command(outdir: str, filename: str):
    """Export the assembly to a single .3mf file"""
    outpath = export_printable_3mf(_generic_assembly(), "assembly", outdir=outdir, filename=filename)
    click.echo(f"Exported whole assembly to {outpath}")


@cli.command("export-wireframe-jpg")
@export_wireframe_jpg_options(default_outdir=DEFAULT_OUTDIR)
def export_wireframe_jpg_command(outdir: str, filename: str | None, **render_opts):
    """Export the assembly to a wireframe JPG"""
    outpath = export_wireframe_jpg(
        shape=Compound(label="assembly", children=_generic_assembly()), outdir=outdir, filename=filename, **render_opts
    )
    click.echo(f"Exported wireframe JPG: {outpath}")


@cli.command("export-shaded-jpg")
@export_shaded_jpg_options(default_outdir=DEFAULT_OUTDIR)
def export_shaded_jpg_command(outdir: str, filename: str | None, **render_opts):
    """Export the assembly to a full-color shaded JPG"""
    outpath = export_shaded_jpg(
        shape=Compound(label="assembly", children=_generic_assembly()), outdir=outdir, filename=filename, **render_opts
    )
    click.echo(f"Exported shaded JPG: {outpath}")


@pytest.fixture
def runner():
    return CliRunner()


def test_export_3mf_options(runner):
    """The --outdir/--filename options default to the CLI's own output directory and
    assembly.3mf, and both are overridable."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export-3mf"])
        assert result.exit_code == 0, result.output
        assert "Exported whole assembly to" in result.output
        assert os.path.getsize(f"{DEFAULT_OUTDIR}/assembly.3mf") > 0

        result_custom = runner.invoke(cli, ["export-3mf", "--outdir", "custom_dir", "-f", "custom.3mf"])
        assert result_custom.exit_code == 0, result_custom.output
        assert os.path.getsize("custom_dir/custom.3mf") > 0


def test_export_3mf_preserves_part_names_and_colors(runner):
    """Part labels and colours survive into the exported 3MF.

    This is what makes the file usable in a slicer: each part arrives as its own named mesh
    object (a part with no label of its own inheriting its body's label), each body arrives as a
    named grouping of those parts, and parts are assigned extruder indices by colour — parts
    sharing a colour share an index, different colours get different ones.
    """
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export-3mf"])
        assert result.exit_code == 0, result.output
        path = f"{DEFAULT_OUTDIR}/assembly.3mf"

        names = _mesh_object_names(path)
        assert set(names) == {"Part One", "Part Two", "Body B"}
        assert all(name != "" for name in names)

        assert _slicer_object_config(path) == [
            ("Body A", [("Part One", "1"), ("Part Two", "2")]),
            ("Body B", [("Body B", "1")]),
        ]


def test_export_wireframe_jpg_options(runner):
    """The wireframe options default sensibly (filename derived from the shape's label) and all
    of the camera, line and scale options are accepted and passed through to the exporter."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export-wireframe-jpg"])
        assert result.exit_code == 0, result.output
        assert "Exported wireframe JPG" in result.output
        assert os.path.getsize(f"{DEFAULT_OUTDIR}/assembly.jpg") > 0

        result_custom = runner.invoke(
            cli,
            [
                "export-wireframe-jpg",
                "--outdir",
                "custom_dir",
                "-f",
                "custom.jpg",
                "--bearing",
                "150",
                "--pitch",
                "20",
                "--yaw",
                "10",
                "--distance",
                "220",
                "-l",
                "0, 0, 5",
                "--focus",
                "120.0",
                "--no-hidden",
                "--line-weight",
                "0.8",
                "--hidden-line-weight",
                "0.3",
                "--line-color",
                "blue",
                "--hidden-line-color",
                "red",
                "--scale",
                "5",
            ],
        )
        assert result_custom.exit_code == 0, result_custom.output
        assert os.path.getsize("custom_dir/custom.jpg") > 0


def test_export_shaded_jpg_options(runner):
    """The shaded options default sensibly (filename derived from the shape's label) and all of
    the camera, image size and edge options are accepted and passed through to the exporter."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export-shaded-jpg"])
        assert result.exit_code == 0, result.output
        assert "Exported shaded JPG" in result.output
        assert os.path.getsize(f"{DEFAULT_OUTDIR}/assembly.jpg") > 0

        result_custom = runner.invoke(
            cli,
            [
                "export-shaded-jpg",
                "--outdir",
                "custom_dir",
                "-f",
                "custom.jpg",
                "--bearing",
                "150",
                "--pitch",
                "20",
                "--yaw",
                "10",
                "--distance",
                "220",
                "--fov",
                "30",
                "-l",
                "0, 0, 5",
                "--width",
                "400",
                "--height",
                "300",
                "--bg-color",
                "lightgray",
                "--no-draw-edges",
                "--edge-color",
                "red",
                "--edge-width",
                "2.0",
            ],
        )
        assert result_custom.exit_code == 0, result_custom.output
        assert os.path.getsize("custom_dir/custom.jpg") > 0


@pytest.mark.parametrize("command", ["export-wireframe-jpg", "export-shaded-jpg"])
def test_look_at_rejects_malformed_vector(runner, command):
    """parse_vector, installed as a Click callback by both JPG option decorators, rejects a
    --look-at value that isn't three numbers."""
    result = runner.invoke(cli, [command, "-l", "100, 200"])
    assert result.exit_code != 0
    assert "must be three comma- or space-separated numbers" in result.output


@pytest.mark.parametrize(
    "command,option",
    [
        ("export-wireframe-jpg", "--line-color"),
        ("export-wireframe-jpg", "--hidden-line-color"),
        ("export-shaded-jpg", "--edge-color"),
        ("export-shaded-jpg", "--bg-color"),
    ],
)
def test_color_options_reject_unknown_color_names(runner, command, option):
    """parse_color, installed as a Click callback on every color option, rejects a name that
    isn't a known color."""
    result = runner.invoke(cli, [command, option, "not-a-real-color"])
    assert result.exit_code != 0
    assert "not defined as a named color" in result.output


def test_export_3mf_orients_every_body_for_printing(runner):
    """export-3mf writes a plate ready to slice, not the assembly in the pose it was modelled in.

    Orienting is the shared export path's job, not each assembly's, so this is what stops an
    assembly from exporting parts lying in whatever direction they happened to be built. "Body B"
    is modelled lying along X, 4 mm tall and floating 50 mm up, but tagged to print on its end: it
    only comes out 20 mm tall and touching the bed if the export oriented and placed it.
    """
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export-3mf"])
        assert result.exit_code == 0, result.output

        bounds = _mesh_object_bounds(f"{DEFAULT_OUTDIR}/assembly.3mf")

        (_, _, height), lowest_z = bounds["Body B"]
        assert height == pytest.approx(20.0), "the body tagged to print on its end was not stood up"
        assert lowest_z == pytest.approx(0.0), "the body was not brought down onto the bed"

        # Parts sharing a body are placed as one, keeping the 2 mm they sit apart as modelled.
        assert bounds["Part One"][1] == pytest.approx(0.0)
        assert bounds["Part Two"][1] == pytest.approx(2.0)


def test_export_3mf_leaves_out_parts_that_are_not_printed(runner):
    """Hardware and other non-printable parts never reach the plate — a screw in the exported file
    would be sliced and printed along with the bodies."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export-3mf"])
        assert result.exit_code == 0, result.output

        assert "Screw" not in _mesh_object_names(f"{DEFAULT_OUTDIR}/assembly.3mf")
