"""The Cloudflare side of the homelab, read with the saved API token: the zone, every
tunnel with its live connectors, and the zone's DNS records.

Read-only. Tunnels and their CNAMEs are made and removed by sharing a machine
(app/core/cftunnel.py); the token and domain are set in Settings.
"""
from flask import Blueprint, jsonify
import threading
import time
import urllib.parse

from app.core import cftunnel
from app.core.logger import log

cloudflare_bp = Blueprint('cloudflare', __name__)

CACHE_SECONDS = 15
_cache = {"at": 0, "data": None}
_lock = threading.Lock()


def _owner(key):
    """'host:name' (a machine on another host) or 'name' (on Arrakis) -> (machine, host)."""
    host, _, name = key.rpartition(":")
    return name, host or None


def _tunnel(t, by_tid):
    share = by_tid.get(t["id"])
    machine, host = _owner(share[0]) if share else (None, None)
    conns = [{
        "id": c.get("id"),
        "colo": c.get("colo_name"),
        "version": c.get("client_version"),
        "origin_ip": c.get("origin_ip"),
        "opened_at": c.get("opened_at"),
        "pending_reconnect": bool(c.get("is_pending_reconnect")),
    } for c in t.get("connections") or []]
    return {
        "id": t["id"],
        "name": t["name"],
        "status": t.get("status"),  # healthy / degraded / down / inactive
        # deleted tunnels stay listed by Cloudflare for a while; kept apart from the live ones
        "deleted": bool(t.get("deleted_at")),
        "deleted_at": t.get("deleted_at"),
        "remote": t.get("config_src") == "cloudflare",
        "created": t.get("created_at"),
        "active_at": t.get("conns_active_at"),
        "inactive_at": t.get("conns_inactive_at"),
        "connections": conns,
        "machine": machine,
        "host": host,
        "hostname": share[1].get("hostname") if share else None,
        "people": len(share[1].get("keys") or []) if share else 0,
    }


def _overview():
    with _lock:
        if _cache["data"] and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["data"]
    zone_id, acct = cftunnel._zone()
    zone = cftunnel._cf("GET", f"/zones/{zone_id}") or {}
    by_tid = {s.get("tunnel_id"): (k, s) for k, s in cftunnel.shares().items() if s.get("tunnel_id")}
    live = [_tunnel(t, by_tid) for t in cftunnel._cf("GET", f"/accounts/{acct}/cfd_tunnel?is_deleted=false&per_page=100") or []]
    gone = [_tunnel(t, {}) for t in cftunnel._cf("GET", f"/accounts/{acct}/cfd_tunnel?is_deleted=true&per_page=100") or []]
    live.sort(key=lambda t: t["name"])
    gone.sort(key=lambda t: t["deleted_at"] or "", reverse=True)
    tunnels = live + gone
    names = {t["id"]: t["name"] for t in live}
    records = []
    for r in cftunnel._cf("GET", f"/zones/{zone_id}/dns_records?per_page=500") or []:
        content = r.get("content") or ""
        tid = content[:-len(".cfargotunnel.com")] if content.endswith(".cfargotunnel.com") else None
        records.append({
            "id": r["id"], "type": r["type"], "name": r["name"], "content": content,
            "proxied": bool(r.get("proxied")), "ttl": r.get("ttl"), "comment": r.get("comment") or "",
            "modified": r.get("modified_on"),
            # a CNAME at a tunnel: which one, or a stale record whose tunnel is gone
            "tunnel": names.get(tid) if tid else None, "dangling": bool(tid and tid not in names),
        })
    order = {"A": 0, "AAAA": 1, "CNAME": 2, "MX": 3, "TXT": 4}
    records.sort(key=lambda r: (r["name"].count("."), r["name"], order.get(r["type"], 9)))
    data = {
        "zone": {
            "id": zone_id, "name": zone.get("name"), "status": zone.get("status"),
            "paused": bool(zone.get("paused")), "plan": (zone.get("plan") or {}).get("name"),
            "name_servers": zone.get("name_servers") or [], "created": zone.get("created_on"),
            "account": (zone.get("account") or {}).get("name"), "account_id": acct,
        },
        "tunnels": tunnels,
        "records": records,
    }
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


@cloudflare_bp.route('', methods=['GET'])
@cloudflare_bp.route('/', methods=['GET'])
def overview():
    if not cftunnel.logged_in():
        return jsonify({"status": "success", "data": {"logged_in": False}})
    try:
        return jsonify({"status": "success", "data": {"logged_in": True, **_overview()}})
    except Exception as e:  # noqa: BLE001
        log.warning(f"cloudflare overview: {e}")
        return jsonify({"status": "error", "message": str(e)})


@cloudflare_bp.route('/tunnels/<tid>/config', methods=['GET'])
def tunnel_config(tid):
    """A remotely managed tunnel's ingress rules (hostname -> service)."""
    try:
        _, acct = cftunnel._zone()
        cfg = cftunnel._cf("GET", f"/accounts/{acct}/cfd_tunnel/{urllib.parse.quote(tid)}/configurations") or {}
        rules = [{"hostname": r.get("hostname") or "", "path": r.get("path") or "", "service": r.get("service")}
                 for r in (cfg.get("config") or {}).get("ingress") or []]
        return jsonify({"status": "success", "data": {"version": cfg.get("version"), "ingress": rules}})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


@cloudflare_bp.route('/tunnels/<tid>', methods=['DELETE'])
def delete_tunnel(tid):
    """Delete a tunnel the dashboard isn't using, with the DNS records that point at it.
    A shared machine's tunnel is removed by stopping the share, which also cleans the machine up."""
    owner = next((k for k, s in cftunnel.shares().items() if s.get("tunnel_id") == tid), None)
    if owner:
        return jsonify({"status": "error", "message": f"This is {owner}'s share; stop sharing the machine instead"})
    try:
        zone_id, acct = cftunnel._zone()
        t = cftunnel._cf("GET", f"/accounts/{acct}/cfd_tunnel/{urllib.parse.quote(tid)}") or {}
        if t.get("deleted_at"):
            return jsonify({"status": "error", "message": "Already deleted"})
        target = f"{t['id']}.cfargotunnel.com"
        removed = []
        for r in cftunnel._cf("GET", f"/zones/{zone_id}/dns_records?type=CNAME&per_page=500") or []:
            if r.get("content") == target:
                cftunnel._cf("DELETE", f"/zones/{zone_id}/dns_records/{r['id']}")
                removed.append(r["name"])
        cftunnel._delete_tunnel(t["id"])
        log.info(f"deleted tunnel {t.get('name')} ({t['id']}), DNS {removed}")
        with _lock:
            _cache["data"] = None
        return jsonify({"status": "success", "data": {"name": t.get("name"), "dns_removed": removed}})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})
