# Multi-Assembly CAD Workspace (build123d)

This project is configured as a multi-assembly workspace designed to support building, testing, documenting, and exporting multiple independent 3D assemblies.

## Why This Approach

The workspace is built so that an LLM can design 3D-printable parts that work on the first print.
LLMs are good at writing code but bad at reasoning about 3D space, and they cannot see what a
printer will do. So the repo never trusts the model's spatial judgement: every claim about geometry
is checked by code, by a render, or by the user.

- **CAD as code** — designs are parametric Python (build123d), the medium an LLM is strongest in.
  Every change is a reviewable diff in git, not an edit inside a binary CAD file.
- **Requirements before geometry** — the `design-assembly` skill makes the model ask what the part
  touches and how people handle it, then write `docs/{assembly}/REQUIREMENTS.md` *before* any code.
  Unanswered questions get recorded as assumptions instead of being guessed silently in the model.
- **Cheap validation first** — the datum, a dimension table, ASCII cross-sections and print
  orientation are agreed in chat before any modelling. Fixing a diagram costs one message; fixing a
  model costs an hour.
- **Look, don't reason** — the model renders shaded and wireframe images to confirm orientation and
  shape, and checks clearances with real numbers (bounding boxes, volumes), since perspective renders
  can mislead. One change per render cycle; after two failed fixes it stops and asks.
- **Automated print checks as feedback** — build volume, bed stability, unsupported layers,
  collisions and single-solid bodies are checked on every assembly automatically. The model gets
  a concrete failure to fix instead of a print that fails hours later.
- **Thresholds that can fail** — printability limits come from published guidance and the printer's
  nozzle size, never from numbers back-fitted to existing parts. The model can't make a check pass
  by loosening it.
- **Mating objects are modelled** — whatever the part clamps, holds or rests on is modelled at its
  real size, so collision checks can prove the fit instead of showing a part holding thin air.
- **Proven building blocks** — screws, nuts and their cutouts come from `src/hardware.py`, and print
  orientation and bed layout are handled once in `src.printer`. The model reuses tested pieces
  instead of re-deriving tolerances or rotations, which is where it slips most often.
- **Guardrails against drift** — geometry snapshots catch any unintended shape change, and the
  publish step always needs the user's approval. Tests and type checks run through subagents, and
  the pre-commit hook blocks failing code.
- **Human gates at each phase** — the user approves the requirements, the sketch and the rendered
  design before tests and docs are finalised. Faults from real prints go back into the requirements.

## Project Layout

Each assembly is independent and isolated within the corresponding subdirectories:

```text
├── README.md                # Global workspace documentation (this file)
├── run-main.sh              # Run CLI commands for a specific assembly
├── run-tests.sh             # Run tests for a specific or all assemblies
├── run-typecheck.sh         # Run static type checking workspace-wide
├── pyrefly.toml             # Linter search path configurations
├── pyrightconfig.json       # Type checker configurations
├── requirements.txt         # Workspace Python dependencies
│
├── photos/                  # Reference photos of parts/assemblies
│   └── {assembly}/          # Reference photos for a specific assembly
│
├── src/                     # Workspace Source Code
│   ├── main.py              # Generic runner that dynamically routes to assemblies
│   └── {assembly}/          # Code for a specific assembly
│       ├── __init__.py
│       ├── main.py          # Click CLI for the assembly
│       └── ...              # Assembly source files (parts, configs, etc.)
│
├── tests/                   # Workspace Tests
│   └── {assembly}/          # Tests for a specific assembly
│       └── ...              # Test files (geometry verification, etc.)
│
├── docs/                    # Workspace Documentation
│   ├── VISUAL_INSPECTION_CHECKLIST.md  # General checklist for all assemblies
│   └── {assembly}/
│       ├── REQUIREMENTS.md  # Must-have / nice-to-have requirements for the assembly
│       ├── README.md        # Detailed specification for the assembly
│       └── VISUAL_INSPECTION_CHECKLIST.md # Assembly-specific checklist (high-level requirements)
│
└── export/                  # Exported CAD Files
    └── {assembly}/          # Exports for a specific assembly (.3mf, .step, .jpg, etc.)
```

## Terminology & Concepts

- **Assembly**: The complete 3D project containing all CAD components, hardware fasteners, negative clearance cutouts, and multi-part arrangements (e.g. `box_with_lid`).
- **Body** (Printable Body): A physical object printed on the 3D printer bed as a single connected piece. A body may be composed of a single part or multiple logical CAD parts fused together for multi-material/multi-color printing (e.g. the phone stand's "Stand" body comprising the stand and its contrasting lip). Printability verification (build volume extents, overhangs, and bridging analysis) is performed on fused **Bodies**.
- **Part**: An individual logical component defined in code (e.g., `"Front Base"`, `"Left Eye"`, `"M3 Screw"`). Parts represent distinct geometric sub-components, hardware items, or visualization clearance volumes.

---

## Available Assemblies

Two sample assemblies demonstrate the framework; add your own alongside them.

1. **[`phone_stand`](docs/phone_stand/README.md)** - A desk phone stand: one printed body in two colours, checked against a modelled phone.
2. **[`box_with_lid`](docs/box_with_lid/README.md)** - A small box with a lid screwed down by four M3 screws into captive square nuts, with sacrificial bridges over the nut slots.

---

## Getting Started

### Requirements
- Python 3.10+
- The environment and dependencies will be configured automatically by the runner scripts.

---

## How to Run Commands

Execute a command for an assembly using `./run-main.sh {assembly} [command]`:

### Interactive 3D Viewing (OCP CAD Viewer)

Open the **OCP CAD Viewer** tab/panel in VS Code / your IDE, then run:

```bash
./run-main.sh {assembly} view
```

### Exporting 3MF

```bash
./run-main.sh {assembly} export-3mf
```

Every assembly's `export-3mf` writes a ready-to-slice build plate: each printable body is rotated
into its own tagged print orientation, dropped onto the bed and packed beside the others. Assemblies
do not orient or place their own parts — `src.exporter.export_printable_3mf` does it for all of them.

### Exporting Images (JPG)

Export high-resolution color/shaded 3D renders:
```bash
./run-main.sh {assembly} export-shaded-jpg [options]
```

Export hidden-line wireframe projection images:
```bash
./run-main.sh {assembly} export-wireframe-jpg [options]
```

For more options and assembly-specific flags, run `./run-main.sh {assembly} --help` or read the assembly's documentation in `docs/{assembly}/README.md`.

---

## Testing & Quality Control

### Running Tests
Run tests for all assemblies:
```bash
./run-tests.sh
```

Run tests only for a specific assembly (e.g. `box_with_lid`) — both its own tests under
`tests/box_with_lid/` (if any) and its slice of the project-wide `tests/test_*_all.py` suites:
```bash
./run-tests.sh box_with_lid
```

Narrow further to a single printable body:
```bash
./run-tests.sh box_with_lid Lid
```

### Static Type Checking
Run Pyright type checking across the entire workspace:
```bash
./run-typecheck.sh
```

### Visual Inspection QA
Perform visual verification by rendering views and checking them against both global and assembly-specific checklists:
- Global requirements: [`docs/VISUAL_INSPECTION_CHECKLIST.md`](docs/VISUAL_INSPECTION_CHECKLIST.md)
- Assembly-specific checklist: `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST.md`

The `visual-inspector` subagent verifies these checklists directly, choosing and rendering the views each item needs (see [`CLAUDE.md`](CLAUDE.md) for the full workflow).

### Git Pre-Commit Hook
You can automatically run type checking and unit tests before every commit by installing the pre-commit hook:
```bash
./setup-hooks.sh
```
This hook will abort the commit if either checking or testing fails, ensuring that you only commit clean, passing code.

---

## How to Add a New Assembly

To add a new assembly named `{assembly_name}` — follow the `design-assembly` skill for the process
(requirement gathering, cheap validation, then geometry); the files it produces are:

1. **Create directories**:
   Create the folders `src/{assembly_name}`, `tests/{assembly_name}`, `docs/{assembly_name}`, and `export/{assembly_name}`.
2. **Add Source Code**:
   - `src/{assembly_name}/assembly.py`: Define `PART_NAMES` (set of all part labels), `PART_CHOICES` (dictionary mapping choice names to sets of part labels), and `create_assembly() -> list[Part | Compound]`. Tag each non-printable part (hardware, clearance cutouts, reference-only parts) with `@src.part_tags.non_printable` (or `@screw`/`@nut`/`@sacrificial` where applicable) — printable is the default, so printable parts need no tag at all.
   - `src/{assembly_name}/main.py`: Click CLI entrypoint using `@export_3mf_options` and `@export_jpg_options` from `src.exporter`. Its `export-3mf` command passes `create_assembly()` straight to `src.exporter.export_printable_3mf`, which orients and lays out the printable bodies — never orient parts here.
3. **Tests**:
   Nothing to wire up — `tests/assemblies.py` discovers the assembly and the project-wide `tests/test_*_all.py` suites start covering it as soon as `src/{assembly_name}/assembly.py` exists. Add `tests/{assembly_name}/test_parts.py` only for an assertion genuinely specific to this one design (see the test rules in [`CLAUDE.md`](CLAUDE.md)).
4. **Add Documentation**:
   Write the requirements in `docs/{assembly_name}/REQUIREMENTS.md` (the need: must-haves, nice-to-haves, what it mates with, assumptions), detailed documentation of the design in `docs/{assembly_name}/README.md` (the solution), and verification criteria in `docs/{assembly_name}/VISUAL_INSPECTION_CHECKLIST.md`.
5. **Update list**:
   Add the assembly to the list of **Available Assemblies** in this root `README.md`.

