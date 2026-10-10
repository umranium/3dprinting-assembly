# Phone Stand — Requirements

## Purpose
A desk stand that holds a phone upright for reading or video calls. A sample assembly showing a
single printed body in two colours, and a modelled reference object the body is checked against.

## Must-have
| ID | Requirement | Verified by |
|----|-------------|-------------|
| M1 | The phone leans back against a rest and cannot slide forward off the stand | visual checklist; collision suite against the modelled phone |
| M2 | The stand does not tip backwards or forwards with the phone in it | visual checklist (stable footprint); user confirmation on the printed part |
| M3 | Prints support-free as one piece | `tests/test_printability_all.py` |
| M4 | The phone's side buttons stay clear of the stand | visual checklist (the phone is wider than the stand) |

## Nice-to-have
| ID | Requirement | Verified by |
|----|-------------|-------------|
| N1 | The front lip prints in a contrasting colour | visual checklist |
| N2 | A charging cable can reach the phone's bottom port | not met — the lip is continuous; a cable slot is the obvious next change |

## Fixed constraints
- Printer: PETG, 0.6 mm nozzle, 256 mm cube build volume (see `CLAUDE.md`).

## Assumptions
- Phone with case up to 165 × 80 × 12 mm. A thicker case fouls the lip (collision suite fails);
  a smaller phone fits with more room.
- 25° lean back from vertical suits desk viewing.

## Open questions
- None blocking.

## Observed faults
- None yet.
