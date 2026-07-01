"""
Unit tests for the fall-detection decision logic -- no camera or GPU needed.

These prove the "brain" (decide_fall + the Reporter debounce) behaves before we
ever point a camera at it. Run inside the WSL venv:

    cd edge
    /root/iot-ai/.venv/bin/python test_fall_detector.py
"""
import types

import numpy as np

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


def test_seated_upright_with_wide_box_is_not_a_fall():
    """The reported false positive: someone sitting still close to the camera
    makes a WIDE box (head+torso fill the frame), but the pose is clearly
    upright -- shoulders above hips, vertical torso. A confident upright pose
    must veto the wide box instead of firing a fall."""
    box = (40, 90, 360, 290)                       # wide: w=320 h=200 (aspect 1.6)
    kp = _kpts(sh_xy=(200, 150), hip_xy=(200, 250))  # upright: hips below shoulders
    fall, _ = fd.decide_fall(box, kp, [1.0] * 17)
    assert fall is False


def test_lying_with_level_shoulders_and_hips_is_a_fall():
    """When shoulders and hips sit at the same height (person flat on the floor)
    it is a fall even if the torso vector is short/ambiguous."""
    box = (50, 120, 300, 250)                      # w=250 h=130 (aspect ~1.9)
    kp = _kpts(sh_xy=(120, 185), hip_xy=(210, 185))  # shoulders/hips level
    fall, _ = fd.decide_fall(box, kp, [1.0] * 17)
    assert fall is True


def test_missing_shoulder_keypoints_do_not_veto_a_wide_box_fall():
    """YOLO reports undetected keypoints at the origin (0,0). Even at full
    confidence those are not real measurements, so they must NOT be trusted --
    otherwise a missing shoulder fabricates an 'upright' torso and vetoes a real
    fall. With the trunk landmarks untrustworthy we fall back to the box."""
    box = (50, 100, 350, 250)                      # wide: w=300 h=150 (aspect 2.0)
    kp = _kpts(sh_xy=(150, 175), hip_xy=(150, 220))
    kp[fd.L_SH] = [0.0, 0.0]                        # shoulders not detected ...
    kp[fd.R_SH] = [0.0, 0.0]                        # ... left at the origin
    fall, _ = fd.decide_fall(box, kp, [1.0] * 17)
    assert fall is True                            # box fallback -> wide -> fall


def test_rotate_frame_90_swaps_dimensions():
    frame = np.zeros((2, 3, 3), dtype=np.uint8)    # H=2, W=3
    out = fd.rotate_frame(frame, 90)
    assert out.shape[:2] == (3, 2)                  # rotated -> H=3, W=2


def test_rotate_frame_zero_is_identity():
    frame = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    out = fd.rotate_frame(frame, 0)
    assert out.shape == frame.shape
    assert np.array_equal(out, frame)


def test_reporter_requires_persistence_then_fires_once():
    clock = {"t": 1000.0}
    fd.time = types.SimpleNamespace(time=lambda: clock["t"])
    posts = []
    fd.requests = types.SimpleNamespace(
        post=lambda url, json=None, timeout=None, headers=None:
            posts.append((url, json)))

    rep = fd.Reporter()
    rep.update(True, 0.9)                              # candidate begins
    clock["t"] = 1000.0 + fd.FALL_SECONDS * 0.5
    rep.update(True, 0.9)                              # half the window -> not yet
    assert posts == []
    clock["t"] = 1000.0 + fd.FALL_SECONDS + 0.1
    rep.update(True, 0.9)                              # past the window -> fires
    assert len(posts) == 1
    clock["t"] = 1000.0 + fd.FALL_SECONDS + 0.6
    rep.update(True, 0.9)                              # already firing -> no dup
    assert len(posts) == 1


def test_reporter_ignores_brief_fall():
    clock = {"t": 2000.0}
    fd.time = types.SimpleNamespace(time=lambda: clock["t"])
    posts = []
    fd.requests = types.SimpleNamespace(
        post=lambda url, json=None, timeout=None, headers=None:
            posts.append((url, json)))

    rep = fd.Reporter()
    rep.update(True, 0.9)                              # candidate
    clock["t"] = 2000.0 + fd.FALL_SECONDS * 0.3
    rep.update(False, 0.0)                             # gone before the window -> reset
    assert posts == []


def test_motiontracker_flags_a_rapid_drop():
    """Standing, then the vertical centre jumps down fast and the box shrinks:
    the tracker should arm 'dropped' and report a low height ratio."""
    tr = fd.MotionTracker()
    tr.update(cy=0.50, h=0.60, t=0.0)              # standing tall
    m = tr.update(cy=0.85, h=0.20, t=0.5)          # collapsed in 0.5s
    assert m["dropped"] is True
    assert m["height_ratio"] < fd.HEIGHT_DROP_RATIO


def test_motiontracker_ignores_slow_sitting():
    """A gradual descent (sitting down) never reaches the drop velocity."""
    tr = fd.MotionTracker()
    m = None
    for k in range(5):                              # 2s, cy 0.50 -> 0.58 slowly
        m = tr.update(cy=0.50 + 0.02 * k, h=0.60 - 0.01 * k, t=0.5 * k)
    assert m["dropped"] is False


def test_combine_fall_keeps_posture_fall():
    """A genuine lying posture (wide box) is kept as a fall."""
    still = {"dropped": False, "height_ratio": 0.4, "confidence": 0.0}
    fall, conf = fd.combine_fall(True, 0.9, aspect=1.5, motion=still)
    assert fall is True and conf == 0.9


def test_combine_fall_vetoes_leaning():
    """The reported false positive: a person LEANING/reclining has a tilted torso
    (posture_fall True) but is still standing-tall (height_ratio high) and the box
    is not wide -> it must NOT be reported as a fall."""
    lean = {"dropped": False, "height_ratio": 0.9, "confidence": 0.0}
    fall, _ = fd.combine_fall(True, 0.9, aspect=0.7, motion=lean)
    assert fall is False


def test_combine_fall_drop_into_collapse_fires_without_wide_box():
    """The case single-frame geometry misses: posture says NOT a fall (tallish
    box, aspect 0.5), but a fast drop ended in a collapsed (low) posture."""
    motion = {"dropped": True, "height_ratio": 0.3, "confidence": 0.8}
    fall, conf = fd.combine_fall(False, 0.2, aspect=0.5, motion=motion)
    assert fall is True
    assert conf > 0.5


def test_combine_fall_drop_without_collapse_does_not_fire():
    """A fast motion that does NOT end low/wide (e.g. still upright) is ignored."""
    motion = {"dropped": True, "height_ratio": 0.9, "confidence": 0.8}
    fall, _ = fd.combine_fall(False, 0.2, aspect=0.4, motion=motion)
    assert fall is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print("PASS", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} tests passed")
