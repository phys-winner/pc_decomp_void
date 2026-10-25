"""Preserve exact-int64 shadows and shared x87 conditions in a pinned runtime copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR_REVISION = '904ac3129d0c9d05efbeec19a1dce6abbe7f5d26'
VENDOR_SHA256 = 'b1b5008f75b6d1174ae9727566ca4d1c1796a6f45c3c030e0bd3c5ecf0a751bb'
SOURCE = ROOT / 'reference/pcrecomp/runtime/native32/native32.c'
OUTPUT = ROOT / 'generated/native-runtime/native32.c'
PATCHES = (
    (b'    double   st[8];', b'\n    int64_t  st_i64[8];\n    int      fpu_cmp;'),
    (b'    memcpy(r->st, g_st, sizeof g_st); r->fp_top = g_fp_top; r->fpu_cw = g_fpu_cw;',
     b'\n    memcpy(r->st_i64, g_st_i64, sizeof g_st_i64);\n    r->fpu_cmp = void_fpu_cmp;'),
    (b'    memcpy(g_st, r->st, sizeof g_st); g_fp_top = r->fp_top; g_fpu_cw = r->fpu_cw;',
     b'\n    memcpy(g_st_i64, r->st_i64, sizeof g_st_i64);\n    void_fpu_cmp = r->fpu_cmp;'),
    (b'        m->r.fpu_cw = 0x027F;', b'\n        m->r.fpu_cmp = 1;'),
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def patch_runtime(raw):
    if sha(raw) != VENDOR_SHA256:
        raise ValueError('Pinned vendor native32.c SHA256 mismatch')
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    patched = raw
    for anchor, addition in PATCHES:
        if raw.count(anchor) != 1:
            raise ValueError('Expected exactly one pinned runtime patch anchor')
        patched = patched.replace(anchor, anchor + addition.replace(b'\n', newline), 1)
    restored = patched
    for anchor, addition in reversed(PATCHES):
        edited = anchor + addition.replace(b'\n', newline)
        if restored.count(edited) != 1:
            raise ValueError('Private runtime patch roundtrip anchor mismatch')
        restored = restored.replace(edited, anchor, 1)
    if restored != raw:
        raise ValueError('Private runtime contains changes outside the pinned insertions')
    return patched


def atomic_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == raw:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        pending = Path(handle.name)
        handle.write(raw)
    try:
        os.replace(pending, path)
    finally:
        if pending.exists():
            pending.unlink()


def prepare(output=OUTPUT, check=False):
    output = Path(output).resolve()
    if not any(output.is_relative_to((ROOT / directory).resolve()) for directory in ('generated', 'build')):
        raise ValueError('Private runtime output must belong to the project generated or build directories')
    revision = subprocess.run(['git', '-C', str(ROOT / 'reference/pcrecomp'),
                               'rev-parse', 'HEAD'], text=True, capture_output=True, check=True).stdout.strip()
    if revision != VENDOR_REVISION:
        raise ValueError('Pinned pcrecomp revision mismatch')
    original = SOURCE.read_bytes()
    private = patch_runtime(original)
    receipt = {'vendor_revision': revision, 'vendor_sha256': sha(original),
               'private_sha256': sha(private), 'insertions': len(PATCHES),
               'changes': ['regs_t.st_i64[8]', 'regs_save exact-int64 copy',
                           'regs_load exact-int64 copy', 'regs_t.fpu_cmp',
                           'regs_save/load shared-condition copy',
                           'new-thread clear conditions'], 'vendor_unchanged': True}
    receipt_path = output.with_name('runtime-receipt.json')
    if check:
        if output.read_bytes() != private or json.loads(receipt_path.read_text()) != receipt:
            raise ValueError('Private runtime or receipt differs from the pinned transform')
    else:
        atomic_write(output, private)
        atomic_write(receipt_path, (json.dumps(receipt, indent=2) + '\n').encode())
    if SOURCE.read_bytes() != original:
        raise ValueError('Vendor runtime changed during preparation')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    receipt = prepare(args.output.resolve(), args.check)
    print(f'Private native32 snapshot fix: {receipt["private_sha256"]} ({len(PATCHES)} insertions; vendor unchanged)')


if __name__ == '__main__':
    main()
