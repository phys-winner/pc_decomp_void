"""Cache reuse requires matching source/header/compiler/options and object bytes."""
import copy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_x86_incremental as build


def main():
    output = ROOT / "build/x86"
    output.mkdir(parents=True, exist_ok=True)
    checks = 0
    with tempfile.TemporaryDirectory(prefix="incremental-cache-test-", dir=output) as temporary:
        folder = Path(temporary).resolve()
        assert folder.is_relative_to(output.resolve())
        object_path = folder / "probe.obj"
        object_path.write_bytes(b"pinned object")
        source, source_hash = "generated/renderer-x86/renderer_0000.c", "1" * 64
        headers = {"native/recomp_types.h": "2" * 64}
        compiler = {"path": "cl.exe", "sha256": "3" * 64, "sdk": "test-sdk"}
        options = ["/O2", "/DRECOMP_TRACE"]
        digest = build.fingerprint(source_hash, headers, compiler, options)
        entry = {"fingerprint": digest, "object": build.key(object_path), "object_sha256": build.sha(object_path)}
        assert build.valid_object(entry, digest); checks += 1
        changes = [("4" * 64, headers, compiler, options),
            (source_hash, {"native/recomp_types.h": "5" * 64}, compiler, options),
            (source_hash, {**headers, "added.h": "6" * 64}, compiler, options),
            (source_hash, headers, {**compiler, "sha256": "7" * 64}, options),
            (source_hash, headers, {**compiler, "sdk": "other-sdk"}, options),
            (source_hash, headers, compiler, ["/O1", "/DRECOMP_TRACE"])]
        for values in changes:
            assert not build.valid_object(entry, build.fingerprint(*values)); checks += 1
        assert not build.valid_object({}, digest); checks += 1
        assert not build.valid_object({"fingerprint":digest,"object_sha256":"0"*64}, digest); checks += 1
        assert not build.valid_object([entry], digest); checks += 1
        assert not build.valid_object({**entry, "object_sha256": "0" * 64}, digest); checks += 1
        receipt = {"status": "COMPILED", "source_hashes_unchanged": True, "mode": "global-offset",
            "compiler": compiler["path"], "compiler_sha256": compiler["sha256"], "sdk": compiler["sdk"],
            "options": options, "source_hashes": {source.replace("/", "\\"): source_hash, **headers},
            "results": [{"source": source.replace("/", "\\"), "exit": 0, "optimization": "/O2",
                "object": build.key(object_path), "object_sha256": build.sha(object_path)}]}
        assert build.renderer_import(source, source_hash, headers, compiler, options, receipt) == entry; checks += 1
        for name, value in (("status", "FAILED"), ("source_hashes_unchanged", False),
                ("mode", "local-flat"), ("compiler_sha256", "0" * 64), ("sdk", "other-sdk"),
                ("options", ["/O1"]), ("source_hashes", {source: source_hash})):
            changed = copy.deepcopy(receipt)
            changed[name] = value
            assert build.renderer_import(source, source_hash, headers, compiler, options, changed) is None
            checks += 1
        changed = copy.deepcopy(receipt)
        changed["results"][0]["object_sha256"] = None
        assert build.renderer_import(source, source_hash, headers, compiler, options, changed) is None; checks += 1
        object_path.write_bytes(b"different object")
        assert not build.valid_object(entry, digest); checks += 1
        assert build.renderer_import(source, source_hash, headers, compiler, options, receipt) is None; checks += 1
    result = {"status": "PASS", "checks": checks, "no_game_or_compiler_executed": True}
    (output / "incremental-cache-test.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__": main()
