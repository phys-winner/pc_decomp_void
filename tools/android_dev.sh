#!/bin/bash
# Build the ARM64 host, push it to the bring-up device and run it there.
#   tools/android_dev.sh [--no-build] [host args...]
set -e
export MSYS_NO_PATHCONV=1
ADB="${ADB:-adb}"
SERIAL="${ANDROID_SERIAL:-${VOID_SERIAL:?Set ANDROID_SERIAL or VOID_SERIAL}}"
cd "$(dirname "$0")/.."
if [ "$1" != "--no-build" ]; then
    python tools/build_android.py --jobs 12 2>&1 | grep -v "^\[progress\]" | grep -v "nfences\|^ 4002\|      |  \|In file included from.*memory.c\|^1 warning generated\|^\[warn\] android/host/memory.c" | tail -30
    "$ADB" -s "$SERIAL" push build/arm64/void-arm64 /data/local/tmp/void/ | tail -1
else
    shift
fi
"$ADB" -s "$SERIAL" shell "cd /data/local/tmp/void && chmod 755 void-arm64 && timeout ${VOID_TIMEOUT:-120} ./void-arm64 $* 2>&1; echo exit=\$?"
