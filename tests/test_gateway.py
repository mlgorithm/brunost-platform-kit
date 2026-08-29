from brunost_platform.gateway import HttpJudgeGateway


def test_worker_controls_escape_ids_and_use_judge_contract(monkeypatch):
    gateway = HttpJudgeGateway(base_url="https://judge.example.test")
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"worker_id": "country/node-1"}

    monkeypatch.setattr(gateway, "_request", fake_request)
    assert gateway.drain_worker("country/node-1", draining=False)["worker_id"] == "country/node-1"
    assert gateway.revoke_worker_credential("country/node-1")["worker_id"] == "country/node-1"
    assert calls == [
        ("POST", "/v1/workers/country%2Fnode-1/drain?draining=false", None),
        ("POST", "/v1/workers/country%2Fnode-1/credential/revoke", None),
    ]
