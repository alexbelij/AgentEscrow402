"""HTTP tests for the timelock router."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app
from server.config import Config, get_config
from server.timelock_api import reset_registry_for_testing

_ADMIN_KEY = "test-admin-key-XXXXX"


class _Clock:
    def __init__(self, t: int = 1_000_000) -> None:
        self.t = t

    def __call__(self) -> int:
        return self.t

    def advance(self, dt: int) -> None:
        self.t += dt


def _cfg(sandbox: bool = True) -> Config:
    return Config(
        admin_api_key=_ADMIN_KEY,
        sandbox=sandbox,
    )


def _mk_client(delay: int = 60, sandbox: bool = True):
    clock = _Clock()
    reset_registry_for_testing(min_delay_seconds=delay, now_fn=clock)
    app.dependency_overrides[get_config] = lambda: _cfg(sandbox=sandbox)
    client = TestClient(app)
    return client, clock


def _headers(key: str | None = _ADMIN_KEY) -> dict[str, str]:
    return {"X-Admin-Key": key} if key else {}


# ---------- auth --------------------------------------------------------


def test_missing_admin_key_forbidden():
    client, _ = _mk_client()
    r = client.post("/timelock/queue", json={"action_type": "configure_fee", "params": {"new_fee_bps": 30}})
    assert r.status_code == 403


def test_wrong_admin_key_forbidden():
    client, _ = _mk_client()
    r = client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {"new_fee_bps": 30}},
        headers={"X-Admin-Key": "wrong"},
    )
    assert r.status_code == 403


def test_no_admin_key_configured_503():
    client, _ = _mk_client()
    app.dependency_overrides[get_config] = lambda: Config(admin_api_key="", sandbox=True)
    r = client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {"new_fee_bps": 30}},
        headers=_headers(),
    )
    assert r.status_code == 503


# ---------- happy path --------------------------------------------------


def test_queue_then_execute_after_delay():
    client, clock = _mk_client(delay=60)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {"new_fee_bps": 30}},
        headers=_headers(),
    )
    assert q.status_code == 200, q.text
    aid = q.json()["action_id"]
    assert q.json()["state"] == "pending"
    assert q.json()["ready_at"] == q.json()["queued_at"] + 60

    # Too early
    r = client.post(f"/timelock/execute/{aid}", headers=_headers())
    assert r.status_code == 425

    # After delay
    clock.advance(60)
    r = client.post(f"/timelock/execute/{aid}", headers=_headers())
    assert r.status_code == 200
    assert r.json()["state"] == "executed"
    assert r.json()["result"]["sandbox"] is True


def test_cancel_pending():
    client, _ = _mk_client(delay=60)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "emergency_freeze", "params": {}},
        headers=_headers(),
    )
    aid = q.json()["action_id"]
    r = client.post(f"/timelock/cancel/{aid}", json={"reason": "abort"}, headers=_headers())
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"
    assert r.json()["cancel_reason"] == "abort"


def test_cannot_execute_cancelled():
    client, clock = _mk_client(delay=0)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "emergency_freeze", "params": {}},
        headers=_headers(),
    )
    aid = q.json()["action_id"]
    client.post(f"/timelock/cancel/{aid}", headers=_headers())
    r = client.post(f"/timelock/execute/{aid}", headers=_headers())
    assert r.status_code == 409


def test_cannot_execute_twice():
    client, clock = _mk_client(delay=0)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "unfreeze", "params": {}},
        headers=_headers(),
    )
    aid = q.json()["action_id"]
    client.post(f"/timelock/execute/{aid}", headers=_headers())
    r = client.post(f"/timelock/execute/{aid}", headers=_headers())
    assert r.status_code == 409


# ---------- validation --------------------------------------------------


def test_unknown_action_type_rejected():
    client, _ = _mk_client()
    r = client.post(
        "/timelock/queue",
        json={"action_type": "steal_funds", "params": {}},
        headers=_headers(),
    )
    assert r.status_code == 400
    assert "unknown action_type" in r.json()["detail"]


def test_missing_params_rejected():
    client, _ = _mk_client()
    r = client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {}},
        headers=_headers(),
    )
    assert r.status_code == 400
    assert "missing params" in r.json()["detail"]


def test_extra_params_rejected():
    client, _ = _mk_client()
    r = client.post(
        "/timelock/queue",
        json={"action_type": "emergency_freeze", "params": {"junk": 1}},
        headers=_headers(),
    )
    assert r.status_code == 400
    assert "unexpected params" in r.json()["detail"]


# ---------- set_delay via timelock --------------------------------------


def test_set_delay_grows_delay_after_execution():
    client, clock = _mk_client(delay=60)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "set_delay", "params": {"new_delay_seconds": 300}},
        headers=_headers(),
    )
    aid = q.json()["action_id"]
    clock.advance(60)
    r = client.post(f"/timelock/execute/{aid}", headers=_headers())
    assert r.status_code == 200

    # subsequent queues use the new delay
    q2 = client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {"new_fee_bps": 30}},
        headers=_headers(),
    )
    assert q2.json()["ready_at"] == q2.json()["queued_at"] + 300


def test_set_delay_cannot_shrink():
    client, clock = _mk_client(delay=60)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "set_delay", "params": {"new_delay_seconds": 30}},
        headers=_headers(),
    )
    aid = q.json()["action_id"]
    clock.advance(60)
    r = client.post(f"/timelock/execute/{aid}", headers=_headers())
    assert r.status_code == 409
    assert "monotonic" in r.json()["detail"]


# ---------- renounce ----------------------------------------------------


def test_renounce_cancels_pending_and_blocks_new():
    client, _ = _mk_client(delay=60)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {"new_fee_bps": 30}},
        headers=_headers(),
    )
    aid = q.json()["action_id"]
    r = client.post("/timelock/renounce", headers=_headers())
    assert r.status_code == 200
    assert r.json()["renounced"] is True

    # pending action is cancelled with reason='renounce'
    got = client.get(f"/timelock/actions/{aid}", headers=_headers()).json()
    assert got["state"] == "cancelled"
    assert got["cancel_reason"] == "renounce"

    # new queue is refused
    r2 = client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {"new_fee_bps": 40}},
        headers=_headers(),
    )
    assert r2.status_code == 410


def test_renounce_idempotent():
    client, _ = _mk_client()
    client.post("/timelock/renounce", headers=_headers())
    r = client.post("/timelock/renounce", headers=_headers())
    assert r.status_code == 200
    assert r.json()["renounced"] is True


# ---------- introspection -----------------------------------------------


def test_status_reports_state():
    client, _ = _mk_client(delay=42)
    client.post(
        "/timelock/queue",
        json={"action_type": "configure_fee", "params": {"new_fee_bps": 30}},
        headers=_headers(),
    )
    r = client.get("/timelock/status", headers=_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["min_delay_seconds"] == 42
    assert body["renounced"] is False
    assert body["pending_count"] == 1
    assert body["action_count"] == 1


def test_list_actions_returns_all():
    client, _ = _mk_client(delay=0)
    for bps in (10, 20, 30):
        client.post(
            "/timelock/queue",
            json={"action_type": "configure_fee", "params": {"new_fee_bps": bps}},
            headers=_headers(),
        )
    r = client.get("/timelock/actions", headers=_headers())
    assert r.status_code == 200
    assert len(r.json()["actions"]) == 3
    assert [a["params"]["new_fee_bps"] for a in r.json()["actions"]] == [10, 20, 30]


def test_get_unknown_action_404():
    client, _ = _mk_client()
    r = client.get("/timelock/actions/9999", headers=_headers())
    assert r.status_code == 404
    r2 = client.post("/timelock/execute/9999", headers=_headers())
    assert r2.status_code == 404


# ---------- sandbox vs live --------------------------------------------


def test_sandbox_result_shape():
    client, clock = _mk_client(delay=0, sandbox=True)
    q = client.post(
        "/timelock/queue",
        json={"action_type": "set_arbiters", "params": {"arbiters": ["a", "b"]}},
        headers=_headers(),
    )
    aid = q.json()["action_id"]
    r = client.post(f"/timelock/execute/{aid}", headers=_headers())
    assert r.status_code == 200
    assert r.json()["result"] == {
        "sandbox": True,
        "action_type": "set_arbiters",
        "params": {"arbiters": ["a", "b"]},
    }
