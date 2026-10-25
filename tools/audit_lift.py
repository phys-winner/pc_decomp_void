"""Audit emitter gaps in IDA function extents; this does not certify a game lift."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY = ROOT / "reference/pcrecomp"


def function_rows(value):
    """Accept direct rows and the MCP result/data/content envelopes."""
    if isinstance(value, list):
        for item in value:
            yield from function_rows(item)
    elif isinstance(value, dict):
        if "addr" in value and "size" in value:
            yield value
        else:
            for key in ("result", "data", "content", "structuredContent"):
                if key in value:
                    yield from function_rows(value[key])
            if value.get("type") == "text" and "text" in value:
                yield from function_rows(value["text"])
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return
        if not isinstance(decoded, str):
            yield from function_rows(decoded)


def number(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def union_bytes(ranges):
    total, end = 0, -1
    for start, stop in sorted(ranges):
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def hazards(instruction, fpu_group, memory_type):
    m = instruction.mnemonic.split()[-1]
    result = []
    if m == "std":
        result.append("direction_flag_set_ignored")
    if m in ("fldcw", "fnstcw"):
        result.append("x87_control_word_ignored_or_constant")
    if m in ("ldmxcsr", "stmxcsr"):
        result.append("sse_control_word_ignored_or_constant")
    if m in ("fldenv", "fnstenv"):
        result.append("x87_environment_ignored")
    if m in ("fninit", "finit", "fnclex", "fclex"):
        result.append("x87_initialization_or_exceptions_ignored")
    if instruction.group(fpu_group):
        result.append("x87_double_register_precision")
    if any(op.type == memory_type and op.size == 10 for op in instruction.operands):
        result.append("x87_80bit_memory_reduced_to_double")
    return result


def audit_module(catalog, binary, analyze_pe, Disassembler, lift32_cpu, x86):
    rows = list(function_rows(json.loads(catalog.read_text(encoding="utf-8"))))
    if not rows:
        raise ValueError(f"No functions in {catalog}")
    funcs = {}
    for row in rows:
        start, size = number(row["addr"]), number(row["size"])
        if not (0 <= start <= 0xFFFFFFFF and 0 < size <= 0x10000000):
            raise ValueError(f"Invalid function extent in {catalog}: {row}")
        if start in funcs and funcs[start] != size:
            raise ValueError(f"Conflicting extents at {start:#x}")
        funcs[start] = size
    raw = binary.read_bytes()
    info = analyze_pe(str(binary))
    if info.pe_type != "PE32":
        raise ValueError(f"Expected PE32: {binary}")
    reader = Disassembler(raw, info.image_base, info.sections)
    image_end = max(info.image_base + s.va_end for s in info.sections)
    lift32_cpu.IMAGE_BASE = info.image_base
    lf = lift32_cpu.Lifter(str(binary), image_end - info.image_base, reader.read_bytes)
    import_slots = {info.image_base + i.iat_rva for i in info.imports}
    records, gaps, failures, function_status = {}, [], [], Counter()
    emitted_dispatches = 0
    ranges = []
    for start, size in sorted(funcs.items()):
        code = reader.read_bytes(start, size)
        if code is None or len(code) != size:
            gaps.append({"address": hex(start), "size": size, "reason": "not_file_backed"})
            continue
        ranges.append((start, start + size))
        instructions = list(lf.md.disasm(code, start))
        decoded = sum(i.size for i in instructions)
        if decoded != size:
            gaps.append({"address": hex(start), "size": size, "decoded": decoded,
                         "reason": "linear_decode_stopped"})
        for ins in instructions:
            key = (ins.address, ins.size, bytes(ins.bytes).hex())
            if key not in records:
                records[key] = {"address": hex(ins.address), "bytes": ins.bytes.hex(),
                                "size": ins.size, "mnemonic": ins.mnemonic,
                                "operands": ins.op_str,
                                "hazards": hazards(ins, x86.X86_GRP_FPU, x86.X86_OP_MEM)}
                if ins.mnemonic.split()[-1] == "call":
                    op = ins.operands[0]
                    if op.type == x86.X86_OP_IMM:
                        records[key]["call"] = ("direct_catalogued_target" if op.imm in funcs
                                                else "direct_target_missing_from_catalog")
                        records[key]["target"] = hex(op.imm & 0xFFFFFFFF)
                    elif (op.type == x86.X86_OP_MEM and not op.mem.base and not op.mem.index
                          and (op.mem.disp & 0xFFFFFFFF) in import_slots):
                        records[key]["call"] = "iat_import_requires_runtime"
                    else:
                        records[key]["call"] = "indirect_target_unresolved"
        try:
            emitted = lf.lift_function(code, start)
        except Exception as error:
            failures.append({"address": hex(start), "size": size,
                             "error": f"{type(error).__name__}: {error}"})
            function_status["emitter_exception"] += 1
            continue
        todo = {int(a, 16) for a in re.findall(r"RECOMP_TODO\((0x[0-9A-Fa-f]+)", emitted)}
        for ins in instructions:
            if ins.address in todo:
                records[(ins.address, ins.size, bytes(ins.bytes).hex())]["todo"] = True
        function_status["emitted_with_todo" if todo else "emitted_without_todo"] += 1
        emitted_dispatches += len(re.findall(r"\bdispatch(?:_jmp)?\(", emitted))
    unique = list(records.values())
    unsupported = [r for r in unique if r.get("todo")]
    hazardous = [r for r in unique if r["hazards"]]
    instruction_union = union_bytes((number(r["address"]), number(r["address"]) + r["size"])
                                    for r in unique)
    return {"module": binary.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "catalog": str(catalog.relative_to(ROOT)),
            "catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
            "catalog_rows": len(rows), "functions": len(funcs),
            "function_status": dict(function_status),
            "function_extent_bytes": sum(size for _, size in funcs.items()),
            "function_extent_union_bytes": union_bytes(ranges),
            "unique_decoded_instructions": len(unique),
            "unique_decoded_instruction_bytes": instruction_union,
            "unique_mnemonics": dict(Counter(r["mnemonic"] for r in unique).most_common()),
            "explicit_todo_instructions": len(unsupported),
            "todo_mnemonics": dict(Counter(r["mnemonic"] for r in unsupported).most_common()),
            "todo_sites": unsupported, "semantic_limit_sites": hazardous,
            "semantic_limit_counts": dict(Counter(h for r in unique for h in r["hazards"]).most_common()),
            "call_sites": dict(Counter(r["call"] for r in unique if "call" in r)),
            "generated_dispatch_sites_with_overlap": emitted_dispatches,
            "decode_or_file_gaps": gaps, "emitter_exceptions": failures,
            "certified_supported_instructions": None,
            "whole_game_supported": False}


def selftest():
    nested = {"result": [{"data": [{"addr": "0x1000", "size": "0x3"}]}]}
    wrapped = {"content": [{"type": "text", "text": json.dumps(nested)}]}
    assert list(function_rows(wrapped)) == [{"addr": "0x1000", "size": "0x3"}]
    assert union_bytes([(1, 5), (3, 9), (10, 12)]) == 10
    assert number("0x20") == 32
    sys.path.insert(0, str(DEPENDENCY))
    from tools.lift import lift32_cpu
    from capstone import x86_const as x86
    lf = lift32_cpu.Lifter(None, 0x10000)
    std = next(lf.md.disasm(b"\xfd", 0x1000))
    assert hazards(std, x86.X86_GRP_FPU, x86.X86_OP_MEM) == ["direction_flag_set_ignored"]
    cw = next(lf.md.disasm(b"\xd9\x2d\x00\x20\x00\x00", 0x1000))
    assert "x87_control_word_ignored_or_constant" in hazards(cw, x86.X86_GRP_FPU, x86.X86_OP_MEM)
    unsupported = lf.lift_function(b"\x0f\x0b", 0x1000)  # ud2 must be counted, never called supported.
    assert "RECOMP_TODO(0x00001000" in unsupported
    print("audit_lift selftest: PASS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    dependency = json.loads((ROOT / "dependencies.json").read_text())["pcrecomp"]
    revision = subprocess.check_output(["git", "-C", str(DEPENDENCY), "rev-parse", "HEAD"],
                                       text=True).strip()
    if revision != dependency["revision"]:
        raise ValueError("pcrecomp revision differs from dependencies.json")
    sys.path.insert(0, str(DEPENDENCY))
    from tools.pe.pe_analyze import analyze_pe
    from tools.disasm.disasm32 import Disassembler
    from tools.lift import lift32_cpu
    from capstone import x86_const as x86
    config = json.loads((ROOT / "port.json").read_text())
    game_bin = Path(config["game_directory"]) / "bin/win32"
    catalogs = sorted((ROOT / "research/ida").glob("*.functions.json"))
    if not catalogs:
        raise ValueError("No completed IDA function catalogs")
    modules = []
    for catalog in catalogs:
        stem = catalog.name.removesuffix(".functions.json")
        binary = next((directory / (stem + ext) for directory in (game_bin, catalog.parent)
                       for ext in (".dll", ".exe")
                       if (directory / (stem + ext)).is_file()), None)
        if binary is None:
            raise ValueError(f"No original module for {catalog}")
        module = audit_module(catalog, binary, analyze_pe, Disassembler, lift32_cpu, x86)
        modules.append(module)
        print(f"{binary.name}: {module['functions']} functions, "
              f"{module['unique_decoded_instructions']} unique decoded instructions, "
              f"{module['explicit_todo_instructions']} explicit TODO, "
              f"{len(module['emitter_exceptions'])} emitter exceptions", flush=True)
    report = {"pcrecomp_revision": revision, "lifter": "lift32_cpu",
              "audit": "static emitter census, not execution",
              "limitations": ["IDA extents can include data, padding or function chunks; linear decode is not reachability.",
                              "Instruction starts deduplicated per module; overlap byte unions avoid double counting.",
                              "Emitting without TODO does not establish bit-exact semantics or compilable C.",
                              "TODO sites are counted only for completely emitted functions; emitter exceptions may hide additional sites.",
                              "Calls, imported APIs, callbacks, exceptions and indirect targets are not closed.",
                              "Function-tail extension performed by the upstream emitter can go outside catalog extents.",
                              "No module has been fully generated, compiled or executed by this audit."],
              "modules": modules, "whole_game_supported": False}
    (ROOT / "research/lift-coverage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Static emitter audit", "", f"pcrecomp: `{revision}`", "",
             "This measures emitter gaps in completed IDA catalogs. It does not certify supported game code.", "",
             "| Module | Functions | Unique decoded instructions | Explicit TODO sites | Emitter exceptions |",
             "|---|---:|---:|---:|---:|"]
    for m in modules:
        lines.append(f"| {m['module']} | {m['functions']} | {m['unique_decoded_instructions']} | "
                     f"{m['explicit_todo_instructions']} | {len(m['emitter_exceptions'])} |")
    for m in modules:
        lines += ["", f"## {m['module']}", "", "TODO mnemonics: " + json.dumps(m["todo_mnemonics"]),
                  "", "Semantic limits: " + json.dumps(m["semantic_limit_counts"]),
                  "", "Call sites (every category still requires closure): " + json.dumps(m["call_sites"]),
                  "", f"Decode/file gaps: {len(m['decode_or_file_gaps'])}; extent byte sum "
                  f"{m['function_extent_bytes']}, union {m['function_extent_union_bytes']}."]
    lines += ["", *["- " + limit for limit in report["limitations"]], "",
              "No whole-game support percentage is claimed. See lift-coverage.json for all TODO and semantic-limit sites."]
    (ROOT / "research/lift-coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
