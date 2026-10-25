"""Exercise the pinned Sound body override using only temporary PE/C fixtures."""
from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lift_media

EXPECTED = bytes.fromhex("8b4424108b088b4424088b118b5224508b44240850ffd2c3")
BODY = "void sub_14061270(void) {\n    eax = 1;\n    esp += 4;\n}\n"
REPLACEMENT = ("void sub_14061270(void) {\n"
               "    extern void void_sound_bulk_read(void);\n"
               "    void_sound_bulk_read();\n}\n")
BEFORE = "void sub_14061260(void) {\n    RECOMP_CALL(sub_14061270);\n}\n\n"
AFTER = "\nvoid sub_14061300(void) {\n    RECOMP_CALL(sub_14061270);\n}\n"


def pe_fixture(base=0x14000000, callback=EXPECTED):
    data = bytearray(0x1200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x14C, 1, 0, 0, 0, 0xE0, 0x2102)
    struct.pack_into("<H", data, 0x98, 0x10B)
    for offset, value in ((28, base), (32, 0x1000), (36, 0x200),
                          (56, 0x62000), (60, 0x200), (92, 16)):
        struct.pack_into("<I", data, 0x98 + offset, value)
    struct.pack_into("<8sIIIIIIHHI", data, 0x178, b".text\0\0\0", 0x1000,
                     0x61000, 0x1000, 0x200, 0, 0, 0, 0, 0x60000020)
    data[0x470:0x470 + len(callback)] = callback
    return bytes(data)


class SoundBulkGeneratorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="void-sound-bulk-generator-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "generated/sound-x86"
        self.directory.mkdir(parents=True)
        self.binary = self.root / "generated/input/Sound.dll"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(pe_fixture())
        self.sources = ["sound_0000.c", "sound_0001.c"]
        (self.directory / self.sources[0]).write_text(BEFORE + BODY + AFTER)
        (self.directory / self.sources[1]).write_text("void sub_14061400(void) {\n    esp += 4;\n}\n")
        (self.directory / "sound_funcs.h").write_text("void sub_14061270(void);\n")
        (self.directory / "recomp_dispatch.c").write_text(
            "const recomp_dispatch_entry_t recomp_dispatch_table[] = {\n"
            "    {0x14061270u, sub_14061270},\n};\n")
        self.report = {"sources": self.sources, "functions": 1889,
                       "status": "GENERATED", "prior_stages": ["game", "engine"]}
        root_patch = patch.object(lift_media, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def snapshot(self):
        return {path.name: path.read_bytes() for path in self.directory.iterdir()}

    def rejected(self, message):
        before, report = self.snapshot(), deepcopy(self.report)
        with self.assertRaisesRegex(ValueError, message):
            lift_media.apply_sound_bulk_read(self.directory, self.report)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.report, report)

    def test_unique_body_preserves_name_direct_calls_header_and_dispatch(self):
        before, report = self.snapshot(), deepcopy(self.report)
        lift_media.apply_sound_bulk_read(self.directory, self.report)
        self.assertEqual((self.directory / self.sources[0]).read_text(), BEFORE + REPLACEMENT + AFTER)
        self.assertEqual((self.directory / self.sources[0]).read_text().count("void_sound_bulk_read();"), 1)
        for filename in (self.sources[1], "sound_funcs.h", "recomp_dispatch.c"):
            self.assertEqual((self.directory / filename).read_bytes(), before[filename])
        override = self.report["bulk_read_callback"]
        self.assertEqual(override["address"], "0x14061270")
        self.assertEqual(override["source"], self.sources[0])
        self.assertEqual(override["original_bytes"], EXPECTED.hex())
        self.assertEqual(override["implementation"], "void_sound_bulk_read")
        report["bulk_read_callback"] = override
        self.assertEqual(self.report, report)
        self.assertEqual(self.binary.read_bytes(), pe_fixture())

    def test_rejects_other_private_base_before_writing(self):
        self.binary.write_bytes(pe_fixture(base=0x10000000))
        self.rejected("does not match the pinned input")

    def test_rejects_changed_callback_bytes_before_writing(self):
        self.binary.write_bytes(pe_fixture(callback=b"\x90" + EXPECTED[1:]))
        self.rejected("does not match the pinned input")

    def test_rejects_missing_definition_without_writing(self):
        path = self.directory / self.sources[0]
        path.write_text(BEFORE + AFTER)
        self.rejected("Missing or duplicate Sound read callback definition")

    def test_rejects_two_definitions_in_one_source_without_writing(self):
        (self.directory / self.sources[0]).write_text(BODY + "\n" + BODY)
        self.rejected("[Dd]uplicate Sound read callback")

    def test_rejects_definitions_in_two_sources_without_writing(self):
        (self.directory / self.sources[1]).write_text(BODY)
        self.rejected("Missing or duplicate Sound read callback definition")


if __name__ == "__main__":
    unittest.main()
