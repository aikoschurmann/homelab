"""Which computer's OrbStack a machine call is about: Arrakis's own, or another host's.

The machine code (app/api/vms.py, app/core/cftunnel.py) runs `orb` the same way for every
host. `current` says which host the request or background thread is working for (None =
Arrakis); run() sends the command there: a local subprocess, or the host's agent over its
command channel (app/api/hosts.py rpc). PerHost keeps one copy of a cache or job table per
host, so two hosts can each have a machine called the same thing. Thread carries the
creating thread's host along.
"""
import contextvars
import subprocess
import threading
from collections.abc import MutableMapping

current = contextvars.ContextVar('orb_host', default=None)


def host():
    return current.get()


def key(name):
    """A machine's id across hosts: its name on Arrakis, '<host>:<name>' elsewhere."""
    h = current.get()
    return name if h is None else f"{h}:{name}"


def run(args, timeout=30, input=None):
    """`orb <args>` on the current host -> (returncode, stdout, stderr), as text."""
    h = current.get()
    if h is None:
        res = subprocess.run(['orb', *args], input=input, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout, res.stderr
    from app.api.hosts import rpc
    return rpc(h, list(args), input or '', timeout)


def managed():
    """Hosts whose OrbStack the dashboard manages right now (switched on and connected)."""
    from app.api.hosts import managed_hosts
    return managed_hosts()


class Thread(threading.Thread):
    """A thread that works for the same host as the one that created it."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ctx = contextvars.copy_context()

    def run(self):
        self._ctx.run(super().run)


class PerHost(MutableMapping):
    """A dict per host behind one name; reads and writes go to the current host's."""
    def __init__(self, factory=dict):
        self._all, self._factory = {}, factory

    def _d(self):
        h = current.get()
        d = self._all.get(h)
        if d is None:
            d = self._all[h] = self._factory()
        return d

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def __delitem__(self, k):
        del self._d()[k]

    def __iter__(self):
        return iter(list(self._d()))

    def __len__(self):
        return len(self._d())

    def drop_host(self, h):
        self._all.pop(h, None)
