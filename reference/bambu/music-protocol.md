# Native Bambu motor sound protocol

Retrieved 2026-11-08 from Bambu's own published MIDI editor and guide:

- Guide: <https://wiki.bambulab.com/en/A1-mini/Midi>
- Editor: <https://midi-to-gcode.bambulab.com/edit>
- Deployed JavaScript: <https://midi-to-gcode.bambulab.com/browserMain-8002fc808330ff1b5d91.js>

Downloaded editor SHA-256: `3e6dc13aa9ad7816b891d4a0bd19acc8b31140cb91f066be9a860dff871caecf`.

The official editor's webpack module 35207 declares the ordered motor names X, Y, Z. Module 31623 serializes those positions into note/duration parameter pairs A/B, C/D, E/F and volume parameters L, M, N. Note values are MIDI pitch minus 23, with zero denoting a rest. The volume lookup table indexes note values 1–72 (MIDI 24–95). The editor rounds timing to 10 ms units and splits long notes into pieces of at most 200 units.

The official standalone exporter enables motors with M17, pauses with M400 S1, starts the sequencer with M1006 S1, initializes channel volumes, emits M1006 notes, waits with M1006 W, then disables motors with M18. This application's exporter changes that workflow deliberately: Z volume is initialized to zero, every timed row explicitly sets E0 F0 N0, and M18 is omitted so the file does not disable Z holding current. Only X and Y are assigned notes. No Cartesian moves, home, temperature, filament, motor-current or velocity commands are generated. This is a native sound program, not a physical XY travel program.

The guide specifically describes A1 mini standalone playback from a `.gcode` file on a microSD card and says printer Sound / Allow Prompt Sound must be enabled. Current Bambu Studio templates provide evidence of intended sound-command use on additional models; actual support still depends on the installed firmware. Neither the guide nor the closed firmware establishes a universal guarantee that every Bambu model or firmware plays these commands. Catalog status records that distinction. No physical printer testing has been performed here.

The app resolves note-on and note-off boundaries, selects at most two active voices, shifts the whole register when possible, and documents individual octave folding if the full source register is wider than the native band. Absolute boundaries are quantized to 10 ms so rounding does not accumulate across notes. Intervals that quantize to zero are reported, not silently lengthened. The generated file is parsed independently to verify its wrapper, notes, durations, X/Y amplitudes, permanently muted Z channel and exact bytes.

Local evidence files were downloaded to `output/app-verification/bambu-native-editor.js` and `bambu-midi.html`; they are research artifacts, not runtime dependencies. The app runs offline.
