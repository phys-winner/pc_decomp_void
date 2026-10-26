"""Prove measured hot bodies keep their arithmetic instead of outlined ARM64 calls."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_android as build
from test_renderer_append import function


def main():
    out = ROOT / 'build/hot-outliner-test'
    out.mkdir(parents=True, exist_ok=True)
    cases = [('renderer', '0006', 'sub_16014290'), ('renderer', '0000', 'sub_160016C0'),
             ('renderer', '0052', 'sub_160902D0'), ('renderer', '0052', 'sub_1608F790'),
             ('engine', '0013', 'sub_11034940'), ('engine', '0023', 'sub_1105E810')]
    assert {name.encode() for _, _, name in cases} == set(build.HOT_FUNCTIONS)
    # Native overrides replace these hot bodies; their lifted fallbacks are cold.
    cases = [case for case in cases if case[2] not in build.NATIVE_OVERRIDES]
    previous_out, previous_release = build.OUT, build.RELEASE
    results = []
    try:
        build.OUT = out
        for module, chunk, name in cases:
            path = ROOT / f'generated/{module}-x86/{module}_{chunk}.c'
            build.RELEASE = None
            patched, _ = build.override_source(path, True)
            attribute = b'__attribute__((section(".text.hot"))) void ' + name.encode() + b'(void) {'
            assert attribute in patched.read_bytes()
            build.RELEASE = {'name': 'other-release'}
            unchanged, _ = build.override_source(path, True)
            assert b'section(".text.hot")' not in unchanged.read_bytes()
            build.RELEASE = None
            body = build.localize_fpu(build.localize_sse((function(path, name) + '\n').encode()))
            counts = []
            for protected in (False, True):
                selected = build.HOT_FUNCTION_START.sub(rb'__attribute__((section(".text.hot"))) \g<0>', body) if protected else body
                source = out / (name + ('-hot.c' if protected else '-outlined.c'))
                source.write_bytes(f'#include "{module}_funcs.h"\n'.encode() + selected)
                assembly = source.with_suffix('.s')
                subprocess.run([str(build.CLANG), *build.GENERATED_FLAGS, '-DRECOMP_LOCAL_REGS',
                    '-DRECOMP_PLAIN_MEMORY', '-I' + str(path.parent), '-S', str(source), '-o', str(assembly)],
                    cwd=ROOT, capture_output=True, text=True, check=True)
                text = assembly.read_text()
                emitted = re.search(r'^' + name + r':.*?^\.Lfunc_end\d+:', text, re.M | re.S)
                assert emitted, name
                counts.append(len(re.findall(r'\b(?:bl|b)\s+OUTLINED_FUNCTION_\d+', emitted[0])))
                if protected:
                    assert counts[-1] == 0, (name, counts)
                    assert '.section\t.text.hot,' in text
            results.append(dict(function=name, outlined_calls=counts[0], protected_outlined_calls=counts[1]))
    finally:
        build.OUT, build.RELEASE = previous_out, previous_release
    assert sum(r['outlined_calls'] for r in results) > 0, 'negative control did not exercise outlining'
    (out / 'result.json').write_text(json.dumps(dict(status='PASS', results=results), indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
