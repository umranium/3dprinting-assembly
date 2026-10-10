# Phone Stand (phone_stand)

> Requirements: [`REQUIREMENTS.md`](REQUIREMENTS.md)

A desk phone stand: a triangulated side frame — base, backrest and rear strut — with a groove at
the front that the phone's bottom edge stands in, held by a contrasting-colour lip.

## What it demonstrates

- **One body, two colours.** `Stand` and `Lip` are separate parts tagged with the same body, so
  they fuse into one print but keep their own colours in the 3MF.
- **A modelled reference object.** The `Phone` is a `@non_printable` slab at its worst-case size,
  leaned against the backrest. It is never trimmed against the stand, so the collision suite would
  catch a groove or lip that is too tight.
- **A free print orientation.** The whole side profile is extruded across the stand's width and
  prints lying on its end face (`DOWN_MINUS_X`): a constant cross-section with no overhangs.

```text
  Side view (Y →, Z ↑)

             phone ╲╲
                    ╲╲  /│ backrest
                     ╲╲/ │
                     /╲╲  ╲ rear strut
          lip ▐█    /  ╲╲   ╲
              ▐█───/────╲╲───╲
              ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀  base, on the desk
```

## Key dimensions

In [`src/phone_stand/config.py`](../../src/phone_stand/config.py):

| Parameter | Value | Source |
|-----------|-------|--------|
| `phone_length` × `phone_width` × `phone_thickness` | 165 × 80 × 12 mm | assumed worst case |
| `lean_deg` | 25° | assumed |
| `stand_width` | 70 mm | narrower than the phone, so buttons stay clear |
| `wall` / `base_thickness` / `lip_thickness` | 6 / 5 / 5 mm | strength |

## Print strategy

| Part | Qty | Orientation | Why |
|------|-----|-------------|-----|
| Stand (incl. Lip) | 1 | on its end face (`DOWN_MINUS_X`) | constant profile, no overhangs; layers run across the backrest's bending load |
