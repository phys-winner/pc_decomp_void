#!/bin/bash
# Drive one running void-arm64 on the bring-up device by hand: the game reads
# new lines of a command file as they arrive (VOID_INPUT_LIVE, script.c).
#   tools/android_live.sh push                    stop the game and install build/arm64/void-arm64 (hash-checked)
#   tools/android_live.sh start [TIMED_SCRIPT]   start the game (optionally with a timed script too)
#   tools/android_live.sh send 'down 57' 'sleep 2' 'up 57'
#   tools/android_live.sh shot [OUT.png]          dump the next frame, fetch it as PNG (960x540)
#   tools/android_live.sh log [N]                 last N lines of the game's own log
#   tools/android_live.sh stop
# VOID_RELEASE=tension drives the 2008 Polish build instead: build/arm64-tension,
# void-arm64-tension, /sdcard/TheVoid/game-polish and lifted-tension.
set -e
export MSYS_NO_PATHCONV=1
ADB="${ADB:-adb}"
SERIAL="${ANDROID_SERIAL:-${VOID_SERIAL:?Set ANDROID_SERIAL or VOID_SERIAL}}"
DIR=/data/local/tmp/void
LIVE=$DIR/live.txt
FRAMES=/sdcard/TheVoid/userdata/frames
cd "$(dirname "$0")/.."
shell() { "$ADB" -s "$SERIAL" shell "$@"; }
BIN=void-arm64; BUILD=build/arm64; RELEASE_ARGS=""; GAME_DIR=${VOID_GAME:-/sdcard/TheVoid/game}
if [ -n "${VOID_RELEASE:-}" ]; then
    BIN=void-arm64-$VOID_RELEASE; BUILD=build/arm64-$VOID_RELEASE; GAME_DIR=${VOID_GAME:-/sdcard/TheVoid/game-polish}
    RELEASE_ARGS="--game $GAME_DIR --images /sdcard/TheVoid/lifted-$VOID_RELEASE"
elif [ -n "${VOID_GAME:-}" ]; then
    RELEASE_ARGS="--game $GAME_DIR"
fi
# The profile folder follows data/info.xml EngTitle: Void (English, German), Turgor (Russian), Tension (Polish).
title() { shell "sed -n 's/.*EngTitle=\"\([^\"]*\)\".*/\1/p' $GAME_DIR/data/info.xml" | tr -d '\r'; }
case "$1" in
push)
    # A running process keeps the executable busy (ETXTBSY): stop it first.
    shell "kill \$(pidof $BIN) 2>/dev/null; sleep 1"
    "$ADB" -s "$SERIAL" push $BUILD/void-arm64 $DIR/$BIN | tail -1
    shell "chmod 755 $DIR/$BIN"
    local_sum=$(sha256sum $BUILD/void-arm64 | cut -c1-16)
    remote_sum=$(shell "sha256sum $DIR/$BIN" | cut -c1-16)
    [ "$local_sum" = "$remote_sum" ] || { echo "push failed: device has $remote_sum, local $local_sum"; exit 1; }
    ;;
start)
    shell "kill \$(pidof void-arm64 void-arm64-tension) 2>/dev/null; rm -f $LIVE; touch $LIVE; rm -rf $FRAMES"
    script=""
    if [ -n "$2" ]; then
        "$ADB" -s "$SERIAL" push "$2" $DIR/live-script.txt >/dev/null 2>&1
        script="VOID_INPUT=$DIR/live-script.txt"
    fi
    shell "cd $DIR && chmod 755 $BIN && (env $script ${VOID_ENV:-} VOID_INPUT_LIVE=$LIVE VOID_SHADER_WAIT=60 nohup ./$BIN $RELEASE_ARGS ${VOID_ARGS:-} > live.log 2>&1 &)"
    echo started
    ;;
send)
    shift
    for command in "$@"; do shell "echo '$command' >> $LIVE"; done
    ;;
shot)
    out="${2:-build/live-shot.png}"
    before=$(shell "ls $FRAMES 2>/dev/null | wc -l")
    shell "echo shot >> $LIVE"
    for i in $(seq 1 240); do
        now=$(shell "ls $FRAMES 2>/dev/null | wc -l")
        [ "$now" != "$before" ] && break
        sleep 0.25
    done
    sleep 0.3
    newest=$(shell "ls -t $FRAMES 2>/dev/null | head -1" | tr -d '\r')
    [ -n "$newest" ] || { echo "no frame dumped (is the game presenting?)"; exit 1; }
    mkdir -p build/live
    "$ADB" -s "$SERIAL" pull "$FRAMES/$newest" build/live/last.bmp >/dev/null 2>&1
    python -c "
from PIL import Image
import sys
Image.open('build/live/last.bmp').convert('RGB').resize((960, 540)).save(sys.argv[1])
" "$out"
    echo "$out"
    ;;
log)
    shell "tail -${2:-15} '/sdcard/TheVoid/userdata/Documents/My Games/$(title)/LogFiles/game.log'"
    ;;
stop)
    shell "kill \$(pidof void-arm64 void-arm64-tension) 2>/dev/null" || true
    ;;
*)
    sed -n 2,9p "$0"
    ;;
esac
