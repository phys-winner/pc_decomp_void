"""Measure a full camera turn per location in an isolated, already loaded APK profile.

Requires the port's live console action and a loaded save. Does not optimize the game.
Results and raw logs are written after every location so interrupted runs are usable.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shlex
import statistics
import subprocess
import time

FPS = re.compile(r"\[gl\] frame (\d+): ([\d.]+) fps; per frame ([\d.]+) ms wall, ([\d.]+) ms cpu, [\d.]+ ms machine wait, ([\d.]+) draws")
HUD = re.compile(r"\[hud\] frame (\d+) shows ([0-9A-Fa-f]+)")
LIVE_MOVE = re.compile(r"\[live\] move (-?\d+) (-?\d+) (-?\d+)")
CAMERA = re.compile(r"\[camera\] frame (\d+) at ([\d.]+) ms:")
PIXELS_PER_DEGREE = 9.05 * 0.192621
LOCATIONS = [1, 2, 3, 4, *range(9, 15), *range(16, 41)]
HUD_LOADING = 0x20000
HUD_BLOCKED = 0x400 | 0x1000 | 0x2000 | 0x4000 | 0x8000 | HUD_LOADING | 0x80000 | 0x100000 | 0x200000 | 0x800000 | 0x1000000
HUD_CONTROL_LOCKED = 0x2000000


def turn_events(seconds, sensitivity):
    if not math.isfinite(seconds) or seconds <= 0 or not math.isfinite(sensitivity) or sensitivity <= 0:
        raise ValueError("positive finite duration and sensitivity required")
    total = math.ceil(360 * PIXELS_PER_DEGREE / sensitivity)
    count = max(1, round(seconds / 0.05))
    sent = 0
    lines = []
    for i in range(1, count + 1):
        goal = round(total * i / count)
        lines += [f"move {goal - sent} 0", "sleep 0.05"]
        if i % 20 == 0:
            lines.append("hud")
        sent = goal
    return lines


def samples(log):
    return [dict(frame=int(m[1]), fps=float(m[2]), wall_ms=float(m[3]), cpu_ms=float(m[4]), draws=float(m[5]))
            for m in FPS.finditer(log)]


def marker_status(log, token):
    marker = re.search(r"\[live\] move 0 0 " + str(token) + r"(?:\r?\n|$)", log)
    if not marker:
        return None
    status = list(HUD.finditer(log[:marker.start()]))
    if not status:
        raise RuntimeError("live marker has no preceding HUD snapshot")
    return dict(frame=int(status[-1][1]), tags=int(status[-1][2], 16), offset=marker.end())


def measured_windows(log, first_frame, last_frame):
    measured = []
    previous = None
    previous_end = 0
    for match in FPS.finditer(log):
        sample = samples(match.group())[0]
        preparing = re.search(r"\[d3dx\].*(?:cache miss|live compile service)", log[previous_end:match.start()])
        if previous is not None and first_frame <= previous < sample["frame"] <= last_frame and not preparing:
            measured.append(dict(sample, first_frame=previous))
        previous = sample["frame"]
        previous_end = match.end()
    return measured


def accepted_location(log, location):
    return re.search(r"\[location\] accepted " + str(location) + r"(?:\s|$)", log) is not None


def full_turn_rate(log):
    clocks = list(CAMERA.finditer(log))
    if len(clocks) != 2:
        raise RuntimeError("camera turn needs two presentation clock boundaries")
    frames = int(clocks[1][1]) - int(clocks[0][1])
    elapsed = (float(clocks[1][2]) - float(clocks[0][2])) / 1000
    if frames <= 0 or elapsed <= 0:
        raise RuntimeError("invalid camera turn presentation clock interval")
    return dict(full_turn_fps=round(frames / elapsed, 2), full_turn_seconds=round(elapsed, 3),
                full_turn_frames=frames)


def self_test():
    for speed in (0.1, 1, 20):
        events = turn_events(20, speed)
        actual = sum(int(e.split()[1]) for e in events if e.startswith("move"))
        assert actual == math.ceil(360 * PIXELS_PER_DEGREE / speed)
        assert actual * speed / PIXELS_PER_DEGREE >= 360
        assert events.count("sleep 0.05") == 400 and events.count("hud") == 20
    line = "[gl] frame {}: 59.2 fps; per frame 16.9 ms wall, 8.2 ms cpu, 0.0 ms machine wait, 80 draws\n"
    assert samples(line.format(600))[0]["fps"] == 59.2
    assert not samples("loading...")
    windows = measured_windows("".join(line.format(frame) for frame in (100, 200, 300, 400)), 150, 350)
    assert [sample["frame"] for sample in windows] == [300]
    assert not marker_status("[live] move 0 0 1234\n", 123)
    preparing = line.format(100) + "[d3dx] main/vs_3_0: cache miss abc recorded\n" + line.format(200) + line.format(300)
    assert [sample["frame"] for sample in measured_windows(preparing, 100, 300)] == [300]
    marked = "[hud] frame 12 shows 2000000\n[live] move 0 0 123\n"
    assert marker_status(marked, 123) == dict(frame=12, tags=HUD_CONTROL_LOCKED, offset=len(marked))
    assert accepted_location("[location] accepted 12\n", 12)
    assert not accepted_location("[location] accepted 123\n", 12)
    assert full_turn_rate("[camera] frame 100 at 1000.00 ms:\n[camera] frame 700 at 21000.00 ms:\n")["full_turn_fps"] == 30
    for duration, sensitivity in ((0, 1), (20, 0), (float("nan"), 1), (20, float("inf"))):
        try:
            turn_events(duration, sensitivity)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid camera calibration accepted")
    print("benchmark self-check PASS: calibrated delta, live completion, HUD, acceptance, complete FPS windows")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serial", required=True)
    p.add_argument("--profile", default="userdata-touchbench")
    p.add_argument("--out", type=Path, default=Path("build/touch-rework/fps"))
    p.add_argument("--locations", type=int, nargs="+", default=LOCATIONS)
    p.add_argument("--seconds", type=float, default=20)
    p.add_argument("--load-timeout", type=float, default=120, help="Seconds allowed for scene loading and shader preparation")
    p.add_argument("--profile-cpu", action="store_true", help="Record a separate 10s simpleperf sample after each FPS turn")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return
    if (not re.fullmatch(r"userdata-[A-Za-z0-9_]+", a.profile) or a.seconds < 10 or not math.isfinite(a.seconds)
            or not math.isfinite(a.load_timeout) or a.load_timeout < 15):
        p.error("use an isolated userdata-NAME profile and at least 10 seconds per turn")
    a.out.mkdir(parents=True, exist_ok=True)
    remote = "/sdcard/TheVoid/" + a.profile
    adb = ["adb", "-s", a.serial]

    def shell(command):
        return subprocess.check_output([*adb, "shell", command], timeout=30).decode("utf-8", "replace")

    def live(lines):
        subprocess.run([*adb, "shell", "cat >> " + remote + "/live.txt"], input=("\n".join(lines) + "\n").encode(), check=True, timeout=15)

    def log():
        return shell("cat " + remote + "/void.log")

    token_count = 0

    def live_status(lines=(), timeout=30):
        nonlocal token_count
        token_count += 1
        token = 2000000000 + token_count
        before = len(log())
        live([*lines, "hud", f"move 0 0 {token}"])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tail = shell("tail -1200 " + remote + "/void.log")
            if re.search(r"\[live\] move 0 0 " + str(token) + r"(?:\r?\n|$)", tail):
                text = log()
                status = marker_status(text[before:], token)
                if status:
                    return text, status
            time.sleep(.5)
        raise RuntimeError("live input queue did not finish before timeout")

    def screenshot(path):
        path.write_bytes(subprocess.check_output([*adb, "exec-out", "screencap", "-p"], timeout=30))

    settings = shell("cat " + remote + "/overrides/settings.xml")
    sens = re.search(r'name="MouseSensitivity"\s+value="([^"]+)"', settings)
    sensitivity = float(sens[1]) if sens else 1
    if not math.isfinite(sensitivity) or sensitivity <= 0:
        raise ValueError("invalid MouseSensitivity")
    metadata = dict(serial=a.serial, profile=a.profile, seconds=a.seconds, settings_xml=settings,
                    calibration_pixels_per_degree=PIXELS_PER_DEGREE, sensitivity=sensitivity,
                    requested_turn_degrees=360, actual_yaw_observed=False,
                    validation="requested location accepted, input queue drained, controllable HUD, complete FPS windows",
                    device=shell("getprop ro.product.model; wm size; dumpsys battery | head -16"))
    (a.out / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    results = []
    for n in a.locations:
        before = len(log())
        live([f"console /go {n}"])
        deadline = time.monotonic() + a.load_timeout
        ready_frame = None
        row = dict(location=n)
        try:
            while time.monotonic() < deadline:
                time.sleep(3)
                text, state = live_status()
                delta = text[before:]
                if not accepted_location(delta, n) or state["tags"] & (HUD_BLOCKED | HUD_CONTROL_LOCKED):
                    ready_frame = None
                else:
                    if ready_frame is None:
                        ready_frame = state["frame"]
                    if len(measured_windows(text, ready_frame, state["frame"])) >= 2:
                        break
                if not shell("pidof org.thevoid.port || true").strip():
                    raise RuntimeError(f"game exited loading location {n}")
            else:
                raise RuntimeError(f"location {n}: no verified controllable scene within {a.load_timeout:g} seconds; last HUD {state['tags']:X}")
            screenshot(a.out / f"location-{n}-start.png")
            events = turn_events(a.seconds, sensitivity)
            expected = math.ceil(360 * PIXELS_PER_DEGREE / sensitivity)
            for turn_attempt in range(1, 4):
                text, start = live_status()
                before_turn = len(text)
                # A complete extra turn warms shaders first encountered while looking around.
                # Existing presentation clocks cover the whole turn, avoiding the phase
                # bias of retaining only complete five-second statistics windows.
                text, end = live_status(["camera 1", "sleep 0.1", *events, "camera 1", "sleep 1"],
                                       timeout=a.seconds + a.load_timeout)
                turn_log = text[before_turn:]
                moves = list(LIVE_MOVE.finditer(turn_log))
                actual = sum(int(move[1]) for move in moves)
                if actual != expected or len(moves) - 1 != sum(event.startswith("move ") for event in events):
                    raise RuntimeError(f"location {n}: incomplete camera input ({actual}/{expected} pixels)")
                if any(int(status[2], 16) & (HUD_BLOCKED | HUD_CONTROL_LOCKED) for status in HUD.finditer(turn_log)):
                    raise RuntimeError(f"location {n}: loading, menu or locked camera during turn")
                # Obtain the next boundary; shader preparation windows and both partial edges are excluded.
                deadline = time.monotonic() + a.load_timeout
                while not samples(text) or samples(text)[-1]["frame"] <= end["frame"]:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"location {n}: no statistics after completed input")
                    time.sleep(.5)
                    text = log()
                measured = measured_windows(text, start["frame"], end["frame"])
                if len(measured) >= 2 and not re.search(r"\[d3dx\].*(?:cache miss|live compile service)", turn_log):
                    break
                print(f"location {n}: warming shaders; repeat turn {turn_attempt}/3", flush=True)
            else:
                raise RuntimeError(f"not enough complete shader-ready frame-statistics windows for location {n}")
            screenshot(a.out / f"location-{n}.png")
            row.update(status="measured", median_fps=round(statistics.median(s["fps"] for s in measured), 1),
                       min_window_fps=min(s["fps"] for s in measured), samples=measured,
                       turn_pixels=actual, start_frame=start["frame"], end_frame=end["frame"],
                       calibrated_turn_degrees=actual * sensitivity / PIXELS_PER_DEGREE,
                       requested_scene_verified=True, actual_yaw_observed=False,
                       turn_attempts=turn_attempt,
                       **full_turn_rate(turn_log),
                       temperature=shell("dumpsys battery | grep temperature").strip())
            print(f"location {n}: median {row['median_fps']}, min window {row['min_window_fps']} fps", flush=True)
        except RuntimeError as error:
            row.update(status="unmeasured", error=str(error))
            screenshot(a.out / f"location-{n}-unmeasured.png")
            print(str(error), flush=True)
        (a.out / f"location-{n}.log").write_text(log()[before:], encoding="utf-8")
        if row.get("status") == "measured" and a.profile_cpu:
            # Sampling is outside the FPS window so its overhead cannot alter the comparison.
            perf = f"/data/local/tmp/void-{a.profile}-{n}.data"
            recorded = subprocess.run([*adb, "shell", "simpleperf record --app org.thevoid.port --duration 10 "
                                       f"-f 1000 --call-graph fp -o {perf}"], capture_output=True, timeout=40)
            (a.out / f"location-{n}-record.txt").write_bytes(recorded.stdout + recorded.stderr)
            row["cpu_profile_ok"] = recorded.returncode == 0
            if recorded.returncode == 0:
                for order in ("tid,symbol", "symbol"):
                    report = shell(f"simpleperf report -i {perf} --sort {order} --percent-limit 0.1")
                    (a.out / f"location-{n}-cpu-{order.replace(',', '-')}.txt").write_text(report, encoding="utf-8")
                subprocess.run([*adb, "pull", perf, str(a.out / f"location-{n}.perf.data")],
                               check=True, capture_output=True, timeout=30)
        game_log = shell("tail -120 " + shlex.quote(remote + "/Documents/My Games/Turgor/LogFiles/game.log"))
        (a.out / f"location-{n}-game.log").write_text(game_log, encoding="utf-8")
        results.append(row)
        (a.out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
