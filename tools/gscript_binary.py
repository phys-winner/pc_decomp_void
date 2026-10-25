"""Bounded reader for the shipped gscript binary layout; no game execution."""
import hashlib
import json
import struct
from pathlib import Path


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def p32(value):
    return struct.pack('<I', value & 0xffffffff)


class Module:
    def __init__(self, data, legacy=False):
        self.legacy = legacy
        self.original = bytes(data)
        self.version = u32(data, 0)
        assert self.version == 0
        offset = 4
        fields = []
        for _ in range(4):
            size = u32(data, offset)
            offset += 4
            assert size <= len(data) - offset
            fields.append(bytearray(data[offset:offset + size]))
            offset += size
        self.pool, self.types, self.table, self.code = fields
        self.debug = bytes(data[offset:])
        self.contexts = []
        count = u32(self.table, 0)
        assert 0 < count < 4096
        offsets = [4 + u32(self.table, 4 + 4*i) for i in range(count)]
        assert offsets == sorted(set(offsets))
        assert offsets[0] == 4 + 4*count
        for i, start in enumerate(offsets):
            end = offsets[i + 1] if i + 1 < count else len(self.table)
            parent, nslots, ntypes = struct.unpack_from('<3I', self.table, start)
            assert parent == 0xffffffff or parent < i
            pos = start + 12
            types = bytes(self.table[pos:pos + ntypes])
            pos += ntypes
            extra_n = u32(self.table, pos)
            pos += 4
            extra = bytes(self.table[pos:pos + 4*extra_n])
            pos += len(extra)
            bind_n = u32(self.table, pos)
            pos += 4
            bindings = bytes(self.table[pos:pos + 4*bind_n])
            pos += len(bindings)
            method_n = u32(self.table, pos)
            pos += 4
            methods = []
            for _ in range(method_n):
                args, name_len = struct.unpack_from('<2I', self.table, pos)
                pos += 8
                assert name_len < 512 and args < 256
                name = bytes(self.table[pos:pos + name_len]).decode('ascii')
                pos += name_len
                link, code_offset = struct.unpack_from('<2I', self.table, pos)
                pos += 8
                signature = bytes(self.table[pos:pos + args])
                pos += args
                assert code_offset % 4 == 0 and code_offset + 8 <= len(self.code)
                methods.append(dict(name=name, args=args, signature=list(signature),
                                    link=link, code_offset=code_offset))
            assert pos == end, (i, pos, end)
            self.contexts.append(dict(parent=parent, nslots=nslots, types=list(types),
                                      extra=extra.hex(), bindings=bindings.hex(), methods=methods))
        assert self.encode() == self.original

    def encode(self):
        contexts = []
        for c in self.contexts:
            extra = bytes.fromhex(c['extra'])
            bindings = bytes.fromhex(c['bindings'])
            blob = struct.pack('<3I', c['parent'], c['nslots'], len(c['types']))
            blob += bytes(c['types']) + p32(len(extra)//4) + extra
            blob += p32(len(bindings)//4) + bindings + p32(len(c['methods']))
            for m in c['methods']:
                name = m['name'].encode('ascii')
                blob += struct.pack('<2I', m['args'], len(name)) + name
                blob += struct.pack('<2I', m['link'], m['code_offset']) + bytes(m['signature'])
            contexts.append(blob)
        count = len(contexts)
        offsets = []
        offset = 4*count
        for blob in contexts:
            offsets.append(offset)
            offset += len(blob)
        table = p32(count) + b''.join(p32(o) for o in offsets) + b''.join(contexts)
        return p32(self.version) + b''.join(p32(len(f)) + bytes(f)
            for f in [self.pool, self.types, table, self.code]) + self.debug

    def ascii(self, offset):
        assert 0 <= offset < len(self.pool)
        end = self.pool.find(0, offset)
        assert end >= offset
        return bytes(self.pool[offset:end]).decode('ascii')

    def wide(self, offset, count):
        assert 0 <= offset <= len(self.pool) and count <= (len(self.pool)-offset)//2
        return bytes(self.pool[offset:offset + 2*count]).decode('utf-16le')

    def opcode(self, op):
        if self.legacy and 54 <= op <= 70:
            return 54 + (op - 54 + 14) % 17
        return op

    def instructions(self):
        """Lengths verified against original VM dispatch at GM 1014BF78."""
        words = [1]*80
        for op in [0, 1, 2, 10, 13, 14, 54, 55, 56, 57, 58, 59, 60,
                   61, 63, 64, 70, 71, 72, 73, 75, 76, 79]:
            words[op] = 2
        for op in [3, 11, 12, 62, 66, 67, 77, 78]:
            words[op] = 3
        words[69] = 4
        offset = 0
        while offset < len(self.code):
            word = u32(self.code, offset)
            opcode = word & 255
            if self.legacy and 54 <= opcode <= 70:
                opcode = 54 + (opcode - 54 + 3) % 17
            if opcode == 255:
                assert word == 0xffffffff
                yield dict(offset=offset, header=True, frame_slots=u32(self.code, offset+4))
                offset += 8
                continue
            assert opcode < 80 and opcode not in [44, 45], (hex(offset), hex(word))
            size = 4*words[opcode]
            assert offset + size <= len(self.code)
            args = [u32(self.code, offset + 4*i) for i in range(1, words[opcode])]
            signed_word = word if word < 0x80000000 else word - 0x100000000
            row = dict(offset=offset, opcode=opcode, register=signed_word >> 8,
                       operands=args, size=size)
            if opcode == 3:
                row['text'] = self.wide(args[1], args[0])
            elif opcode in [60, 61, 71, 73]:
                row['symbol'] = self.ascii(args[0])
            elif opcode == 62:
                row['symbol'] = self.ascii(args[1])
            yield row
            offset += size


def read_asset(name):
    index = json.loads(Path('research/vfs-index.json').read_text())
    for container in index['containers']:
        entry = next((e for e in container['entries'] if e['name'] == name), None)
        if entry:
            source = Path(index['source']) / container['name']
            with source.open('rb') as f:
                f.seek(entry['offset'])
                data = f.read(entry['size'])
            assert len(data) == entry['size']
            return data, dict(container=str(source), entry=entry,
                             sha256=hashlib.sha256(data).hexdigest())
    raise ValueError(name)


if __name__ == '__main__':
    import argparse
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--asset', default='Scripts\\ui\\main_menu.bin')
    parser.add_argument('--output', default='build/native-ui/main-menu-inspection.json')
    parser.add_argument('--range', nargs=2, type=lambda s: int(s, 0))
    args = parser.parse_args()
    data, source = read_asset(args.asset)
    module = Module(data)
    rows = list(module.instructions())
    output = Path(args.output)
    assert output.resolve().is_relative_to(Path('build/native-ui').resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(source=source, roundtrip='PASS',
        pool_size=len(module.pool), type_size=len(module.types),
        code_size=len(module.code), contexts=module.contexts, instructions=rows),
        ensure_ascii=False, indent=2), encoding='utf-8')
    if args.range:
        for row in rows:
            if args.range[0] <= row['offset'] < args.range[1]:
                print(f"{row['offset']:06X}", row)
    print(json.dumps(dict(status='PASS', source=source, context_count=len(module.contexts),
        instructions=len(rows), output=str(output))))
