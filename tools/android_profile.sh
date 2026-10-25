#!/bin/bash
# Profile the ARM64 host on the bring-up device with simpleperf.
#   tools/android_profile.sh INPUT_SCRIPT WAIT_SECONDS [DURATION_SECONDS]
# Starts void-arm64 with the scripted input, waits until the scene of
# interest, records a flat CPU profile of all threads and prints the hottest
# symbols (report in build/android-profile.txt).
set -e
export MSYS_NO_PATHCONV=1
ADB="${ADB:-adb}"
SERIAL="${ANDROID_SERIAL:-${VOID_SERIAL:?Set ANDROID_SERIAL or VOID_SERIAL}}"
INPUT="$1"
WAIT="${2:-120}"
DURATION="${3:-10}"
cd "$(dirname "$0")/.."
"$ADB" -s "$SERIAL" push "$INPUT" /data/local/tmp/void/profile-input.txt >/dev/null
"$ADB" -s "$SERIAL" shell "cd /data/local/tmp/void && rm -f perf.data && \
  (VOID_INPUT=/data/local/tmp/void/profile-input.txt VOID_SHADER_WAIT=60 ./void-arm64 > profile-run.log 2>&1 &) && \
  sleep $WAIT && pid=\$(pidof void-arm64) && \
  simpleperf record -p \$pid --duration $DURATION -f 2000 -o perf.data >/dev/null 2>&1; \
  simpleperf report -i perf.data --sort comm,symbol --percent-limit 0.3 2>/dev/null | head -80; \
  kill \$pid 2>/dev/null; grep 'fps' profile-run.log | tail -3" | tee build/android-profile.txt
