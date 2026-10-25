"""Generate Android build inputs from the configured original PC games."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LIFTERS = ("lift_gamemodule", "lift_engine", "lift_filesystems", "lift_media",
           "lift_renderer", "lift_nxcharacter", "lift_physx", "lift_d3dx")


def run(name, *args):
    logs = ROOT / "build/prepare"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{name}.log"
    print(f"Preparing {name}; log: {log.relative_to(ROOT)}", flush=True)
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / f"{name}.py"), *map(str, args)],
                                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text(encoding="utf-8", errors="replace")[-6000:], file=sys.stderr)
        raise SystemExit(f"{name} failed ({result.returncode}); see {log.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tension", action="store_true", help="Also prepare the Polish 2008 Tension release")
    args = parser.parse_args()
    config_path = ROOT / "port.json"
    if not config_path.is_file():
        parser.error("copy port.example.json to port.json and set your original game and middleware locations")
    config = json.loads(config_path.read_text())
    required = [ROOT / config["game_directory"] / "bin/win32" / name for name in
                ("Game.exe", "GameModule.dll", "Engine.dll", "FS.dll", "VFS.dll", "Sound.dll",
                 "Video.dll", "RendererD3D.dll", "NxCharacter.dll")]
    required += [ROOT / config["physx_directory"] / name for name in ("PhysXCore.dll", "PhysXCooking.dll")]
    required += [ROOT / config["d3dx_compiler"]]
    if args.tension:
        from lift_release import load_release
        required += [module["path"] for module in load_release("tension")["modules"]]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("missing original inputs:\n" + "\n".join(missing))
    for name in LIFTERS:
        run(name)
    run("build_vfs_index")
    if args.tension:
        from lift_release import load_release
        spec = load_release("tension")
        run("lift_release", "tension")
        game = next(m["path"].parents[2] for m in spec["modules"] if m["name"] == "Game")
        run("build_vfs_index", "--game", game, "--out", ROOT / "research/vfs-index.polish.json")
    print("Inputs prepared. Run python -B tools/build_game_apk.py", flush=True)


if __name__ == "__main__":
    main()
