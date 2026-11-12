# Shared launcher source

This directory contains the shared launcher source used by The Void and Tension
0.5-dev. The Java templates are rendered into `org.thevoid.port.launcher` by
`tools/launcher.py`; the game specification is `../port.json`. The repository's
[GPL-3.0 license](../../LICENSE) applies to this source snapshot.

The APK builder selects `PORT_LAUNCHER`, this bundled copy, or a neighboring
launcher checkout, in that order. A normal clone therefore has the launcher
sources needed for the Android build. Android SDK 37 and a JDK are required.

```powershell
python android/launcher/tools/launcher.py check --spec android/port.json
python android/launcher/tools/update_manifest.py --repo phys-winner/pc_decomp_void --out build/update.json --state build/versions.json
```

The manifest tool reads the version and signing certificate from the APK and
checks GitHub asset hashes. Publish the release as latest and attach its
`update.json` so the launcher can find updates. Game data, keys and generated
outputs are not part of this directory.
