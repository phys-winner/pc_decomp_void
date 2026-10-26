"""Document the conservative SM3 material-cache seed; never edit original inputs.

This is separate from the host's content-addressed D3DX response bundle. Keep
both SM3 libraries, all common stage databases, and every unrecognized file.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNUSED_FAMILIES = ("20", "20h", "2a", "2ah", "2b", "2bh")
OMITTED = {"effects" + family + suffix for family in UNUSED_FAMILIES for suffix in (".dat", ".hdr")}


def selected(name):
    return name.lower() not in OMITTED


def manifest():
    releases = []
    for release, renderer in (("the-void-russian", "generated/input/RendererD3D.dll"),
                              ("the-void-polish", "generated/tension/input/RendererD3D.dll")):
        directory = ROOT / "original" / release / "Void/Cache"
        files = [dict(name=p.name, bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                      seed=selected(p.name)) for p in sorted(directory.iterdir()) if p.is_file()]
        before = sum(f["bytes"] for f in files)
        after = sum(f["bytes"] for f in files if f["seed"])
        releases.append(dict(release=release, renderer=renderer, renderer_sha256=hashlib.sha256((ROOT / renderer).read_bytes()).hexdigest(),
                             bytes_original=before, bytes_seeded=after, bytes_omitted=before-after, files=files))
    return dict(profile=dict(HDR=[0, 1, 2], lightmap=[0, 1, 2], shadows=[0, 1, 2], material_families=["30", "30h"],
                             strategies=[dict(HDR=0, force="fx_3_0", family="30"),
                                         dict(HDR=1, force="fx_3_0hs", family="30h"),
                                         dict(HDR=2, force="fx_3_0hf", family="30h")],
                             advertised_vertex_shader="vs_3_0", advertised_pixel_shader="ps_3_0"),
                status="CONSERVATIVE_STATIC_SELECTION; full route/device open closure is separate",
                limits=["Both effects30 and effects30h are kept: the renderer exposes an iterator over an explicitly selected library as well as its active HDR library.",
                        "All five original stage databases and custom.dat/hdr are kept; a stage profile does not have to match the material's SM3 family.",
                        "New profiles omit the 12 known SM2 files; existing app profiles remove those same regenerable cache assets once, using .port-sm3-only-v1. Original install inputs, settings, saves and unknown files are not removed.",
                        "No host D3DX response keys are removed by this selection; all requested combat/hidden/dynamic keys need their own closure."],
                evidence={"2009": dict(strategy="0x162E43E8", family="0x16084BF0", plain="0x16084C10", profile="0x16180CC0", library="0x16173C60", iterator="0x161748A0"),
                          "2008": dict(strategy="0x162E43E0", family="0x160849A0", plain="0x160849C0", profile="0x16180820"),
                          "selector": "Active SM3 getter returns 30h for nonzero HDR; plain getter returns 30. Material family IDs 6/7 share these strategies; full HDR strategy has state 2 and family ID 7.",
                          "runtime": "D3DXGetVertexShaderProfile/D3DXGetPixelShaderProfile and D3D caps advertise SM3; Profile.writeRenderer forces fx_3_0 / fx_3_0hs / fx_3_0hf to match HDR off / simplified / full. Lighting and shadow quality do not change this strategy selection."},
                releases=releases)


if __name__ == "__main__":
    path = ROOT / "research/material-cache-fixed-high.json"
    data = manifest()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for release in data["releases"]:
        print(f"{release['release']}: {release['bytes_original']:,} -> {release['bytes_seeded']:,} bytes; {release['bytes_omitted']:,} omitted")
    print(path)
