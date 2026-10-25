"""Reject stale vendor inputs and modified private runtime outputs."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_native_runtime import PATCHES,SOURCE,VENDOR_SHA256,patch_runtime,prepare,sha


class NativeRuntimePreparationTests(unittest.TestCase):
    def test_exact_pinned_insertions_and_roundtrip(self):
        original=SOURCE.read_bytes(); self.assertEqual(sha(original),VENDOR_SHA256)
        private=patch_runtime(original)
        newline=b'\r\n'if b'\r\n'in original else b'\n'
        for anchor,addition in reversed(PATCHES):
            edited=anchor+addition.replace(b'\n',newline)
            self.assertEqual(private.count(edited),1)
            private=private.replace(edited,anchor,1)
        self.assertEqual(private,original)

    def test_changed_vendor_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
            patch_runtime(SOURCE.read_bytes()+b'\n')

    def test_modified_output_and_receipt_are_rejected(self):
        build = ROOT / 'build'
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='runtime-prepare-test-', dir=build)as temporary:
            output=Path(temporary)/'native32.c'; prepare(output); prepare(output,check=True)
            self.assertTrue(output.resolve().is_relative_to(build.resolve()))
            output.write_bytes(output.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'differs'):
                prepare(output,check=True)
            prepare(output); output.with_name('runtime-receipt.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'differs'):
                prepare(output,check=True)

    def test_vendor_and_outside_outputs_are_rejected_before_writing(self):
        original = SOURCE.read_bytes()
        for output in (SOURCE, ROOT.parent / 'outside-native32.c'):
            with self.assertRaisesRegex(ValueError, 'must belong'):
                prepare(output)
        self.assertEqual(SOURCE.read_bytes(), original)
        self.assertFalse((ROOT.parent / 'outside-native32.c').exists())


if __name__=='__main__': unittest.main()
