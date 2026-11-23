import json, subprocess
from flask import Blueprint, jsonify, request, g

from app.core import access
from app.core.logger import log

access_bp = Blueprint('access', __name__)


@access_bp.route('/me', methods=['GET'])
def me():
    who = getattr(g, 'who', None)
    return jsonify({"status": "success", "data": {"role": getattr(g, 'role', None), "owner": g.role == 'owner',
                                                  "login": who and who['login'], "name": who and who['name']}})


def _tailnet_people():
    """Everyone Tailscale knows besides the owner: members, and people devices were shared with or by."""
    try:
        st = json.loads(subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5).stdout)
    except Exception as e:
        log.warning(f"tailscale status for access: {e}")
        return []
    me = st['Self']['UserID']
    users = st.get('User') or {}
    devices = {}
    for p in (st.get('Peer') or {}).values():
        if p.get('UserID') != me and not p.get('Tags'):
            devices[p['UserID']] = devices.get(p['UserID'], 0) + 1
    out = []
    for uid, n in devices.items():
        u = users.get(str(uid)) or {}
        if u.get('LoginName') and u['LoginName'] != 'tagged-devices':
            out.append({"login": u['LoginName'], "name": u.get('DisplayName') or u['LoginName'], "devices": n})
    return sorted(out, key=lambda x: x['name'].lower())


@access_bp.route('', methods=['GET'])
def people():
    if g.role != 'owner':
        return jsonify({"status": "error", "message": "Only the owner sees who has access"}), 403
    roles = access.load()
    seen = _tailnet_people()
    known = {p['login'] for p in seen}
    # people with a role who aren't on the tailnet right now stay listed, so access can be taken away
    seen += [{"login": l, "name": l, "devices": 0} for l in roles if l not in known]
    return jsonify({"status": "success", "data": [{**p, "role": roles.get(p['login'])} for p in seen]})


@access_bp.route('', methods=['PUT'])
def set_role():
    if g.role != 'owner':
        return jsonify({"status": "error", "message": "Only the owner can change who has access"}), 403
    body = request.get_json(silent=True) or {}
    login, role = (body.get('login') or '').strip(), body.get('role')
    if not login or role not in (None, *access.ROLES):
        return jsonify({"status": "error", "message": "login and role (viewer, admin or null) are needed"}), 400
    access.set_role(login, role)
    log.info(f"access: {login} -> {role or 'none'}")
    return jsonify({"status": "success"})
