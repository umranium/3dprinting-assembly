# General Visual Inspection Checklist (All Projects)

This checklist defines the global visual criteria and modeling standards that apply to all CAD assemblies across this workspace. Assembly-specific checklists located in `docs/{assembly}/VISUAL_INSPECTION_CHECKLIST.md` supplement these general requirements.

> [!NOTE]
> The items below describe **qualitative visual conditions** (what parts look like in rendered images), not dimensional measurements. Verification agents/subagents should render as many JPG views (isometric assembly, isolated parts, hidden-line views, close-ups) as needed to confirm each condition. Exact numerical dimensions and tolerances are validated by unit tests.

---

## 1. Fasteners, Screws, & Hardware Clearances

- [ ] **Through-Hole Screw Clearance**: Every body through which a screw passes shows a visible through-hole with an annular gap around the screw shaft, ensuring screws pass freely without biting or binding into intermediate bodies.
- [ ] **Nut & Insert Clearance for Easy Insertion**: Cavities, slots, pockets, and recesses for captive hardware (square nuts, hex nuts, heat-set inserts) show visible clearance around the hardware on all sides so parts can be inserted easily without tight friction.
- [ ] **Nut & Screw Channel Alignment**: Nut pockets and captive recesses align directly with their corresponding screw channels, with clear and unobstructed entry paths for screws.
- [ ] **Screw Head Seating**: Countersinks, counterbores, or head recesses allow fastener heads to sit flush or recessed relative to the outer surface with visible clearance around the perimeter.
- [ ] **No Hardware Collisions**: Fastener models (screws, bolts, nuts, inserts) sit neatly inside their dedicated pockets and channels without colliding with or cutting through solid printed geometry.

---

## 2. Assembly Fit & Interfaces

- [ ] **Mating Parts Are Modelled and In Place**: Every real-world object the assembly clamps, holds, shrouds, rests on or passes through appears in the assembly render as a reference part, sitting where it really sits. An assembly rendered holding nothing means a mating part has not been modelled, and nothing in the image can then show whether it fits.
- [ ] **Mating Parts Are Drawn Whole**: Each reference part is the real object at its own dimensions, with no notch, flat or slice taken out of it where the assembly meets it. A mating part visibly trimmed to the shape of the part being tested proves nothing about the fit, because it was cut to fit.
- [ ] **Fit Against Mating Parts Reads Correctly**: Where the design intends clearance, a gap is visible all the way round between the mating part and the surfaces meant to clear it. Where the design intends contact, the two meet along the contacting surfaces with no visible gap and neither standing inside the other.
- [ ] **Mating Surfaces**: Interlocking parts, sliding inserts, rails, and alignment joints match mating profiles cleanly along their intended contact planes with visible joint seams or clearance gaps.
- [ ] **Multi-Body / Multi-Color Interfaces**: In multi-color or inlaid parts, inlaid elements meet flush at exterior surfaces without unintended volume overlaps, step-offs, or sunken gaps.
- [ ] **Symmetry & Orientation**: Symmetrical features are positioned evenly across symmetry planes, and functional elements (sockets, plugs, keyrings, text) are oriented in the correct operational direction.

---

## 3. 3D Printability & Support-Free Geometry

- [ ] **Horizontal Hole Overhangs**: Horizontal through-holes and screw channels feature teardrop or angled overhang profiles to prevent sagging or drooping when printed without supports.
- [ ] **Teardrop Apex Points The Way The Body Builds**: Each teardrop's point aims along the print-up direction of the body it is cut into, not merely along some axis. Where one screw joins two bodies that print in different orientations, each body's own hole is aimed by its own print direction, so the same joint can show teardrops pointing different ways in different parts. A teardrop lying on its side leaves the bore an ordinary round ceiling and is no better than no teardrop at all.
- [ ] **Self-Supporting Transitions**: Internal cavities, pockets, and overhangs are tapered, chamfered, or oriented with open access in the print direction to print cleanly without internal supports.
- [ ] **Feature Definition & Printable Widths**: Thin walls, ribs, embossed graphics, and text strokes appear clearly defined, continuous, and robust enough to resolve on standard extrusion nozzles.

---

## 4. Finishing, Ergonomics, & Boundary Confinement

- [ ] **Edge Treatments**: External perimeter edges and exposed corners feature smooth fillets or chamfers to eliminate sharp edges.
- [ ] **Feature Boundary Confinement**: Surface features (text, logos, inlays, icons) sit comfortably within flat planar regions and do not cross or bleed into perimeter chamfers, fillets, or outer part boundaries.
- [ ] **No Artifacts / Stray Geometry**: Assemblies and individual parts are free from unexpected sliver walls, floating disconnected bodies, phantom shells, or leftover boolean cutting remnants.
