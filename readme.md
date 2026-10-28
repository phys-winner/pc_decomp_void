# pc_decomp_void

## Version 0.3-dev

Missing shader variants compile in a separate process on small CPU cores, with
private learned caches, a pregenerated shader pack and additional GL warm-up recipes.
The launcher can convert textures to ASTC 4x4 or ETC2, report GPU support and control FPS.
This release also adds adaptive physics timing, x4 anisotropy defaults, water-reflection
controls, region-lighting caching, body-screen/map-picture fixes and corresponding
Tension improvements. See [CHANGELOG.md](CHANGELOG.md) for the complete release notes
and [TECHDEBT-2008.md](TECHDEBT-2008.md) for remaining Tension work.

The texture encoders are pinned upstream Git submodules: ASTC Encoder 5.7.0
(`baff485b0ff36d2f95d28961605106502c653966`) and etcpak
(`3d716e1550023dc5ff8b602636af8b76584e0b66`, including bcdec). Initialize them with
`git submodule update --init --recursive`; dependency fetching also initializes
missing submodules and checks their revisions. No copied encoder sources are tracked
in the parent repository. `STATE.md` and `research/` remain local and ignored.


Native Android ARM64 port of **The Void**, built by statically recompiling the
original PC x86 executables to C and providing an Android Win32 compatibility
layer. The launcher can also run the separate **Tension (2008)** build.

**Bring your own original game files.** This repository contains the port's
sources, function catalogs, build tools and tests. Original EXE/DLL files,
game assets, generated game C, APKs, private configuration and signing keys are
excluded from version control.

The port has been tested with the **Russian Steam version of The Void**:
[The Void on Steam](https://store.steampowered.com/app/37000/The_Void/).
This is an unofficial fan project, independent of Ice-Pick Lodge and the other
rights holders. Game names and original content belong to their respective owners.

## Status

Current version: **0.3-dev** (`versionCode=4`). See [CHANGELOG.md](CHANGELOG.md). This is a development build for
sideloading, signed with a local development key.

- Original x86 game logic is translated ahead of time with
  [pcrecomp](https://github.com/sp00nznet/pcrecomp) and compiled by the Android NDK.
- The native host provides Win32, Direct3D 9, sound, filesystem, input and PhysX
  compatibility. Rendering uses OpenGL ES; there is no Windows emulator or JIT.
- The Android launcher imports a game folder or ZIP and provides graphics,
  audio, touch, gyro and other port settings.
- Touch controls cover movement, camera, interaction, drawing, the heart, map
  and journal. Mouse, keyboard and gamepad handling are also included.
- The Void 2009 and optional Tension 2008 use separate native libraries and
  release-specific script patches. The app identifies the supplied game data.
- Native libraries are packed as independently checked 128 MiB XZ chunks and
  unpacked in parallel on the first launch. The APK supports 16 KB native-library alignment.
- The 2009 library includes a lifted D3DX shader compiler; the build also
  generates a cache from the original game's static and procedural shaders.

The project is still in development. A complete playthrough, every scene,
save, ending and device/GPU combination have not been exhaustively tested.
Unsupported x86/x87 paths can stop with diagnostic traps. Performance and
shader preparation time depend on the scene and device.

## Build requirements

The supplied build tools currently target **64-bit Windows and PowerShell**.
Gradle and Android Studio are not required when the command-line tools are
installed.

| Component | Version/configuration used |
| --- | --- |
| Python | 3.13; packages pinned in `requirements.txt` |
| Git | Available on `PATH` |
| Java | JDK 24; set `JAVA_HOME` |
| Android SDK Platform | `platforms;android-36` |
| Android SDK Build Tools | `build-tools;36.1.0` |
| Android NDK | r27c, `27.2.12479018` |
| Android Platform Tools | Optional, for ADB deployment |
| Visual Studio C++ tools | x86 compiler and Windows SDK, for the shader-cache helper |
| XZ Utils | 5.4 or newer; `XZ`, `PATH` or the Git for Windows copy |
| Target device | ARM64, OpenGL ES 3.2; Android 11/API 30 or newer recommended |

The manifest declares API 26 as the minimum and API 28 as the target; native
code is currently compiled for API 30. Older Android versions are unverified.
Allow several gigabytes for the games and substantially more for generated C,
object files and native libraries. The default native build uses 12 compiler jobs.

Install the Android components with the SDK Manager or `sdkmanager.bat`:

```powershell
sdkmanager.bat "platforms;android-36" "build-tools;36.1.0" "ndk;27.2.12479018" "platform-tools"
```

## Original inputs

Use your own legally obtained PC installation. The lifters check SHA-256 before
translating the binaries; another executable build cannot be substituted just
because its filename matches.

For The Void 2009, point `game_directory` at the complete Russian Steam
installation, containing `bin/win32`, `data` and the game's other directories.
The exact original inputs include:

| Input | SHA-256 |
| --- | --- |
| `bin/win32/Game.exe` (Steam original) | `5e58f8183ce15110a21120e317c439af14b245e57f973ed274c3c4c27f3d21f2` |
| `bin/win32/GameModule.dll` | `a0075c2316bdb658724aaec595339a8ad2459832620b0a9dac3c7359a4330562` |
| `bin/win32/Engine.dll` | `bb7c9f554e1eb96ef11a99c2bddeb26e73de26680da7ce1a86acd3eb353c5061` |
| PhysX 2.8.1 `PhysXCore.dll` | `df8d6bf07d024b8dce846a4bfcc5fdf4c42afc5e67acd43afb66cf28bfffff88` |
| PhysX 2.8.1 `PhysXCooking.dll` | `c6fd154743ff39427a22aef0c41592ee2b555c046aa32121eeb5fc9e24bc2494` |
| DirectX November 2007 x86 `d3dx9_36.dll` | `c12f0ab0338eb5031d3d04beaf7208ac848f7e037d21ff963d2af90221cbe935` |

FS, VFS, Sound, Video, RendererD3D and NxCharacter are also required; their exact
hashes are pinned in the corresponding `tools/lift_*.py` files. PhysXLoader is
handled by the host; supply the two matching PhysX engine DLLs from your own
installation of the NVIDIA legacy system software.

The build processes the Steam executable into an ignored working copy and
verifies its recovered hash. Original installations are read-only inputs.
All required function catalogs are in `config/`; IDA databases and local
research reports are not needed to build the Android app.

## Build the APK

Run these commands from the repository root.

1. Install the Python requirements and fetch the pinned source dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   $env:PYTHONUTF8 = "1"
   python -m pip install -r requirements.txt
   .\tools\fetch_dependencies.ps1
   ```

   The dependency script checks Git revisions and rejects modified tracked
   dependency files. The vendored dlmalloc source is checked by SHA-256.
   Do not substitute the dependencies' latest branches.

2. Configure your local toolchains and original files:

   ```powershell
   $env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
   $env:ANDROID_NDK = Join-Path $env:ANDROID_HOME "ndk\27.2.12479018"
   $env:JAVA_HOME = Read-Host "JDK installation directory"
   Copy-Item port.example.json port.json
   notepad port.json
   ```

   Set `game_directory`, `physx_directory` and `d3dx_compiler` to your inputs.
   Paths can be absolute or relative to the repository root. The example uses
   ignored directories under `original/`. In JSON, use forward slashes or
   escaped backslashes. Keep `port.json` private.

   Paths such as `C:\Games\The Void` and `C:\Users\Player` in the native host
   describe its synthetic Windows filesystem, not a developer's computer.

   The Android SDK is selected through `ANDROID_SDK`, `ANDROID_HOME`,
   `ANDROID_SDK_ROOT`, then the current Windows account's usual SDK directory.
   `ANDROID_NDK` overrides the pinned NDK location. `JAVA_HOME` must contain
   `bin/javac.exe` and `bin/keytool.exe`.

   Extract the D3DX input from your own game's DirectX redistributable:

   ```powershell
   $game = (Get-Content port.json -Raw | ConvertFrom-Json).game_directory
   New-Item -ItemType Directory -Force original | Out-Null
   expand.exe -F:d3dx9_36.dll (Join-Path $game "DirectX\Nov2007_d3dx9_36_x86.cab") original
   ```

   With the example configuration, the extracted file is
   `original/d3dx9_36.dll`. If you use a different destination, update
   `d3dx_compiler` accordingly. The shader-cache helper loads this verified DLL
   from its own build directory and does not require a system-wide D3DX copy.

Both APK builders require your protected signing key at `android/debug.keystore`
(alias `androiddebugkey`, store/key password `android`). Supply your own development
key before building and keep it for subsequent updates. Missing or unusable keys
stop the build; the builders never generate or replace a key automatically.
Keep all signing keys out of version control.

3. Generate C and the original asset index, then compile, package, align and sign:

   ```powershell
   python -B tools/prepare_android.py
   python -B tools/build_game_apk.py
   ```

   Preparation logs are under `build/prepare`. Generated PE copies and C are
   under `generated/`. Shader bytecode, script overrides and all native build
   outputs stay under ignored directories.

   Preparation indexes the resources in `game_directory`. If the verified
   binaries and the desired localization's resources are kept in separate
   installations, explicitly index the desired data before packaging:

   ```powershell
   python -B tools/build_vfs_index.py --game original/the-void-russian --out research/vfs-index.json
   ```

   This command supplies resources only; executable hashes remain checked
   against the configured original Steam inputs. The resource index must match
   the game data you intend to run.

The APK is written to **`build/android-game/the-void.apk`**. A complete build
also writes **`pub/the-void-0.3-dev-<sha256-prefix>.apk`**. The eight-character
suffix is the first eight hexadecimal characters of the signed APK's SHA-256.

To limit native compilation parallelism, build first and package those libraries:

```powershell
python -B tools/build_android.py --shared --jobs 4
python -B tools/build_game_apk.py --skip-native
```

### Optional Tension 2008

Tension is a different build, supplied by the Polish release/depot. It requires
its own complete original installation and **PhysX 2.7.3**, rather than the
2009 version's PhysX 2.8.1. Exact inputs are recorded in
[`config/releases/tension.json`](config/releases/tension.json).

Set `releases.tension.game_directory` and `releases.tension.physx_directory`
in your private `port.json`, then prepare both versions:

```powershell
python -B tools/prepare_android.py --tension
python -B tools/build_game_apk.py
```

The APK builder includes Tension when `generated/tension/release.json` exists.
For a smaller build containing only the 2009 version, use
`python -B tools/build_game_apk.py --release-only void`. For limited compiler
parallelism with both versions, additionally run
`python -B tools/build_android.py --shared --release tension --jobs 4`
before packaging with `--skip-native`.

German script patches are optional. To include them, index your own complete
German installation before packaging:

```powershell
python -B tools/build_vfs_index.py --game original/the-void-german --out research/vfs-index.german.json
```

The debug-picker regeneration check also needs this German index and the
Polish index; the checked-in picker sources allow ordinary APK builds without
those optional inputs.

## Install and supply data

Install the APK on an ARM64 Android device, open The Void launcher and grant
the requested file access. Select a complete game folder or import a ZIP of
your installation. Store different releases in separate folders. The APK
contains the lifted executable images and port patches; the game's full
resources must be supplied separately.

The first launch unpacks the selected native library and prepares caches.
Saves, settings, logs and writable caches live in `userdata` inside the game
folder selected in the launcher. Existing profiles under `/sdcard/TheVoid`
move there at startup; destination files take priority, and conflicting
originals remain in the old folder. Back up your saves before switching
between independently signed builds.

ADB deployment is optional and requires an explicitly selected device:

```powershell
adb devices
$env:ANDROID_SERIAL = Read-Host "ADB device serial"
python -B tools/build_game_apk.py --skip-native --install
```

You can pass `--serial SERIAL` instead. Building without deployment flags does
not contact a phone. No device identifier belongs in tracked configuration.

## Versioning and checks

Versions follow `0.1-dev`, `0.3-dev`, `0.3-dev`, and so on, with Android version
codes `2`, `3`, `4`, respectively (`versionCode = minor + 1`). The source of
truth is `android/app/AndroidManifest.xml`. Rebuilding does not bump the version.

```powershell
python -B tests/test_publication.py
python -B tests/test_d3dx_lift.py
python -B tests/test_apk_package.py
```

The publication check audits the files Git would publish, private-file
exclusions, example settings, version numbering, toolchain selection and the
preparation workflow. The APK check verifies signature, ZIP integrity, 16 KB
alignment, lossless stripping, native XZ chunks and indexed assets. The full
APK check expects both game versions to have been prepared and packaged.

Additional regression tests are in `tests/`. Some require original files,
generated modules, the Windows C++ toolchain or an explicitly selected device;
they are not a single portable test suite.

## License and credits

The project's own port code, tools and documentation are licensed under the
**GNU General Public License, version 3 or (at your option) any later version**
(`GPL-3.0-or-later`). See [LICENSE](LICENSE). This is a strong copyleft license;
distribution of covered modifications must preserve its source availability
and licensing requirements.

Third-party code retains its original license and attribution. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), including pcrecomp, MojoShader,
dlmalloc, stb, XZ Embedded, Xiph codecs and The Void Extractor.

This license grant covers only code and documentation the project can license.
It does not relicense The Void, Tension, their resources, proprietary middleware,
or code generated from their binaries. An APK built with those inputs contains
original or transformed third-party material and is not a wholly GPL-owned
replacement for the original games. The source repository supplies none of
those proprietary inputs.
