"""Run the original damage-particle offset and cleanup with nullable attackers."""
from pathlib import Path
import runpy
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from gscript_binary import Module
from patch_scripts import PATCHES, append, jump_patch, patch_damage_limfa_target, read_entry, rows_of
from patch_native_menu import Assembler

VM = runpy.run_path(str(ROOT / "tests/test_touch_native.py"))["VM"]
NAME = "Scripts\\fx\\fx_player_damage_limfa.bin"


class ConsumingBranchVM(VM):
    """Keep the shared test VM unchanged; model this proven branch lifetime."""
    def run(self, start, regs=None, stops=()):
        regs = dict(regs or {})
        pc = start + 8 if self.rows[start].get("header") else start
        branches = {at for at, row in self.rows.items() if row.get("opcode") in (55, 56)}
        for _ in range(100):
            if pc in stops:
                return pc, regs
            row = self.rows[pc]
            if row.get("opcode") in (55, 56):
                value = regs.get(row["register"])
                # Guest object truth tests pointer liveness, not collection
                # length. Even an empty string/container has a live handle.
                condition = True if isinstance(value, (str, dict, list, tuple)) else bool(value)
                # Native tags3/4 are consumed even when their object is live.
                if value is not None and not isinstance(value, (bool, int, float)):
                    regs.pop(row["register"], None)
                pc = row["operands"][0] if condition == (row["opcode"] == 56) else pc + row["size"]
            else:
                pc, regs = super().run(pc, regs, stops=tuple(branches | set(stops)))
                if pc is None:
                    return None, regs
        raise AssertionError("branch fixture exceeded instruction budget")


def shipped_branch_probe():
    """Execute actual x86 JZ/JNZ + conversion + refcount code, without stubs."""
    import pefile
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
    from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EBX, UC_X86_REG_EDI
    pe = pefile.PE(str(ROOT / "original/the-void-russian/bin/win32/GameModule.dll"))
    image, base = pe.get_memory_mapped_image(), pe.OPTIONAL_HEADER.ImageBase
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(base, (len(image) + 4095) & ~4095)
    uc.mem_write(base, image)
    uc.mem_map(0x20000000, 0x100000)
    context, frame, code, handle = 0x20001000, 0x20002000, 0x20003000, 0x20004000
    obj, stack = 0x20005000, 0x200e0000
    def put(at, value): uc.mem_write(at, struct.pack("<I", value))
    def get(at): return struct.unpack("<I", uc.mem_read(at, 4))[0]
    count = 0
    for opcode, address in ((55, 0x1014bbdf), (56, 0x1014bc13)):
        for kind, value, truth in ((0, 0, False), (0, 1, True), (1, 0, False), (1, 7, True),
                                   (2, 0, False), (2, 0x3fc00000, True), (5, 0, False),
                                   (3, 0, False), (4, 0, False),
                                   (3, handle, True), (4, handle, True),
                                   (3, handle, False), (4, handle, False)):
            put(context + 0x34, frame)
            put(context + 0x1c, code)
            put(stack - 0x24, code)
            put(frame + 3 * 8, value)
            put(frame + 3 * 8 + 4, kind)
            put(handle, obj if truth else 0)
            uc.mem_write(handle + 4, struct.pack("<HH", 20, 20))
            uc.mem_write(code, struct.pack("<II", (3 << 8) | opcode, 0x80))
            for reg, value_reg in ((UC_X86_REG_EBP, stack), (UC_X86_REG_ESP, stack - 0x4000),
                                   (UC_X86_REG_EBX, context), (UC_X86_REG_EDI, code)):
                uc.reg_write(reg, value_reg)
            uc.emu_start(address, 0x1014be7e, count=500)
            target = code + 0x80 if truth == (opcode == 56) else code + 8
            assert uc.reg_read(UC_X86_REG_EDI) == target
            assert get(stack - 0x24) == target
            assert get(frame + 3 * 8 + 4) == (5 if kind in (3, 4) else kind)
            if value == handle:
                strong, weak = struct.unpack("<HH", uc.mem_read(handle + 4, 4))
                assert (strong, weak) == ((19, 20) if kind == 3 else (20, 19))
            count += 1
    return count


def main():
    native_branches = shipped_branch_probe()
    comparisons = 0
    for lang, index in (("ru", "research/vfs-index.json"), ("de", "research/vfs-index.german.json")):
        original = Module(read_entry(index, NAME))
        patched = Module(original.encode())
        info = patch_damage_limfa_target(patched, lang)
        assert patched.contexts == original.contexts and patched.table == original.table
        assert patched.types == original.types and patched.pool == original.pool and patched.debug == original.debug
        site = int(info["sites"][0], 16)
        cleanup_transition = int(info["null_target_transition"], 16)
        assert all(a == b for i, (a, b) in enumerate(zip(original.code, patched.code))
                   if not site <= i < site + 8)
        rows = rows_of(original)
        name = next(i for i, row in enumerate(rows) if row.get("text") == "getLimfaTargetOffset")
        finish = rows[name + 3]["offset"]
        assert rows[name + 1]["opcode"] == 57 and rows[name + 2]["opcode"] == 76

        def execute(module, offset):
            trace = []
            def call_def(default, method):
                assert method == "getLimfaTargetOffset"
                trace.append((method, default))
                return default if offset is None else offset
            vm = ConsumingBranchVM(module, globals={1: {"callDef": call_def}}, named={"!vec3": lambda x, y, z: (x, y, z)})
            end, regs = vm.run(site, {0: 5.0, 9: "unrelated"}, stops=(finish,))
            return end, regs, trace

        # The normal hit target's authored override and default have exactly
        # the original call arguments, result, register cleanup and lifetime.
        for value in (None, (0, .5, 0), (1, 2, 3), (-12.5, 0, 44.25)):
            before, after = execute(original, value), execute(patched, value)
            assert before == after, (lang, value, before, after)
            assert after[0] == finish and after[1][0] == 5.0 and after[1][9] == "unrelated"
            comparisons += 1

        # Reproduce the C10 regression independently: testing an object and
        # reusing the consumed condition must fail on an otherwise live target.
        buggy = Module(original.encode())
        a = Assembler(buggy)
        a.raw(original.code[site:site + 8])
        a.emit(55, 3, cleanup_transition)
        a.emit(54, 0, site + 8)
        jump_patch(buggy, bytes(original.code), site, 8, append(buggy, a))
        try:
            execute(buggy, None)
        except AttributeError as error:
            assert "NoneType" in str(error) and "callDef" in str(error)
        else:
            raise AssertionError("C10 consumed-receiver regression was not reproduced")
        comparisons += 1

        # A real null attacker reproduces line68 on the original module.
        try:
            ConsumingBranchVM(original, globals={1: None}).run(site, {0: 5.0})
        except AttributeError as error:
            assert "NoneType" in str(error) and "callDef" in str(error)
        else:
            raise AssertionError("original null-target callback was not reproduced")
        vm = ConsumingBranchVM(patched, globals={1: None})
        end, regs = vm.run(site, {0: 5.0})
        assert end is None and vm.transition == (4, 816, ()) and regs[0] == 5.0
        assert ConsumingBranchVM(patched, globals={1: None}).run(site, stops=(cleanup_transition,))[0] == cleanup_transition
        comparisons += 1

        # False scalar sentinels/expired references follow the same authored
        # retirement branch. Truthy invalid input still reports an error,
        # rather than having its failure globally hidden by the patch.
        class DeadReference:
            def __bool__(self): return False
        for target in (False, 0, 0.0, DeadReference()):
            vm = ConsumingBranchVM(patched, globals={1: target})
            vm.run(site)
            assert vm.transition == (4, 816, ())
            comparisons += 1
        for target in (True, 1, 1.5, "not-an-actor", "", {}):
            for module in (original, patched):
                try:
                    ConsumingBranchVM(module, globals={1: target}).run(site)
                except (AttributeError, KeyError):
                    pass
                else:
                    raise AssertionError("truthy invalid target was silently accepted")
            comparisons += 1

        # Continue through that exact original cleanup state: stop emission,
        # retain its one-second drain, remove the particle and its rigid actor.
        cleanup = next(row for row in rows if row["offset"] == cleanup_transition)
        state = cleanup["operands"][0]
        code = [row for row in rows if state < row["offset"] < 1000]
        wait = next(row["operands"][0] for row in code if row["opcode"] == 63)
        actions = []
        particle = {"setSysParameterFloat": lambda *args: actions.append(("period", *args)),
                    "remove": lambda: actions.append(("particle-remove",))}
        def wait_one_second(regs, base):
            assert regs[base - 1] == 1000000
            actions.append(("wait", 1000000))
        vm = VM(patched, globals={0: particle}, named={"setKinematic": lambda value: actions.append(("kinematic", value)),
                                                     "remove": lambda: actions.append(("actor-remove",))},
                calls={wait: wait_one_second})
        vm.run(state)
        assert actions == [("kinematic", True), ("period", 0, "PPeriod", 1000000),
                           ("wait", 1000000), ("particle-remove",), ("actor-remove",)]
        comparisons += 1
        combined = Module(original.encode())
        dict(PATCHES)[NAME](combined, lang)
        assert combined.contexts == original.contexts and combined.types == original.types
        list(Module(combined.encode()).instructions())
    print(f"PASS damage limfa target: {comparisons} RU/DE fixtures; {native_branches} shipped x86 JZ/JNZ cases; "
          "original null and C10 consumed-receiver failures reproduced; live offset/default calls preserved; "
          "targetless particles use original timed cleanup; metadata preserved")


if __name__ == "__main__":
    main()
