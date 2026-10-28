# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project rules (from the user)

- **Change only the 2009 game ("The Void", library `libvoid.so`).** Do not change behaviour of the
  2008 game (Tension, the Polish CD Projekt release, library `libvoid_tension.so`, `config/releases/tension.json`).
  Host code is shared by both libraries: put 2009-only native changes under `#ifndef VOID_RELEASE`
  (the Tension build defines `VOID_RELEASE`), and gate Java changes on the release
  (`GameActivity.Release.library`: `"void"` is 2009, `"void_tension"` is 2008).
- **Every 2009 change that 2008 would need goes into [TECHDEBT-2008.md](TECHDEBT-2008.md)**
  (what, where, why it is not ported, what porting needs). 2008 tech debt is kept only there.
- **Commits** happen only when the user asks. Before committing:
  1. read TECHDEBT-2008.md and tell the user which items are open;
  2. make sure no committed file carries personal data: device serials (adb serials such as
     those in `adb devices`), local network IPs/ports, user names, e-mail addresses, Windows user paths
     (a Windows home directory), private keys. Local files to check: `port.json` (`device`),
     `STATE.md` (device serials, LAN addresses). Write "the test phone (POCO X3 NFC)" instead of a serial.
  3. Sign release commits with the user's configured GPG key and public GitHub identity.
     Keep private keys and personal machine details outside the repository.
- `android/debug.keystore` is a protected build input (the APK update key): never delete or regenerate it.
- Test only on the phone the user names; other phones attached to adb are someone else's.
  Do not touch the player's own `userdata`/saves: use a QA profile folder next to it.

## What this is

A static recompilation of The Void (Ice-Pick Lodge, 2008/2009, 32-bit Windows) to ARM64 Android.
The game's x86 DLLs/EXE are lifted function by function into C (`generated/<module>-x86/*.c`, not in Git),
compiled with the NDK together with a Win32/Direct3D 9/DirectSound/PhysX high-level emulation host
into one shared library, and run by a Java app without Gradle. The original game files are an
input the player supplies; nothing from the game is committed. `README.md` is in English;
`CHANGELOG.md` is in Russian. `STATE.md` and `research/` are local, ignored working notes.

## Commands

All commands run from the repository root (Windows; Python 3.13, NDK 27 under the Android SDK, JDK).

```powershell
python -B tools/build_android.py --shared --jobs 4                     # 2009 libvoid.so (build/arm64)
python -B tools/build_android.py --shared --jobs 4 --release tension   # 2008 libvoid_tension.so (build/arm64-tension)
python -B tools/build_game_apk.py --skip-native --no-publish           # APK from both built libraries -> build/android-game/the-void.apk
python -B tests/test_apk_package.py --no-publish                       # signature, 16 KB alignment, xz streams, assets
adb -s <serial> install -r build/android-game/the-void.apk             # keep data; same signing key
```

- `build_android.py` reuses objects by SHA-256 fingerprint: a host-only change recompiles a few files
  and relinks (~1 min); a header in `android/runtime` or `android/host/*.h` recompiles more.
  Both libraries must be rebuilt when shared host code changes, before packaging.
- `build_game_apk.py` without `--no-publish` also copies a signed APK to `pub/` (a release step: only on request).
  It packs the libraries as xz (cached in `build/native-xz`), `build/shadercache/results`,
  `build/overrides` (patched game scripts), `lib/arm64-v8a/libvoidxz.so` and `libtexconv.so`.
- Patched game scripts/strings: `python -B tools/patch_scripts.py` regenerates `build/overrides`
  (the in-game options pages come from `tools/patch_options.py`).
- Shader cache for the APK: `tools/build_shader_cache.py`; device misses can be served by
  `tools/shader_service.py`, but the phone compiles missing shaders itself by default (see below).
- Dependencies: `tools/fetch_dependencies.ps1` (pinned in `dependencies.json`; `reference/astcenc` and
  `reference/etcpak` are pinned upstream Git submodules).
- Windows x86 stage (earlier work, see README): `tools/build_x86.ps1 -Sound`, `tools/run_x86.ps1 -Sound`.

Tests are standalone scripts; run one with `python -B tests/test_<name>.py` (a few are unittest-based and
accept `-k`). Many need local inputs: the original game under `original/`, `port.json`'s Steam
directory, `generated/`, or build artifacts (`build/runtime-assets`, `build/native-ui`); a missing
input fails with FileNotFoundError, which is an environment gap, not a regression. Java changes:
`python -B tests/test_shader_progress.py` compiles every Java source against the real Android API.

## Architecture

- **Lifting** (`tools/lift_*.py`, catalogs `config/<Module>.functions.json`, jump tables): each module is
  rebased (RendererD3D at `0x16000000`, Engine `0x11000000`, FS/VFS `0x12/0x13000000`, the lifted
  Microsoft d3dx9_36 compiler at `0x1A000000`; IDA databases use the original bases, e.g. RendererD3D
  `0x10000000`, so `sub_16207990` in a profile is `0x10207990` in IDA). Generated C keeps x86 state in
  globals (`g_eax`, `g_esp`, lazy flags `g_flag_k/a/b/cf`, x87 `g_st`/`g_fp_top`) declared in
  `android/runtime/recomp_types.h`; guest memory is a 4 GB reservation (`MEM32`, `GPTR`).
- **Native overrides**: a function listed in `NATIVE_OVERRIDES` (tools/build_android.py; a release's list is
  `native_overrides` in `generated/<release>/release.json`) is renamed `<name>_lifted` and replaced by a host C function of
  the same name, which must leave the guest state exactly as the original would (stack/ESP after `ret n`,
  callee-saved registers, flags when consumed) and usually falls back to `_lifted` when its checks fail.
  Examples: `android/host/renderer_region_native.c`, `physx.c` (`sub_110DE7C0`), `renderer_native.c`.
  Host files name the overridden functions and the image constants they read through macros (2009 values
  under `#ifndef VOID_RELEASE`); for a release `tools/lift_release.py --finish` writes them into
  `generated/<release>/release_overrides.h` from the release's twins of the 2009 bodies (same bytes but for
  relocated fields and outside branches, found by content; `TWINS` there), so an override whose twin is
  missing simply is not compiled for that release. Shared modules (the lifted compiler) come from the 2009 stage.
- **Host** (`android/host`): Win32 APIs, threads, files/VFS (`files.c`), COM objects (`com.c`),
  Direct3D 9 on GLES 3.2 (`d3d9_*.c`; shaders through MojoShader + a GLSL program cache),
  D3DX (`d3dx9.c`: textures, shader compile with the profile/APK cache and the lifted compiler),
  DirectSound/Vorbis, PhysX glue (`physx.c`), touch HUD (`hud.c`), entry and JNI (`android_main.c`).
  `void_log` writes `<profile>/void.log`; the game's own log is `<profile>/Documents/My Games/<title>/LogFiles/game.log`.
- **App** (`android/app/src/org/thevoid/port`): `Launcher` (game folder, unpacking, options, texture
  conversion card), `GameActivity` (starts the native game, settings into the game's `settings.xml`),
  `Controls` (touch layer), `Settings` (SharedPreferences `touch` + the game's `Port*` props),
  `NativeLibrary` (unpacks the xz libraries on first start), `Images` (lifted PE images).
- **Profiles**: the writable profile lives in `<game folder>/userdata` (QA runs use another folder name,
  passed as `--es userdata`). Live debug commands: append lines to `<profile>/live.txt`
  (e.g. `console /go 18`, `camera N`, `move dx dy`); `[location]`, `[gl] frame` and `[camera]` lines in
  void.log are what the benchmark scripts read.
- **Shaders**: RendererD3D generates HLSL per light/shadow/fog variant and asks D3DXCompileShader again in
  every frame for a variant it could not get (the object is then not drawn). The game keeps its own
  effect/shader DBs in `<profile>/PublicDocuments/My Games/<title>/Cache` (copied from the game's `Void`
  folder at profile creation; delete it for a cold test). Answers come from the profile cache, the APK
  bundle (`build/shadercache/results`), the APK pack (`assets/shaderpack.bin` from
  `build/shadercache/pregen-results`, the script's `shaderwarm` pregenerator), or the on-device compile
  (lifted d3dx9_36, byte-identical to fxc; both games save results in the app's private
  `files/shaderlearned/<hash>.bin`, looked up first; `no-device-compile` / `no-bundle` files switch it).
  A variant missing inside the pass builder (`sub_161FCEC0` in 2009, renderer_native.c) goes to
  `ShaderCompilerService` (process `:shaders` with the game's own library, small cores, page
  `files/shaderservice`, requests `files/shaderrequests`) and the build fails until it answers;
  `no-compile-service` turns that off. GL program recipes: `build/shaderwarm`
  (`tools/merge_shader_recipes.py` merges phones' `files/shaderwarm`).
- **Textures**: Adreno 6xx has no S3TC; DXT is decoded to RGBA8 at load unless the launcher converted the
  game's textures into `<game>/data/port-textures.tvt` (ETC2 or ASTC, `android/texconv`, format in `tvtx.h`).
