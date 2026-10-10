---
name: design-assembly
description: Use when creating a new 3D-printable assembly, changing an existing one (new requirement, new dimension, reshaped part), or responding to a fault observed in a real print. Covers requirement elicitation, the requirements document under docs/{assembly}/REQUIREMENTS.md, the cheap-then-expensive validation loop, and the guards that keep a language model from guessing about 3D space.
---

# Designing and Changing an Assembly

Cheap validation before expensive validation; the user's confirmation gates each transition.
Requirements are written down before geometry, and the model is never the place where an
unanswered question gets silently resolved.

Everything in `CLAUDE.md` still applies — printer facts, standard hardware reuse, test placement,
subagent delegation, geometry-snapshot order, and the visual-QA opt-out. This skill is the
procedure; those are the constraints.

## Which entry point

- **New assembly** — start at Phase 1, then follow the bootstrap file list in Phase 5.
- **Change to an existing assembly** — start at Phase 1, but only for what the change touches;
  the existing `docs/{assembly}/REQUIREMENTS.md` is the baseline you are amending.
- **A part failed in a real print** — start at Phase 0.

## Phase 0 — Fault intake (only when something failed in use)

1. Ask what happened, in the user's own terms: what broke or didn't fit, when (during printing,
   during assembly, in use), and after how long.
2. Ask for a photo into `photos/{assembly}/` if the failure is visible.
3. Name the cause before touching geometry — a wall too thin, a clearance too tight, a load path
   nobody accounted for, a tool that doesn't reach.
4. Write it into REQUIREMENTS.md: a dated line under **Observed faults**, and the new or amended
   **must-have** it implies. A fault that doesn't change a requirement is a fault you have not
   understood yet.
5. Fix the model, not the check. If a printability or collision check flags the part, that check
   is the messenger.

Then continue at Phase 1 for anything the fix opens up, or Phase 2 if the requirement is clear.

## Phase 1 — Elicit requirements before writing anything

Ask in **one batched round** (use `AskUserQuestion`), not a drip of single questions. Every
dimensional question says how to measure it and what changes if the answer changes — "width of
the frame's back rail, measured across the flat, since the tape pad can't be wider than it".

Cover four things. The first two are the ones that get skipped; do not skip them.

**a. What it touches.** Enumerate every other object in contact with or constrained by the
assembly:

- what it mounts to — and the material and finish of that surface (tape won't hold on textured
  powder coat; screws need something to bite);
- what passes through or near it — cables, screws, light, airflow, a moving door;
- what it rests on, and what carries the load;
- the load itself: how heavy, in what direction, static or knocked;
- what is adjacent that it must not foul.

**Every object this turns up gets modelled.** A row in REQUIREMENTS.md is not enough: each thing
the assembly clamps, holds, shrouds, rests on or passes through becomes a `@non_printable`
reference part in `assembly.py`, with its dimensions in `config.py`. See "Modelling what the
assembly touches" below — this is not optional and it is not deferred to later.

**b. How people interact with it.** Enumerate the handling:

- install and removal order — what must be reachable while something else is already in place;
- which tool reaches which fastener, from which direction, with how much swing room (a driver
  needs a cone of clearance, not just a hole);
- how often it comes apart, and whether it must come apart without disturbing something else;
- what is gripped, pressed, or pulled, and by whom — a child pulling at it is a requirement;
- cleaning, storage, transport.

**c. Function and success.** What the assembly must do, and how the user will know it worked.

**d. Constraints.** Hardware on hand, colours/materials, build volume, deadlines, anything fixed.

Then write `docs/{assembly}/REQUIREMENTS.md` (shape below) and **show it to the user before
writing code**. Every item from (a) and (b) either becomes a requirement or is explicitly
dropped. Anything still unanswered goes under **Assumptions** with the value you intend to use
and what breaks if it is wrong, or under **Open questions** if you cannot proceed without it.

### Modelling what the assembly touches

Everything enumerated in (a) is modelled as a `@non_printable` reference part, positioned exactly
where it really sits relative to the datum. This is a hard requirement of every assembly in this
project, new or amended, and it is not "nice for the render".

**Why it is not optional.** An assembly is a set of claims about parts that are not the assembly —
this bore grips *that* pipe, this bracket clears *that* connector. Unmodelled, none of those claims
can be checked by anything: `tests/collisions.py` has nothing to find an interference against,
and every render shows the part holding thin air. Modelled, the existing project-wide checks start
proving the fit for free, with no new test to write.

Five rules, all of them consequences of the collision checks treating a reference part exactly like
any other:

- **Real dimensions, from the Fixed constraints.** Where a dimension was never measured, model the
  worst case of the range recorded under Assumptions and point the `config.py` comment at that
  assumption. Do not go back to the user for a figure that assumption already says is non-blocking.
- **Never trim a reference part against the printed parts.** It is drawn at its own real,
  undeformed dimensions and left whole. Cut it to fit and an overlap becomes arithmetically
  impossible, so the collision suite reports the fit clear however wrong the printed geometry is —
  green, but measuring nothing. A reference part has to be able to fail. This holds even when the
  real object is compliant and would genuinely deform in use: model the pipe round, not squeezed.
- **An interference fit therefore shows up as a real overlap, and that is a design question.**
  Raise it with the user rather than resolving it in the model — either the fit is not wanted, or
  the design has to achieve its hold some other way. Do not make the overlap disappear by reshaping
  the reference part, and do not widen a collision check to tolerate it.
- **Reference parts that touch *each other* are booleaned or fused**, so a real joint between two
  of them (a barb pushed into a pipe, a plug seated in a socket) does not read as an unexpected
  intersection. This is the one place a boolean is allowed, because neither part is the thing
  under test. Cutting one with the other keeps them separately labelled for `-p` rendering;
  fusing them into a single factory (e.g. a power board and the plugs seated in its sockets) is
  the alternative when a shared label is acceptable.
- **Each is one connected solid**, since `check_parts_are_single_solids` runs on non-printable
  parts too — a pipe modelled as two stubs either side of a clamp fails it.

Stop where the measurements stop. Model a straight stub of tube rather than inventing the bend
radius nobody measured, and say in the docstring where the reference deliberately ends.

## Phase 2 — Validate the idea in a cheap medium

In this order, in the chat, before any code:

1. **Datum and axes in words** — "origin at the tape face, +Z up the frame's back, +Y away from
   the frame". Every later dimension is relative to this. A stated frame is what keeps the
   geometry from drifting; an unstated one guarantees it will.
2. **Dimension table** — parameter, value, and where the value came from (measured, requirement,
   standard hardware, assumed). Filling a table is reliable; free-forming numbers into geometry
   is not.
3. **ASCII cross-section or diagram** — one per view that matters, with the datum marked.

4. **Body split and print orientation** — decide, and state, how the design divides into printed
   bodies and which way up each one prints. This is a design decision, not an export setting:
   see below.

Get the user's agreement on all four before writing code. Reworking a diagram costs a message;
reworking a model costs an hour.

### Choosing the body split and print orientations

Do this *before* the geometry, because the orientation dictates the geometry — which pockets can
open upward, which holes have to become teardrops, which face lands against the bed, and which way
the layer lines run relative to the load. Chosen afterwards, it means redrawing the part.

State for each body: **its down direction, and what that orientation buys and costs.** Any unit
`Vector` is available, not just the six axis directions; `src.printer`'s `DOWN_*` constants are
shorthand for the axis-aligned cases. Tag the direction on the body and let
`src.exporter.export_printable_3mf` orient and lay out the plate — never orient parts in an
assembly's `main.py`.

Three things are in tension, and none of them automatically wins. Say which one you traded away:

- **Geometric complexity** — features that exist only to make an orientation printable are a real
  cost. A sideways hole needs a teardrop; a pocket facing the wrong way needs a chamfered mouth or
  a redesign. Cheap to add, but they clutter the part and each one is a thing to get wrong.
- **Ease of printing** — support-free, sound bed contact and a stance that won't topple, no
  unsupported bridges, and layer lines running *across* the load rather than along a plane it can
  split on. A part that prints as a constant cross-section through its whole height has no layer
  boundary for a bend to split at; a part standing up through the same bend does.
- **Ease of assembly** — fewer bodies mean fewer fasteners, fewer alignment problems and less to
  lose. But refusing to split can force an orientation that needs supports, buries a nut where no
  hand reaches, or puts a critical face on a rough overhang.

Useful tiebreakers, in rough order of how often they decide it:

- Put the face that has to mate accurately against the bed — in FDM it is the most dimensionally
  accurate face on the part.
- Orient so the working load pulls across the layers, not along a single layer boundary.
- Prefer the orientation that leaves pockets, nut slots and cavities opening upward; a pocket with
  a closed floor printed above the bed is an unsupported bridge with a hole in it.
- Split a body only when the split buys something concrete — printability, tool access, an
  assembly step that is otherwise impossible, or a build-volume limit. Every split adds a fastener
  and an alignment problem, so make it earn its place.
- Where one screw joins two bodies that print different ways up, each body's hole is aimed by its
  own print direction. The same joint can show teardrops pointing different ways.

Record the outcome in the assembly's README print-strategy table: part, quantity, orientation, and
one line of why. If the orientation later has to change, that is a design change — go back to
Phase 2, not a quick re-tag.

## Phase 3 — Source-only changes, verified by looking

Update `src/{assembly}/`, render, share with the user. Do **not** run `./run-tests.sh` or
`./run-typecheck.sh` yet — tests written against the old geometry fail by construction and that
noise is not useful while the design is moving.

Rules for this loop, all of them there because a language model reasons about 3D space badly:

- **One change per render cycle.** Two changes in one render means a defect cannot be attributed.
- **Render the changed body alone and in the assembly.** `./run-main.sh {assembly}
  export-shaded-jpg -p '{part}'` and `export-wireframe-jpg`, then `-p Assembly`. Wireframe shows
  interior pockets and channels that shading hides.
- **Confirm orientation by looking, never by reasoning.** Do not conclude that a rotation put a
  face where you wanted it — render and see. Teardrop direction, mirrored parts, and anything
  built through a `Rotation` or `Location` are the usual offenders.
- **Verify spatial claims numerically.** Renders are perspective, so they lie about clearance and
  alignment. Check the actual numbers with a throwaway probe — ad hoc and uncommitted, never a
  new command added to `src/`. This is a read-only probe, not a test run: it does not go through
  the `test-runner` subagent. It uses the virtualenv the runner scripts create, so run any
  `./run-main.sh` command once first if `.venv/` does not exist yet.

  ```bash
  .venv/bin/python -c "
  from src.{assembly} import assembly
  for p in assembly.create_assembly():
      bb = p.bounding_box()
      print(p.label, bb.min, bb.max)
  "
  ```

  Bounding boxes, `.center()`, and `.volume` answer "does it clear", "is it centred", "did the
  cut actually remove anything" far better than an image does.
- **Thrash guard.** If two render cycles fail to fix the *same* visual defect, stop. Report what
  you see, what you changed, and what you expected, and ask. A third guess is not a plan, and the
  user usually knows the physical reason in one sentence.
- **Escalate a requirement problem, don't design around it.** If the geometry can't satisfy a
  must-have, go back to Phase 2 rather than quietly reshaping the model or relaxing the
  requirement.

Let the user confirm the design before continuing.

## Phase 4 — Only after the user confirms: tests, types, docs

1. **Route each must-have to its verification.** Prefer a property every assembly must satisfy,
   added to the shared helpers and picked up by the project-wide `tests/test_*_all.py` suites.
   An assembly-specific test in `tests/{assembly}/test_parts.py` is the exception, for a
   constraint no other assembly could have. Some must-haves are verified by a visual checklist
   item, and some only by the user handling the printed part — say which, in REQUIREMENTS.md.
   Not every must-have gets its own test; see the test rules in `CLAUDE.md` before adding one.
2. **Run the tests and the typecheck**, scoped to the assembly (`./run-tests.sh {assembly}`),
   delegated to the `test-runner` and `type-checker` subagents. If a failure reveals a real
   design problem rather than a stale expectation, return to Phase 2.
3. **Update the docs** — `docs/{assembly}/REQUIREMENTS.md` if anything about the need changed,
   `docs/{assembly}/README.md` for the solution as built, and
   `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST.md` for any new qualitative criterion. A lesson
   that generalises to other assemblies belongs in the workspace-wide
   `docs/VISUAL_INSPECTION_CHECKLIST.md` instead. Keeping the checklist current is all that is
   owed here: **never run the `visual-inspection-planner` or `visual-inspector` subagents unless
   the user explicitly asks for visual inspection**, and do not offer them. Rendering images
   yourself for the loop in Phase 3 is unaffected.
4. **Geometry snapshot**: an intentional shape change fails the snapshot check until the baseline
   is republished. Publish first (`./run-publish-snapshot.sh`), then commit.
5. **Clean up** any JPGs rendered along the way.

## Phase 5 — New assembly bootstrap

Create, in this order:

1. `docs/{assembly}/REQUIREMENTS.md` — Phase 1's output, agreed first.
2. `src/{assembly}/__init__.py`, `config.py` (the dimension table as parameters), `assembly.py`
   (`PART_NAMES`, `PART_CHOICES`, `create_assembly()`), `main.py` (the Click CLI wired to the
   shared exporter options).
3. `docs/{assembly}/README.md` and `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST.md`.
4. An entry in the root `README.md` list of available assemblies.
5. `photos/{assembly}/` for reference photos, if there are any.

Tests need no wiring: `tests/assemblies.py:discover_assemblies` finds the assembly and every
project-wide suite starts covering it the moment `src/{assembly}/assembly.py` exists. Create
`tests/{assembly}/` only when there is a genuinely assembly-specific assertion to put in it.

## The requirements document

`docs/{assembly}/REQUIREMENTS.md` records the *need*; `docs/{assembly}/README.md` records the
*solution*. They are separate because requirements outlive design revisions.

```markdown
# {Assembly} — Requirements

## Purpose
One paragraph: what problem, for whom, where it lives.

## Must-have
| ID | Requirement | Verified by |
|----|-------------|-------------|
| M1 | ...         | test / visual checklist item / user confirmation on the printed part |

## Nice-to-have
| ID | Requirement | Verified by |
|----|-------------|-------------|

## Fixed constraints
Measured dimensions of everything it mates with, hardware used, printer limits, materials.

## Assumptions
Value used, and what breaks if it is wrong.

## Open questions
Unanswered items, marked blocking or not.

## Observed faults
Dated: what failed on a real print, and which requirement it became.
```

Keep must-have and nice-to-have as the only two tiers. Requirements are written as behaviour
("the leg detaches without disturbing the tape bond"), not as geometry ("the tab is 5 mm thick") —
geometry belongs in `config.py` and the dimension table.
