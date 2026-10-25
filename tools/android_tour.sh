#!/bin/bash
# tools/android_tour.sh OUTDIR N... : with the game running (console enabled), visit each
# location number with the console's /go N, wait for it, screenshot it, and
# record whether the process lives and what the game log says.
# Env: VOID_RELEASE / VOID_GAME as for tools/android_live.sh.
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
ADB="${ADB:-adb}"
SERIAL="${ANDROID_SERIAL:-${VOID_SERIAL:?Set ANDROID_SERIAL or VOID_SERIAL}}"
out=$1; shift
mkdir -p "$out"
BIN=void-arm64; [ -n "${VOID_RELEASE:-}" ] && BIN=void-arm64-$VOID_RELEASE
for n in "$@"; do
  before=$("$ADB" -s "$SERIAL" shell "wc -l < /data/local/tmp/void/live.log" | tr -d '\r')
  bash tools/android_live.sh send 'key C0' 'sleep 0.8' >/dev/null
  bash tools/android_type.sh "/go $n"
  bash tools/android_live.sh send 'sleep 1' 'key C0' 'sleep 1' >/dev/null
  # wait for a settled frame rate with real draws (or 120 s)
  for i in $(seq 1 60); do
    sleep 2
    l=$("$ADB" -s "$SERIAL" shell 'tail -1 /data/local/tmp/void/live.log')
    d=$(echo "$l" | sed -n 's/.* \([0-9]*\) draws.*/\1/p'); f=$(echo "$l" | sed -n 's/.*: \([0-9]*\)[0-9.]* fps.*/\1/p')
    [ $i -gt 8 ] && [ -n "$d" ] && [ "$d" -gt 20 ] && [ -n "$f" ] && [ "$f" -gt 8 ] && [ "$f" -lt 300 ] && break
  done
  sleep 4
  if ! "$ADB" -s "$SERIAL" shell "pidof $BIN" >/dev/null; then
    echo "location $n: PROCESS GONE"
    "$ADB" -s "$SERIAL" shell "tail -n +$before /data/local/tmp/void/live.log | grep -a -v '^\[gl\] frame' | tail -20"
    exit 1
  fi
  bash tools/android_live.sh shot "$out/loc-$n.png" >/dev/null
  fps=$("$ADB" -s "$SERIAL" shell 'tail -1 /data/local/tmp/void/live.log' | sed -n 's/.*: \([0-9.]*\) fps.*draws.*/\1/p' | tr -d '\r')
  errs=$(bash tools/android_live.sh log 40 | grep -c "<Error>")
  name=$(bash tools/android_live.sh log 40 | grep -a "music inited\|location inited" | tail -1 | sed 's/.*]: //')
  echo "location $n: ok, ${fps} fps, ${errs} script errors in the last 40 log lines; $name"
done
