"""Geometry regression snapshots, backed by GitHub Releases rather than any file committed to
the repo. Each printable body's exact shape (see src.printer.group_by_body) is compared against
a baseline stored as a gzip-compressed BREP file (exact B-Rep, not a mesh) attached to the
latest GitHub release, via a boolean intersection volume -- so shape changes are caught exactly
rather than via mesh/tessellation tolerance (which would be flaky), and bodies are compared in
their natural/local frame (before src.printer.orient_for_printing), so a change to
print-orientation logic alone can never cause a spurious mismatch.

Each body's touching parts are first fused (see _fuse_body()) into the single solid that body
actually becomes once printed -- a body is the printed artifact, not the loose collection of
logical parts it was modelled from, so that fused solid is what's worth snapshotting.

Equality is then checked via intersection, not a symmetric-difference cut: two shapes are
identical iff `intersect(current, baseline).volume` equals both `current.volume` and
`baseline.volume` (if their overlap equals both operands' full volume, they must be the same set
of points) -- the same reasoning tests/collisions.py already uses to detect overlap between
parts, just applied to detect equality instead of collision.

A `current.cut(baseline)`-style symmetric difference was tried first and rejected: OCCT's
boolean cut solver hangs indefinitely (confirmed reproducible, not merely slow) when diffing a
Compound of several touching solids against a shifted copy of itself, once the shift exceeds
~0.02mm. `.intersect()` does not hit this -- the exact same cases that hung complete in under a
second.

IMPORTANT -- fused and un-fused baselines must never be mixed. Intersecting a fused solid
against an *un-fused* Compound of the same geometry silently returns a badly wrong overlap
volume (measured: ~176mm^3 where ~5865mm^3 is correct) rather than failing loudly, while
fused-vs-fused and unfused-vs-unfused both give the correct answer. Publishing and checking
therefore both go through _fuse_body(), and a baseline published before fusing was introduced
must be republished (./run-publish-snapshot.sh) rather than compared against.

To accept an intentional geometry change: run `./run-publish-snapshot.sh` to build every
assembly fresh and publish a new dated GitHub release (bundling each assembly's assembly.3mf,
assembly.jpg, and one .brep.gz per printable body) marked "latest", then commit as normal --
by the time you commit, `./run-tests.sh`'s snapshot check already matches the new baseline. Set
SKIP_GEOMETRY_SNAPSHOT=1 to bypass the check for one run without publishing, if you know a change
is intentional but haven't published a new baseline yet.

If no release exists yet, or `gh` isn't installed/authenticated, or the network is unreachable,
the check is skipped (not failed) with a printed notice -- this is a best-effort safety net, not
a hard gate on infrastructure health.
"""

import argparse
import datetime
import gzip
import importlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from build123d import Compound, Part, ShapeList, export_brep, export_stl, import_brep

from src.printer import group_by_body

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO_ROOT / ".cache" / "geometry_snapshot"

# build123d's export_brep/import_brep round-trip preserves volume to ~1e-11 relative error in
# practice (a plain re-export/re-import of an unchanged shape), while a genuine geometry
# difference measures order-1 relative volume difference. 1e-9 leaves ~100x margin over measured
# roundtrip noise while staying many orders of magnitude below any real change.
ABS_TOLERANCE_MM3 = 1e-6
REL_TOLERANCE = 1e-9


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def is_skip_mode() -> bool:
    """True if SKIP_GEOMETRY_SNAPSHOT is set to anything other than unset/empty/"0" -- an
    explicit escape hatch for an intentional change that hasn't been published as a new baseline
    yet (see publish_release()/run-publish-snapshot.sh), so it doesn't block a commit."""
    return os.environ.get("SKIP_GEOMETRY_SNAPSHOT", "") not in ("", "0")


def latest_release_tag() -> str | None:
    """The tag name of the GitHub release currently marked "latest", or None if there is no
    release yet, gh isn't authenticated, or the repo/network is unreachable."""
    result = _run(["gh", "release", "view", "--json", "tagName", "-q", ".tagName"])
    if result.returncode != 0:
        return None
    tag = result.stdout.strip()
    return tag or None


def _safe_name(body_name: str) -> str:
    """Sanitize a body name (e.g. "Back Insert") into a filename-safe fragment we control
    end-to-end. GitHub silently rewrites spaces in uploaded asset filenames (e.g. to dots),
    so relying on a body name round-tripping unchanged through a release asset filename would
    desync the publish side from the check/download side; sanitizing before upload avoids
    GitHub touching our filenames at all."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", body_name)


def _baseline_cache_dir(assembly_name: str, tag: str) -> Path:
    return CACHE_DIR / tag / assembly_name


def download_baseline(assembly_name: str, tag: str) -> Path:
    """Local directory containing this assembly's {assembly}__{body}.brep.gz baseline files for
    `tag`, downloading (once) and caching them under .cache/geometry_snapshot/ if not already
    present. Downloads land in a fresh temp dir first and are moved into place with a single
    rename, so concurrent test workers racing to populate the same cache entry can't observe a
    partially-written directory."""
    final_dir = _baseline_cache_dir(assembly_name, tag)
    if final_dir.exists():
        return final_dir

    tmp = Path(tempfile.mkdtemp(prefix="geometry_snapshot_dl_"))
    try:
        result = _run(
            [
                "gh",
                "release",
                "download",
                tag,
                "--pattern",
                f"{assembly_name}__*.brep.gz",
                "--dir",
                str(tmp),
                "--skip-existing",
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"failed to download {assembly_name!r} baseline from release {tag!r}: {result.stderr}")

        final_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(tmp, final_dir)
        except OSError:
            # Another worker won the race and already populated final_dir; that's fine.
            if not final_dir.exists():
                raise
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final_dir


def _load_baseline_body(cache_dir: Path, assembly_name: str, safe_body_name: str) -> Compound | None:
    """`safe_body_name` must already be sanitized via _safe_name() -- see that function's
    docstring for why we never try to recover the original body name from a downloaded
    filename."""
    gz_path = cache_dir / f"{assembly_name}__{safe_body_name}.brep.gz"
    if not gz_path.exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        brep_path = Path(tmp) / f"{safe_body_name}.brep"
        with gzip.open(gz_path, "rb") as src, open(brep_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return cast(Compound, import_brep(brep_path))


def _tolerance(volume_a: float, volume_b: float) -> float:
    return max(ABS_TOLERANCE_MM3, REL_TOLERANCE * max(volume_a, volume_b))


def _fuse_body(body_parts: list[Part | Compound]) -> Compound:
    """Fuse a printable body's individual touching parts (see src.printer.group_by_body) into the
    single solid it becomes once printed. Every comparison -- and every published baseline -- goes
    through this, so both sides of an intersect() are always fused; see the module docstring for
    why mixing a fused shape with an un-fused one silently produces a wrong overlap volume."""
    if len(body_parts) == 1:
        return Compound(children=body_parts)
    fused = body_parts[0].fuse(*body_parts[1:])
    return fused if isinstance(fused, Compound) else Compound(children=[fused])


def _overlap_volume(a: Compound, b: Compound) -> float:
    """Volume of a.intersect(b), normalized to a plain float -- intersect() (unlike fuse()/cut())
    can return a ShapeList of disjoint pieces instead of a single Shape."""
    overlap = a.intersect(b)
    if overlap is None:
        return 0.0
    if isinstance(overlap, ShapeList):
        return sum(s.volume for s in overlap)
    return overlap.volume


def _baseline_safe_names(cache_dir: Path, assembly_name: str) -> set[str]:
    prefix = f"{assembly_name}__"
    return {p.name.removeprefix(prefix).removesuffix(".brep.gz") for p in cache_dir.glob(f"{prefix}*.brep.gz")}


def check_body_set(assembly_name: str, body_names: list[str], tag: str) -> list[str]:
    """Compare the assembly's current set of printable bodies against the set that has a baseline
    in release `tag`.

    This is the assembly-level half of the snapshot check, and it cannot be pushed down to a
    per-body test: a body that has been deleted from the model produces no test to run, so
    nothing would notice it had gone. Same shape as check_assembly_set, one level down.

    Returns a failure description per body missing a baseline or left over from one, or [] if the
    two sets agree.
    """
    cache_dir = download_baseline(assembly_name, tag)
    # Bodies are matched by their sanitized filename fragment (see _safe_name), not their raw
    # name, since GitHub rewrites raw filenames containing spaces on upload.
    current_by_safe_name = {_safe_name(name): name for name in body_names}
    baseline_safe_names = _baseline_safe_names(cache_dir, assembly_name)

    failures: list[str] = []
    missing = sorted(current_by_safe_name[s] for s in set(current_by_safe_name) - baseline_safe_names)
    extra = sorted(baseline_safe_names - set(current_by_safe_name))
    if missing:
        failures.append(
            f"{missing} have no baseline in release {tag!r} -- run ./run-publish-snapshot.sh to publish one"
        )
    if extra:
        failures.append(
            f"{extra} have a baseline in release {tag!r} but no matching body in the current assembly -- "
            + "run ./run-publish-snapshot.sh to publish an updated release, or restore the body if unintended"
        )
    return failures


def check_body_geometry(assembly_name: str, body_name: str, body_parts: list[Part | Compound], tag: str) -> list[str]:
    """Compare one printable body's exact geometry against its baseline in release `tag`.

    A body with no baseline at all is not a failure here — check_body_set is what reports the two
    sets disagreeing, and reporting it in both places would fail two tests for one cause.

    Returns a failure description if the geometry differs, or [] if it matches (or has no
    baseline to compare against).
    """
    cache_dir = download_baseline(assembly_name, tag)
    baseline = _load_baseline_body(cache_dir, assembly_name, _safe_name(body_name))
    if baseline is None:
        return []

    current = _fuse_body(body_parts)
    overlap_volume = _overlap_volume(current, baseline)
    tolerance = _tolerance(baseline.volume, current.volume)
    current_gap = current.volume - overlap_volume
    baseline_gap = baseline.volume - overlap_volume
    if current_gap > tolerance or baseline_gap > tolerance:
        return [
            f"{body_name!r} geometry differs from release {tag!r}'s baseline: overlap volume "
            + f"{overlap_volume:.6g} mm^3 vs current {current.volume:.3f} mm^3 (gap {current_gap:.6g}) and "
            + f"baseline {baseline.volume:.3f} mm^3 (gap {baseline_gap:.6g}), tolerance {tolerance:.3g} mm^3 -- "
            + "if intentional, run ./run-publish-snapshot.sh"
        ]
    return []


def check_assembly_set(assembly_names: list[str], tag: str) -> list[str]:
    """Compare the current set of assemblies discovered under src/ against the set of assemblies
    covered by release `tag`'s assets (derived from each asset's "{assembly}__..." filename
    prefix -- see _safe_name()/publish_release()). Returns a failure description if they differ,
    or [] if they match or the release's assets can't be listed. Whether there is a release to
    compare against at all is resolved once by the snapshot_tag fixture (see tests/conftest.py),
    not here."""
    result = _run(["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"])
    if result.returncode != 0:
        print(f"[geometry_snapshot] failed to list release {tag!r} assets, skipping assembly-set check")
        return []

    released_names = {line.split("__", 1)[0] for line in result.stdout.splitlines() if "__" in line}
    current_names = set(assembly_names)

    failures: list[str] = []
    missing = sorted(current_names - released_names)
    extra = sorted(released_names - current_names)
    if missing:
        failures.append(
            f"{missing} have no baseline at all in release {tag!r} -- run ./run-publish-snapshot.sh to publish one"
        )
    if extra:
        failures.append(
            f"{extra} have a baseline in release {tag!r} but no longer exist under src/ -- "
            + "run ./run-publish-snapshot.sh to publish an updated release, or restore the assembly if unintended"
        )
    return failures


# --- Publishing (the accept/update action) ---------------------------------------------------


def _next_available_tag() -> str:
    date_str = datetime.date.today().isoformat()
    result = _run(["gh", "release", "list", "--json", "tagName", "-q", ".[].tagName"])
    existing = (
        {line.strip() for line in result.stdout.splitlines() if line.strip()} if result.returncode == 0 else set()
    )
    if date_str not in existing:
        return date_str
    suffix = 2
    while f"{date_str}-{suffix}" in existing:
        suffix += 1
    return f"{date_str}-{suffix}"


def _publish_assembly(assembly_name: str, staging_dir: Path) -> list[Path]:
    files: list[Path] = []

    # Reuse each assembly's own export-3mf/export-shaded-jpg CLI commands so the published
    # artifacts are byte-for-byte what the CLI produces.
    export_3mf = _run(
        [
            str(REPO_ROOT / "run-main.sh"),
            assembly_name,
            "export-3mf",
            "--outdir",
            str(staging_dir),
            "--filename",
            "assembly.3mf",
        ]
    )
    if export_3mf.returncode != 0:
        raise RuntimeError(f"export-3mf failed for {assembly_name}: {export_3mf.stderr}")
    dst_3mf = staging_dir / f"{assembly_name}__assembly.3mf"
    (staging_dir / "assembly.3mf").rename(dst_3mf)
    files.append(dst_3mf)

    export_jpg = _run(
        [
            str(REPO_ROOT / "run-main.sh"),
            assembly_name,
            "export-shaded-jpg",
            "--outdir",
            str(staging_dir),
            "--filename",
            "assembly.jpg",
        ]
    )
    if export_jpg.returncode != 0:
        raise RuntimeError(f"export-shaded-jpg failed for {assembly_name}: {export_jpg.stderr}")
    dst_jpg = staging_dir / f"{assembly_name}__assembly.jpg"
    (staging_dir / "assembly.jpg").rename(dst_jpg)
    files.append(dst_jpg)

    assembly_module = importlib.import_module(f"src.{assembly_name}.assembly")
    parts = assembly_module.create_assembly()
    bodies = group_by_body(parts)
    with tempfile.TemporaryDirectory() as tmp:
        for body_name, body_parts in bodies.items():
            safe_name = _safe_name(body_name)
            brep_path = Path(tmp) / f"{safe_name}.brep"
            export_brep(_fuse_body(body_parts), brep_path)
            gz_path = staging_dir / f"{assembly_name}__{safe_name}.brep.gz"
            with open(brep_path, "rb") as src, gzip.open(gz_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            files.append(gz_path)

    return files


def publish_release(assembly_names: list[str] | None = None) -> str:
    """Build every assembly (or just `assembly_names`) fresh, publish a new dated GitHub release
    bundling each assembly's assembly.3mf, assembly.jpg, and one .brep.gz per printable body, and
    mark it "latest". Returns the created release tag."""
    from tests.assemblies import discover_assemblies

    names = assembly_names or [name for name, _ in discover_assemblies()]
    tag = _next_available_tag()

    with tempfile.TemporaryDirectory() as staging:
        staging_dir = Path(staging)
        all_files: list[Path] = []
        for name in names:
            all_files.extend(_publish_assembly(name, staging_dir))

        create = _run(
            [
                "gh",
                "release",
                "create",
                tag,
                *(str(f) for f in all_files),
                "--title",
                f"Geometry Snapshot {tag}",
                "--notes",
                f"Automated geometry/export snapshot for: {', '.join(names)}",
                "--latest",
            ]
        )
        if create.returncode != 0:
            raise RuntimeError(f"failed to publish release {tag!r}: {create.stderr}")

    return tag


# --- Debug convenience (not part of pass/fail logic) -------------------------------------------


def export_snapshot_diff(assembly_name: str, body_name: str, tag: str | None = None) -> dict[str, str]:
    """Materialize the baseline and current shapes of one body as STL files under
    export/{assembly}/snapshot_diff/, for manual side-by-side inspection of a mismatch (e.g. in a
    viewer or slicer). Both shapes are fused via _fuse_body(), matching what
    check_body_geometry() compares. Deliberately does not attempt to also compute/export a
    boolean diff shape -- that would need cut(), which is the operation found to hang (see module
    docstring)."""
    resolved_tag = tag or latest_release_tag()
    if resolved_tag is None:
        raise RuntimeError("no GitHub release available to diff against")

    cache_dir = download_baseline(assembly_name, resolved_tag)
    baseline = _load_baseline_body(cache_dir, assembly_name, _safe_name(body_name))
    if baseline is None:
        raise FileNotFoundError(f"no baseline for {body_name!r} in release {resolved_tag!r}")

    assembly_module = importlib.import_module(f"src.{assembly_name}.assembly")
    bodies = group_by_body(assembly_module.create_assembly())
    if body_name not in bodies:
        raise KeyError(f"{body_name!r} is not a current body of {assembly_name!r}; have {sorted(bodies)}")
    current = _fuse_body(bodies[body_name])

    target_dir = REPO_ROOT / "export" / assembly_name / "snapshot_diff"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_paths: dict[str, str] = {}
    for label, shape in (("baseline", baseline), ("current", current)):
        stl_path = str(target_dir / f"{body_name}_{label}.stl")
        export_stl(shape, stl_path)
        out_paths[label] = stl_path
    return out_paths


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("publish", help="build every assembly and publish a new dated GitHub release marked latest")

    diff_parser = sub.add_parser("diff", help="export baseline/current STL pair for one body")
    diff_parser.add_argument("assembly")
    diff_parser.add_argument("body")
    diff_parser.add_argument("--tag", default=None)

    args = parser.parse_args()

    if args.command == "publish":
        tag = publish_release()
        print(f"Published release {tag!r} (marked latest)")
    elif args.command == "diff":
        for label, path in export_snapshot_diff(args.assembly, args.body, tag=args.tag).items():
            print(f"{label}: {path}")


if __name__ == "__main__":
    _main()
