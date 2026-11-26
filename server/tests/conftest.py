import os, sys, tempfile

# Isolated state: never touch the real ~/.config/homelab. Must be set before app.* is imported.
os.environ['HOMELAB_HOME'] = tempfile.mkdtemp(prefix='homelab-test-')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(scope='session')
def app():
    import app.main as main
    main.start_all_pollers = lambda: None   # no background threads in tests
    return main.create_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def as_owner(monkeypatch):
    """Requests from 127.0.0.1 count as this Mac (off macOS, loopback is never proxied)."""
    monkeypatch.setattr(sys, 'platform', 'linux')
    return {'REMOTE_ADDR': '127.0.0.1'}
