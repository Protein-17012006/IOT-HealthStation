"""
Unit tests for the fall-alert email logic (edge/webapp/notify.py).

No AWS, no network, no boto3: the SNS client is a fake that records calls and
the cooldown clock is passed in explicitly. Run:  python test_notify.py
"""
import notify


class _FakeSns:
    def __init__(self):
        self.calls = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "fake"}


def _reset(topic="arn:aws:sns:ap-southeast-1:0:health-station-fall", cooldown=300):
    notify.TOPIC_ARN = topic
    notify.COOLDOWN = cooldown
    notify.PUBLIC_URL = "http://alb.example"
    notify._last_email_ts = 0.0


def test_should_send_true_after_cooldown():
    assert notify.should_send(now=1000.0, last_ts=0.0, cooldown=300) is True


def test_should_send_false_within_cooldown():
    assert notify.should_send(now=100.0, last_ts=0.0, cooldown=300) is False


def test_build_message_has_confidence_source_and_link():
    subject, body = notify.build_message(0.87, "YOLOv8s", now=0.0,
                                         dashboard_url="http://alb.example")
    assert subject == "FALL DETECTED - Patient Monitoring Station"
    assert subject.isascii()
    assert "0.87" in body
    assert "YOLOv8s" in body
    assert "http://alb.example" in body


def test_notify_fall_disabled_when_no_topic():
    _reset(topic="")
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is False
    assert fake.calls == []


def test_notify_fall_publishes_first_time():
    _reset()
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is True
    assert len(fake.calls) == 1
    assert fake.calls[0]["TopicArn"] == notify.TOPIC_ARN
    assert "FALL DETECTED" in fake.calls[0]["Subject"]


def test_notify_fall_suppressed_within_cooldown():
    _reset()
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is True
    assert notify.notify_fall(0.9, "YOLO", now=1060.0, client=fake) is False
    assert len(fake.calls) == 1


def test_notify_fall_sends_again_after_cooldown():
    _reset()
    fake = _FakeSns()
    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=fake) is True
    assert notify.notify_fall(0.9, "YOLO", now=1400.0, client=fake) is True
    assert len(fake.calls) == 2


def test_notify_fall_swallows_publish_error():
    _reset()

    class _Boom:
        def publish(self, **kw):
            raise RuntimeError("sns down")

    assert notify.notify_fall(0.9, "YOLO", now=1000.0, client=_Boom()) is False
    # a failed publish must NOT consume the cooldown slot
    assert notify._last_email_ts == 0.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print("PASS", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} tests passed")
