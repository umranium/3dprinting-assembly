import click
from build123d import Compound

from src.exporter import (
    export_3mf_options,
    export_printable_3mf,
    export_shaded_jpg,
    export_shaded_jpg_options,
    export_wireframe_jpg,
    export_wireframe_jpg_options,
)

from . import assembly as assembly

DEFAULT_OUTDIR = "export/box_with_lid"


@click.group()
def cli():
    """Box With Lid CLI"""
    pass


@cli.command("export-3mf")
@export_3mf_options(default_outdir=DEFAULT_OUTDIR)
def export_3mf_command(outdir: str, filename: str):
    """Export every printable part, oriented and laid out on the build plate, to a single .3mf file"""
    parts = assembly.create_assembly()
    outpath = export_printable_3mf(parts, "Box With Lid Printable Assembly", outdir=outdir, filename=filename)
    click.echo(f"Exported whole assembly to {outpath}")


@cli.command("view")
def view_command():
    """View the assembly in OCP CAD Viewer"""
    from ocp_vscode import show

    parts = assembly.create_assembly()
    show(Compound(label="Box With Lid Assembly", children=parts))


@cli.command("export-wireframe-jpg")
@export_wireframe_jpg_options(default_outdir=DEFAULT_OUTDIR)
@click.option(
    "--part",
    "-p",
    type=click.Choice(list(assembly.PART_CHOICES.keys()), case_sensitive=False),
    default="Assembly",
    help="Part or assembly to export",
)
def export_wireframe_jpg_command(part: str, outdir: str, filename: str | None, **render_opts):
    """Export a part or the assembly to a wireframe JPG"""
    parts = assembly.create_assembly()
    lookup = {k.lower(): v for k, v in assembly.PART_CHOICES.items()}
    target_labels = lookup[part.lower()]
    selected_parts = [p for p in parts if p.label in target_labels]
    shape = Compound(label=part, children=selected_parts) if len(selected_parts) > 1 else selected_parts[0]

    outpath = export_wireframe_jpg(
        shape=shape,
        outdir=outdir,
        filename=filename or f"{part.lower().replace(' ', '_')}.jpg",
        **render_opts,
    )
    click.echo(f"Exported {part} to wireframe JPG: {outpath}")


@cli.command("export-shaded-jpg")
@export_shaded_jpg_options(default_outdir=DEFAULT_OUTDIR)
@click.option(
    "--part",
    "-p",
    type=click.Choice(list(assembly.PART_CHOICES.keys()), case_sensitive=False),
    default="Assembly",
    help="Part or assembly to export",
)
def export_shaded_jpg_command(part: str, outdir: str, filename: str | None, **render_opts):
    """Export a part or the assembly to a full-color shaded 3D JPG"""
    parts = assembly.create_assembly()
    lookup = {k.lower(): v for k, v in assembly.PART_CHOICES.items()}
    target_labels = lookup[part.lower()]
    selected_parts = [p for p in parts if p.label in target_labels]
    shape = Compound(label=part, children=selected_parts) if len(selected_parts) > 1 else selected_parts[0]

    outpath = export_shaded_jpg(
        shape=shape,
        outdir=outdir,
        filename=filename or f"{part.lower().replace(' ', '_')}.jpg",
        **render_opts,
    )
    click.echo(f"Exported {part} to shaded JPG: {outpath}")


if __name__ == "__main__":
    cli()
