#!/bin/bash
# Profile-guided optimisation of the generated code on the bring-up device.
#   python tools/build_android.py --pgo-generate      (build/arm64-pgogen)
#   tools/android_pgo.sh [SCRIPT...]                  train, pull, merge -> build/pgo/void.profdata
#   python tools/build_android.py --pgo-use build/pgo/void.profdata
# Each training script runs the instrumented game once and ends with `quit`,
# which writes the profile (script.c); the defaults cover intros, the menu, a
# new game's first location and a loaded save's map.
set -e
export MSYS_NO_PATHCONV=1
ADB="${ADB:-adb}"
SERIAL="${ANDROID_SERIAL:-${VOID_SERIAL:?Set ANDROID_SERIAL or VOID_SERIAL}}"
PROFDATA="${PROFDATA:-${ANDROID_NDK:?Set ANDROID_NDK}/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-profdata.exe}"
DIR=/data/local/tmp/void
cd "$(dirname "$0")/.."
scripts=("$@")
[ ${#scripts[@]} -gt 0 ] || scripts=(build/input-pgo-location.txt build/input-pgo-map.txt)
"$ADB" -s "$SERIAL" shell "kill \$(pidof void-arm64) 2>/dev/null; rm -f $DIR/pgo-*.profraw; sleep 1" || true
"$ADB" -s "$SERIAL" push build/arm64-pgogen/void-arm64 $DIR/void-arm64 | tail -1
for script in "${scripts[@]}"; do
    "$ADB" -s "$SERIAL" push "$script" $DIR/pgo-input.txt >/dev/null
    echo "training with $script"
    "$ADB" -s "$SERIAL" shell "cd $DIR && chmod 755 void-arm64 && LLVM_PROFILE_FILE=$DIR/pgo-%p.profraw \
        VOID_INPUT=$DIR/pgo-input.txt VOID_SHADER_WAIT=60 timeout 900 ./void-arm64 > pgo-run.log 2>&1; \
        grep -e 'profile written' -e 'signal' -e 'fps' pgo-run.log | tail -4"
done
mkdir -p build/pgo
rm -f build/pgo/*.profraw
for f in $("$ADB" -s "$SERIAL" shell "ls $DIR/pgo-*.profraw" | tr -d '\r'); do
    "$ADB" -s "$SERIAL" pull "$f" build/pgo/ | tail -1
done
"$PROFDATA" merge -o build/pgo/void.profdata build/pgo/*.profraw
ls -la build/pgo/void.profdata
