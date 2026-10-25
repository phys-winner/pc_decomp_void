"""Verify drawing validation and input release order without sending real input."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import windows_route as route


def main():
    events, moves = [], []
    def send(event):
        events.append((event.kind, event.value.keyboard.scan if event.kind else 0,
                       event.value.keyboard.flags if event.kind else event.value.mouse.flags))
    def cursor(x, y):
        moves.append((x, y)); return 1
    frame = (42, 10, 20, 800, 600)
    with patch.object(route, 'target', return_value=frame), patch.object(route, 'send', side_effect=send), \
         patch.object(route.user, 'SetCursorPos', side_effect=cursor), patch.object(route.time, 'sleep'):
        route.draw(7, [[100, 100], [200, 200]], 0.01)
        assert events == [(1, 0x1d, 8), (0, 0, 2), (0, 0, 4), (1, 0x1d, 10)]
        assert moves == [(110, 120), (110, 120), (210, 220)]
        for points in ([], [[0, 0]], [[0, 0], [800, 0]], [[0, 0], [0, 600]],
                       [[0, 0], [-1, 0]], [[0, 0], [True, 5]], [[0, 0], [1.0, 5]]):
            events.clear()
            try: route.draw(7, points, 0.01)
            except ValueError: pass
            else: raise AssertionError(points)
            assert not events
        events.clear()
        with patch.object(route, 'target', side_effect=[frame, frame, RuntimeError('focus lost')]):
            try: route.draw(7, [[0, 0], [1, 1]], 0.01)
            except RuntimeError: pass
            else: raise AssertionError('focus loss must abort')
        assert events[-2:] == [(0, 0, 4), (1, 0x1d, 10)]
        events.clear()
        def fail_up(event):
            send(event)
            if not event.kind and event.value.mouse.flags == 4: raise OSError('release failed')
        with patch.object(route, 'send', side_effect=fail_up):
            try: route.draw(7, [[0, 0], [1, 1]], 0.01)
            except OSError: pass
            else: raise AssertionError('release failure must propagate')
        assert events[-1] == (1, 0x1d, 10)
    assert route.KEY_SCANS['F5']==0x3f and route.KEY_SCANS['F8']==0x42
    print('Owned drawing input validation / release ordering PASS; no real input sent')


if __name__ == '__main__': main()
