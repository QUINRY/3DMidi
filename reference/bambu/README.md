# Bambu Lab profile evidence

Checked 2026-11-08 against the manufacturer's own Bambu Studio repository at commit [`4c2c19a4bf698edf153555dfe28fd4f81d6550be`](https://github.com/bambulab/BambuStudio/tree/4c2c19a4bf698edf153555dfe28fd4f81d6550be/resources/profiles/BBL/machine).

The sibling JSON files are unmodified snapshots of the 0.4 mm machine presets, model metadata, machine-start/machine-end templates, and inherited common machine presets. `app/bambu_catalog.json` records each snapshot's original path, pinned URL, and SHA-256. `tree.json` is the repository tree returned by GitHub at the same revision.

Only preset values are read. None of the source G-code is executed or copied wholesale into the music output. The source start routines include homing, heating, probing, extrusion, and Z movements that are unsuitable for this application's standalone cold-music workflow.

## Native sound capability

Active `M1006 S1`, note commands, and `M1006 W` occur in these **12** official startup templates:

- A1, A1 mini, A2L
- P2S
- X1, X1 Carbon, X2D
- H2C, H2D, H2D Pro, H2S, H3C

The X1 and X1 Carbon commands are active lines in the manufacturer's `20251031` startup templates, not commented examples. This establishes source-template support, not compatibility with every earlier installed firmware version.

P1P, P1S, and X1E have no `M1006` sequence in their pinned official startup templates. They are listed as unavailable for native music; a Klipper `printer.cfg` cannot supply this missing Bambu firmware capability. Absence from these templates is not proof that every firmware release rejects `M1006`, so the status deliberately says support is unverified.

The generated native sound workflow uses the official web editor's note protocol. See [music-protocol.md](music-protocol.md) for the independent JavaScript-source evidence, MIDI offset, timing, X/Y channels, and muted Z channel.

## Geometry and limits

Build dimensions are the **slicer preset's printable envelope**, obtained by resolving the preset's `inherits` chain and reading `printable_area` / `printable_height`. They are not substituted marketing dimensions. In particular:

- P1P/P1S/X1/X1 Carbon/X1E inherit `printable_height = 250` mm.
- X2D has `printable_height = 261` mm.
- A1 is 256 × 256 × 256; A1 mini 180 × 180 × 180; A2L 330 × 320 × 325.
- P2S is 256 × 256 × 256.
- H2D/H2D Pro are 350 × 320 × 325; H2C/H3C 330 × 320 × 325; H2S 340 × 320 × 340.

The snapshot's `extruder_printable_area` is also retained for machines with different nozzle-specific envelopes. Because native music emits no positioning moves, none of these model coordinates or limits drive XY or Z motion.

`profile_limits` records the first (normal-mode) X/Y speed and acceleration entries, not an acoustic calibration. These arrays may include additional extruders and operating modes. For example, the A1 mini inherits a 20,000 mm/s² slicer limit; this does not assert the advertised or physically achieved acceleration. Native sound does not issue `M204` or use these numbers to move the machine.

The inspected machine presets do not publish the XY motor full-step counts or pulley travel needed for the Klipper motion-to-pitch conversion. No `steps/mm`, microstep setting, `rotation_distance`, or Klipper command support is inferred for Bambu profiles. The source's `gcode_flavor` is `marlin`; the application uses a separate Bambu sound backend.

## Recent model identity

The most recent models are confirmed by primary manufacturer publications, rather than assumed released because their names occur in a source tree:

- [A2L manufacturer announcement, 2026-06-01](https://forum.bambulab.com/t/creative-playground-extra-large-meet-the-a2l/254169) identifies a bed-slinger and 330 × 320 × 325 mm nominal volume.
- [X2D manufacturer manual](https://csm.bblcdn.cn/hub/bcef71ed8da34c49a7fc5c7b93a26cfa.pdf), version 2026.04.
- [H3C manufacturer announcement, 2026-11-03](https://blog.bambulab.com/tool-changer-game-changer-bambu-lab-presents-h3c-the-defining-new-generation-of-3d-printers/) identifies 330 × 320 × 325 mm nominal volume, 1,400 mm/s and 25,000 mm/s² claimed limits.

Run the read-only consistency check:

```powershell
.venv\Scripts\python.exe -X utf8 reference\bambu\check_bambu_catalog.py
```

Source verification and an offline command check do not constitute a physical printer or acoustic test.
