"""Disassemble N instructions of a PE image at a VA, annotating string operands: x86dis.py IMAGE VA N"""
import sys, pefile, capstone, json
path, start, count = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3])
pe = pefile.PE(path, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = False
strings = {}
def s_at(va):
    off = va - base
    if 0 <= off < len(data):
        raw = data[off:off+120]
        end = raw.find(b'\0')
        if end > 3:
            try:
                t = raw[:end].decode('ascii')
                if all(32 <= ord(c) < 127 for c in t): return t
            except: pass
        # utf16
        try:
            end = raw.find(b'\0\0')
            t = raw[:end+ (end % 2)].decode('utf-16le')
            if len(t) > 3 and all(32 <= ord(c) < 127 for c in t): return 'L"' + t + '"'
        except: pass
    return None
n = 0
for insn in md.disasm(data[start - base:start - base + count * 16], start):
    extra = ''
    for tok in insn.op_str.replace(',', ' ').replace('[', ' ').replace(']', ' ').split():
        if tok.startswith('0x') and len(tok) >= 9:
            s = s_at(int(tok, 16))
            if s: extra = '   ; "' + s + '"'
    print('%08X: %-8s %s%s' % (insn.address, insn.mnemonic, insn.op_str, extra))
    n += 1
    if n >= count: break
