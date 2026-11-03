"""One-off protected EC2 migration; never commit runtime credentials or reports."""

import hashlib
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

ROOT = Path("/opt/dalm/backend/deploy/aws")
STATE = Path("/var/lib/dalm/db-migration")
PGROOT = Path("/var/lib/dalm/postgres")
IMAGE = "pgvector/pgvector:0.8.7-pg18-trixie"
API = "dalm-aws-api-1"
NETWORK = "dalm-aws_default"


def run(args, *, input=None, env=None, binary=False):
    p = subprocess.run(
        args, input=input, env=env, capture_output=True, text=not binary, check=False
    )
    if p.returncode:
        # Keep raw errors private; SQL errors can include row data.
        log = STATE / ("error-" + secrets.token_hex(4) + ".log")
        log.write_bytes(p.stderr if binary else p.stderr.encode())
        raise RuntimeError("Command failed; protected diagnostics: " + str(log))
    return p.stdout if binary else p.stdout.strip()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True))
    os.chmod(path, 0o600)


def local_sql(sql, db="dalm"):
    return run(
        [
            "docker",
            "exec",
            "-i",
            "dalm-db-postgres-1",
            "psql",
            "-X",
            "-U",
            "postgres",
            "-d",
            db,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
    )


def quote(s):
    return '"' + s.replace('"', '""') + '"'


def literal(s):
    return "'" + s.replace("'", "''") + "'"


SNAPSHOT = """import asyncio,os,json
import asyncpg
async def main():
    os.umask(0o077)
 c=await asyncpg.connect(host=os.environ['PGHOST'],port=int(os.environ['PGPORT']),user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],database=os.environ['PGDATABASE'],ssl=os.environ['PGSSLMODE'])
 out={'tables':{},'sequences':{},'revision':await c.fetchval('SELECT version_num FROM alembic_version')}
 tables=await c.fetch("SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2")
 def q(s): return '"'+s.replace('"','""')+'"'
 for t in tables:
  name=q(t['schemaname'])+'.'+q(t['tablename'])
  r=await c.fetchrow("SELECT count(*) AS count,md5(coalesce(string_agg(h,'' ORDER BY h),'')) AS hash FROM (SELECT md5(to_jsonb(t)::text) h FROM "+name+" t) s")
  out['tables'][name]=dict(r)
 for s in await c.fetch("SELECT schemaname,sequencename FROM pg_sequences WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2"):
  name=q(s['schemaname'])+'.'+q(s['sequencename'])
  out['sequences'][name]=dict(await c.fetchrow('SELECT last_value,is_called FROM '+name))
 print(json.dumps(out,sort_keys=True))
 await c.close()
asyncio.run(main())"""

SOURCE_SQL = """import asyncio,os,json
import asyncpg
async def main():
 c=await asyncpg.connect(host=os.environ['PGHOST'],port=int(os.environ['PGPORT']),user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],database=os.environ['PGDATABASE'],ssl=os.environ['PGSSLMODE'])
 sql=os.environ['MIGRATION_SQL']
 rows=await c.fetch(sql)
 print(json.dumps([dict(r) for r in rows],default=str))
 await c.close()
asyncio.run(main())"""


def app_python(code, settings, extra=None):
    env = dict(os.environ, **settings, **(extra or {}))
    flags = [v for k in list(settings) + list(extra or {}) for v in ("-e", k)]
    return run(
        ["docker", "run", "--rm", "--network", NETWORK, *flags, app_image, "python", "-c", code],
        env=env,
    )


def source_sql(sql):
    return json.loads(app_python(SOURCE_SQL, source, {"MIGRATION_SQL": sql}))


def snapshot(settings):
    return json.loads(app_python(SNAPSHOT, settings))


def dump(name):
    archive = STATE / (name + ".dump")
    env = dict(os.environ, **source)
    flags = [v for k in source for v in ("-e", k)]
    with archive.open("xb") as f:
        p = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                NETWORK,
                *flags,
                IMAGE,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
            ],
            env=env,
            stdout=f,
            stderr=subprocess.PIPE,
            check=False,
        )
    if p.returncode:
        (STATE / "dump-error.log").write_bytes(p.stderr)
        raise RuntimeError("Dump failed; inspect private log")
    print("Dump complete:", archive.stat().st_size, "bytes", flush=True)
    return archive


def restore(archive, db):
    assert local_sql("SELECT 1 FROM pg_database WHERE datname=" + literal(db)) == "", (
        "Destination already exists"
    )
    local_sql(
        "CREATE DATABASE "
        + quote(db)
        + " OWNER dalm TEMPLATE template0 ENCODING "
        + literal("UTF8")
    )
    local_sql("CREATE EXTENSION vector", db)
    # Only managed extension ownership differs; all user schema/data objects are restored.
    listing = run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            str(STATE) + ":/backup:ro",
            IMAGE,
            "pg_restore",
            "--list",
            "/backup/" + archive.name,
        ]
    )
    kept = (
        "\n".join(
            line
            for line in listing.splitlines()
            if not (" EXTENSION " in line or " COMMENT - EXTENSION " in line)
        )
        + "\n"
    )
    toc = STATE / (db + ".list")
    toc.write_text(kept)
    # localhost trust applies inside this private DB container; no credentials in arguments.
    run(["docker", "cp", str(archive), "dalm-db-postgres-1:/tmp/" + archive.name])
    run(["docker", "cp", str(toc), "dalm-db-postgres-1:/tmp/" + toc.name])
    run(
        [
            "docker",
            "exec",
            "dalm-db-postgres-1",
            "pg_restore",
            "-U",
            "postgres",
            "--role=dalm",
            "-d",
            db,
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            "--use-list=/tmp/" + toc.name,
            "/tmp/" + archive.name,
        ]
    )
    local_sql("ANALYZE", db)
    target = {
        "PGHOST": "postgres",
        "PGPORT": "5432",
        "PGUSER": "dalm",
        "PGPASSWORD": app_password,
        "PGDATABASE": db,
        "PGSSLMODE": "disable",
    }
    return target


def verify(expected, target, label):
    actual = snapshot(target)
    save(STATE / (label + "-source.json"), expected)
    save(STATE / (label + "-target.json"), actual)
    if actual != expected:
        raise RuntimeError("Data comparison failed; no switch performed")
    print(
        label
        + ": all "
        + str(len(actual["tables"]))
        + " tables and "
        + str(len(actual["sequences"]))
        + " sequences match; revision "
        + actual["revision"],
        flush=True,
    )
    return actual


SOURCE_SETTINGS = "import json,os\nfrom sqlalchemy.engine import make_url\nu=make_url(os.getenv('DALM_BACKUP_DATABASE_URL') or os.environ['DALM_DATABASE_URL'])\nh=u.host.replace('-pooler.','.') if u.host.endswith('neon.tech') else u.host\nprint(json.dumps(dict(PGHOST=h,PGPORT=str(u.port or 5432),PGUSER=u.username,PGPASSWORD=u.password or '',PGDATABASE=u.database,PGSSLMODE=u.query.get('sslmode',u.query.get('ssl','require')))))"

WRITE_CHECK = "async def main():\n c=await asyncpg.connect(host=os.environ['PGHOST'],port=int(os.environ['PGPORT']),user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],database=os.environ['PGDATABASE'],ssl=False)\n t=c.transaction(); await t.start()\n await c.execute('CREATE TABLE public.__dalm_migration_write_check(id integer)')\n await c.execute('INSERT INTO public.__dalm_migration_write_check VALUES (1)')\n await t.rollback()\n assert not await c.fetchval(\"SELECT to_regclass('public.__dalm_migration_write_check')\")\n assert not await c.fetchval('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')\n await c.close()\n print('App-role write and rollback: PASS')\nasyncio.run(main())"


def main():
    global app_image, source, app_password
    STATE.mkdir(parents=True, exist_ok=True)
    PGROOT.mkdir(parents=True, exist_ok=True)
    app_image = run(["docker", "inspect", "-f", "{{.Config.Image}}", API])
    settings_file = STATE / "source-settings.json"
    if settings_file.exists():
        source = json.loads(settings_file.read_text())
    else:
        code = SOURCE_SETTINGS
        source = json.loads(run(["docker", "exec", API, "python", "-c", code]))
        save(settings_file, source)

    phase = os.environ.get("MIGRATION_PHASE", "prepare")
    if phase == "prepare":
        pwfile = STATE / "app-password"
        if not pwfile.exists():
            pwfile.write_text(secrets.token_urlsafe(40))
        app_password = pwfile.read_text()
        secretsdir = PGROOT / "secrets"
        secretsdir.mkdir(mode=0o700, exist_ok=True)
        admin = secretsdir / "postgres_password"
        if not admin.exists():
            admin.write_text(secrets.token_urlsafe(48))
        run(["docker", "compose", "-f", str(PGROOT / "compose.yaml"), "up", "-d", "--wait"])
        if not local_sql("SELECT 1 FROM pg_roles WHERE rolname='dalm'"):
            local_sql(
                "CREATE ROLE dalm LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD "
                + literal(app_password)
            )
        print(
            "Private PostgreSQL healthy; application role has no superuser privileges", flush=True
        )
        archive = dump("trial-" + str(int(time.time())))
        before = snapshot(source)
        target = restore(archive, "dalm_trial_" + str(int(time.time())))
        verify(before, target, "trial")
        save(STATE / "trial-settings.json", target)
        print("PREPARE_COMPLETE", flush=True)
    elif phase == "cutover":
        app_password = (STATE / "app-password").read_text()
        run(["systemctl", "stop", "dalm-deploy.timer"])
        # Wait for any currently running deployment before changing runtime settings.
        if (
            subprocess.run(
                ["systemctl", "is-active", "--quiet", "dalm-deploy.service"], check=False
            ).returncode
            == 0
        ):
            raise RuntimeError("Deployment is running; retry after it completes")
        original = source_sql(
            "SELECT setconfig FROM pg_db_role_setting WHERE setdatabase=(SELECT oid FROM pg_database WHERE datname=current_database()) AND setrole=0"
        )
        save(STATE / "original-database-settings.json", original)
        # Preserve a rollback copy before modifying anything.
        envbackup = STATE / "app.env.before"
        assert not envbackup.exists(), "Cutover has already started"
        envbackup.write_bytes((ROOT / ".env").read_bytes())
        source_sql(
            "ALTER DATABASE "
            + quote(source["PGDATABASE"])
            + " SET default_transaction_read_only=on"
        )
        source_sql(
            "SELECT pg_terminate_backend(pid) AS terminated FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
        )
        assert (
            source_sql("SHOW default_transaction_read_only")[0]["default_transaction_read_only"]
            == "on"
        )
        print("Original DB read-only; source writers fenced", flush=True)
        try:
            expected = snapshot(source)
            archive = dump("final-" + str(int(time.time())))
            db = "dalm_production_" + str(int(time.time()))
            target = restore(archive, db)
            result = verify(expected, target, "final")
            # Verify a write transaction using the app role, then roll it back.
            check = SNAPSHOT[: SNAPSHOT.index("async def main():")] + WRITE_CHECK
            print(app_python(check, target), flush=True)
            url = (
                "postgresql+asyncpg://dalm:"
                + app_password
                + "@postgres:5432/"
                + db
                + "?ssl=disable"
            )
            lines = [
                x
                for x in (ROOT / ".env").read_text().splitlines()
                if not x.startswith(("DALM_DATABASE_URL=", "DALM_BACKUP_DATABASE_URL="))
            ]
            tmp = ROOT / ".env.db-switch"
            tmp.write_text("\n".join(lines) + "\nDALM_DATABASE_URL=" + url + "\n")
            os.replace(tmp, ROOT / ".env")
            run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(ROOT / "compose.yaml"),
                    "--project-directory",
                    str(ROOT),
                    "up",
                    "-d",
                    "--no-deps",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "api",
                ]
            )
            import urllib.request

            ready = json.load(urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=10))
            assert ready["status"] == "ready"
            save(STATE / "production-settings.json", target)
            save(
                STATE / "result.json",
                {
                    "database": db,
                    "tables": len(result["tables"]),
                    "rows": sum(x["count"] for x in result["tables"].values()),
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "backup_bytes": archive.stat().st_size,
                    "ready": ready,
                },
            )
            print(
                "CUTOVER_COMPLETE: API healthy on local PostgreSQL; original retained read-only",
                flush=True,
            )
        except BaseException:
            # Do not automatically switch back after the API may have accepted new writes.
            print(
                "CUTOVER_FAILED: protected source backup and restored DB retained; inspect before rollback",
                flush=True,
            )
            raise
        finally:
            run(["systemctl", "start", "dalm-deploy.timer"])
    else:
        raise ValueError("Unknown phase")


if __name__ == "__main__":
    import fcntl

    with open("/run/lock/dalm-auto-deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            main()
        finally:
            if os.environ.get("MIGRATION_PHASE") == "cutover":
                subprocess.run(["systemctl", "start", "dalm-deploy.timer"], check=True)
