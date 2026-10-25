"""Validate pinned Renderer input and the offline generated dispatch closure."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lift_renderer as renderer


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check():
    directory = ROOT / "generated/renderer-x86"
    report = json.loads((directory / "report.json").read_text())
    assert report["status"] == "GENERATED", report
    revision = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]["revision"]
    previous, _ = renderer.media_dispatch(revision)
    game = json.loads((ROOT / "port.json").read_text())["game_directory"]
    source, raw, private, proof = renderer.prepare_input(game)
    assert (ROOT / report["input_image"]).read_bytes() == private
    assert report["binary_sha256"] == sha(raw) == renderer.SPEC["sha256"]
    assert report["rebased_sha256"] == proof["rebased_sha256"] == sha(private)
    assert report["roundtrip"] == "PASS"
    assert report["pcrecomp_revision"] == revision
    assert report["runtime_integration"] == "NOT_ATTEMPTED"
    assert report["whole_game"] == report["execution_coverage"] == "UNVERIFIED"

    # A near-identical but unpinned original must fail before decoding.
    with tempfile.TemporaryDirectory(prefix="void-renderer-pin-") as temporary:
        target = Path(temporary) / "bin/win32/RendererD3D.dll"
        target.parent.mkdir(parents=True)
        changed = bytearray(raw)
        changed[-1] ^= 1
        target.write_bytes(changed)
        try:
            renderer.prepare_input(temporary)
        except ValueError as error:
            assert str(error) == "Renderer original hash mismatch"
        else:
            raise AssertionError("Unpinned Renderer bytes accepted")

    definitions, direct, traps, hashes = [], set(), {}, {}
    for name in report["sources"]:
        path = directory / name
        text = path.read_text()
        hashes[name] = sha(path.read_bytes())
        definitions += [int(a, 16) for a in re.findall(r"^void sub_([0-9A-F]+)\(void\) \{", text, re.M)]
        direct.update(int(a, 16) for a in re.findall(r"RECOMP_CALL\(sub_([0-9A-F]+)\)", text))
        for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', text):
            value = json.loads(instruction)
            assert address not in traps or traps[address] == value
            traps[address] = value
        assert not any(marker in text for marker in ("UNIMPLEMENTED:", "unknown reg ", "unknown condition:")), name
    assert len(definitions) == len(set(definitions)) == report["functions"]
    assert all(renderer.RENDERER_BASE <= a < renderer.RENDERER_BASE + renderer.SPEC["span"] for a in definitions)
    dispatch = (directory / report["dispatch_source"]).read_text()
    rows = re.findall(r"^\s*\{0x([0-9A-F]+)u, sub_([0-9A-F]+)\},$", dispatch, re.M)
    assert all(a == b for a, b in rows)
    addresses = [int(a, 16) for a, _ in rows]
    assert addresses == sorted(set(addresses))
    assert set(previous).isdisjoint(definitions)
    assert addresses == sorted([*previous, *definitions])
    assert len(previous) == report["prior_dispatch_entries"]
    assert len(addresses) == report["merged_dispatch_entries"]
    assert direct <= set(addresses)
    assert report["undefined_direct_symbols"] == 0
    recorded_traps = json.loads((directory / report["static_trap_source"]).read_text())
    assert recorded_traps == [{"address": "0x" + a, "instruction": value} for a, value in sorted(traps.items())]
    assert len(traps) == report["unique_static_trap_sites"]
    assert sha(source.read_bytes()) == renderer.SPEC["sha256"]
    assert all(sha((directory / name).read_bytes()) == digest for name, digest in hashes.items())
    output = ROOT / "build/renderer-generation"
    output.mkdir(parents=True, exist_ok=True)
    receipt = {"status": "PASS", "input_pin_negative_control": "PASS",
        "original_sha256": sha(raw), "private_sha256": sha(private), "pcrecomp_revision": revision,
        "source_hashes": hashes, "report_sha256": sha((directory / "report.json").read_bytes()),
        "functions": len(definitions), "merged_dispatch_entries": len(addresses),
        "unique_static_trap_sites": len(traps), "undefined_direct_symbols": 0,
        "runtime_integration": "NOT_ATTEMPTED", "execution_coverage": "UNVERIFIED"}
    (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "source_hashes"}))


if __name__ == "__main__":
    check()
