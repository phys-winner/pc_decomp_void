# Changelog

## 0.2-dev — 2026-10-27

Development release of the native Android ARM64 port of **The Void (2009)** and **Tension (2008)**. Bring your own original game files.

## Changes

- Fixed the Body/Memory tutorial exit that could leave progression waiting after the screen closed. The original color refunds, inventory restoration and tutorial conditions are preserved. Updated the instructions in four languages and bundled six missing tutorial shaders.
- Improved color transfers, heart labels, Body-to-journal transitions, page navigation and the three-finger map gesture.
- Corrected shader state handling and SM3/HDR quality selection, audio listener parameters, voice/ambience routing and audio-worker scheduling. Added native fast paths for selected rendering and data-decompression operations.
- Updated developer location routes for both game versions, corrected legacy conversation/battle entry commands and removed routes with verified missing original dependencies.
- Improved native-library compression using independent 128 MiB XZ blocks and tuned LZMA literals. Compared with the first 0.2-dev package, the compressed libraries decreased from **147.1 MB to 138.3 MB (6.0%)** and the APK from **171.8 MB to 163.0 MB (5.1%)**. The unpacked library bytes are unchanged by repacking.
- Both APK builders now require an existing protected project signing key and stop if it is missing or unusable.

## Measured performance

Paired tests on a Snapdragon 8s Gen 3, with three loads per build and warm filesystem/shader caches:

| Location and route | Median loading time | CPU time during loading |
| --- | --- | --- |
| Map to Ire's Lake (`Girl/ire.xml`) | 11.22 → 10.34 s (**7.8% less**) | 11.94 → 10.82 s (**9.4% less**) |

A sustained FPS increase was not established in Ire (`Girl/ire.xml`), Yuna (`Girl/una.xml`) or Fog (`Park/foggyroots.xml`). The comparative CPU samples used the same 20 FPS limit and do not measure maximum FPS. The loading results are a small warm-cache sample.

## Download and update

- APK: **the-void-0.2-dev-20fc240f.apk**, **162,963,047 bytes**.
- Android version: **0.2-dev**, version code **3**.
- Signed with the same APK key as the previous release, for compatible updates.
- Original game resources must be supplied separately. Saves, settings and caches are stored in `userdata` next to the selected game copy.

Source licensing and third-party notices are included with the release.

Package validation passed: signature, ZIP integrity, 16 KB alignment, both native libraries, all **16,653 indexed asset records**, and independent-stream decoding through XZ Embedded. A corrupted-stream negative control was rejected.

This is a testing build. A complete playthrough and every language/device combination have not been exhaustively tested. First-launch unpack time with the larger blocks has not been remeasured on a phone. The reported persistent audio echo was not reproduced during validation.

### APK SHA-256

```text
20fc240f68b03c0c4b20734f89a68b03fd88b8581829823e4be6260b723d2bac
```
