# Ender-3 V3 KE automatic music startup

The Python/config snapshots in this directory come from the manufacturer's repository at commit [`a63fb1a71672b91b505e0bda68fae2ede49f1168`](https://github.com/CrealityOfficial/Ender-3_V3_KE_Klipper/tree/a63fb1a71672b91b505e0bda68fae2ede49f1168). `source-replay.json` records local snapshot hashes and an AST replay of the real vendor move functions. No printer was operated by these tests.

The app restores the normal source-profile velocity, acceleration and smoothing limits before the ordinary `G28`, including when a previously interrupted file left a 3 mm/s global cap. It never imposes a 3 mm/s global velocity limit. After native homing it clears heater targets and the mesh, then applies `M204 S100` only for the separate absolute `G1 Z20 ... F180` clearance move. Normal limits are restored after that Z move and again after the music/return positioning. Z is absent from the music block. There is no fabricated position or extra unhomed lift.

The regression in `app/test_ke_auto_export.py` replays emitted limit commands at G28 and at file completion. It then runs the pinned vendor Move implementation to verify a requested 30 mm/s XY homing move remains 30 mm/s. The earlier `source-replay.json` includes the old 3 mm/s cap as a diagnostic example of the bug, not the current startup policy.

## What the global limit can and cannot bound

- `klippy/toolhead.py:19–22`: normal Move construction uses the ToolHead acceleration and `min(requested_speed, max_velocity)`.
- `klippy/extras/homing.py:94` and `toolhead.py:499–511`: normal endstop homing reaches ToolHead `drip_move` / `move`.
- `config/F005/sensorless.cfg:43–63`: `_IF_MOVE_X` / `_IF_MOVE_Y` issue a direct `FORCE_MOVE STEPPER=stepper_z ... VELOCITY=20` on a fresh start.
- `klippy/extras/force_move.py:79–97,129–136`: FORCE_MOVE submits its own trapezoid with the requested velocity. It does not read the normal ToolHead cap or feed multiplier.
- `klippy/extras/homing_override.py`: the recursive native G28 handler is held as a Python callable; no external `G28.1` alias is registered by this implementation.

The included optional [`midi_ke_slow_z.cfg`](midi_ke_slow_z.cfg) wraps FORCE_MOVE, forwarding non-Z calls unchanged and preserving the requested Z distance. Only direct Z velocity/acceleration are capped; a controlled acceleration is added when stock omits it. The real stock `_IF_MOVE_X` Jinja macro is rendered in the regression test and passed through the actual wrapper template: its `DISTANCE=5 VELOCITY=20` becomes `DISTANCE=5 VELOCITY=3 ACCEL=100`. See [`KE_YAVAS_Z_KURULUM.txt`](KE_YAVAS_Z_KURULUM.txt) for one-time installation and removal instructions.

## Remaining firmware limits

`prtouch_v2.py` and `z_compensate.py` load MIPS-specific compiled wrappers. Their internal speed, direct-MCU motion, and heating behavior cannot be established from these Python loaders. The app does not report that every internal probe movement is proven slow, nor that installed firmware matches this source snapshot. The optional FORCE_MOVE wrapper affects only direct Z moves; normal homing uses the printer profile limits. Existing stock homing may heat/probe; the music file does not itself issue a positive heater target.

No endstop is disabled, no synthetic homed flag is set, and no extra FORCE_MOVE is emitted by the app. Native homing failures abort normally rather than proceeding with music. Normal limits are set before G28, so a homing failure does not leave a deliberately lowered global velocity cap. The app does not suppress firmware errors.
