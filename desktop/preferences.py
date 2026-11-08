"""A small, validated preferences file independent of the loopback port."""
import json
import os
from pathlib import Path
import threading

LANGUAGES = {"en", "tr", "de", "es", "fr", "pt", "zh", "ja", "ru", "ar"}
_lock = threading.Lock()


def preferences_path():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "3DMidi/preferences.json"


def get_preferences():
    with _lock:
        try:
            data = json.loads(preferences_path().read_text(encoding="utf-8"))
            language = data.get("language")
            return {"language": language if language in LANGUAGES else "en"}
        except (OSError, ValueError, AttributeError, TypeError):
            return {"language": "en"}


def set_preferences(data):
    if not isinstance(data, dict) or not isinstance(data.get("language"), str) or data["language"] not in LANGUAGES:
        raise ValueError("Unsupported language.")
    saved = {"language": data["language"]}
    with _lock:
        path = preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved) + "\n", encoding="utf-8")
        temporary.replace(path)
    return saved


def text(message, language=None):
    from resources import APP
    language = language or get_preferences()["language"]
    if not isinstance(language, str) or language not in LANGUAGES:
        language = "en"
    try:
        catalog = json.loads((APP / "static/locales.json").read_text(encoding="utf-8"))
        return catalog["messages"].get(message, {}).get(language, message)
    except (OSError, ValueError, TypeError):
        return message
