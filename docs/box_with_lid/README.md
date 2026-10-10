# Box With Lid (box_with_lid)

> Requirements: [`REQUIREMENTS.md`](REQUIREMENTS.md)

An open box with a corner boss in each inside corner, and a lid held down by four M3 screws into
captive square nuts in those bosses.

## What it demonstrates

- **Standard hardware.** Every screw, nut and clearance comes from
  `hardware.create_screw_joint()`; each body subtracts the shared clearance voids.
- **Two bodies, both mechanically checked.** The project-wide mechanical suite pairs each screw
  with its nut, checks they clamp different bodies, that each body is stopped from spinning about
  the screw, and that the seam between them cannot be pried open.
- **Rotational capture by geometry.** A lip on top of the box's walls drops into a groove under
  the lid, so the lid cannot twist or slide even before the screws are tight.
- **A sacrificial bridge.** The roof of each nut slot is a bridge with the screw's hole through
  it; a one-layer disc (`Nut Bridge`, tagged `@sacrificial`) plugs the hole for that layer and is
  pushed through by the screw on assembly.

```text
  Section through a corner (X →, Z ↑)

     ┌──┬──────────── lid (groove underneath)
     │▒▒│ screw head, flush
     ├┐ │ ┌──────────
     ││ ║ │  lip in groove
     ││ ║ │
     ││▐█▌│ ← nut, slid in from inside the box
     ││ ║ │
     ││ boss
     └┴────────────── floor
```

## Key dimensions

In [`src/box_with_lid/config.py`](../../src/box_with_lid/config.py):

| Parameter | Value | Source |
|-----------|-------|--------|
| `length` × `width` × `wall_height` | 70 × 50 × 35 mm | demo size |
| `wall` / `floor` | 3.6 / 2.4 mm | 6 and 4 nozzle widths |
| `lip_height` / `lip_clearance` | 3 / 0.2 mm | locating fit |
| `screw_length` | 12 mm | M3 socket head, `src/hardware.py` |

## Print strategy

| Part | Qty | Orientation | Why |
|------|-----|-------------|-----|
| Box | 1 | floor down (`DOWN_MINUS_Z`) | cavity, bosses and lip all build straight up; nut slots open sideways with a sacrificial bridge over each |
| Lid | 1 | underside down (`DOWN_MINUS_Z`) | the groove sits on the bed and the counterbores open upward, so nothing overhangs |

## Assembly

1. Push a square nut into each boss's slot from inside the box.
2. Seat the lid, lip into groove.
3. Drive the four screws from the top; the first one through each hole punches the sacrificial
   bridge.
