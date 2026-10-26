"""Keep Uta's mono ambience distinct from the localized stereo intro Poema."""
import json
from pathlib import Path
import struct
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCENE = "Scenes\\Girl\\uta.xml"
ALIAS = "port_poema_mono"


def poema_overrides(index_path):
    index = json.loads((ROOT / index_path).read_text(encoding="utf-8"))

    def exact(name):
        for container in index["containers"]:
            for entry in container["entries"]:
                if entry["name"] == name:
                    source = Path(index["source"])
                    if not source.is_absolute():
                        source = ROOT / source
                    with (source / container["name"]).open("rb") as archive:
                        archive.seek(entry["offset"])
                        data = archive.read(entry["size"])
                    assert len(data) == entry["size"]
                    return data
        raise ValueError("missing original asset: " + name)

    scene = exact(SCENE)
    actors = [actor for actor in ET.fromstring(scene).iter("Actor")
              if actor.find("Properties/property[@name='Sound'][@value='poema']") is not None]
    assert len(actors) == 1
    assert actors[0].find("Script").get("Filename") == "sound/gen_sound3dperiod"
    before = b'name="Sound" value="poema"'
    assert scene.count(before) == 1
    patched = scene.replace(before, b'name="Sound" value="' + ALIAS.encode("ascii") + b'"')
    assets = [(SCENE, SCENE, scene, patched)]
    for rate in (22, 44):
        original = "Sounds\\poema#%d.ogg" % rate
        data = exact(original)
        packet = data.index(b"\x01vorbis")
        assert data.startswith(b"OggS") and data[packet + 11] == 1
        assert struct.unpack_from("<I", data, packet + 12)[0] > 0
        assets.append(("Sounds\\%s#%d.ogg" % (ALIAS, rate), original, data, data))
    return assets
