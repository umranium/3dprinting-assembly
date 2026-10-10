import os
import tempfile

import click
import pytest
from build123d import Box, Color, Compound

from src.exporter import (
    export_jpg,
    export_shaded_jpg,
    export_shape_jpg,
    export_wireframe_jpg,
    parse_color,
    parse_vector,
)


def test_parse_vector():
    class DummyParam:
        name = "test_vec"

    param = DummyParam()

    assert parse_vector(None, param, None) is None
    assert parse_vector(None, param, "") is None
    assert parse_vector(None, param, "100, 200, 300") == (100.0, 200.0, 300.0)
    assert parse_vector(None, param, "100 200 300") == (100.0, 200.0, 300.0)

    with pytest.raises(click.BadParameter):
        parse_vector(None, param, "100, 200")

    with pytest.raises(click.BadParameter):
        parse_vector(None, param, "abc, def, ghi")


def test_parse_color():
    class DummyParam:
        name = "test_color"

    param = DummyParam()

    assert parse_color(None, param, None) is None
    c = Color("red")
    assert parse_color(None, param, c) == c
    assert isinstance(parse_color(None, param, "blue"), Color)

    with pytest.raises(click.BadParameter):
        parse_color(None, param, "invalid-non-existent-color-name")


def test_export_wireframe_jpg_default_and_custom_options():
    box = Box(10, 20, 30)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Default options
        out1 = os.path.join(tmpdir, "box_default.jpg")
        result1 = export_wireframe_jpg(box, out1)
        assert result1 == out1
        assert os.path.exists(out1)
        assert os.path.getsize(out1) > 0

        # Custom options with export_jpg alias
        out2 = os.path.join(tmpdir, "subdir", "box_custom.jpg")
        result2 = export_jpg(
            box,
            outpath=out2,
            bearing=30.0,
            pitch=20.0,
            yaw=10.0,
            distance=300.0,
            look_at=(0, 0, 0),
            focus=100.0,
            show_hidden=False,
            line_weight=0.8,
            line_color="blue",
            scale=1.5,
            rotate_z_to_y=False,
        )
        assert result2 == out2
        assert os.path.exists(out2)
        assert os.path.getsize(out2) > 0

        # outdir and filename options
        box.label = "LabeledBox"
        result3 = export_shape_jpg(box, outdir=os.path.join(tmpdir, "nested_dir"))
        expected_out3 = os.path.join(tmpdir, "nested_dir", "LabeledBox.jpg")
        assert result3 == expected_out3
        assert os.path.exists(expected_out3)
        assert os.path.getsize(expected_out3) > 0

        result4 = export_wireframe_jpg(box, outdir=os.path.join(tmpdir, "nested_dir2"), filename="custom_name.jpg")
        expected_out4 = os.path.join(tmpdir, "nested_dir2", "custom_name.jpg")
        assert result4 == expected_out4
        assert os.path.exists(expected_out4)
        assert os.path.getsize(expected_out4) > 0


def test_export_shaded_jpg_default_and_custom_options():
    box = Box(10, 20, 30)
    box.color = Color("cyan")
    box.label = "ShadedBox"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Default options
        out1 = os.path.join(tmpdir, "shaded_default.jpg")
        result1 = export_shaded_jpg(box, out1)
        assert result1 == out1
        assert os.path.exists(out1)
        assert os.path.getsize(out1) > 0

        # Custom options
        out2 = os.path.join(tmpdir, "subdir", "shaded_custom.jpg")
        result2 = export_shaded_jpg(
            box,
            outpath=out2,
            bearing=30.0,
            pitch=20.0,
            yaw=10.0,
            distance=300.0,
            look_at=(0, 0, 0),
            width=800,
            height=600,
            background_color="lightgray",
            draw_edges=True,
            edge_color="red",
            edge_width=2.0,
        )
        assert result2 == out2
        assert os.path.exists(out2)
        assert os.path.getsize(out2) > 0

        # outdir and filename options
        result3 = export_shaded_jpg(box, outdir=os.path.join(tmpdir, "nested_dir"))
        expected_out3 = os.path.join(tmpdir, "nested_dir", "ShadedBox.jpg")
        assert result3 == expected_out3
        assert os.path.exists(expected_out3)
        assert os.path.getsize(expected_out3) > 0


def test_export_assembly_3mf_options():
    from src.exporter import export_3mf, export_assembly_3mf

    box = Box(10, 20, 30)
    box.label = "PartA"
    assy = Compound(children=[box])

    with tempfile.TemporaryDirectory() as tmpdir:
        # Full outpath
        out1 = os.path.join(tmpdir, "assy1.3mf")
        res1 = export_assembly_3mf(assy, outpath=out1)
        assert res1 == out1
        assert os.path.exists(out1)
        assert os.path.getsize(out1) > 0

        # outdir + filename
        res2 = export_3mf(assy, outdir=os.path.join(tmpdir, "sub"), filename="custom.3mf")
        expected_out2 = os.path.join(tmpdir, "sub", "custom.3mf")
        assert res2 == expected_out2
        assert os.path.exists(expected_out2)
        assert os.path.getsize(expected_out2) > 0
