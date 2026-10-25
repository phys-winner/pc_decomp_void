#!/bin/bash
# tools/android_type.sh 'TEXT' ['TEXT' ...]: type each line into the running game
# (live input, tools/android_live.sh) and press Enter after it: console commands
# (`<Console />` in data/config.xml, toggled with `), e.g. '/giveall' '/go 3'.
export MSYS_NO_PATHCONV=1
ADB="${ADB:-adb}"
SERIAL="${ANDROID_SERIAL:-${VOID_SERIAL:?Set ANDROID_SERIAL or VOID_SERIAL}}"
f=$(mktemp)
for text in "$@"; do
  for ((i = 0; i < ${#text}; i++)); do
    ch="${text:i:1}"
    case "$ch" in
      [a-z]) printf 'key %X\nsleep 0.05\n' "'$(echo "$ch" | tr a-z A-Z)" ;;
      [A-Z]) printf 'down 10\nkey %X\nup 10\nsleep 0.05\n' "'$ch" ;;
      [0-9]) printf 'key %X\nsleep 0.05\n' "'$ch" ;;
      /) printf 'key BF\nsleep 0.05\n' ;;
      _) printf 'down 10\nkey BD\nup 10\nsleep 0.05\n' ;;
      -) printf 'key BD\nsleep 0.05\n' ;;
      .) printf 'key BE\nsleep 0.05\n' ;;
      ' ') printf 'key 20\nsleep 0.05\n' ;;
    esac
  done
  printf 'key D\nsleep 0.5\n'
done > "$f"
"$ADB" -s "$SERIAL" shell "cat >> /data/local/tmp/void/live.txt" < "$f"
rm -f "$f"
