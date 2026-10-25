"""Local toolchain settings; no machine paths or device IDs belong in source."""
import os
from pathlib import Path

SDK = Path(os.environ.get("ANDROID_SDK") or os.environ.get("ANDROID_HOME") or
           os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "AppData/Local/Android/Sdk")
NDK = Path(os.environ.get("ANDROID_NDK", SDK / "ndk/27.2.12479018"))
JAVA_HOME = Path(os.environ.get("JAVA_HOME", ""))
ADB = os.environ.get("ADB", str(SDK / "platform-tools/adb.exe"))
