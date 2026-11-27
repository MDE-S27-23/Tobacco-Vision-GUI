"""Remembers a few choices between runs (the printer, its resolution)

Stored in %APPDATA%\\TobaccoVisionGUI\\settings.json. Losing the file only means
the choices are asked again, so every error here is ignored.
"""

import json
import os

APP_FOLDER = "TobaccoVisionGUI"


def _path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_FOLDER, "settings.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**changes):
    data = load()
    data.update(changes)
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
        os.replace(temp, path)
    except OSError:
        pass
