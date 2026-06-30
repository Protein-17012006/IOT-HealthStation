"""
Unit tests for the fall-detection decision logic -- no camera or GPU needed.

These prove the "brain" (decide_fall + the Reporter debounce) behaves before we
ever point a camera at it. Run inside the WSL venv:

    cd edge
    /root/iot-ai/.venv/bin/python test_fall_detector.py
"""
import types

import fall_detector_yolo as fd


def _kpts(sh_xy, hip_xy):
    """A 17x2 keypoint list with shoulders/hips set and the rest left at zero."""
    kp = [[0.0, 0.0] for _ in range(17)]
    kp[fd.L_SH] = [sh_xy[0] - 10, sh_xy[1]]
    kp[fd.R_SH] = [sh_xy[0] + 10, sh_xy[1]]
    kp[fd.L_HIP] = [hip_xy[0] - 10, hip_xy[1]]
    kp[fd.R_HIP] = [hip_xy[0] + 10, hip_xy[1]]
    return kp


def test_standing_upright_is_not_a_fall():
    box = (100, 50, 200, 350)                      # tall: w=100 h=300
    kp = _kpts(sh_xy=(150, 120), hip_xy=(150, 240))  # vertical torso
    fall, _ = fd.decide_fall(box, kp, [1.0] * 17)
    assert fall is False


def test_lying_wide_box_is_a_fall():
    box = (50, 100, 350, 200)                      # wide: w=300 h=100
    fall, conf = fd.decide_fall(box)               # box alone is decisive
    assert fall is True
    assert conf > 0.5


def test_bending_over_while_standing_is_not_a_fall():
    box = (100, 50, 220, 350)                      # still tall (aspect ~0.34)
    kp = _kpts(sh_xy=(120, 150), hip_xy=(260, 150))  # torso horizontal
    fall, _ = fd.decide_fall(box, kp, [1.0] * 17)
    assert fall is False                           # tall box overrides -> safe


def test_horizontal_torso_with_nonupright_box_is_a_fall():
    box = (50, 100, 250, 290)                      # w=200 h=190 (aspect ~1.05)
    kp = _kpts(sh_xy=(80, 195), hip_xy=(220, 195))   # torso horizontal
    fall, _ = fd.decide_fall(box, kp, [1.0] * 17)
    assert fall is True


def test_low_keypoint_confidence_falls_back_to_box():
    box = (100, 50, 200, 350)                      # tall, not wide
    kp = _kpts(sh_xy=(120, 150), hip_xy=(260, 150))  # horizontal but...
    fall, _ = fd.decide_fall(box, kp, [0.1] * 17)  # ...untrusted -> ignored
    assert fall is False


def test_reporter_requires_persistence_then_fires_once():
    clock = {"t": 1000.0}
    fd.time = types.SimpleNamespace(time=lambda: clock["t"])
    posts = []
    fd.requests = types.SimpleNamespace(
        post=lambda url, json=None, timeout=None: posts.append((url, json)))

    rep = fd.Reporter()
    rep.update(True, 0.9)                           # t=1000.0 candidate begins
    clock["t"] = 1000.5
    rep.update(True, 0.9)                           # 0.5s -> not yet
    assert posts == []
    clock["t"] = 1001.3
    rep.update(True, 0.9)                           # 1.3s >= 1.2 -> fires
    assert len(posts) == 1
    clock["t"] = 1001.8
    rep.update(True, 0.9)                           # already firing -> no dup
    assert len(posts) == 1


def test_reporter_ignores_brief_fall():
    clock = {"t": 2000.0}
    fd.time = types.SimpleNamespace(time=lambda: clock["t"])
    posts = []
    fd.requests = types.SimpleNamespace(
        post=lambda url, json=None, timeout=None: posts.append((url, json)))

    rep = fd.Reporter()
    rep.update(True, 0.9)                           # candidate
    clock["t"] = 2000.5
    rep.update(False, 0.0)                          # gone after 0.5s -> reset
    assert posts == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print("PASS", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} tests passed")
