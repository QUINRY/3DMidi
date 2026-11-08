# 3DMidi

**Turn MIDI files into music played by 3D printer motors.**

An offline Windows app with printer-specific G-code, movement and tempo controls, a melody preview and 129 bundled MIDI examples. No Python installation or internet connection is needed to convert a file.

[Download for Windows](https://github.com/QUINRY/3DMidi/releases/latest) · [Türkçe](README.tr.md)

## Get started

1. Download **3DMidi.exe** from the latest release and double-click it. No installer is needed.
2. Select your printer. **Snapmaker U1** is the default.
3. Open a `.mid` / `.midi` file, or choose an example from the MIDI library.
4. Set movement speed and tempo to **Slow / Medium / Fast**.
5. Generate G-code and save a short test, the full song or the JSON validation report using **Save As**.

Windows 10/11 **x64** and [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) are required. WebView2 is present on many Windows systems. The executable is not code-signed.

## Languages and settings

English is the default. Open **Settings → Language** to choose English, Türkçe, Deutsch, Español, Français, Português, 简体中文, 日本語, Русский or العربية.

The interface changes immediately and the preference is saved on your computer. Arabic has a right-to-left layout. Menus and controls are localized; technical details use English when a translation is unavailable. Track names, original source attribution and G-code instructions keep their original data.

## Printer support

- **31 selectable profiles** in a source-backed catalog of 50 Klipper and Bambu Lab models.
- Snapmaker U1: XY motor music.
- Ender-3 V3 KE and Creality K2 / K2 Pro / K2 Plus: X-only music.
- K2 family: adjustable FOC acoustic range, movement speed and tempo.
- Supported Bambu Lab models: native `M1006` music with the Z sound channel muted.
- Custom Klipper CoreXY / Cartesian configurations can be imported from a complete `printer.cfg`. Includes and macros are never executed.

**Z is never used for the melody.** Startup and homing depend on the profile. Physical testing has not been performed on every model. Read the selected profile's notes, clear the bed and start with the short test. Some profiles require prior homing and at least 20 mm physical nozzle-to-bed clearance.

The app creates files locally. It does not connect to a printer or send G-code automatically.

## Run from source

Python 3.12 on Windows x64:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r desktop/requirements.txt
.\.venv\Scripts\python desktop/launcher.py
```

For local browser use:

```powershell
.\.venv\Scripts\python app/server.py --open
```

## Build the portable executable

```powershell
.\.venv\Scripts\python desktop/build.py
```

The build creates `output/windows/3DMidi.exe`, a ZIP package and SHA-256 checksums. It checks all 129 bundled MIDI hashes, local API authentication, U1 conversion and generated downloads. The Windows workflow is in `.github/workflows/windows.yml`.

Run the tests:

```powershell
.\.venv\Scripts\python -m pip install -r deploy/requirements.txt
.\.venv\Scripts\python -m unittest discover -s app -p "test_*.py"
.\.venv\Scripts\python -m unittest discover -s desktop -p "test_*.py"
```

## License and contributing

Application code is **GPLv3**. MIDI compositions and arrangements retain their individual source, attribution and stated license status; the application license grants no additional music rights. See [LICENSE](LICENSE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `app/midi_library.json`.

Issues and pull requests are welcome. You can download and modify your own copy; only the owner and authorized collaborators can write directly to this repository.
