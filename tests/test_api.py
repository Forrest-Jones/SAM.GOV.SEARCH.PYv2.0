"""The SAM.gov client: missing keys, rejected keys, and backoff."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import find_opportunities as fo  # noqa: E402


class _Resp:
    def __init__(self, status, headers=None, payload=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code} for url with api_key=secret")


def test_a_missing_key_is_a_clear_error_and_does_not_call_sam(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not call the network")
    monkeypatch.setattr(fo.requests, "get", boom)
    try:
        fo.request_with_retry({}, 2)
        raised = False
    except fo.SamApiError as e:
        raised = True
        assert "SAM_API_KEY" in str(e)
        assert "secret" not in str(e).lower() or "api_key" not in str(e)
    assert raised


def test_a_rejected_key_names_the_problem(monkeypatch):
    monkeypatch.setattr(fo.requests, "get", lambda *a, **k: _Resp(401, text="nope api_key=secret"))
    monkeypatch.setattr(fo.time, "sleep", lambda *_: None)
    try:
        fo.request_with_retry({"api_key": "secret"}, 3)
        raised = False
    except fo.SamApiError as e:
        raised = True
        message = str(e)
        assert "401" in message
        assert "SAM_API_KEY" in message
        assert "secret" not in message
    assert raised


def test_rate_limits_honor_retry_after_then_succeed(monkeypatch):
    calls = {"n": 0}
    slept = []

    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(429, headers={"Retry-After": "7"})
        return _Resp(200, payload={"opportunitiesData": []})

    monkeypatch.setattr(fo.requests, "get", fake_get)
    monkeypatch.setattr(fo.time, "sleep", lambda seconds: slept.append(seconds))
    resp = fo.request_with_retry({"api_key": "k"}, 3)
    assert resp.status_code == 200
    assert slept == [7]
    assert calls["n"] == 2


def test_an_http_date_retry_after_does_not_crash(monkeypatch):
    # A past date means "wait nothing", not ValueError from int("Wed, ...").
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(503, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        return _Resp(200, payload={})

    monkeypatch.setattr(fo.requests, "get", fake_get)
    monkeypatch.setattr(fo.time, "sleep", lambda *_: None)
    resp = fo.request_with_retry({"api_key": "k"}, 3)
    assert resp.status_code == 200


def test_garbage_retry_after_falls_back_to_backoff(monkeypatch):
    assert fo.retry_after_seconds("not-a-date", attempt=2) == 4
    assert fo.retry_after_seconds("15", attempt=1) == 15
    assert fo.retry_after_seconds("9999", attempt=1) == fo.MAX_BACKOFF_SECONDS


def test_a_failed_page_does_not_pretend_the_list_is_complete(monkeypatch, capsys):
    def fake_get(*a, **k):
        raise fo.requests.exceptions.ConnectionError("api_key=secret down")

    monkeypatch.setattr(fo.requests, "get", fake_get)
    monkeypatch.setattr(fo.time, "sleep", lambda *_: None)
    results = fo.fetch("541219", "01/01/2026", "02/01/2026", "k", 10, 1)
    assert results == []
    err = capsys.readouterr().err
    assert "incomplete" in err
    assert "secret" not in err


def test_the_search_asks_for_standalone_solicitations(monkeypatch):
    seen = {}

    def fake(params, max_retries, url=None):
        seen["ptype"] = params["ptype"]
        return _Resp(200, payload={"opportunitiesData": [], "totalRecords": 0})

    monkeypatch.setattr(fo, "request_with_retry", fake)
    fo.fetch("541219", "01/01/2026", "02/01/2026", "k", 10, 1)
    codes = set(seen["ptype"].split(","))
    assert {"o", "k", "p", "r"} <= codes
