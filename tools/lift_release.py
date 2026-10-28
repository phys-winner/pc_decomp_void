"""Lift every module of another release of the game (another build of the
binaries) the way the 2009 build was lifted, into generated/<release>/.

    python tools/lift_release.py tension [--only Sound,Video] [--finish] [--catalogs-only]

config/releases/<release>.json names the game directory and, per module, the
file, its SHA-256 and the private base (the same bases as the 2009 build, so
the Android host's loader and memory map apply unchanged). Function catalogs
come from pcrecomp's Capstone recursive descent (disasm32.py) over the
original, unrebased image, as for RendererD3D and PhysX in the 2009 build
(research/ida/<release>/<Name>.capstone.json; written when missing; the live
catalog goes to config/releases/<release>/<Name>.functions.json).

What the 2009 lifters pinned by address is found by content here:
- the CRT memcpy/memmove bodies (opening sequence push ebp / mov ebp,esp /
  push edi / push esi / mov esi,[ebp+0Ch] / mov ecx,[ebp+10h] /
  mov edi,[ebp+8]) and libvorbis mdct_backward in Sound.dll: native
  overrides (android/host/crt_native.c, sound_native.c);
- Sound.dll's Vorbis read callback, which ignores fread's nmemb: replaced
  by void_sound_bulk_read (android/host/hooks.c), as tools/lift_media.py does.
They go to generated/<release>/release.json and release_overrides.h, which
tools/build_android.py --release <release> compiles into the host.

A release's shared_modules are modules the 2009 build lifted that call no
game code (Microsoft's HLSL compiler, tools/lift_d3dx.py): --finish adds
their functions to this release's dispatch table and their images to its
images, and the build compiles their generated sources from the 2009 stage.
The 2009 Game.exe isFirstRun gate (0x00436A10) is not patched: the host's
registry answers FirstRun=0 for any Ice-pick Lodge title.
"""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

import capstone
import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions
from lift_engine import rebase_image, relocation_sites, sha256

CRT_COPY = bytes.fromhex("558bec57568b750c8b4d108b7d08")
# libvorbis mdct_backward (LTCG: ecx = lookup, eax = in, [esp+4] = out); 2009 Sound.dll 0x10018AB0.
MDCT_BACKWARD = bytes.fromhex("83ec0853558b6c2414568bd9578bf88b038bf0c1f802d1fe8d14308d5495008d2c85000000008b43088d4cb7e4895424")
VORBIS_READ = bytes.fromhex("8b4424108b088b4424088b118b5224508b44240850ffd2c3")

# The 2009 build's native overrides (tools/build_android.py NATIVE_OVERRIDES)
# that the host names through macros (android/host/*.c, 2009 values under
# #ifndef VOID_RELEASE). A release gets one where its module holds the 2009
# body unchanged but for relocated fields and branches out of the body: its
# twin (the k-th of k identical 2009 bodies is the k-th such twin). The
# twin's relocated fields give the release's value of each constant the host
# reads from the image; the zlib messages are found as strings.
TWINS = (
    ("Sound", 0x1400F440, "SOUND_VORBIS_OPEN1"),           # libvorbisfile (vorbis_native.c)
    ("Sound", 0x1400F540, "SOUND_VORBIS_OPEN2"),
    ("Sound", 0x14010500, "SOUND_VORBIS_READ"),
    ("Sound", 0x1400F590, "SOUND_VORBIS_CLEAR"),
    ("Sound", 0x1400F6D0, "SOUND_VORBIS_PCM_TOTAL"),
    ("Sound", 0x140101D0, "SOUND_VORBIS_PCM_SEEK"),
    ("Engine", 0x110EC930, "ENGINE_NAVMESH_LEAF"),         # navmesh_native.c
    ("Engine", 0x1105E810, "ENGINE_SAT"),                  # renderer_region_native.c
    ("Engine", 0x110014F0, "ENGINE_DEBUG_VECTOR"),         # physics_native.c
    ("Engine", 0x1110BF90, "ENGINE_LOG_LINE"),             # renderer_native.c
    ("RendererD3D", 0x16082260, "RENDERER_APPEND12"),      # renderer_native.c
    ("RendererD3D", 0x1616AED0, "RENDERER_SCENE_PASS"),
    ("RendererD3D", 0x161FCEC0, "RENDERER_PASS_BUILD"),
    ("RendererD3D", 0x161F8460, "RENDERER_PASS_SPLIT"),
    ("RendererD3D", 0x160D6ED0, "RENDERER_SAT"),           # renderer_region_native.c
    ("RendererD3D", 0x16013760, "RENDERER_REGION_LIGHT"),
    ("RendererD3D", 0x16014090, "RENDERER_REGION_WALK"),
    ("RendererD3D", 0x16120040, "RENDERER_ADLER32"),       # renderer_adler_native.c
    ("RendererD3D", 0x1611E830, "RENDERER_INFLATE_INIT"),  # renderer_inflate_native.c
    ("RendererD3D", 0x1611E7D0, "RENDERER_INFLATE_RESET"),
    ("RendererD3D", 0x1611E9F0, "RENDERER_INFLATE"),
    ("RendererD3D", 0x1611FFF0, "RENDERER_INFLATE_END"),
    # PhysXCore: the debug renderer's line append (physics_native.c). The
    # allocator's source line on the growth path, which the host leaves to the
    # lifted body, may differ (0x121 in 2.8.1, 0x118 in 2.7.3).
    ("PhysXCore", 0x181802C0, "PHYSX_DEBUG_LINE", (0x1818035A,)),
)
TWIN_CONSTANTS = (   # (macro, the 2009 function whose twin holds it, the 2009 value)
    ("ENGINE_EPSILON", 0x110EC930, 0x11122974),            # float 1e-6
    ("ENGINE_FIXED_TO_UNITS", 0x110EC930, 0x11122D0C),     # float 0.005
    ("ENGINE_SAT_EPSILON", 0x1105E810, 0x11122CE0),        # float 0x3f7fffef
    ("RENDERER_SAT_EPSILON", 0x160D6ED0, 0x162D2A64),
    ("RENDERER_INFLATE_ZFREE", 0x1611E830, 0x161467A0),    # zlib's default allocator
    ("RENDERER_INFLATE_ZALLOC", 0x1611E830, 0x161467B0),
)
# zlib 1.2.3's messages in RendererD3D (renderer_inflate_native.c); the native
# inflate hands back the image's own copy, "data error" when it has none.
INFLATE_MESSAGES = (0x162CE800, 0x162CE818, 0x162CE830, 0x162CE850, 0x162CE868, 0x162CE884, 0x162CE89C,
                    0x162CE8B8, 0x162CE8D4, 0x162CE8F8, 0x162CE914, 0x162CE934, 0x162CE948, 0x162CE95C,
                    0x162CE978, 0x162CE990, 0x162CE9A4, 0x162CF434, 0x162CF440, 0x162CF468)
INFLATE_DATA_ERROR = 0x162CF434
# Engine's physics::CScene (android/host/physx.c), whose bodies differ between
# the PhysX SDKs (2.8.1 in 2009, 2.7.3 in 2008) in the fields these patterns
# capture. The constructor's setTiming(step, 8, FIXED): fld [step]; push ebx;
# mov ecx, ebp; mov [esi+14h], ebp; mov edx, [ecx]; mov eax, [edx+setTiming];
# push 8; push ecx; fstp [esp]; call eax.
SCENE_TIMING = re.compile(rb"\xD9\x05(....)\x53\x8B\xCD\x89\x6E\x14\x8B\x11\x8B\x82(....)\x6A\x08\x51\xD9\x1C\x24\xFF\xD0", re.S)
# CScene::fetch: sub esp, 10h; push esi; mov esi, ecx; cmp byte [esi+simulating], 0;
# je; mov ecx, [esi+14h]; mov eax, [ecx]; mov edx, [eax+fetchResults]; push ebx;
# push 0; push 1; push 1; call edx; mov ecx, [esi+14h]; mov eax, [ecx];
# mov eax, [eax+getTiming]; lea edx, [esp+8]; push edx.
SCENE_FETCH = re.compile(rb"\x83\xEC\x10\x56\x8B\xF1\x80\x7E(.)\x00\x74.\x8B\x4E\x14\x8B\x01\x8B\x90....\x53\x6A\x00"
                         rb"\x6A\x01\x6A\x01\xFF\xD2\x8B\x4E\x14\x8B\x01\x8B\x80(....)\x8D\x54\x24\x08\x52", re.S)
SCENE_2009 = {"ENGINE_SCENE_FETCH": 0x110DE7C0, "ENGINE_STEP_RVA": 0x12A25C, "CSCENE_SIMULATING": 0x40,
              "NXSCENE_SET_TIMING": 0x148, "NXSCENE_GET_TIMING": 0x14C}


def load_release(name):
    spec = json.loads((ROOT / f"config/releases/{name}.json").read_text())
    local = json.loads((ROOT / "port.json").read_text()).get("releases", {}).get(name, {})
    game = (ROOT / local.get("game_directory", spec["game_directory"])).resolve()
    physx = (ROOT / local.get("physx_directory", spec["physx_directory"])).resolve()
    for module in spec["modules"]:
        module["path"] = Path(module["file"].format(game=game, physx=physx))
        module["base"] = int(module["base"], 0)
    return spec


def capstone_catalog(release, module):
    """Use the pinned Capstone catalog shipped with the port."""
    config = ROOT / f"config/releases/{release}/{module['name']}.functions.json"
    rows = json.loads(config.read_text())
    if len({r["address"] for r in rows}) != len(rows):
        raise ValueError(f"{module['name']}: duplicate catalog addresses")
    return rows, {}


def prepare(module, generated):
    raw = module["path"].read_bytes()
    if sha256(raw) != module["sha256"]:
        raise ValueError(f"{module['name']}: {module['path']} hash mismatch")
    pe = pefile.PE(data=raw, fast_load=True)
    oh = pe.OPTIONAL_HEADER
    if pe.FILE_HEADER.Machine != 0x14C or oh.Magic != 0x10B:
        raise ValueError(f"{module['name']}: not a PE32 i386 image")
    pe.parse_data_directories(directories=[0, 1, 9, 13])
    if any(oh.DATA_DIRECTORY[i].VirtualAddress or oh.DATA_DIRECTORY[i].Size for i in (9, 13)):
        raise ValueError(f"{module['name']}: PE TLS or delay imports")
    proof = {"original_base": hex(oh.ImageBase), "base": hex(module["base"]), "span": hex(oh.SizeOfImage),
             "entry_rva": oh.AddressOfEntryPoint, "original_sha256": module["sha256"]}
    if module["base"] == oh.ImageBase:
        image = raw
    else:
        image, rebase = rebase_image(raw, module["base"])
        if rebase_image(image, oh.ImageBase)[0] != raw:
            raise ValueError(f"{module['name']}: reverse rebase differs")
        parsed, sites, _ = relocation_sites(raw)
        base_offset = parsed.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
        allowed = {i for _, off in sites for i in range(off, off + 4)} | set(range(base_offset, base_offset + 4))
        if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, image))):
            raise ValueError(f"{module['name']}: unexpected rebase byte changes")
        proof.update(highlow_fixups=rebase["highlow_fixups"])
    exports = []
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        exports = [(e.name.decode() if e.name else None, e.ordinal, e.address)
                   for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if not e.forwarder]
    proof["exports"] = [{"name": n, "ordinal": o, "address": hex(module["base"] + rva)} for n, o, rva in exports]
    input_path = generated / "input" / module["path"].name
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(image)
    proof["rebased_sha256"] = sha256(image)
    # Data exports (NxCharacter's NxControllerManager vtable) are not entries.
    code = [(s.VirtualAddress, s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData))
            for s in pe.sections if s.Characteristics & 0x20000000]
    entries = [module["base"] + rva for _, _, rva in exports if any(a <= rva < b for a, b in code)]
    return input_path, image, proof, entries


def find_code(image, pattern, base):
    """Live VAs where `pattern` starts inside an executable section."""
    pe = pefile.PE(data=image, fast_load=True)
    hits = []
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        data = section.get_data()
        for match in re.finditer(re.escape(pattern), data):
            hits.append(base + section.VirtualAddress + match.start())
    return hits


class Body:
    """A lifted module's rebased image: code, relocated fields and catalog sizes by live address."""
    def __init__(self, image, report, catalog):
        data = image.read_bytes()
        if sha256(data) != report["rebased_sha256"]:
            raise ValueError(f"{image}: not the image its report was lifted from")
        self.pe = pefile.PE(data=data, fast_load=True)
        self.pe.parse_data_directories(directories=[5])
        self.data, self.base = data, self.pe.OPTIONAL_HEADER.ImageBase
        self.relocs = {self.base + e.rva for block in getattr(self.pe, "DIRECTORY_ENTRY_BASERELOC", [])
                       for e in block.entries if e.type == 3}
        rows = json.loads(catalog.read_text())
        # Catalogs are by the original image's addresses (its code from base + 0x1000).
        original = int(report["original_base"], 16) if "original_base" in report else rows[0]["address"] & ~0xFFFF
        self.sizes = {r["address"] - original + self.base: r["size"] for r in rows}
        self.code = [(self.base + s.VirtualAddress, s.get_data()) for s in self.pe.sections
                     if s.Characteristics & 0x20000000]

    def read(self, va, n):
        offset = self.pe.get_offset_from_rva(va - self.base)
        return self.data[offset:offset + n]

    def u32(self, va):
        return int.from_bytes(self.read(va, 4), "little")

    def string(self, va):
        offset = self.pe.get_offset_from_rva(va - self.base)
        return self.data[offset:self.data.index(b"\0", offset) + 1]

    def find_string(self, text):
        return [self.base + self.pe.get_rva_from_offset(m.start()) for m in re.finditer(re.escape(text), self.data)]

    def body(self, address, loose=()):
        """The body's bytes as a pattern: relocated fields, branches out of it and
        the immediates of the `loose` instructions masked."""
        size = self.sizes[address]
        code = self.read(address, size)
        keep = [True] * size
        for i in range(size):
            if address + i in self.relocs:
                keep[i:i + 4] = [False] * len(keep[i:i + 4])
        exits = []
        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        decoder.detail = True
        for insn in decoder.disasm(code, address):
            if insn.address in loose:
                at = insn.address - address + insn.imm_offset
                keep[at:at + insn.imm_size] = [False] * insn.imm_size
            if not (insn.group(capstone.CS_GRP_JUMP) or insn.group(capstone.CS_GRP_CALL)):
                continue
            operand = insn.operands[0] if insn.operands else None
            if operand is None or operand.type != capstone.x86.X86_OP_IMM or address <= operand.imm < address + size:
                continue
            width = 4 if insn.size >= 5 else 1
            at = insn.address - address + insn.size - width
            keep[at:at + width] = [False] * width
            exits.append((at, width, operand.imm))
        rx = re.compile(b"".join(re.escape(code[i:i + 1]) if k else b"." for i, k in enumerate(keep)), re.S)
        return rx, exits

    def matches(self, rx):
        return [start + m.start() for start, data in self.code for m in rx.finditer(data)]

    def scene_timing(self):
        """CScene::fetch, the scenes' step (float 1/60) and NxScene's timing slots, or None."""
        timing = [(start + m.start(), m.groups()) for start, data in self.code for m in SCENE_TIMING.finditer(data)]
        fetch = [(start + m.start(), m.groups()) for start, data in self.code for m in SCENE_FETCH.finditer(data)]
        if len(timing) != 1 or len(fetch) != 1 or fetch[0][0] not in self.sizes:
            return None
        step, set_slot = (int.from_bytes(field, "little") for field in timing[0][1])
        if self.read(step, 4) != struct.pack("<f", 1 / 60):
            return None
        return {"ENGINE_SCENE_FETCH": fetch[0][0], "ENGINE_STEP_RVA": step - self.base,
                "CSCENE_SIMULATING": fetch[0][1][0][0], "NXSCENE_SET_TIMING": set_slot,
                "NXSCENE_GET_TIMING": int.from_bytes(fetch[0][1][1], "little")}


def find_twins(release, spec, generated):
    """TWINS, TWIN_CONSTANTS and INFLATE_MESSAGES in this release, by content."""
    modules = {m["name"]: m for m in spec["modules"]}
    bodies, functions = {}, {}
    for name in {twin[0] for twin in TWINS}:
        module = modules[name]
        mine = generated / f"{module['prefix']}-x86"
        theirs = ROOT / f"generated/{module['prefix']}-x86"
        bodies[name] = (Body(ROOT / "generated/input" / module["path"].name, json.loads((theirs / "report.json").read_text()),
                             ROOT / f"config/{name}.functions.json"),
                        Body(generated / "input" / module["path"].name, json.loads((mine / "report.json").read_text()),
                             ROOT / f"config/releases/{release}/{name}.functions.json"))
        functions[name] = set(json.loads((mine / "functions.json").read_text()))
    found, values, twins = {}, {}, []
    for name, address, macro, *loose in TWINS:
        old, new = bodies[name]
        rx, exits = old.body(address, *loose)
        copies, hits = old.matches(rx), new.matches(rx)
        if address not in copies or len(hits) != len(copies):
            print(f"{macro}: no twin of 0x{address:08X} ({len(copies)} in 2009, {len(hits)} here)", flush=True)
            continue
        twin, size = hits[copies.index(address)], old.sizes[address]
        if twin not in functions[name] or new.sizes.get(twin) != size:
            raise ValueError(f"{macro}: twin 0x{twin:08X} is no lifted function of its size")
        if {i for i in range(size) if address + i in old.relocs} != {i for i in range(size) if twin + i in new.relocs}:
            raise ValueError(f"{macro}: twin 0x{twin:08X} relocates other fields")
        fields = {}
        for i in range(size):
            if address + i in old.relocs and fields.setdefault(old.u32(address + i), new.u32(twin + i)) != new.u32(twin + i):
                raise ValueError(f"{macro}: 0x{old.u32(address + i):08X} has two places in the twin")
        for at, width, target in exits:
            displacement = int.from_bytes(new.read(twin + at, width), "little", signed=True)
            fields[target] = twin + at + width + displacement
        found[address] = (name, twin, fields)
        twins.append({"macro": macro, "module": name, "2009": hex(address), "address": hex(twin)})
    for macro, function, value in TWIN_CONSTANTS:
        if function in found:
            values[macro] = found[function][2][value]
    old, new = bodies["Engine"]
    if old.scene_timing() != SCENE_2009:
        raise ValueError("the CScene patterns no longer find the 2009 Engine's scene timing")
    scene = new.scene_timing()
    if scene and scene["ENGINE_SCENE_FETCH"] in functions["Engine"]:
        fetch = scene.pop("ENGINE_SCENE_FETCH")
        twins.append({"macro": "ENGINE_SCENE_FETCH", "module": "Engine", "2009": hex(SCENE_2009["ENGINE_SCENE_FETCH"]),
                      "address": hex(fetch)})
        values.update(scene)
    else:
        print("ENGINE_SCENE_FETCH: no CScene timing found", flush=True)
    if 0x1611E9F0 in found:
        old, new = bodies["RendererD3D"]
        messages = []
        for address in INFLATE_MESSAGES:
            hits = new.find_string(old.string(address))
            if len(hits) != 1:
                raise ValueError(f"zlib message at 0x{address:08X}: {len(hits)} copies here")
            messages.append(hits[0])
        values["RENDERER_INFLATE_MESSAGES"] = messages
        values["RENDERER_INFLATE_DATA_ERROR"] = messages[INFLATE_MESSAGES.index(INFLATE_DATA_ERROR)]
    return twins, values


def patch_vorbis_read(directory, report, address):
    pattern = re.compile(rf"^void sub_{address:08X}\(void\) \{{\n.*?^\}}", re.M | re.S)
    matched = [(name, (directory / name).read_text()) for name in report["sources"]
               if pattern.search((directory / name).read_text())]
    if len(matched) != 1:
        raise ValueError("Missing or duplicate Sound read callback definition")
    name, source = matched[0]
    (directory / name).write_text(pattern.sub(
        f"void sub_{address:08X}(void) {{\n    extern void void_sound_bulk_read(void);\n    void_sound_bulk_read();\n}}",
        source))
    report["bulk_read_callback"] = {"address": hex(address), "source": name, "implementation": "void_sound_bulk_read"}


def static_traps(directory, sources):
    traps = {}
    for name in sources:
        text = (directory / name).read_text()
        for address, instruction in re.findall(r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', text):
            traps[address] = json.loads(instruction)
    return [{"address": "0x" + a, "instruction": t} for a, t in sorted(traps.items())]


def lift_module(release, module, generated, revision):
    """Lift one module on its own: other modules are reached through the
    dispatch table (PE modules only call each other through imports)."""
    name, prefix = module["name"], module["prefix"]
    directory = generated / f"{prefix}-x86"
    directory.mkdir(parents=True, exist_ok=True)
    report = {"status": "GENERATING", "module": module["path"].name, "release": release}
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    input_path, image, proof, export_entries = prepare(module, generated)
    rows, stats = capstone_catalog(release, module)
    delta = module["base"] - int(proof["original_base"], 0)
    catalog = [{"address": r["address"] + delta, "size": r["size"]} for r in rows]
    tables_path = ROOT / f"config/releases/{release}/{name}.jump-tables.json"
    tables = {}
    if tables_path.exists():
        tables = {int(r["address"], 0) + delta: (r.get("first_index", 0), r["count"])
                  for r in json.loads(tables_path.read_text())}
    seeds_path = ROOT / f"config/releases/{release}/{name}.seeds.json"
    seeds = [int(a, 0) for a in json.loads(seeds_path.read_text())] if seeds_path.exists() else []
    info, imports, decoder, functions, rejected = collect_functions(
        input_path, catalog, [*export_entries, *seeds], label=name, jump_tables=tables)
    if info.image_base != module["base"]:
        raise ValueError(f"{name}: decode base")
    emitted = emit_functions(directory, imports, decoder, functions, label=name,
                             header_name=f"{prefix}_funcs.h", chunk_prefix=prefix, firstrun_gate=None)
    entry = module["base"] + proof["entry_rva"]
    overrides = {"crt_memmove": [hex(a) for a in find_code(image, CRT_COPY, module["base"]) if a in functions]}
    if name == "Sound":
        mdct = [a for a in find_code(image, MDCT_BACKWARD, module["base"]) if a in functions]
        reads = [a for a in find_code(image, VORBIS_READ, module["base"]) if a in functions]
        if len(mdct) != 1:
            raise ValueError(f"Sound: mdct_backward found {len(mdct)} times (android/host/sound_native.c needs it)")
        if len(reads) != 1:
            raise ValueError(f"Sound: Vorbis read callback found {len(reads)} times")
        overrides.update(mdct_backward=hex(mdct[0]), vorbis_read=hex(reads[0]))
        patch_vorbis_read(directory, emitted, reads[0])
    traps = static_traps(directory, emitted["sources"])
    (directory / "static-traps.json").write_text(json.dumps(traps, indent=2) + "\n")
    (directory / "functions.json").write_text(json.dumps(sorted(functions)) + "\n")
    report.update(status="GENERATED", **proof, entry=hex(entry), **emitted, overrides=overrides,
                  catalog_source="Capstone 5.0.7 recursive descent (pcrecomp disasm32.py)",
                  catalog_stats=stats, catalog_input=f"config/releases/{release}/{name}.functions.json",
                  pcrecomp_revision=revision, input_image=str(input_path.relative_to(ROOT)),
                  rejected_non_catalog_entries=len(rejected), function_list="functions.json",
                  unique_static_trap_sites=len(traps), whole_game="UNVERIFIED")
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("module", "base", "entry", "functions", "unique_static_trap_sites")}),
          flush=True)


def finish(release, spec, generated):
    """Merge the modules' functions into one dispatch table (in the last
    module's directory, where tools/build_android.py looks) and write the
    host's release_overrides.h and release.json."""
    entries, headers, crt = [], [], []
    overrides = {}
    game_entry = None
    for module in spec["modules"]:
        directory = generated / f"{module['prefix']}-x86"
        report = json.loads((directory / "report.json").read_text())
        if report.get("status") != "GENERATED":
            raise SystemExit(f"{module['name']}: not lifted yet")
        functions = json.loads((directory / "functions.json").read_text())
        if set(entries) & set(functions):
            raise ValueError(f"{module['name']}: dispatch overlap")
        entries += functions
        headers.append(f"../{module['prefix']}-x86/{module['prefix']}_funcs.h")
        crt += [(module["name"], int(a, 16)) for a in report["overrides"]["crt_memmove"]]
        overrides.update({k: v for k, v in report["overrides"].items() if k != "crt_memmove"})
        if module["name"] == "Game":
            game_entry = int(report["entry"], 16)
    last = generated / f"{spec['modules'][-1]['prefix']}-x86"
    shared, images = {}, {m["prefix"]: f"generated/{release}/input/{m['path'].name}" for m in spec["modules"]}
    for module in spec.get("shared_modules", []):
        prefix = module["prefix"]
        directory = ROOT / f"generated/{prefix}-x86"
        report = json.loads((directory / "report.json").read_text())
        if report.get("status") != "GENERATED":
            raise SystemExit(f"{module['name']}: not lifted yet (2009 stage)")
        image = (ROOT / report["input_image"]).read_bytes()
        if sha256(image) != report["rebased_sha256"]:
            raise ValueError(f"{module['name']}: {report['input_image']} does not match its report")
        base = int(report["base"], 16)
        span = pefile.PE(data=image, fast_load=True).OPTIONAL_HEADER.SizeOfImage
        header = directory / f"{prefix}_funcs.h"
        # Its header declares the 2009 stage's dispatch; its own bodies are those in its image.
        own = [a for a in (int(x, 16) for x in re.findall(r"^void sub_([0-9A-F]{8})\(void\);", header.read_text(), re.M))
               if base <= a < base + span]
        if not own or set(entries) & set(own):
            raise ValueError(f"{module['name']}: no functions or dispatch overlap")
        entries += own
        headers.append(Path(os.path.relpath(header, last)).as_posix())
        copy = generated / "input" / report["image_name"]
        if not copy.is_file() or copy.read_bytes() != image:
            copy.write_bytes(image)
        shared[prefix] = directory.relative_to(ROOT).as_posix()
        images[prefix] = copy.relative_to(ROOT).as_posix()
    emit_dispatch(last / "recomp_dispatch.c", sorted(entries), headers)
    mdct = int(overrides["mdct_backward"], 16)
    lines = ["/* Generated by tools/lift_release.py: what the host overrides in this release. */",
             "#pragma once",
             "#define RELEASE_CRT_MEMMOVES(X) " + " ".join(f"X(sub_{a:08X})" for _, a in crt),
             f"#define SOUND_MDCT_BACKWARD sub_{mdct:08X}",
             f"#define SOUND_MDCT_BACKWARD_LIFTED sub_{mdct:08X}_lifted",
             f"#define SOUND_BULK_READ_VA 0x{int(overrides['vorbis_read'], 16):08X}u",
             f"#define RELEASE_GAME_ENTRY 0x{game_entry:08X}u"]
    twins, values = find_twins(release, spec, generated)
    for twin in twins:
        lines += [f"#define {twin['macro']} sub_{int(twin['address'], 16):08X}",
                  f"#define {twin['macro']}_LIFTED sub_{int(twin['address'], 16):08X}_lifted"]
    lines += [f"#define {macro} " + (",".join(f"0x{v:08X}u" for v in value) if isinstance(value, list) else f"0x{value:08X}u")
              for macro, value in values.items()]
    (generated / "release_overrides.h").write_text("\n".join(lines) + "\n")
    native = [f"sub_{a:08X}" for _, a in crt] + [f"sub_{mdct:08X}"] + [f"sub_{int(t['address'], 16):08X}" for t in twins]
    (generated / "release.json").write_text(json.dumps({
        "release": release, "title": spec["title"], "modules": [m["prefix"] for m in spec["modules"]],
        "shared_modules": shared, "images": images,
        "native_overrides": native,
        "overrides": {**overrides, "crt_memmove": [{"module": n, "address": hex(a)} for n, a in crt]},
        "twins": twins, "twin_constants": {m: [hex(x) for x in v] if isinstance(v, list) else hex(v) for m, v in values.items()},
        "game_entry": hex(game_entry), "dispatch_entries": len(entries)}, indent=2) + "\n")
    print(f"{release}: {len(entries)} dispatch entries; native overrides {len(native)} ({len(twins)} twins of 2009's)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("release")
    parser.add_argument("--catalogs-only", action="store_true")
    parser.add_argument("--only", help="Lift these modules (comma-separated names) without merging")
    parser.add_argument("--finish", action="store_true", help="Only merge the lifted modules")
    args = parser.parse_args()
    spec = load_release(args.release)
    generated = ROOT / "generated" / args.release
    generated.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "-C", str(ROOT / "reference/pcrecomp"), "rev-parse", "HEAD"],
                                       text=True).strip()
    if args.catalogs_only:
        for module in spec["modules"]:
            rows, stats = capstone_catalog(args.release, module)
            print(f"{module['name']}: {len(rows)} catalog entries {stats}", flush=True)
        return
    if not args.finish:
        wanted = set(args.only.split(",")) if args.only else {m["name"] for m in spec["modules"]}
        unknown = wanted - {m["name"] for m in spec["modules"]}
        if unknown:
            raise SystemExit(f"unknown modules {sorted(unknown)}")
        for module in spec["modules"]:
            if module["name"] in wanted:
                lift_module(args.release, module, generated, revision)
        if args.only:
            return
    finish(args.release, spec, generated)


if __name__ == "__main__":
    main()
