"""Tracked catalog works without IDA files, across checkout line endings."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lift_gamemodule


def main():
    catalog = json.loads((ROOT / "config/GameModule.functions.json").read_text())
    text = json.dumps(catalog, indent=1) + "\n"
    with tempfile.TemporaryDirectory(prefix="catalog-check-") as directory:
        checkout = Path(directory)
        source = checkout / "config/GameModule.functions.json"
        source.parent.mkdir()
        with patch.object(lift_gamemodule, "ROOT", checkout):
            for newline in ("\n", "\r\n"):
                raw = text.replace("\n", newline).encode()
                source.write_bytes(raw)
                actual, digest = lift_gamemodule.load_catalog()
                assert actual == catalog and digest == hashlib.sha256(raw).hexdigest()
                assert not (checkout / "research").exists()
                assert source.read_bytes() == raw
            catalog[0]["address"] += 1
            source.write_text(json.dumps(catalog))
            try:
                lift_gamemodule.load_catalog()
            except ValueError as error:
                assert str(error) == "Normalized GameModule catalog hash mismatch"
            else:
                raise AssertionError("Modified function address passed the catalog pin")
    print("PASS: tracked GameModule catalog needs no IDA files; LF/CRLF accepted, altered VA rejected")


if __name__ == "__main__":
    main()
