# Box With Lid — Requirements

## Purpose
A small desk storage box with a lid screwed down at the corners. A sample assembly showing two
printed bodies joined with standard hardware: screws, captive nuts and a sacrificial bridge.

## Must-have
| ID | Requirement | Verified by |
|----|-------------|-------------|
| M1 | The lid screws down onto the box and cannot slide or twist once seated | `tests/test_mechanical_all.py` (rotational capture, prying); visual checklist |
| M2 | Every screw is driven from the top | visual checklist |
| M3 | Removing the lid leaves the nuts in the box, not loose | visual checklist (nut slots open into the box, never towards the lid) |
| M4 | Both bodies print support-free | `tests/test_printability_all.py` |
| M5 | Screws and nuts have a clear path and clamp the two bodies together | `tests/test_mechanical_all.py` |

## Nice-to-have
| ID | Requirement | Verified by |
|----|-------------|-------------|
| N1 | Screw heads finish flush with the lid top | visual checklist |
| N2 | Box and lid print in contrasting colours | visual checklist |

## Fixed constraints
- Hardware: 4 × M3 × 12 socket head screws, 4 × M3 square nuts (`src/hardware.py`).
- Printer: PETG, 0.6 mm nozzle (see `CLAUDE.md`).

## Assumptions
- Outside size 70 × 50 mm, walls 35 mm tall: an arbitrary demo size, change freely in `config.py`.

## Open questions
- None blocking.

## Observed faults
- None yet.
