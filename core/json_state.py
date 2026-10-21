"""Small JSON state files on disk: the monitors' "last page seen" and the SPG
override data. Moved out of features/monitors/sitemap.py because the SPG overrides
use it too and are not a sitemap monitor."""

import json
import os


def load_json_state(path: str, default: dict) -> dict:
    """Loads a JSON dict from disk, or a copy of `default` if the file
    doesn't exist yet (first run on a new machine)."""

    if not os.path.exists(path):
        return dict(default)

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json_state(path: str, data: dict) -> None:
    """Atomic write (`.tmp` file + `os.replace`): a crash mid-save leaves
    the previous state intact instead of a corrupted/truncated JSON."""

    os.makedirs(os.path.dirname(path), exist_ok=True)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, path)
