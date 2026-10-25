"""Find `jmp [reg*4 + table]` sites whose table holds targets the lifted body
has no label for (the decoder sized the table too short, as for the gscript
VM's unbounded opcode table): such a target traps at run time as an
unresolved control-flow target. Prints a suggested jump-tables declaration.

    python tools/check_jump_tables.py generated/tension [--image-dir generated/tension/input]
"""
import argparse
import json
from pathlib import Path
import re
import struct

import pefile

JUMP = re.compile(r"MEM32\((e[a-d]x|e[sd]i|ebp) \* 4 \+ 0x([0-9A-F]{8})\)\); goto _ljump;")
FUNC = re.compile(r"^void sub_([0-9A-F]{8})\(void\) \{$", re.M)
LABEL = re.compile(r"^L_([0-9A-F]{8}):", re.M)


def image_reader(path):
    pe = pefile.PE(str(path), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    data = pe.get_memory_mapped_image()
    code = [(base + s.VirtualAddress, base + s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData))
            for s in pe.sections if s.Characteristics & 0x20000000]
    return base, data, code


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("generated", type=Path)
    args = parser.parse_args()
    release = json.loads((args.generated / "release.json").read_text())
    findings = {}
    for prefix in release["modules"]:
        directory = args.generated / f"{prefix}-x86"
        report = json.loads((directory / "report.json").read_text())
        base, data, code = image_reader(Path(release["images"][prefix]))
        original_base = int(report["original_base"], 16)
        for name in report["sources"]:
            text = (directory / name).read_text()
            starts = [(m.start(), m.group(1)) for m in FUNC.finditer(text)]
            for i, (start, func) in enumerate(starts):
                end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
                body = text[start:end]
                jumps = set(JUMP.findall(body))
                if not jumps:
                    continue
                labels = {int(l, 16) for l in LABEL.findall(body)}
                low, high = int(func, 16), max(labels) if labels else int(func, 16)
                for _, table in jumps:
                    table = int(table, 16)
                    missing, count, nulls = [], 0, 0
                    for index in range(256):
                        off = table - base + 4 * index
                        if off + 4 > len(data):
                            break
                        target = struct.unpack_from("<I", data, off)[0]
                        if target == 0:
                            nulls += 1
                            if nulls > 4:
                                break
                            count = index + 1
                            continue
                        if not any(a <= target < b for a, b in code) or not low <= target <= high + 0x4000:
                            break
                        count = index + 1
                        if target not in labels:
                            missing.append(target)
                    if missing:
                        key = (prefix, table)
                        findings[key] = {"module": prefix, "function": "0x" + func,
                                         "table": hex(table - base + original_base), "live_table": hex(table),
                                         "count": count, "missing": [hex(m) for m in missing[:8]], "missing_count": len(missing)}
    for f in findings.values():
        print(json.dumps(f))
    print(f"{len(findings)} tables with unlabelled targets")


if __name__ == "__main__":
    main()
