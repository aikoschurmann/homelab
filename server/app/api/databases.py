from flask import Blueprint, jsonify, request, Response
import csv
import io
import json
import sqlite3
import os
import glob
import time
import threading
from urllib.parse import quote

from app.core import dbsources
from app.core.logger import log
from app.core import paths
from app.core import server_cfg

databases_bp = Blueprint('databases', __name__)

DB_DIR = paths.DATA

# Full COUNT(*) scans over every table are expensive (metrics.db alone has ~900k
# rows) and the frontend polls this endpoint, so serve a short-lived cache.
CACHE_TTL = 30
_cache = {"ts": 0, "data": None}
_cache_lock = threading.Lock()

def _qi(name):
    # Quote an SQLite identifier (table names come from the DB files themselves)
    return '"' + name.replace('"', '""') + '"'

@databases_bp.route('', methods=['GET'])
@databases_bp.route('/', methods=['GET'])
def list_databases():
    refresh = request.args.get('refresh') == '1'
    with _cache_lock:
        if not refresh and _cache["data"] is not None and time.time() - _cache["ts"] < CACHE_TTL:
            return jsonify({"status": "success", "data": _cache["data"]})
        result = _scan_databases() + _machine_databases(refresh)
        _cache.update(ts=time.time(), data=result)
    return jsonify({"status": "success", "data": result})


def _invalidate():
    with _cache_lock:
        _cache["data"] = None


# Table info for a snapshot only changes when the snapshot does (pihole-FTL.db has
# millions of rows, too many to count on every list).
_snap_tables = {}


def _machine_databases(refresh=False):
    out = []
    try:
        found = dbsources.discover(force=refresh)
    except Exception as e:  # noqa: BLE001
        log.warning(f"machine databases: {e}")
        return out
    for d in found:
        snap = dbsources.snapshot_info(d)
        tables = None
        if snap:
            key = (snap["path"], snap["at"])
            if key not in _snap_tables:
                try:
                    _snap_tables[key] = _tables(snap["path"])
                except Exception as e:  # noqa: BLE001
                    _snap_tables[key] = []
                    log.warning(f"tables of {d['id']}: {e}")
            tables = _snap_tables[key]
        out.append({
            "id": d["id"], "name": d["name"], "path": d["path"], "type": "SQLite",
            "service": d["used_by"] or d["machine"], "size_bytes": d["size"] + d["wal"],
            "host": d["host"], "host_name": d["host_name"], "machine": d["machine"],
            "modified": d["mtime"], "tables": tables,
            "snapshot": {"at": snap["at"], "size": snap["size"]} if snap else None,
        })
    return out

def _tables(path):
    """Name, row count, indexes and columns of every table, read-only (never a write lock
    on another app's live database, e.g. Jellyfin's)."""
    tables = []
    conn = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=2)
    try:
        c = conn.cursor()
        names = [(r[0], r[1]) for r in c.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')") if not r[0].startswith('sqlite_')]
        for t, kind in names:
            try:
                # views aren't counted: one over a big table (Pi-hole's queries) takes seconds
                count = c.execute(f"SELECT COUNT(*) FROM {_qi(t)}").fetchone()[0] if kind == 'table' else None
                idx = c.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND tbl_name=?", (t,)).fetchone()[0]
                # (cid, name, type, notnull, dflt_value, pk)
                cols = [{"name": r[1], "type": r[2] or "UNKNOWN", "pk": bool(r[5])} for r in c.execute(f"PRAGMA table_info({_qi(t)})")]
                tables.append({"name": t, "view": kind == 'view', "rows": count, "indexes": idx, "columns": len(cols), "col_list": cols})
            except Exception:  # noqa: BLE001
                tables.append({"name": t, "view": kind == 'view', "rows": -1, "indexes": 0, "columns": 0, "col_list": []})
    finally:
        conn.close()
    # tables biggest first, then views
    return sorted(tables, key=lambda x: (x["view"], -(x["rows"] or 0)))


def _scan_databases():
    result = []
    
    # Dynamically scan the ~/.databases folder
    db_files = glob.glob(os.path.join(DB_DIR, '*.db')) + glob.glob(os.path.join(DB_DIR, '*.sqlite'))
    
    # We can still manually add Jellyfin since it's an external app
    external_dbs = [
        {
            "id": "jellyfin",
            "name": "Jellyfin Server DB",
            "path": os.path.expanduser("~/Library/Application Support/jellyfin/data/jellyfin.db"),
            "service": "Jellyfin",
            "type": "SQLite"
        }
    ]
    
    all_targets = external_dbs
    for f in db_files:
        basename = os.path.basename(f)
        name = basename.replace('.db', '').replace('.sqlite', '').replace('_', ' ').title()
        
        # Determine service name
        service = "Dashboard" if basename == "metrics.db" else "User Database"
        
        all_targets.append({
            "id": basename,
            "name": name,
            "path": f,
            "service": service,
            "type": "SQLite"
        })

    for db in all_targets:
        if os.path.exists(db['path']):
            try:
                size_bytes = os.path.getsize(db['path'])
                
                tables = _tables(db['path'])
                
                result.append({
                    "id": db["id"],
                    "name": db["name"],
                    "path": db["path"],
                    "service": db["service"],
                    "type": db["type"],
                    "host": None, "host_name": server_cfg.name(), "machine": None,
                    "modified": int(os.path.getmtime(db['path'])),
                    "size_bytes": size_bytes,
                    "tables": tables
                })
            except Exception as e:
                result.append({
                    "id": db["id"],
                    "name": db["name"],
                    "path": db["path"],
                    "service": db["service"],
                    "type": db["type"],
                    "host": None, "host_name": server_cfg.name(), "machine": None,
                    "error": str(e)
                })
    return result


# ---- browsing and read-only queries ---------------------------------------------------
# Every connection is opened with mode=ro, so nothing here can write to a live
# database (Jellyfin's or the dashboard's own). Queries are also limited to one
# read statement, a few seconds and a row cap.


MAX_ROWS = 500
QUERY_SECONDS = 5
READ_START = ('select', 'with', 'pragma', 'explain', 'values')


def _db_path(db_id):
    """The file to read: a local database itself, or the snapshot of one in a machine
    (copied on first use)."""
    with _cache_lock:
        data = _cache["data"]
    for db in data or _scan_databases():
        if db['id'] == db_id and not db.get('machine'):
            return db['path']
    d = dbsources.find(db_id)
    if not d:
        return None
    snap = dbsources.snapshot_info(d) or dbsources.take_snapshot(d)
    if data is not None and not any(x['id'] == db_id and x.get('snapshot') for x in data):
        _invalidate()  # the list now has tables for it
    return snap["path"]


@databases_bp.route('/<db_id>/snapshot', methods=['POST'])
def refresh_snapshot(db_id):
    """Copy a machine's database again, to see what changed since the last copy."""
    d = dbsources.find(db_id)
    if not d:
        return jsonify({"status": "error", "message": "Only databases inside machines are copied"})
    try:
        snap = dbsources.take_snapshot(d)
        _invalidate()
        return jsonify({"status": "success", "data": {"at": snap["at"], "size": snap["size"]}})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


def _cell(v):
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    if isinstance(v, str) and len(v) > 2000:
        return v[:2000] + '…'
    return v


def _run(path, sql, params=()):
    conn = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=2)
    deadline = time.time() + QUERY_SECONDS
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
    try:
        started = time.time()
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS + 1)
        return {
            "columns": cols,
            "rows": [[_cell(v) for v in r] for r in rows[:MAX_ROWS]],
            "truncated": len(rows) > MAX_ROWS,
            "ms": round((time.time() - started) * 1000, 1),
        }
    finally:
        conn.close()


def _table_select(path, table):
    """SELECT for one table with the request's sort and column filters -> (sql, params, filtered).
    Column names are checked against the table, values are bound."""
    conn = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=2)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if table not in names:
            raise LookupError("Unknown table")
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_qi(table)})")]
        try:
            conn.execute(f"SELECT rowid FROM {_qi(table)} LIMIT 0")
            has_rowid = True
        except sqlite3.OperationalError:
            has_rowid = False
    finally:
        conn.close()
    try:
        filters = json.loads(request.args.get('f') or '{}')
    except ValueError:
        filters = {}
    where, params = [], []
    for c, v in filters.items():
        v = str(v).strip()
        if c in cols and v:
            if v.upper() == 'NULL':
                where.append(f"{_qi(c)} IS NULL")
            else:
                where.append(f"CAST({_qi(c)} AS TEXT) LIKE ?")
                params.append(f"%{v}%")
    sql = f"SELECT * FROM {_qi(table)}" + (" WHERE " + " AND ".join(where) if where else "")
    sort, desc = request.args.get('sort'), request.args.get('dir', 'desc') != 'asc'
    if sort in cols:
        sql += f" ORDER BY {_qi(sort)} {'DESC' if desc else 'ASC'}"
    elif has_rowid:  # newest first
        sql += f" ORDER BY rowid {'DESC' if desc else 'ASC'}"
    return sql, params, bool(where)


@databases_bp.route('/<db_id>/tables/<table>/rows', methods=['GET'])
def table_rows(db_id, table):
    try:
        path = _db_path(db_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": f"Couldn't copy it from the machine: {e}"})
    if not path:
        return jsonify({"status": "error", "message": "Unknown database"})
    limit = min(max(request.args.get('limit', 50, type=int), 1), 200)
    offset = max(request.args.get('offset', 0, type=int), 0)
    try:
        sql, params, filtered = _table_select(path, table)
        data = _run(path, sql + " LIMIT ? OFFSET ?", (*params, limit, offset))
        data.update(limit=limit, offset=offset, total=None)
        if filtered:  # how many match, for the pager
            data["total"] = _run(path, f"SELECT count(*) FROM ({sql})", params)["rows"][0][0]
        return jsonify({"status": "success", "data": data})
    except LookupError as e:
        return jsonify({"status": "error", "message": str(e)})
    except sqlite3.OperationalError as e:
        msg = str(e)
        return jsonify({"status": "error", "message": f"Stopped after {QUERY_SECONDS} seconds; narrow the filter" if 'interrupted' in msg else msg})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})


EXPORT_MAX = 100_000


@databases_bp.route('/<db_id>/tables/<table>/export.csv', methods=['GET'])
def export_table(db_id, table):
    """The table as CSV, with the same sort and filters as the browser, up to EXPORT_MAX rows."""
    try:
        path = _db_path(db_id)
        if not path:
            return Response("Unknown database", status=404)
        sql, params, _ = _table_select(path, table)
    except LookupError as e:
        return Response(str(e), status=404)

    def rows():
        conn = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=2)
        try:
            cur = conn.execute(sql + " LIMIT ?", (*params, EXPORT_MAX))
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([d[0] for d in cur.description])
            for i, r in enumerate(cur):
                w.writerow([f"<{len(v)} bytes>" if isinstance(v, bytes) else v for v in r])
                if i % 500 == 0:
                    yield buf.getvalue(); buf.seek(0); buf.truncate()
            yield buf.getvalue()
        finally:
            conn.close()
    name = f"{table}.csv".replace('"', '')
    return Response(rows(), mimetype='text/csv', headers={"Content-Disposition": f'attachment; filename="{name}"'})


@databases_bp.route('/<db_id>/query', methods=['POST'])
def run_query(db_id):
    try:
        path = _db_path(db_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": f"Couldn't copy it from the machine: {e}"})
    if not path:
        return jsonify({"status": "error", "message": "Unknown database"})
    sql = ((request.json or {}).get('sql') or '').strip().rstrip(';').strip()
    if not sql:
        return jsonify({"status": "error", "message": "Write a query first"})
    if not sql.lower().startswith(READ_START):
        return jsonify({"status": "error", "message": "Only read queries (SELECT, WITH, PRAGMA, EXPLAIN) are allowed here"})
    if not sqlite3.complete_statement(sql + ';') or ';' in sql:
        return jsonify({"status": "error", "message": "One statement at a time"})
    try:
        return jsonify({"status": "success", "data": _run(path, sql)})
    except sqlite3.OperationalError as e:
        msg = str(e)
        if 'interrupted' in msg:
            msg = f"Stopped after {QUERY_SECONDS} seconds; narrow the query"
        return jsonify({"status": "error", "message": msg})
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(e)})
