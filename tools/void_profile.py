"""Where the installed release keeps its profile.

The profile folders (Documents\\My Games\\<title>, Public Documents\\My Games\\
<title>\\Cache, ProgramData\\Ice-pick Lodge\\<title>) carry data/info.xml
EngTitle: "Void" for the English release, "Turgor" for the Russian one
("Тургор: Голос Цвета"). android/host/main.c resolves it the same way."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def game_directory():
    return Path(json.loads((ROOT / "port.json").read_text())["game_directory"])


def profile_title(game=None):
    info = (game or game_directory()) / "data/info.xml"
    try:
        match = re.search(r'EngTitle="([^"]+)"', info.read_text(encoding="utf-8-sig", errors="replace"))
    except OSError:
        match = None
    return match.group(1) if match else "Void"
