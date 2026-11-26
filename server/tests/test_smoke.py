"""Smoke tests: the app builds, every route is registered, and the access gate holds."""
from app.core import access


def test_app_builds_with_all_blueprints(app):
    prefixes = {r.rule.split('/')[2] for r in app.url_map.iter_rules() if r.rule.startswith('/api/')}
    for p in ('hosts', 'vms', 'backups', 'cloudflare', 'access', 'metrics', 'compute', 'server'):
        assert p in prefixes


def test_untrusted_ip_is_refused(client):
    r = client.get('/api/server', environ_base={'REMOTE_ADDR': '8.8.8.8'})
    assert r.status_code == 403


def test_unknown_tailnet_device_is_refused(client, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, '{}', ''))
    r = client.get('/api/server', environ_base={'REMOTE_ADDR': '100.100.1.2'})
    assert r.status_code == 403


def test_owner_can_read(client, as_owner):
    r = client.get('/api/server', environ_base=as_owner)
    assert r.status_code == 200
    assert 'X-Response-Time' in r.headers


def test_cross_site_request_is_blocked(client, as_owner):
    r = client.post('/api/server', environ_base=as_owner, headers={'Sec-Fetch-Site': 'cross-site'})
    assert r.status_code == 403


def test_foreign_origin_is_blocked(client, as_owner):
    r = client.get('/api/server', environ_base=as_owner, headers={'Origin': 'https://evil.example'})
    assert r.status_code == 403


def test_same_origin_is_allowed(client, as_owner):
    r = client.get('/api/server', environ_base=as_owner, headers={'Origin': 'http://localhost'})
    assert r.status_code == 200


def test_viewer_rules():
    ok = access.viewer_allowed
    assert ok('GET', '/api/hosts')
    assert ok('GET', '/api/access/me')
    assert not ok('POST', '/api/hosts')
    assert not ok('DELETE', '/api/vms/x')
    assert not ok('GET', '/api/access')
    assert not ok('GET', '/api/term/abc')
    assert not ok('GET', '/terminal')
    assert not ok('GET', '/api/backups/foo/download')
    assert not ok('GET', '/api/hosts/install.sh')
