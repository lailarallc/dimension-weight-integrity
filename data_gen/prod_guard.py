"""Refuse to connect to Postgres when the target is really production.

Blocks a local port held by flyctl/fly (a `fly proxy` tunnel to cinderhaven-db)
or a Fly hostname. Fails closed: if the owner of a local port can't be
determined, it refuses. Override with ALLOW_PROD_DB=1. Stdlib only.

Master copy lives in fleet-ops/prod_guard/. Repos vendor this file unchanged.

    import prod_guard
    prod_guard.check(DATABASE_URL)          # URL or libpq "host=... port=..." DSN
    prod_guard.check(host="localhost", port=5432)

CLI (for dbt / Make / R pre-steps), exits non-zero when blocked:

    python prod_guard.py [DSN | host:port]  # defaults to $DATABASE_URL, then PGHOST/PGPORT
"""
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

FLY_PROCS = {"flyctl", "fly"}
FLY_HOST = re.compile(r"\.(fly\.dev|flycast|internal)$")
LOOPBACK = {"", "localhost", "127.0.0.1", "::1"}


class ProdDatabaseError(RuntimeError):
    pass


def _listener(port):
    """Lowercased name (no .exe) of the process listening on local TCP `port`, or None.

    Several processes can listen on one port: Docker on 0.0.0.0:5432 next to a
    `fly proxy` on 127.0.0.1:5432, where a localhost connection reaches the
    tunnel. So every listener is read and a fly owner wins. On Windows a
    listener whose PID can't be resolved raises (fail closed); lsof on
    macOS/Linux silently omits processes it can't see (e.g. another user's).
    """
    if sys.platform == "win32":
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=True).stdout
        pids = []
        for p in (line.split() for line in out.splitlines()):
            if (len(p) == 5 and p[0] == "TCP" and p[3] == "LISTENING"
                    and p[1].rsplit(":", 1)[-1] == str(port) and p[4] not in pids):
                pids.append(p[4])
        names = []
        for pid in pids:
            row = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, check=True).stdout.strip()
            if not row.startswith('"'):
                raise RuntimeError(f"no process found for PID {pid}")
            names.append(row.split(",")[0].strip('"').lower().removesuffix(".exe"))
    else:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fc"],
                             capture_output=True, text=True).stdout
        names = [line[1:].lower() for line in out.splitlines() if line.startswith("c")]
    return next((n for n in names if n in FLY_PROCS), names[0] if names else None)


def _host_port(dsn):
    if "://" in dsn:
        u = urlparse(dsn)
        return u.hostname, u.port
    kv = dict(re.findall(r"(\w+)=(\S+)", dsn))  # libpq "host=... port=..." form
    return kv.get("host"), kv.get("port")


def check(dsn=None, host=None, port=None):
    """Raise ProdDatabaseError if the target looks like production."""
    if os.environ.get("ALLOW_PROD_DB") == "1":
        return
    if dsn:
        host, port = _host_port(dsn)
    host = (host or os.environ.get("PGHOST") or "localhost").lower()
    port = int(port or os.environ.get("PGPORT") or 5432)
    if FLY_HOST.search(host):
        raise ProdDatabaseError(f"{host} is a Fly host (production). Set ALLOW_PROD_DB=1 if you mean it.")
    if host in LOOPBACK:
        try:
            proc = _listener(port)
        except Exception as e:  # fail closed: an unknown owner is treated as production
            raise ProdDatabaseError(f"can't tell what owns localhost:{port} ({e}). Refusing.") from e
        if proc in FLY_PROCS:
            raise ProdDatabaseError(f"localhost:{port} is a {proc} tunnel to production. "
                                    "Close it, or set ALLOW_PROD_DB=1.")


def main(argv):
    arg = argv[1] if len(argv) > 1 else os.environ.get("DATABASE_URL")
    try:
        if arg and "://" not in arg and "=" not in arg and ":" in arg:
            h, p = arg.rsplit(":", 1)
            check(host=h, port=p)
        else:
            check(arg)
    except ProdDatabaseError as e:
        print(f"prod_guard: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
