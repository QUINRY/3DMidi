# Third-party components and sample files

3DMidi application code is distributed under GNU GPL version 3. The license text is in `LICENSE`. This does not assign a new license to the included MIDI compositions, arrangements, printer configurations, or upstream code.

## Klipper and Snapmaker reference code

`app/assets/u1_toolhead.py` and `app/assets/u1_metadata_parser.py` retain their upstream copyright and GPLv3 notices. The planner is based on Kevin O'Connor's Klipper work and Snapmaker's U1 firmware. Only the pinned, hash-checked planner classes are evaluated offline; the application does not connect to a printer or MCU.

The exact U1 reference commit and file hashes are recorded in `app/assets/manifest.json`. Source: <https://github.com/Snapmaker/u1-klipper>. Printer profile source links and revisions are recorded in `app/printer_catalog.json` and `app/bambu_catalog.json`.

## MIDI library

All 129 selected MIDI files are included with their original source, attribution, hash, transformation and stated license metadata in `app/midi_library.json`. Additional provenance is in `app/popular_midi_sources.json` and `app/assets/library/popular/SOURCES_AND_LICENSES.json`.

The classical excerpts retain their individual Mutopia source and Creative Commons/public-domain information in those records. The popular-song archive does not establish a reusable license for each composition or arrangement; those records explicitly say when no license was specified. The Mario file was supplied by the project owner. Inclusion in this repository does not assert that these MIDI files are GPL-licensed or grant third-party music rights.

## Desktop runtime

The Windows executable bundles Python and these Python packages, with their upstream licenses and copyright notices preserved in `desktop/assets/dependency-licenses.txt`:

- Python — PSF License
- pywebview — BSD 3-Clause
- pythonnet — MIT
- clr_loader — MIT
- cffi — MIT
- pycparser — BSD 3-Clause
- Bottle — MIT
- proxy_tools — MIT
- typing_extensions — PSF-2.0
- Mido — MIT
- packaging — Apache-2.0 / BSD-2-Clause
- Jinja2 and MarkupSafe — BSD 3-Clause

PyInstaller is a build tool licensed under GPLv2-or-later with its bootloader exception. Microsoft Edge WebView2 Runtime is provided separately by Microsoft under its own terms; it is not embedded in this release. See <https://developer.microsoft.com/microsoft-edge/webview2/>.
