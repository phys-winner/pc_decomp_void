"""Run the shipped x86 opcode blocks, including their actual Variant cleanup.

Virtual object methods are observation stubs; operand decoding, register copies,
reference increments and sub_101DD510 execute from the original DLL bytes.
"""
from pathlib import Path
import struct

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]


def main():
    pe = pefile.PE(str(ROOT / 'original/the-void-russian/bin/win32/GameModule.dll'))
    image = pe.get_memory_mapped_image()
    base = pe.OPTIONAL_HEADER.ImageBase
    vm = Uc(UC_ARCH_X86, UC_MODE_32)
    vm.mem_map(base, (len(image) + 4095) & ~4095)
    vm.mem_write(base, image)
    vm.mem_map(0x20000000, 0x100000)
    context, frame, code = 0x20001000, 0x20002000, 0x20003000
    handle, obj, vtable = 0x20004000, 0x20005000, 0x20006000
    setter, getter, member = 0x20007000, 0x20007100, 0x20007200
    stack = 0x200e0000
    calls = []

    def read(address):
        return struct.unpack('<I', vm.mem_read(address, 4))[0]

    def write(address, value):
        vm.mem_write(address, struct.pack('<I', value))

    def variant(reg, value, kind):
        write(frame + reg * 8, value)
        write(frame + reg * 8 + 4, kind)

    def ret(arguments=0):
        sp = vm.reg_read(UC_X86_REG_ESP)
        vm.reg_write(UC_X86_REG_EIP, read(sp))
        vm.reg_write(UC_X86_REG_ESP, sp + 4 + arguments)

    def observe(uc, address, size, data):
        if address == 0x101475d0:
            # Convert the Variant object handle into an object pointer pair.
            source, dest = uc.reg_read(UC_X86_REG_ECX), uc.reg_read(UC_X86_REG_EAX)
            assert read(source + 4) & 15 in (3, 4)
            write(dest, read(read(source)))
            write(dest + 4, 0)
            ret()
        elif address == 0x10147780:
            ret()  # cdecl validation; the dispatcher removes its argument.
        elif address == 0x1000f4b0:
            ref = uc.reg_read(UC_X86_REG_EAX)
            count = struct.unpack('<H', uc.mem_read(ref + 4, 2))[0]
            assert count > 1  # This fixture retains the source elsewhere.
            uc.mem_write(ref + 4, struct.pack('<H', count - 1))
            ret()
        elif address in (setter, getter):
            sp = uc.reg_read(UC_X86_REG_ESP)
            target, key, count = read(sp + 12), read(sp + 20), read(sp + 24)
            assert count == 1
            calls.append((address, target, key, read(frame + key * 8)))
            if address == getter:
                variant(target, 765, 1)
            ret(24)
        elif address == member:
            sp = uc.reg_read(UC_X86_REG_ESP)
            variant(read(sp + 16), 876, 1)
            uc.reg_write(UC_X86_REG_EAX, 1)
            ret(16)

    vm.hook_add(UC_HOOK_CODE, observe)

    def run(address, instruction):
        write(context + 0x34, frame)
        write(context + 0x2c, frame)
        write(context + 0x14, 0x20008000)
        write(0x20008000, 0x20009000)
        write(handle, obj)
        vm.mem_write(handle + 4, struct.pack('<HH', 20, 20))
        write(obj, vtable)
        write(vtable + 0x10, getter)
        write(vtable + 0x14, setter)
        write(vtable + 0x18, member)
        vm.mem_write(code, instruction)
        for reg, value in ((UC_X86_REG_EBX, context), (UC_X86_REG_EDI, code),
                           (UC_X86_REG_EBP, stack), (UC_X86_REG_ESP, stack - 0x4000)):
            vm.reg_write(reg, value)
        vm.emu_start(address, 0x1014be7b, count=1000)
        assert vm.reg_read(UC_X86_REG_EIP) == 0x1014be7b

    # MOVE aliases the object handle, rather than copying tuple elements.
    variant(3, handle, 3)
    variant(10, 0, 5)
    run(0x10147e35, struct.pack('<II', (3 << 8) | 10, 10))
    assert read(frame + 10 * 8) == handle
    assert read(frame + 10 * 8 + 4) == 3
    assert struct.unpack('<H', vm.mem_read(handle + 4, 2))[0] == 21

    variant(9, 123, 1)
    variant(10, handle, 3)
    variant(11, 456, 1)
    run(0x1014b58d, struct.pack('<II', (10 << 8) | 59, (9 << 8) | 1))
    assert calls[-1] == (setter, 9, 11, 456)
    assert read(frame + 10 * 8 + 4) == 5  # Actual DD510 clears receiver.
    assert read(frame + 9 * 8 + 4) == 1

    variant(10, handle, 3)
    run(0x1014b4e5, struct.pack('<II', (9 << 8) | 58, 1))
    assert calls[-1][:3] == (getter, 9, 11)
    assert read(frame + 9 * 8) == 765
    assert read(frame + 10 * 8 + 4) == 5

    variant(10, handle, 3)
    run(0x1014b62f, struct.pack('<II', (9 << 8) | 60, 0))
    assert read(frame + 9 * 8) == 876
    assert read(frame + 10 * 8 + 4) == 5
    print('PASS shipped x86 MOVE alias/refcount and GET/MEMBER/STORE receiver consumption')


if __name__ == '__main__':
    main()
