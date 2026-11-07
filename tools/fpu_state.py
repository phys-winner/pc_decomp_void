"""Compile the 2009 Android CRT's x87 save/restore sites from their pinned opcodes."""
import re

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from capstone.x86_const import X86_OP_MEM

STATE_NOP = re.compile(rb'/\* (fnsave|fsave|frstor): FPU state is not a memory image here \*/ '
                       rb'/\* 0x([0-9A-F]{8}): [^\r\n]*? \*/')


def state_instruction(instruction):
    """Same checked route as BioShock; unsupported addressing must not become a no-op."""
    from lift_game import CheckedLifter

    prefixes = []
    for byte in instruction.bytes:
        if byte not in (0xF0, 0xF2, 0xF3, 0x2E, 0x36, 0x3E, 0x26, 0x64, 0x65, 0x66, 0x67, 0x9B):
            break
        prefixes.append(byte)
    if (instruction.mnemonic not in ('fnsave', 'fsave', 'frstor') or
            len(instruction.operands) != 1 or instruction.operands[0].type != X86_OP_MEM or
            any(byte in prefixes for byte in (0xF0, 0xF2, 0xF3, 0x67))):
        raise ValueError(f'unsupported x87 state instruction at {instruction.address:08X}')
    address = CheckedLifter()._fmt_mem_addr(instruction.operands[0].mem)
    return ('{ extern void void_fpu_state(uint32_t, uint32_t, int, int); '
            f'void_fpu_state((uint32_t)({address}), 0x{instruction.address:08X}u, '
            f'{int(instruction.mnemonic == "frstor")}, {int(0x66 in prefixes)}); }} '
            f'/* 0x{instruction.address:08X}: {instruction.mnemonic} {instruction.op_str} */').encode()


def patch_fpu_state(text, image):
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    decoder.detail = True

    def replace(match):
        address = int(match[2], 16)
        code = b''
        for start, _, raw, size in image.sections:
            offset = address - start
            if 0 <= offset < size:
                code = image.data[raw + offset:raw + min(offset + 15, size)]
                break
        instruction = next(decoder.disasm(code, address, count=1), None)
        if instruction is None or instruction.mnemonic.encode() != match[1]:
            raise ValueError(f'x87 save/restore comment differs from its pinned image at {address:08X}')
        return state_instruction(instruction)

    return STATE_NOP.sub(replace, text)
