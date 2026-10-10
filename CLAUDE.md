# Response Style

Always answer short and concise. Never verbose.

- Lead with the most important point — conclusion first, supporting detail after (if at all).
- Use bullets, not paragraphs. Never write long paragraphs.
- If there is nuance worth expanding on, name it in one line and offer it as an option to dig into — do not dump all the detail and expect it to be read.
- Do not narrate work in progress. No commentary before, between, or alongside tool calls about what you are reading, checking, searching, or about to do. Do the work silently and output only the final answer.
- When explaining how something works (an algorithm, a check, why a number was chosen), lead with a plain-language analogy and keep extending that one image. Name the mechanism in ordinary words before — or instead of — the jargon. Plain register, still short.

# Rules

- Do not create, update, or write a `walkthrough.md` artifact at the end of any task.
- Note that running tests and typechecks can take 60 seconds or more.
- **Investigate directly.** For a bounded lookup — reading a few known files, one targeted grep, diagnosing a single concrete failure — use `Read`/`Bash`/`Grep` yourself rather than spawning an `Agent`. Reserve subagents for genuinely open-ended, multi-location exploration (and for the mandated delegations below). The user often has the domain context already and would rather be asked directly.
- **Ground thresholds in published guidance.** When a check turns on a numeric constant — a printability limit, a clearance, an aspect ratio — look up the established published rule online *before* writing the check, since the sourced rule shapes what the check measures, not just the number. Measuring the repo's existing parts is a sanity check on that constant, never the thing that sets it: a threshold back-fitted to current parts cannot fail. If a real part is marginal against the published number, raise it rather than loosening the constant.
- Always use standard parts defined in `src/hardware.py` whenever possible — do not redefine parts in assemblies. This includes negative volumes! Do not manually sketch and extrude geometries like `Circle`, `Rectangle`, `Cone`, or `Box` inline to create screw clearance holes, countersinks, or nut pockets. You must import and instantiate the standard hardware cutouts (e.g., `hardware.m3_square_nut_pocket`, `hardware.m3_vertical_screw_hole`) and subtract them.
- **Subagent Delegation**: All typechecks (`./run-typecheck.sh`), unit tests (`./run-tests.sh`), git commits/operations, and visual inspection checklist planning/execution MUST be delegated to subagents (the `type-checker`, `test-runner`, `git-committer`, `visual-inspection-planner`, and `visual-inspector` agents in `.claude/agents/`). The primary agent must not run these directly and must spawn subagents to perform them.
- **Unit Testing — generalise first**: Before writing any new test, try to express it as a property every
  assembly must satisfy and put it in the project-wide, auto-discovered suites: add or extend a check in the
  shared helper (`tests/collisions.py`, `tests/printability.py`, `tests/mechanical.py`) and wire it into the
  matching `tests/test_*_all.py` suite. Those suites are parametrized by `tests/conftest.py` over two
  units: take an `assembly` parameter for a check about how an assembly's parts relate to each other, or a
  `body` parameter for a check about one printable body on its own (printability, geometry). Either way the
  check covers every existing assembly and every future one the moment its `src/{assembly}/assembly.py`
  exists. A check that a *deleted* thing would silently escape — an untagged part, a missing body — has to
  stay at assembly level, since a body that no longer exists produces no per-body test to fail.
  - **Assembly-specific tests are the exception, not the default.** Only write into
    `tests/{assembly}/test_parts.py` when the assertion is genuinely specific to that one design — a feature
    or constraint no other assembly has or could have. Never add a per-assembly copy of something an
    `_all` suite already checks, and never add one whose only distinction is re-running a generic check
    with different inputs or a tighter number.
  - **Test behaviour, not values.** Assert the property that makes the design work — that a nut is
    captured, that a body is one connected solid, that hardware has a clear path — rather than pinning
    the coordinates, volumes or dimensions that happen to produce it today. A test that restates the
    model's numbers back to itself fails on every intentional change and catches no real defect; the
    geometry snapshot suite (`tests/test_geometry_snapshot_all.py`) already covers "did the shape
    change at all".
  - **Shared machinery gets one generic test.** Anything in the base layer (`src/exporter.py` option
    decorators and callbacks, the exporter functions, `export-3mf`) is tested once in `tests/test_cli.py`
    against a synthetic assembly of plain boxes, never against real assemblies — not even to prove a real
    assembly is wired to the shared path. The synthetic fixture is cheap geometry but structurally
    complete (nested bodies, a shared colour and a differing one, one unlabelled part) so every branch is
    still exercised. Per-assembly wrappers do not get their own tests. Match fixture size to what a test
    asserts: an exit code and an output file do not need a 27-part assembly.
  - **Default config only.** Do not write tests that rebuild a parametric assembly across non-default
    config values to re-check that it still builds or still has no collisions. The sweep itself is
    unwanted, not merely its duplication — do not consolidate sweeps into a shared fixture either.
  - **Never change `src/` to serve the tests.** If the motivation for an edit under `src/` is "this makes
    the tests faster / less duplicated / easier to write", the answer is no by default; solve it on the
    test side. `src/` changes when the design changes. Offer an `src/` refactor as an option if it
    genuinely seems right, but never take it without the user explicitly choosing it.
  - **Use pytest's own mechanisms.** Share expensive objects with fixture scoping
    (`@pytest.fixture(scope="module"/"session")`), not a hand-rolled `lru_cache`. A cache is only
    defensible where a fixture cannot reach — collection-time work such as building a parametrize list,
    or patching a call made inside production code — and then say plainly why. Expect the user to forgo a
    real speedup rather than accept a hand-rolled cache; report the cost honestly instead of
    reintroducing one.
  - When creating a new assembly, verify:
    1. **Printability**: Every printable part must pass `tests.printability.get_print_extents`, `tests.printability.check_bed_contact` and `tests.printability.check_layers` — those checks define what printable means, so do not restate their criteria here. Print orientation is a free direction, not one of six: pass any unit `Vector`, using the `DOWN_*` constants in `src.printer` only as shorthand for the axis-aligned cases. Orienting and placing bodies for the printer is a base-level job done once in `src.printer.build_print_plate` for every assembly — tag each body's down direction and let `src.exporter.export_printable_3mf` do the rest; never orient or offset parts in an assembly's `main.py`.
    2. **Single Body**: Covered project-wide by `tests.collisions.check_parts_are_single_solids` (every part is one
       connected solid), `tests.collisions.check_body_is_one_solid` (the parts sharing a body tag fuse into one)
       and `tests.collisions.check_no_body_overlaps_another_body` (no two bodies share volume), all run
       automatically by `tests/test_collisions_all.py` — do not add a per-assembly copy.
    3. **No Intersections/Collisions**: Covered project-wide by the checks in `tests.collisions`, which
       `tests/test_collisions_all.py` runs automatically for every assembly — unexpected part
       intersections, overlapping clearances, and sacrificial parts (connected to a body, and not
       wholly consumed by the hardware that pierces them). Do not add a per-assembly copy; only add
       an assembly-specific test when it asserts a behaviour those generic checks cannot express at all.

# Printer & Printability

- **The printer is PETG on an enclosed machine with a 0.6 mm nozzle.** The nozzle sets the floor for what
  any printability check can care about; derive minimum-feature and noise constants from it rather than
  picking round numbers.
- Because it is PETG in an enclosure, **thermal warping and bed peel-off are not failure modes here.** Do
  not propose minimum first-layer-area or corner-lifting checks; the absence of one is intentional. What
  does matter is mechanical stance — a tall part toppling from nozzle side-loads — which is what
  `check_bed_contact`'s height-to-base-width ratio verifies.
- **The fused printable body is the unit of geometry.** For comparing, snapshotting, exporting or
  validating an assembly, group with `src.printer.group_by_body()` and fuse (`parts[0].fuse(*parts[1:])`)
  rather than working with loose parts. Never compare a fused shape against an un-fused compound of the
  same geometry — OCCT's `.intersect()` silently returns a wrong volume in that mixed case.

# Designing or Changing an Assembly

Creating a new assembly, changing an existing one, or responding to a fault seen on a real print all
follow the `design-assembly` skill — invoke it at the start of that work rather than improvising a
process. It covers requirement elicitation, the requirements document at
`docs/{assembly}/REQUIREMENTS.md`, the cheap-then-expensive validation loop, and the guards that keep a
language model from guessing about 3D space. The rules in this file are the constraints that hold
throughout; the skill is the procedure.

Every assembly has a `docs/{assembly}/REQUIREMENTS.md` recording the *need* — must-haves and
nice-to-haves, the things it mates with, assumptions, open questions, and faults observed on real prints.
`docs/{assembly}/README.md` records the *solution*. Keep them separate: requirements outlive design
revisions.

# Geometry Snapshots

- Every printable body's shape is compared each run against a baseline BREP on the latest GitHub Release
  (`tests/geometry_snapshot.py`). The pre-commit hook runs the full suite, so an intentional geometry
  change fails the commit until the baseline is refreshed.
- **The order is publish, then commit.** `./run-publish-snapshot.sh` runs the suite excluding the snapshot
  check and only publishes if that passes — the other tests answer "is this geometry right?", while the
  snapshot check only answers "did it change?", and a change is exactly what is being accepted.
- **There is deliberately no escape-hatch flag** to silence a snapshot mismatch. Do not reintroduce one:
  any skip flag lets a commit pass with a stale published baseline.
- **The publish is approved every time.** `.claude/settings.json` carries an `ask` rule for
  `./run-publish-snapshot.sh`; that prompt is the design. If a run is refused, do not retry it or route it
  through a subagent hoping for different permissions — report that the publish is owed and let the user
  decide.

# Verifying Model Changes (Visual Inspection QA)

- After making any change to a 3D model (geometry, positions, rotations, dimensions, etc.), first verify
that the changes made were as were requested by the user by running `./run-main.sh <assembly_name> export-shaded-jpg` for color/shaded rendering and `./run-main.sh <assembly_name> export-wireframe-jpg` for for hidden-line wireframe rendering.
- After you've visually verified the changes, let the user verify the changes.
- After the user has confirmed that the changes are what he's after, run the visual QA workflow below.

> **Opt-out (overrides the workflow below): never run the `visual-inspector` subagent unless the user
> explicitly asks for visual inspection/QA.** Do not offer it and do not ask whether they want it. Step 1
> alone — keeping `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST.md` current — is still done for every model
> change, including new assemblies. Ad hoc rendering for your own or the user's direct verification
> (`export-shaded-jpg` / `export-wireframe-jpg`) is unaffected.

### Visual QA Workflow
1. **Primary Agent Responsibility**: When model requirements or designs change, the primary agent MUST update the corresponding visual inspection checklist in `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST.md` to reflect the updated validation criteria. All models must also satisfy the workspace-wide criteria in `docs/VISUAL_INSPECTION_CHECKLIST.md`.
   - **Which file a criterion goes in**: `docs/VISUAL_INSPECTION_CHECKLIST.md` is the single
     workspace-wide file whose criteria apply to every assembly; `docs/{assembly}/` files only supplement
     it. A lesson learned while working on one assembly belongs in the workspace-wide file if it
     generalises to any assembly with a similar hardware pattern — putting it in that assembly's own file
     is a scope mistake. ("the general/high-level/workspace-wide checklist" always means the shared file.)
     Example of such a generalising rule: a nut or insert pocket must never open on the same side the
     screw enters from, or removing the screw's mating part leaves nothing retaining the nut.
   - **Visual vs. Dimensional Criteria**: Checklist items must describe **qualitative visual conditions** (e.g. visible clearance gaps, flush alignment, features staying within flat boundaries without crossing into chamfers/fillets, continuous walls, proper part nesting). Do NOT prescribe numerical measurements, coordinate values, or tolerances (e.g. "$r = 16.15\text{ mm}$", "$0.2\text{ mm}$ clearance", "$Z = -7.0$") in visual checklists — exact dimensions belong in unit tests (`tests/`), not visual inspection checklists.
2. **Planning the Detailed Checklist**: The checklists in step 1 are high-level requirements, not execution instructions. If `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST_DETAILED.md` does not exist yet, or the workspace-wide or assembly-specific checklist changed since it was last generated, delegate to the `visual-inspection-planner` subagent to break every requirement down into a detailed checklist at that path — one section per requirement, each with the exact terminal command(s) needed to render the verifying screenshot(s) and an explicit, low-inference description of what to check for in the image (e.g. "the frame's back edge and the backrest surface form a single continuous line with no gap" rather than "looks flush"). This step uses a larger model precisely because picking good views and writing unambiguous criteria requires real geometric judgment; if the checklist is already current, skip straight to step 3.
3. **Executing the Detailed Checklist**: Delegate to the `visual-inspector` subagent to run each command in `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST_DETAILED.md` exactly as written, inspect the resulting JPGs (saved to `export/{assembly}/`) with the `Read` tool, and verify them against that section's stated criteria — this is a mechanical comparison, not a judgment call, so a smaller model is sufficient. Spawn multiple `visual-inspector` subagents in parallel, splitting the detailed checklist's sections across them, to speed up inspection. The agent should only display/report the inspection results and must not modify or check off items in any checklist file.
4. **Custom Views and Parts**: If a detailed checklist section's command needs adjusting (e.g. its view didn't clearly show the feature), the fix belongs in `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST_DETAILED.md` via the `visual-inspection-planner` subagent, not as an ad-hoc override during execution. Example commands for targeting specific parts and camera coordinates:
   ```bash
   ./run-main.sh <assembly_name> export-shaded-jpg -p <part_name> --bearing <deg> --pitch <deg> --distance <n>
   ./run-main.sh <assembly_name> export-wireframe-jpg -p <part_name> --bearing <deg> --pitch <deg> --distance <n>
   ```
   Adjust parameters like `--bearing`/`--pitch` (camera position relative to `--look-at`, as a horizontal angle from +Y and an elevation angle above the horizontal plane, both in degrees), `--yaw` (camera roll), `--distance`, `--look-at`, and `--part` to obtain the best viewpoints. Both exporters always use a perspective camera, and `--distance` is a real physical camera placement — like a real camera, there is no auto-fit step, so try a few different `--distance` values and see which one frames the part well rather than expecting one default to work for every shape or view.
5. **Iterate**: If any rendered output fails to meet the checklist criteria, adjust the code and repeat verification until everything passes.
6. **Cleanup**: Once all checks pass and verification is complete, you MUST delete all the generated JPG files (e.g., from `export/{assembly}/`) to keep the repository clean. `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST_DETAILED.md` is a checked-in artifact and is not deleted, but must be regenerated (step 2) whenever the high-level checklist it derives from changes.
