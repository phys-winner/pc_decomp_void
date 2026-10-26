"""Check the six captured SM3 tutorial recipes; optionally regenerate only them."""
import argparse
import hashlib
from itertools import islice
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_shader_cache as cache

KEYS = {"38ae2c180627a3d9", "64c6a95141481acc", "6b1e07f37cd4631b",
        "6baec45b2c72e1fd", "e3ae3775dc9cedad", "eead7e2b4ae85eeb"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--reference-results", type=Path)
    args = parser.parse_args()
    manifest_path = cache.TUTORIAL_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["profile"] == "ps_3_0" and manifest["flags"] == 0x4412
    assert manifest["macros"] == "hdr_enabled=1\nprofile_ps_3_0=1\nprofile_ps=1\n"
    recipes = list(cache.tutorial_shaders())
    assert len(recipes) == 6 and {key for _, key, _ in recipes} == KEYS
    assert list(islice(cache.shaders(), 6)) == recipes, "normal cache generator must include the six recipes"
    for item, (_, key, _) in zip(manifest["shaders"], recipes):
        source = (cache.TUTORIAL_DIR / item["source"]).read_bytes()
        assert item["source"] == key + ".hlsl" and re.fullmatch(r"[0-9a-f]{64}", item["bytecode_sha256"])
        assert b"\0" not in source and not re.search(rb"^\s*#\s*include\b", source, re.M)
        assert cache.request(source + b"\n", "ps_3_0", manifest["macros"].encode(), 0x4412)[0] != key
    if not args.compile:
        print("PASS six pinned SM3 tutorial keys; normal generator inclusion; source mutation changes key")
        return
    cache.WORK.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tutorial-shader-test-", dir=ROOT / "build"))
    requests, results = work / "requests", work / "results"
    requests.mkdir(); results.mkdir()
    for _, key, data in recipes:
        (requests / (key + ".req")).write_bytes(data)
    compiler = cache.build_tool()
    run = subprocess.run([str(compiler), str(requests), str(results)], cwd=work, capture_output=True)
    (work / "stdout.txt").write_bytes(run.stdout)
    (work / "stderr.txt").write_bytes(run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    assert {p.name for p in results.iterdir()} == {key + ".bin" for key in KEYS}
    cache.verify_tutorial_bytecode(results)
    rows = []
    for item in manifest["shaders"]:
        key = item["key"]; binary = (results / (key + ".bin")).read_bytes()
        assert len(binary) % 4 == 0 and struct.unpack_from("<I", binary)[0] == 0xFFFF0300
        assert struct.unpack_from("<I", binary, len(binary) - 4)[0] == 0xFFFF
        if args.reference_results:
            assert binary == (args.reference_results / (key + ".bin")).read_bytes()
        rows.append(dict(key=key, source_sha256=sha((cache.TUTORIAL_DIR / item["source"]).read_bytes()),
                         request_sha256=sha((requests / (key + ".req")).read_bytes()),
                         result_size=len(binary), result_sha256=sha(binary)))
    damaged = results / (manifest["shaders"][0]["key"] + ".bin")
    original = damaged.read_bytes()
    try:
        damaged.write_bytes(original + b"\0")
        try:
            cache.verify_tutorial_bytecode(results)
        except AssertionError:
            pass
        else:
            raise AssertionError("damaged bytecode accepted")
    finally:
        damaged.write_bytes(original)
    cache.verify_tutorial_bytecode(results)
    receipt = dict(status="passed", compile_count=6, manifest_sha256=sha(manifest_path.read_bytes()),
                   generator_sha256=sha(Path(cache.__file__).read_bytes()), compiler_sha256=sha(compiler.read_bytes()),
                   reference_results=str(args.reference_results.resolve()) if args.reference_results else None,
                   reference_comparison="byte_exact" if args.reference_results else "manifest_sha256",
                   negative_control="damaged bytecode rejected", canonical_cache_modified=False,
                   device_operations=False, requests=rows)
    output = work / "receipt.json"
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(dict(status="passed", compiled=6, receipt=str(output), sha256=sha(output.read_bytes()))))


if __name__ == "__main__":
    main()
