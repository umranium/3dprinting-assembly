import math
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Sequence, cast

import click
from build123d import Axis, Color, Compound, ExportSVG, LineType, Mesher, Part, Unit
from build123d.geometry import Vector, VectorLike
from build123d.topology.shape_core import Shape
from build123d.topology.three_d import Mixin3D
from lib3mf import Lib3MF
from OCP.AIS import AIS_DisplayMode, AIS_InteractiveContext, AIS_Shape  # type: ignore
from OCP.Aspect import Aspect_DisplayConnection, Aspect_NeutralWindow, Aspect_TypeOfLine  # type: ignore
from OCP.Graphic3d import Graphic3d_Camera, Graphic3d_MaterialAspect, Graphic3d_NameOfMaterial  # type: ignore
from OCP.OpenGl import OpenGl_GraphicDriver  # type: ignore
from OCP.Prs3d import Prs3d_LineAspect  # type: ignore
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor  # type: ignore
from OCP.V3d import V3d_Viewer  # type: ignore

from src.printer import build_print_plate


def flatten_and_label(shape: Shape, parent_label: str = "", parent_color: Color | None = None) -> list[Shape]:
    """
    Recursively traverse a build123d shape hierarchy (using .children where available
    to preserve original Python objects and attributes like .label and .color, and
    otherwise falling back to list(shape) for Compounds/Parts without explicit children).

    Assigns the parent/ancestor label and color to child shapes if they do not
    have their own set, and returns a flat list of terminal shapes (e.g. Solid).
    """
    label = shape.label if shape.label else parent_label
    color = shape.color if shape.color else parent_color

    # Check if shape has python-level children (like Compound)
    if hasattr(shape, "children") and shape.children:
        solids = []
        for child in shape.children:
            solids.extend(flatten_and_label(child, label, color))
        return solids
    # If it is a Compound but has no python-level children (e.g., a Part/Compound with underlying solids),
    # iterate over its shapes (using list(shape)) and assign the label and color to each child.
    elif isinstance(shape, Compound):
        solids = []
        for child in list(shape):
            solids.extend(flatten_and_label(child, label, color))
        return solids
    else:
        # It's a terminal shape (Solid, etc.)
        shape.label = label
        shape.color = color
        return [shape]


def export_assembly_3mf(
    assy: Compound | list[Shape] | list[Part],
    outpath: str | None = None,
    outdir: str | None = None,
    filename: str | None = None,
    linear_deflection: float = 0.001,
    angular_deflection: float = 0.1,
) -> str:
    """
    Export an assembly to a single 3MF file using build123d Mesher, ensuring
    object names (labels) and colors are correctly preserved for each mesh object.

    If the provided assembly has top-level groupings (children), they will be
    grouped into ComponentObjects in the 3MF file using lib3mf.

    Parameters:
        assy: Compound or list of shapes/parts to export.
        outpath: Full path to the output .3mf file (takes precedence over outdir/filename).
        outdir: Output directory (used when outpath is not provided).
        filename: Output filename (defaults to 'assembly.3mf' if not given).
        linear_deflection: Linear deflection for meshing.
        angular_deflection: Angular deflection for meshing.

    Returns:
        The output file path.
    """
    if isinstance(assy, list):
        assy = Compound(children=assy)

    if not outpath:
        target_name = (
            filename if filename else (f"{assy.label}.3mf" if getattr(assy, "label", None) else "assembly.3mf")
        )
        outpath = os.path.join(outdir, target_name) if outdir else target_name

    target_dir = os.path.dirname(os.path.abspath(outpath))
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    groups = []
    flat_shapes = []

    if hasattr(assy, "children") and assy.children:
        for child in assy.children:
            child_shapes = flatten_and_label(child)
            if child_shapes:
                groups.append((child.label or "Component", len(child_shapes)))
                flat_shapes.extend(child_shapes)
    else:
        flat_shapes = flatten_and_label(assy)

    mesher = Mesher(unit=Unit.MM)
    mesher.add_shape(flat_shapes, linear_deflection=linear_deflection, angular_deflection=angular_deflection)
    mesher.write(outpath)

    if len(groups) > 1:
        # We need to load the generated 3mf and rewrite it using lib3mf's ComponentsObject
        wrapper = Lib3MF.Wrapper()
        model: Any = wrapper.CreateModel()
        assert model is not None
        reader = model.QueryReader("3mf")
        assert reader is not None
        reader.ReadFromFile(outpath)

        build_items = []
        iterator = model.GetBuildItems()
        assert iterator is not None
        while iterator.MoveNext():
            build_items.append(iterator.GetCurrent())

        # Group logic
        if sum(count for _, count in groups) == len(build_items):
            new_components = []
            idx = 0
            for name, count in groups:
                comp_obj = model.AddComponentsObject()
                assert comp_obj is not None
                comp_obj.SetName(name)
                for _ in range(count):
                    item = build_items[idx]
                    comp_obj.AddComponent(item.GetObjectResource(), item.GetObjectTransform())
                    idx += 1
                new_components.append(comp_obj)

            # Clear old build items and add our new compound items
            build_item_iterator = model.GetBuildItems()
            assert build_item_iterator is not None
            old_items = []
            for _ in range(build_item_iterator.Count()):
                build_item_iterator.MoveNext()
                old_items.append(build_item_iterator.GetCurrent())
            for old_item in old_items:
                model.RemoveBuildItem(old_item)

            for comp_obj in new_components:
                model.AddBuildItem(comp_obj, wrapper.GetIdentityTransform())

            writer = model.QueryWriter("3mf")
            assert writer is not None
            writer.WriteToFile(outpath)

    # --- INJECT BAMBU STUDIO CONFIG TO PRESERVE NAMES ---
    # Bambu Studio loses names of instances in ComponentsObjects unless we inject Metadata/model_settings.config
    try:
        import zipfile

        with zipfile.ZipFile(outpath, "r") as zin:
            xml_content = zin.read("3D/3dmodel.model")

        root = ET.fromstring(xml_content)
        ns = {"ns": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}

        build = root.find("ns:build", ns)
        if build is not None:
            build_items = build.findall("ns:item", ns)
            config_root = ET.Element("config")

            unique_colors = []
            for shape in flat_shapes:
                if shape.color is not None:
                    c = shape.color.wrapped.GetRGB()  # type: ignore
                    rgba = (c.Red(), c.Green(), c.Blue())
                    if rgba not in unique_colors:
                        unique_colors.append(rgba)

            has_config = False
            flat_idx = 0
            for item in build_items:
                obj_id = item.get("objectid")
                if not obj_id:
                    continue
                obj = root.find(f".//ns:object[@id='{obj_id}']", ns)
                if obj is not None:
                    components_element = obj.find("ns:components", ns)
                    if components_element is not None:
                        has_config = True
                        cfg_obj = ET.SubElement(config_root, "object", id=str(obj_id))

                        obj_name = obj.get("name")
                        if obj_name:
                            ET.SubElement(cfg_obj, "metadata", key="name", value=str(obj_name))
                        ET.SubElement(cfg_obj, "metadata", key="extruder", value="1")

                        components = components_element.findall("ns:component", ns)
                        for comp in components:
                            comp_obj_id = comp.get("objectid")
                            if not comp_obj_id:
                                flat_idx += 1
                                continue
                            ref_obj = root.find(f".//ns:object[@id='{comp_obj_id}']", ns)
                            raw_name = ref_obj.get("name") if ref_obj is not None else None
                            name = raw_name if raw_name else f"Part {comp_obj_id}"

                            part = ET.SubElement(cfg_obj, "part", id=str(comp_obj_id), subtype="normal_part")
                            ET.SubElement(part, "metadata", key="name", value=str(name))

                            if flat_idx < len(flat_shapes):
                                shape = flat_shapes[flat_idx]
                                if shape.color is not None:
                                    c = shape.color.wrapped.GetRGB()  # type: ignore
                                    rgba = (c.Red(), c.Green(), c.Blue())
                                    extruder_idx = unique_colors.index(rgba) + 1
                                    ET.SubElement(part, "metadata", key="extruder", value=str(extruder_idx))
                            flat_idx += 1
                    else:
                        has_config = True
                        cfg_obj = ET.SubElement(config_root, "object", id=str(obj_id))

                        obj_name = obj.get("name")
                        if obj_name:
                            ET.SubElement(cfg_obj, "metadata", key="name", value=str(obj_name))

                        if flat_idx < len(flat_shapes):
                            shape = flat_shapes[flat_idx]
                            if shape.color is not None:
                                c = shape.color.wrapped.GetRGB()  # type: ignore
                                rgba = (c.Red(), c.Green(), c.Blue())
                                extruder_idx = unique_colors.index(rgba) + 1
                                ET.SubElement(cfg_obj, "metadata", key="extruder", value=str(extruder_idx))
                        flat_idx += 1

            if has_config:
                config_xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(config_root, encoding="utf-8")
                # Write to a temp file and replace
                temp_outpath = outpath + ".tmp"
                with zipfile.ZipFile(temp_outpath, "w") as zout:
                    with zipfile.ZipFile(outpath, "r") as zin:
                        for info in zin.infolist():
                            if info.filename != "Metadata/model_settings.config":
                                zout.writestr(info, zin.read(info.filename))
                    zout.writestr("Metadata/model_settings.config", config_xml)
                os.replace(temp_outpath, outpath)
    except Exception as e:
        print(f"Warning: Failed to inject model_settings.config: {e}")

    return outpath


export_3mf = export_assembly_3mf


def export_printable_3mf(
    parts: Sequence[Part | Compound],
    label: str,
    outpath: str | None = None,
    outdir: str | None = None,
    filename: str | None = None,
) -> str:
    """Export an assembly's printable parts, oriented and laid out on the build plate, to a .3mf
    file. This is what every assembly's export-3mf command calls: it takes the raw parts straight
    from create_assembly() and does the orienting itself (see src.printer.build_print_plate), so
    that orienting for printing cannot be forgotten by an assembly or done differently by each
    one. export_assembly_3mf() below it stays the plain "write this shape out" primitive.
    """
    return export_assembly_3mf(build_print_plate(parts, label), outpath=outpath, outdir=outdir, filename=filename)


def part_choices(part_names: set[str]) -> dict[str, set[str]]:
    """Build the standard choices for a CLI's -p/--part selector: the whole assembly plus each
    part individually selectable by its own name."""
    return {"Assembly": part_names, **{name: {name} for name in part_names}}


def parse_vector(ctx: Any, param: Any, value: Any) -> tuple[float, float, float] | None:
    """Click parameter callback to parse 3D coordinates from comma- or space-separated strings."""
    if value is None or value == "":
        return None
    try:
        vals = [float(x) for x in value.replace(",", " ").split()]
        if len(vals) != 3:
            raise ValueError()
        return (vals[0], vals[1], vals[2])
    except Exception:
        name = getattr(param, "name", "parameter")
        raise click.BadParameter(f"{name} must be three comma- or space-separated numbers, e.g., '100,200,300'")


def parse_color(ctx: Any, param: Any, value: Any) -> Color | None:
    """Click parameter callback to parse a color name or hex into a build123d Color object."""
    if value is None:
        return None
    if isinstance(value, Color):
        return value
    try:
        return Color(value)
    except ValueError as e:
        raise click.BadParameter(str(e))


# Elevation angle of a classic isometric view (asin(1/sqrt(3))), used as the default pitch.
ISOMETRIC_PITCH_DEG = math.degrees(math.asin(1 / math.sqrt(3)))


def spherical_camera_vectors(bearing: float, pitch: float, yaw: float) -> tuple[Vector, Vector]:
    """
    Convert bearing/pitch/yaw (degrees) into a (direction, up) pair, in the shape's natural
    Z-up world coordinates, describing where the camera sits and how it's oriented relative to
    whatever point it's looking at.

    `direction` points from the look-at point toward the camera: `bearing` is the horizontal
    angle from +Y, increasing clockwise when viewed from above (bearing=0 -> +Y, bearing=90 ->
    +X); `pitch` is the elevation angle above the horizontal plane (pitch=0 -> camera level with
    the target, pitch=90 -> camera directly above looking straight down, pitch=-90 -> directly
    below looking straight up).

    `up` is derived by keeping the horizon level (the component of world +Z perpendicular to
    `direction`), then rolling it around the `direction` axis by `yaw` degrees (yaw=0 keeps the
    horizon level; positive yaw rolls the camera clockwise as seen from its own viewpoint). Near
    straight-down/up views, where world +Z is parallel to `direction` and "level" is undefined,
    the bearing's horizontal direction is used as the fallback reference instead.
    """
    bearing_rad = math.radians(bearing)
    pitch_rad = math.radians(pitch)
    horizontal = math.cos(pitch_rad)
    direction = Vector(
        horizontal * math.sin(bearing_rad),
        horizontal * math.cos(bearing_rad),
        math.sin(pitch_rad),
    ).normalized()

    world_up = Vector(0, 0, 1)
    level_up = world_up - direction * world_up.dot(direction)
    if level_up.length < 1e-9:
        level_up = Vector(math.sin(bearing_rad), math.cos(bearing_rad), 0)
    level_up = level_up.normalized()

    yaw_rad = math.radians(yaw)
    cos_y, sin_y = math.cos(yaw_rad), math.sin(yaw_rad)
    # Rodrigues' rotation formula: rotate level_up around the direction axis by yaw.
    up = (
        level_up * cos_y + direction.cross(level_up) * sin_y + direction * direction.dot(level_up) * (1 - cos_y)
    ).normalized()

    return direction, up


def export_wireframe_jpg(
    shape: Shape | Mixin3D | Compound,
    outpath: str | None = None,
    outdir: str | None = None,
    filename: str | None = None,
    look_at: VectorLike | None = None,
    bearing: float = 45.0,
    pitch: float = ISOMETRIC_PITCH_DEG,
    yaw: float = 0.0,
    distance: float = 500.0,
    focus: float = 300.0,
    show_hidden: bool = True,
    line_weight: float = 0.5,
    hidden_line_weight: float = 0.2,
    line_color: Color | str = "black",
    hidden_line_color: Color | str = "gray",
    scale: float = 10.0,
    rotate_z_to_y: bool = True,
) -> str:
    """
    Export a build123d shape to a wireframe JPG file via SVG projection and sips conversion.

    Always uses a perspective projection; framing is controlled entirely by `bearing`/`pitch`,
    `distance`, and `focus` — move the camera closer/farther (`distance`) or change the
    perspective distortion (`focus`) to change what fills the frame.

    Parameters:
        shape: build123d Shape/Compound to render.
        outpath: Complete output file path for the JPG image (takes precedence over outdir/filename).
        outdir: Output directory for the JPG file (used when outpath is not provided).
        filename: Output filename (defaults to '<shape_label>.jpg' or 'shape.jpg' if not given).
        look_at: Target point to look at, in the shape's natural (unrotated) world coordinates
            (defaults to shape center).
        bearing: Horizontal angle (degrees) from +Y to where the camera sits relative to
            `look_at`, increasing clockwise viewed from above (0 -> +Y, 90 -> +X).
        pitch: Elevation angle (degrees) of the camera above the horizontal plane through
            `look_at` (0 -> level with the target, 90 -> directly above looking straight down,
            -90 -> directly below looking straight up).
        yaw: Roll (degrees) of the camera around its own viewing axis, relative to a level
            horizon (0 -> level; positive rolls clockwise as seen from the camera).
        distance: Distance from `look_at` to place the camera, in the direction given by
            `bearing`/`pitch`.
        focus: Focal length for the perspective projection (smaller values are more wide-angle/
            distorted, larger values are flatter/more telephoto-like).
        show_hidden: Whether to render hidden lines as dashed lines.
        line_weight: Visible line width in mm.
        hidden_line_weight: Hidden line width in mm.
        line_color: Color of visible lines (Color instance or name/hex string).
        hidden_line_color: Color of hidden lines (Color instance or name/hex string).
        scale: SVG export scale factor.
        rotate_z_to_y: If True, rotate the Z-up shape to Y-up orientation (-90 deg around X axis) before projection.

    Returns:
        The output file path.
    """
    if isinstance(shape, list):
        shape = Compound(children=shape)

    if not outpath:
        target_name = filename if filename else (f"{shape.label}.jpg" if getattr(shape, "label", None) else "shape.jpg")
        outpath = os.path.join(outdir, target_name) if outdir else target_name

    target_dir = os.path.dirname(os.path.abspath(outpath))
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    dir_vec, up_vec = spherical_camera_vectors(bearing, pitch, yaw)
    target_point = Vector(look_at) if look_at is not None else cast(Any, shape).center()
    eye_point = target_point + dir_vec * distance

    target_shape: Any = shape.rotate(Axis.X, -90) if rotate_z_to_y else shape

    if rotate_z_to_y:
        # project_to_viewport operates on target_shape, which is already rotated -90deg about
        # X. Apply the same rotation to the eye/target/up vectors so callers can keep specifying
        # them in the shape's natural (unrotated) world coordinates.
        eye_point = eye_point.rotate(Axis.X, -90)
        target_point = target_point.rotate(Axis.X, -90)
        up_vec = up_vec.rotate(Axis.X, -90)

    visible, hidden = target_shape.project_to_viewport(
        viewport_origin=eye_point,
        viewport_up=up_vec,
        look_at=target_point,
        focus=focus,
    )

    exporter = ExportSVG(scale=scale)

    c_line = line_color if isinstance(line_color, Color) else Color(line_color)
    c_hidden = hidden_line_color if isinstance(hidden_line_color, Color) else Color(hidden_line_color)

    exporter.add_layer(
        "visible",
        line_color=c_line,
        line_weight=line_weight,
        line_type=LineType.CONTINUOUS,
    )
    exporter.add_shape(visible, layer="visible")

    if show_hidden and len(hidden) > 0:
        exporter.add_layer(
            "hidden",
            line_color=c_hidden,
            line_weight=hidden_line_weight,
            line_type=LineType.HIDDEN,
        )
        exporter.add_shape(hidden, layer="hidden")

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
        svg_path = tf.name

    try:
        exporter.write(svg_path)
        subprocess.run(
            ["sips", "-s", "format", "jpeg", svg_path, "--out", outpath],
            check=True,
            capture_output=True,
        )
    finally:
        if os.path.exists(svg_path):
            os.remove(svg_path)

    return outpath


# Backward compatibility aliases
export_shape_jpg = export_wireframe_jpg
export_jpg = export_wireframe_jpg


def export_shaded_jpg(
    shape: Shape | Mixin3D | Compound | list[Shape],
    outpath: str | None = None,
    outdir: str | None = None,
    filename: str | None = None,
    look_at: VectorLike | None = None,
    bearing: float = 45.0,
    pitch: float = ISOMETRIC_PITCH_DEG,
    yaw: float = 0.0,
    distance: float = 500.0,
    fov: float = 45.0,
    width: int = 1200,
    height: int = 1200,
    background_color: Color | str = "white",
    bg_color: Color | str | None = None,
    draw_edges: bool = True,
    edge_color: Color | str = "black",
    edge_width: float = 1.5,
) -> str:
    """
    Export a build123d shape or assembly to a full-color shaded 3D JPG using
    OpenCASCADE's headless offscreen OpenGL renderer.

    Always uses a perspective projection; framing is controlled entirely by `bearing`/`pitch`,
    `distance`, and `fov` — move the camera closer/farther (`distance`) or widen/narrow the
    lens (`fov`) to change what fills the frame.

    Parameters:
        shape: build123d Shape, Compound, or list of shapes to render.
        outpath: Complete output file path for the JPG image (takes precedence over outdir/filename).
        outdir: Output directory for the JPG file (used when outpath is not provided).
        filename: Output filename (defaults to '<shape_label>.jpg' or 'shape.jpg' if not given).
        look_at: Target point to look at (defaults to shape center).
        bearing: Horizontal angle (degrees) from +Y to where the camera sits relative to
            `look_at`, increasing clockwise viewed from above (0 -> +Y, 90 -> +X).
        pitch: Elevation angle (degrees) of the camera above the horizontal plane through
            `look_at` (0 -> level with the target, 90 -> directly above looking straight down,
            -90 -> directly below looking straight up).
        yaw: Roll (degrees) of the camera around its own viewing axis, relative to a level
            horizon (0 -> level; positive rolls clockwise as seen from the camera).
        distance: Distance from `look_at` to place the camera, in the direction given by
            `bearing`/`pitch`. Moving the camera closer/farther changes how much of the frame
            the shape fills, same as a real camera.
        fov: Vertical field of view in degrees for the perspective camera. Unlike the wireframe
            exporter's `focus` (a build123d/HLR focal-length-style value), this is a plain FOV
            angle passed to OCCT's Graphic3d_Camera — the two are not directly comparable.
        width: Output image width in pixels.
        height: Output image height in pixels.
        background_color: Canvas background color.
        draw_edges: Whether to render crisp face boundary edge contours on top of shaded faces.
        edge_color: Color of face boundary edge lines.
        edge_width: Width of face boundary edge lines.

    Returns:
        The output file path.
    """
    if isinstance(shape, list):
        shape = Compound(children=shape)

    if not outpath:
        target_name = filename if filename else (f"{shape.label}.jpg" if getattr(shape, "label", None) else "shape.jpg")
        outpath = os.path.join(outdir, target_name) if outdir else target_name

    target_dir = os.path.dirname(os.path.abspath(outpath))
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    flat_shapes = flatten_and_label(shape)

    disp = Aspect_DisplayConnection()
    driver = OpenGl_GraphicDriver(disp, False)
    viewer = V3d_Viewer(driver)
    viewer.SetDefaultLights()
    viewer.SetLightOn()

    context = AIS_InteractiveContext(viewer)
    context.SetDisplayMode(AIS_DisplayMode.AIS_Shaded, False)

    for solid in flat_shapes:
        if solid.wrapped is None:
            continue
        ais = AIS_Shape(solid.wrapped)
        ais.SetDisplayMode(AIS_DisplayMode.AIS_Shaded)
        ais.SetMaterial(Graphic3d_MaterialAspect(Graphic3d_NameOfMaterial.Graphic3d_NOM_PLASTIC))

        if draw_edges:
            drawer = ais.Attributes()
            drawer.SetFaceBoundaryDraw(True)
            ec = edge_color if isinstance(edge_color, Color) else Color(edge_color)
            if ec.wrapped is not None:
                ergb = ec.wrapped.GetRGB()
                line_aspect = Prs3d_LineAspect(
                    Quantity_Color(ergb.Red(), ergb.Green(), ergb.Blue(), Quantity_TypeOfColor.Quantity_TOC_RGB),
                    Aspect_TypeOfLine.Aspect_TOL_SOLID,
                    edge_width,
                )
                drawer.SetFaceBoundaryAspect(line_aspect)

        c = solid.color if solid.color else Color("gray")
        if c.wrapped is not None:
            ais.SetColor(c.wrapped.GetRGB())
            if c.wrapped.Alpha() < 1.0:
                ais.SetTransparency(1.0 - c.wrapped.Alpha())
        context.Display(ais, False)

    context.UpdateCurrentViewer()

    view = viewer.CreateView()
    win = Aspect_NeutralWindow()
    win.SetSize(width, height)
    view.SetWindow(win)

    effective_bg = bg_color if bg_color is not None else background_color
    bg = effective_bg if isinstance(effective_bg, Color) else Color(effective_bg)
    if bg.wrapped is not None:
        bgrgb = bg.wrapped.GetRGB()
        view.SetBackgroundColor(
            Quantity_Color(bgrgb.Red(), bgrgb.Green(), bgrgb.Blue(), Quantity_TypeOfColor.Quantity_TOC_RGB)
        )
    view.MustBeResized()

    camera = view.Camera()
    camera.SetProjectionType(Graphic3d_Camera.Projection_Perspective)
    camera.SetFOVy(fov)

    dir_vec, up_vec = spherical_camera_vectors(bearing, pitch, yaw)
    target_point = Vector(look_at) if look_at is not None else cast(Any, shape).center()
    eye_point = target_point + dir_vec * distance

    view.SetEye(float(eye_point.X), float(eye_point.Y), float(eye_point.Z))
    view.SetAt(float(target_point.X), float(target_point.Y), float(target_point.Z))
    view.SetUp(float(up_vec.X), float(up_vec.Y), float(up_vec.Z))

    # Deliberately no FitAll(): for a perspective camera, FitAll() recomputes magnification to
    # make the shape fit the frame regardless of Eye position, which would silently cancel out
    # `distance` entirely. `distance` is a real physical camera placement, like a real camera's
    # position — moving it changes how much of the frame the shape fills, with no auto-fit step
    # to undo that.
    view.Dump(outpath)
    return outpath


def export_wireframe_jpg_options(default_outdir: str | None = None):
    """
    Click composite decorator that applies standard wireframe JPG export CLI options
    (--outdir, --filename, --bearing, --pitch, --yaw, --distance, --look-at, --focus,
    --show-hidden, --line-weight, --hidden-line-weight, --line-color, --hidden-line-color,
    --scale).
    """

    def decorator(f: Any) -> Any:
        options = [
            click.option("--scale", type=float, default=10.0, help="SVG scaling factor"),
            click.option("--hidden-line-color", default="gray", callback=parse_color, help="Color of hidden lines"),
            click.option("--line-color", default="black", callback=parse_color, help="Color of visible lines"),
            click.option("--hidden-line-weight", type=float, default=0.2, help="Weight of hidden lines in mm"),
            click.option("--line-weight", type=float, default=0.5, help="Weight of visible lines in mm"),
            click.option("--show-hidden/--no-hidden", default=True, help="Render hidden lines as dashed lines"),
            click.option(
                "--focus",
                type=float,
                default=300.0,
                help="Focal length for the perspective projection (smaller = more wide-angle/distorted)",
            ),
            click.option(
                "--look-at",
                "-l",
                default=None,
                callback=parse_vector,
                help='Target point to look at as "X,Y,Z" (defaults to shape center)',
            ),
            click.option(
                "--yaw",
                type=float,
                default=0.0,
                help="Camera roll in degrees around its own viewing axis (0 = level horizon)",
            ),
            click.option(
                "--pitch",
                type=float,
                default=ISOMETRIC_PITCH_DEG,
                help="Camera elevation in degrees (90 = straight down, -90 = straight up),",
            ),
            click.option(
                "--bearing",
                type=float,
                default=45.0,
                help="Horizontal angle in degrees from +Y to the camera, clockwise from above (0 = +Y, 90 = +X)",
            ),
            click.option("--distance", type=float, default=500.0, help="Distance from --look-at to place the camera"),
            click.option("--filename", "-f", default=None, help="Output filename (defaults to <part>.jpg)"),
            click.option("--outdir", default=default_outdir, help="Output directory"),
        ]
        for opt in options:
            f = opt(f)
        return f

    return decorator


export_jpg_options = export_wireframe_jpg_options


def export_shaded_jpg_options(default_outdir: str | None = None):
    """
    Click composite decorator for standard shaded JPG export CLI options
    (--outdir, --filename, --bearing, --pitch, --yaw, --distance, --fov, --look-at, --width,
     --height, --bg-color, --draw-edges/--no-draw-edges, --edge-color, --edge-width).
    """

    def decorator(f: Any) -> Any:
        options = [
            click.option(
                "--fov",
                type=float,
                default=45.0,
                help="Vertical field of view in degrees for the perspective camera",
            ),
            click.option("--edge-width", type=float, default=1.5, help="Width of face boundary edge lines"),
            click.option(
                "--edge-color", default="black", callback=parse_color, help="Color of face boundary edge lines"
            ),
            click.option(
                "--draw-edges/--no-draw-edges", default=True, help="Draw face boundary edge lines on shaded surfaces"
            ),
            click.option(
                "--background-color",
                "--bg-color",
                "background_color",
                default="white",
                callback=parse_color,
                help="Background color",
            ),
            click.option("--height", type=int, default=1200, help="Output image height in pixels"),
            click.option("--width", type=int, default=1200, help="Output image width in pixels"),
            click.option(
                "--look-at",
                "-l",
                default=None,
                callback=parse_vector,
                help='Target point to look at as "X,Y,Z" (defaults to shape center)',
            ),
            click.option(
                "--yaw",
                type=float,
                default=0.0,
                help="Camera roll in degrees around its own viewing axis (0 = level horizon)",
            ),
            click.option(
                "--pitch",
                type=float,
                default=ISOMETRIC_PITCH_DEG,
                help="Camera elevation in degrees (90 = straight down, -90 = straight up),",
            ),
            click.option(
                "--bearing",
                type=float,
                default=45.0,
                help="Horizontal angle in degrees from +Y to the camera, clockwise from above (0 = +Y, 90 = +X)",
            ),
            click.option("--distance", type=float, default=500.0, help="Distance from --look-at to place the camera"),
            click.option("--filename", "-f", default=None, help="Output filename (defaults to <part>.jpg)"),
            click.option("--outdir", default=default_outdir, help="Output directory"),
        ]
        for opt in options:
            f = opt(f)
        return f

    return decorator


def export_3mf_options(default_outdir: str | None = None):
    """
    Click composite decorator that applies standard 3MF export CLI options
    (--outdir, --filename).
    """

    def decorator(f: Any) -> Any:
        options = [
            click.option("--filename", "-f", default="assembly.3mf", help="Output filename"),
            click.option("--outdir", default=default_outdir, help="Output directory"),
        ]
        for opt in options:
            f = opt(f)
        return f

    return decorator
