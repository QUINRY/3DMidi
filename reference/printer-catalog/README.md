# Printer profile provenance

The application catalog is `app/printer_catalog.json`. It defaults to Snapmaker U1.
Research date: 2026-11-08. This is a selection of source-verifiable printers, not a sales ranking or a claim that every Klipper printer is supported.

## What is verified

Each selectable entry records the manufacturer repository, full pinned commit, original path, Git blob SHA, and a local snapshot.
X/Y limits, rotation distances, microsteps, printer kinematics, maximum velocity/acceleration, and optional smoothing values were taken from active configuration sections.
Commented values and stale header comments are not used.
The snapshot SHA-256 hashes describe the UTF-8/LF local snapshots, whose line endings were normalized on saving.

No physical music playback test has been performed on the newly added printers.
`source_verified` means the numeric profile matches a pinned official configuration; it does not establish the installed printer's revision, homing behavior, acoustics, or tuning.
Users with changed mechanics, different firmware variants, or custom builds should import the actual device configuration.

Klipper's default `full_steps_per_rotation` is 200 when absent in an axis section.
This is defined by `config.getint('full_steps_per_rotation', 200, ...)` in the saved official [stepper.py](https://github.com/Klipper3d/klipper/blob/282db764dc568841837f68af3964762189d2baee/klippy/stepper.py).
Explicit configuration values take precedence.
Any future geared X/Y axes must preserve their gear ratio in addition to rotation distance.

## Startup and movement policy

U1 retains its existing optional native XY homing. Ender-3 V3 KE defaults to its dedicated full-home/slow-clearance startup.
K2, K2 Pro, and K2 Plus now use `k2_xy_home` in both music modes and listening scans: restore normal machine limits, run plain `G28 X Y`, clear the mesh again, then position at 30 mm/s before applying music acceleration. Normal limits are restored at the end.
The pinned K2 homing overrides route X/Y requests separately from full Z homing. Full Z homing may invoke probing/nozzle-clean routines, so the music file requests only X/Y. Native firmware Z safety behavior is retained; no explicit Z target, measured clearance, or physical homing test is claimed. The bed must be empty. Source snapshots are recorded in `reference/k2-startup/manifest.json`.
Other Klipper profiles use `prepared_only`: the user prepares/homes the printer through its normal controls and sets a safe Z clearance before running music.
The root application owns enforcement and G-code validation.

K2-family music is X-only in both FOC-band and STEP-cadence modes. Y remains at its setup position throughout the melody; emitted musical moves contain only X and F words. CoreXY axis swapping is disabled for these routes, and both motors' equal cadences are checked in the STEP model. The default FOC band is X 12–16 mm/s from the user's K2 Pro A07/A08 listening feedback; tempo remains independent. Older alternating/Y settings normalize to X, and the interface exposes only the active X band. Previous Y listening scans are retained as diagnostic history, separate from generated music.

The music velocity/acceleration fields are deliberate application ceilings, bounded by the official profile maxima.
They are not manufacturer-recommended music values or acoustically measured optimums.
CoreXY defaults use at most 360 mm/s and 12,000 mm/s².
Cartesian bed-moving models use at most 180 mm/s and 3,000 mm/s².
The large SV08 Max uses at most 300 mm/s and 10,000 mm/s².

## Revision and volume details

K1 and K1 Max each have two official variants: 72 mm and 40 mm X/Y rotation distance.
Both are explicitly labeled in the selection; a model name alone does not identify its pulley revision.
The original K1 config uses 72 mm; the repository's `_1` config uses 40 mm.

Native X/Y travel bounds include manufacturer service/purge margins and can exceed nominal print dimensions.
`build_volume_mm` is nominal advertised print volume, while each axis' `min`/`max` comes from the active firmware config.
K1-family `printer_params.cfg` files contain a 220 mm Z variable in some revisions even though product specifications list 250 mm.
The nominal display value follows the linked manufacturer product specifications; motion bounds follow `printer.cfg`.
K2, K2 Pro, K2 Plus, and Hi nominal dimensions follow their matching `printer_params.cfg`.
QIDI Q2's full nominal 270×270×256 mm volume applies without QIDI BOX; see its linked official volume note.
No Z music moves are derived from these nominal volumes.

## Gated entries

Neptune 4 / Pro / Plus / Max remain configuration-required because the official source repo supplies firmware code and large system images, without a directly reviewed model/revision-specific numeric profile in this pass.
The official Elegoo guidance distinguishes ribbon-cable and Type-C hardware: do not assume one set of motor parameters across those revisions.
QIDI X-Plus 3 and X-Max 3 official repositories inspected here primarily contain display software; their printer motion configuration was not verified.
Max4 and Plus5 require the actual configuration as well.
Voron and Rat Rig builds vary in size, pulley/motor/gear configuration, and kinematics; the installed configuration is authoritative.
CoreXZ and delta entries are explicitly unsupported by this XY converter.

## Official snapshots

| Selection | Source |
|---|---|
| Snapmaker U1 | [Snapmaker/u1-klipper / lava/printer.cfg](https://github.com/Snapmaker/u1-klipper/blob/7ac453b50fe6779b2ec0b759038a17da5e6d671d/lava/printer.cfg) |
| Creality K1 · 72 mm kasnak profili | [CrealityOfficial/K1_Series_Klipper / config/K1_CR4CU220812S12/printer.cfg](https://github.com/CrealityOfficial/K1_Series_Klipper/blob/e09f36e6ada60e5467b0bef731a96263b5d8095b/config/K1_CR4CU220812S12/printer.cfg) |
| Creality K1 · 40 mm kasnak profili | [CrealityOfficial/K1_Series_Klipper / config/K1_CR4CU220812S12_1/printer.cfg](https://github.com/CrealityOfficial/K1_Series_Klipper/blob/e09f36e6ada60e5467b0bef731a96263b5d8095b/config/K1_CR4CU220812S12_1/printer.cfg) |
| Creality K1 Max · 72 mm kasnak profili | [CrealityOfficial/K1_Series_Klipper / config/K1_MAX_CR4CU220812S12/printer.cfg](https://github.com/CrealityOfficial/K1_Series_Klipper/blob/e09f36e6ada60e5467b0bef731a96263b5d8095b/config/K1_MAX_CR4CU220812S12/printer.cfg) |
| Creality K1 Max · 40 mm kasnak profili | [CrealityOfficial/K1_Series_Klipper / config/K1_MAX_CR4CU220812S12_1/printer.cfg](https://github.com/CrealityOfficial/K1_Series_Klipper/blob/e09f36e6ada60e5467b0bef731a96263b5d8095b/config/K1_MAX_CR4CU220812S12_1/printer.cfg) |
| Creality K1C | [CrealityOfficial/K1_Series_Klipper / config/K1C_CR4CU220812S12/printer.cfg](https://github.com/CrealityOfficial/K1_Series_Klipper/blob/e09f36e6ada60e5467b0bef731a96263b5d8095b/config/K1C_CR4CU220812S12/printer.cfg) |
| Creality K1 SE | [CrealityOfficial/K1_Series_Klipper / config/K1_SE_CR4CU220812S12/printer.cfg](https://github.com/CrealityOfficial/K1_Series_Klipper/blob/e09f36e6ada60e5467b0bef731a96263b5d8095b/config/K1_SE_CR4CU220812S12/printer.cfg) |
| Creality K2 | [CrealityOfficial/K2_Series_Klipper / config/F021_CR0CN200400C10/printer.cfg](https://github.com/CrealityOfficial/K2_Series_Klipper/blob/bc0a52078ace1e4d82995e396b38457b9f441024/config/F021_CR0CN200400C10/printer.cfg) |
| Creality K2 Pro | [CrealityOfficial/K2_Series_Klipper / config/F012_CR0CN200400C10/printer.cfg](https://github.com/CrealityOfficial/K2_Series_Klipper/blob/bc0a52078ace1e4d82995e396b38457b9f441024/config/F012_CR0CN200400C10/printer.cfg) |
| Creality K2 Plus | [CrealityOfficial/K2_Series_Klipper / config/F008/printer.cfg](https://github.com/CrealityOfficial/K2_Series_Klipper/blob/bc0a52078ace1e4d82995e396b38457b9f441024/config/F008/printer.cfg) |
| Creality Hi | [CrealityOfficial/Hi_Klipper / config/F018_CR4NU200360C20/printer.cfg](https://github.com/CrealityOfficial/Hi_Klipper/blob/646b6aaaa4dc1fe9c4f773f1a425ea4666e5ed9b/config/F018_CR4NU200360C20/printer.cfg) |
| Creality Ender-3 V3 KE | [CrealityOfficial/Ender-3_V3_KE_Klipper / config/F005/printer.cfg](https://github.com/CrealityOfficial/Ender-3_V3_KE_Klipper/blob/a63fb1a71672b91b505e0bda68fae2ede49f1168/config/F005/printer.cfg) |
| Sovol SV07 | [Sovol3d/SOVOL_KLIPAD50_SYSTEM / klipper_configuration/SV07/printer.cfg](https://github.com/Sovol3d/SOVOL_KLIPAD50_SYSTEM/blob/c2e82b5908cfc95f165350e47eab5872b600e042/klipper_configuration/SV07/printer.cfg) |
| Sovol SV07 Plus | [Sovol3d/SOVOL_KLIPAD50_SYSTEM / klipper_configuration/SV07 PLUS/printer.cfg](https://github.com/Sovol3d/SOVOL_KLIPAD50_SYSTEM/blob/c2e82b5908cfc95f165350e47eab5872b600e042/klipper_configuration/SV07 PLUS/printer.cfg) |
| Sovol SV08 | [Sovol3d/SV08 / home/sovol/printer_data/config/printer.cfg](https://github.com/Sovol3d/SV08/blob/a60644875f8c756d20b3828c9416518b414b5491/home/sovol/printer_data/config/printer.cfg) |
| Sovol SV08 Max | [Sovol3d/SV08MAX / home/sovol/printer_data/config/printer.cfg](https://github.com/Sovol3d/SV08MAX/blob/68c28ea4ef5a81279d69c0e7d3b6433f0945192b/home/sovol/printer_data/config/printer.cfg) |
| QIDI Q1 Pro | [QIDITECH/QIDI_Q1_Pro / config/printer.cfg](https://github.com/QIDITECH/QIDI_Q1_Pro/blob/61836007215a8b4f71418ac62059bc81c1f40b93/config/printer.cfg) |
| QIDI Plus4 | [QIDITECH/QIDI_PLUS4 / config/printer.cfg](https://github.com/QIDITECH/QIDI_PLUS4/blob/ec595fc903540564be757bcafa745cd5c4a52cd0/config/printer.cfg) |
| QIDI Q2 | [QIDITECH/QIDI_Q2 / config/printer.cfg](https://github.com/QIDITECH/QIDI_Q2/blob/3f6bcc8bc295ecf067b45345c5bdb2139b287f17/config/printer.cfg) |

Additional manufacturer sources for nominal dimensions are stored on the corresponding catalog entries as `volume_source_url`.
The copied configuration and Python snapshots retain upstream comments and licensing context; use the original repositories for full license terms.

Run `python reference/printer-catalog/check_catalog.py` to compare catalog values with the snapshots. This is a data consistency check, not printer hardware validation.

