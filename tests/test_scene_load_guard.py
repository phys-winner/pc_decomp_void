"""Execute the real load_map loop; a ready map requires a fresh guard reply."""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import scene_audit


class Clock:
    def __init__(self):
        self.now = 0

    def tick(self):
        self.now += .25
        return self.now


class Device:
    def __init__(self, ready=True, fresh=True, ack=1):
        self.ready, self.fresh, self.ack = ready, fresh, ack
        self.guard_requests = 0
        self.log = "[scene-audit] World.Vars.god_mode=1 old reply\n"

    def status(self, events=()):
        if "console /load 5.sav" in events:
            return dict(frame=10, tags=0x400)
        if "console /audit_guard" in events:
            self.guard_requests += 1
            if self.ack and self.guard_requests >= self.ack:
                self.log += "[scene-audit] World.Vars.god_mode=1 fresh reply\n"
        return dict(frame=13 if self.fresh else 10, tags=0x400 if self.ready else 0)

    def game_log(self):
        return self.log


def run(device, failure=None):
    clock = Clock()
    with patch.object(scene_audit.time, "monotonic", clock.tick), patch.object(scene_audit.time, "sleep"):
        try:
            scene_audit.load_map(device, "5.sav", 3)
        except RuntimeError as error:
            assert failure and failure in str(error), str(error)
        else:
            assert failure is None, "a missing fresh guard reply was accepted"


def main():
    good = Device()
    run(good)
    assert good.guard_requests == 1
    retry = Device(ack=2)
    run(retry)
    assert retry.guard_requests == 2
    missing_guard = Device(ack=None)
    run(missing_guard, "/audit_guard was not acknowledged")
    assert missing_guard.guard_requests > 1
    not_ready = Device(ready=False)
    run(not_ready, "did not reach the map")
    assert not_ready.guard_requests == 0
    stale_frame = Device(fresh=False)
    run(stale_frame, "did not reach the map")
    assert stale_frame.guard_requests == 0
    print("PASS actual load_map: fresh/retried guard accepted; stale reply, no reply, missing map and stale frames rejected")


if __name__ == "__main__":
    main()
