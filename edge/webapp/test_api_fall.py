"""
Wiring test: POST /api/fall logs the event AND fires the email notifier.
Uses Flask's test client with db.insert_event + notify.notify_fall stubbed
(no DB, no AWS). Requires Flask + PyMySQL installed (same as running the
dashboard locally). Run:  python test_api_fall.py
"""
import app as webapp
import db
import notify


def test_api_fall_logs_event_and_calls_notify():
    events = []
    calls = []
    orig_insert, orig_notify = db.insert_event, notify.notify_fall
    db.insert_event = lambda *a, **k: events.append(a)
    notify.notify_fall = lambda confidence, source, **k: calls.append((confidence, source))
    try:
        client = webapp.app.test_client()
        resp = client.post("/api/fall",
                           json={"confidence": 0.83, "source": "YOLOv8s"})
        assert resp.status_code == 200
        assert len(events) == 1                 # fall event still logged
        assert len(calls) == 1                  # notifier fired exactly once
        assert abs(calls[0][0] - 0.83) < 1e-6
        assert calls[0][1] == "YOLOv8s"
    finally:
        db.insert_event, notify.notify_fall = orig_insert, orig_notify


if __name__ == "__main__":
    test_api_fall_logs_event_and_calls_notify()
    print("PASS test_api_fall_logs_event_and_calls_notify")
    print("\n1/1 tests passed")
