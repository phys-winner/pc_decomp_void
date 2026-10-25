"""Same pinned native codec: original bytewise versus fread bulk callbacks."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from test_memmove import compiler_environment

ROOT = Path(__file__).resolve().parents[1]
SOUND_SHA = "855c2b0cd392b7d4faf82bc62bd9d3db211c5a7b34cd273db60617fc657de6f9"
ASSETS = ("Sounds\\ui_body_active_palette_full2#22.ogg",
          "Sounds\\stiltman_jump_loop_down#22.ogg",
          "Sounds\\ui_body_active_palette_full2#44.ogg",
          "Sounds\\stiltman_jump_loop_down#44.ogg",
          "Sounds\\tutorial_first_donor_on_sister#22.ogg",
          "Sounds\\girl_sister_obscure_dance5#44.ogg")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    output = ROOT / "build/vorbis-callback-pcm"
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tests/vorbis_callback_pcm_probe.c"
    codec = ROOT / "research/ida/Sound.dll"
    assert sha(codec.read_bytes()) == SOUND_SHA, "Native codec input changed"
    index = json.loads((ROOT / "research/vfs-index.json").read_text())
    container = next(c for c in index["containers"] if c["name"] == "Sounds.vfs")
    archive = Path(index["source"]) / container["name"]
    assert archive.stat().st_size == container["size"], "Sound archive size changed"
    compiler, env, sdk = compiler_environment()
    executable = output / "probe.exe"
    compiled = subprocess.run([str(compiler), "/nologo", "/O2", "/Oy-", "/W3", "/std:c11",
        "/D_CRT_SECURE_NO_WARNINGS", str(source), f"/Fo{output}\\", f"/Fe{executable}",
        "/link", "/MACHINE:X86", "/NXCOMPAT"], cwd=ROOT, env=env, capture_output=True, text=True)
    (output / "compile.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode: raise RuntimeError(compiled.stdout + compiled.stderr)
    results = []
    with archive.open("rb") as original:
        for filename in ASSETS:
            entry = next(e for e in container["entries"] if e["name"] == filename)
            original.seek(entry["offset"]); payload = original.read(entry["size"])
            assert len(payload) == entry["size"] and payload.startswith(b"OggS")
            identification = payload.index(b"\x01vorbis")
            channels = payload[identification + 11]
            rate = struct.unpack_from("<I", payload, identification + 12)[0]
            asset_dir = output / Path(filename.replace("\\", "/")).stem
            asset_dir.mkdir(exist_ok=True)
            copied = asset_dir / "input.ogg"; copied.write_bytes(payload)
            modes = []
            for mode in ("legacy", "bulk"):
                pcm = asset_dir / f"{mode}.pcm"
                decoded = subprocess.run([str(executable), str(codec), str(copied), str(pcm), mode],
                    cwd=ROOT, capture_output=True, text=True, timeout=20)
                text = decoded.stdout + decoded.stderr
                (asset_dir / f"{mode}.txt").write_text(text)
                if decoded.returncode: raise RuntimeError(f"{filename}/{mode} exit{decoded.returncode}:\n{text}")
                metadata = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
                raw_pcm = pcm.read_bytes()
                assert len(raw_pcm) == int(metadata["pcm_total"]) * channels * 2
                modes.append({"mode": mode, "exit": decoded.returncode, "metadata": metadata,
                              "pcm_sha256": sha(raw_pcm), "pcm_bytes": len(raw_pcm)})
            assert (asset_dir / "legacy.pcm").read_bytes() == (asset_dir / "bulk.pcm").read_bytes(), filename
            assert int(modes[1]["metadata"]["read_calls"]) < int(modes[0]["metadata"]["read_calls"])
            results.append({"entry": entry, "asset_sha256": sha(payload), "channels": channels,
                            "rate": rate, "modes": modes, "pcm_identical": True})
            print(f"PASS {filename}: {channels}ch/{rate}Hz PCM={modes[0]['pcm_bytes']}B; "
                  f"reads {modes[0]['metadata']['read_calls']} -> {modes[1]['metadata']['read_calls']}", flush=True)
    assert sha(codec.read_bytes()) == SOUND_SHA
    (output / "result.json").write_text(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
        "compiler": str(compiler), "sdk": sdk, "codec_sha256": SOUND_SHA,
        "probe_source_sha256": sha(source.read_bytes()), "probe_executable_sha256": sha(executable.read_bytes()),
        "index_sha256": sha((ROOT / "research/vfs-index.json").read_bytes()),
        "codec_entry_rvas": {"open1": "0xF440", "open2": "0xF540", "read": "0x10500",
                             "clear": "0xF590", "pcm_total": "0xF6D0",
                             "original_read_callback": "0x61270"},
        "legacy_executes_original_adapter_with_synthetic_native_thiscall_stream": True,
        "no_directsound_factory_or_device_or_playback_or_ui": True,
        "no_guest_runtime": True, "results": results}, indent=2))


if __name__ == "__main__": main()
