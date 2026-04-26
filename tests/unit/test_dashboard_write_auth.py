"""
Dashboard write endpoints must require either a configured
``SONIQ_DASHBOARD_API_KEY`` or a localhost connection. The 0.0.2 contract:
- API key set -> the global API-key middleware already validated it, so
  the write goes through.
- No API key, loopback caller -> allowed (developer's laptop).
- No API key, remote caller -> 403 with an instructional message.
"""

import pytest
from fastapi import HTTPException

pytest.importorskip("fastapi")


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, *, client_host, host_header):
        self.client = _FakeClient(client_host) if client_host else None
        self.headers = {"host": host_header}


def _set_api_key(monkeypatch, api_key=None):
    if api_key is None:
        monkeypatch.delenv("SONIQ_DASHBOARD_API_KEY", raising=False)
    else:
        monkeypatch.setenv("SONIQ_DASHBOARD_API_KEY", api_key)


def test_localhost_writes_allowed_without_api_key(monkeypatch):
    from soniq.dashboard.fastapi_app import _require_write_authorization

    _set_api_key(monkeypatch, api_key=None)
    req = _FakeRequest(client_host="127.0.0.1", host_header="localhost:6161")

    _require_write_authorization(req)  # no exception


def test_remote_write_without_api_key_is_403(monkeypatch):
    from soniq.dashboard.fastapi_app import _require_write_authorization

    _set_api_key(monkeypatch, api_key=None)
    req = _FakeRequest(client_host="10.0.0.5", host_header="dashboard.example.com")

    with pytest.raises(HTTPException) as exc:
        _require_write_authorization(req)
    assert exc.value.status_code == 403
    assert "SONIQ_DASHBOARD_API_KEY" in exc.value.detail


def test_remote_write_with_api_key_set_passes_through(monkeypatch):
    """When an API key is configured, the global middleware already
    validated it. The write guard treats the call as authorized."""
    from soniq.dashboard.fastapi_app import _require_write_authorization

    _set_api_key(monkeypatch, api_key="secret")
    req = _FakeRequest(client_host="10.0.0.5", host_header="dashboard.example.com")

    _require_write_authorization(req)


def test_loopback_with_proxied_host_header_still_local(monkeypatch):
    from soniq.dashboard.fastapi_app import _is_localhost_request

    req = _FakeRequest(client_host="127.0.0.1", host_header="127.0.0.1")
    assert _is_localhost_request(req) is True


def test_loopback_client_with_external_host_header_is_not_local(monkeypatch):
    """A reverse proxy may sit on the same host (loopback peer) but pass
    through a public Host header. Treat that as non-local so writes still
    require an API key."""
    from soniq.dashboard.fastapi_app import _is_localhost_request

    req = _FakeRequest(client_host="127.0.0.1", host_header="public.example.com")
    assert _is_localhost_request(req) is False
