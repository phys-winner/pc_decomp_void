#!/bin/bash
# A/B timing on the bring-up device: run one ARM64 build with the scripted
# input (new game, first location) and print the frame statistics it logs.
#   tools/android_bench.sh [BUILD_DIR] [RUN_SECONDS] [NAME=VALUE...]
# BUILD_DIR defaults to build/arm64 (build/arm64-globalregs-volatilemem for the
# upstream code model); NAME=VALUE pairs are passed to the game's
# environment (VOID_MDCT=lifted, ...); VOID_BENCH_INPUT picks another input script
# (build/input-load-save.txt: the map of the newest save). The log stays on the
# device as bench.log.
set -e
export MSYS_NO_PATHCONV=1
ADB="${ADB:-adb}"
SERIAL="${ANDROID_SERIAL:-${VOID_SERIAL:?Set ANDROID_SERIAL or VOID_SERIAL}}"
BUILD="${1:-build/arm64}"
RUN_SECONDS="${2:-170}"
shift 2 2>/dev/null || shift $#
cd "$(dirname "$0")/.."
# A running game keeps the executable busy (ETXTBSY): stop it before the push.
"$ADB" -s "$SERIAL" shell "kill \$(pidof void-arm64) 2>/dev/null; sleep 1" || true
"$ADB" -s "$SERIAL" push "$BUILD/void-arm64" /data/local/tmp/void/void-arm64 >/dev/null
"$ADB" -s "$SERIAL" push "${VOID_BENCH_INPUT:-build/input-profile.txt}" /data/local/tmp/void/profile-input.txt >/dev/null
"$ADB" -s "$SERIAL" shell "cd /data/local/tmp/void && chmod 755 void-arm64 && \
  echo \"cpu temp: \$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)\" && \
  env $* VOID_INPUT=/data/local/tmp/void/profile-input.txt VOID_SHADER_WAIT=60 \
  timeout $RUN_SECONDS ./void-arm64 > bench.log 2>&1; \
  grep -e 'fps' -e 'signal' -e 'fatal' -e 'mdct' bench.log | tail -9"
