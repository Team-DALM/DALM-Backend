"""Create a private PostgreSQL backup and verify it in an isolated scratch DB.

Run as root on EC2. No database credential is printed or passed in command arguments.
The optional --upload copies the verified archive to the configured private S3 bucket.
"""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def call(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def backup(directory: Path, upload: bool) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    # Resolve the app's parsed connection settings inside its existing container.
    code = '''import json,os
from sqlalchemy.engine import make_url
u=make_url(os.getenv("DALM_BACKUP_DATABASE_URL") or os.environ["DALM_DATABASE_URL"])
print(json.dumps(dict(PGHOST=u.host,PGPORT=str(u.port or 5432),PGUSER=u.username,
 PGPASSWORD=u.password or "",PGDATABASE=u.database,PGSSLMODE=u.query.get("sslmode",u.query.get("ssl","require")))))'''
    settings = json.loads(call(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code], cwd=ROOT,
    ))
    env = dict(os.environ, **settings)
    flags = [part for key in settings for part in ("-e", key)]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = directory / f"dalm-{stamp}.dump"
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            subprocess.run(
                ["docker", "run", "--rm", *flags, "postgres:17", "pg_dump",
                 "--format=custom", "--no-owner", "--no-acl"],
                env=env, stdout=output, check=True,
            )
        # All scratch data is isolated from the network and disposed after validation.
        name = "dalm-restore-check-" + secrets.token_hex(5)
        scratch_env = dict(os.environ, POSTGRES_PASSWORD=secrets.token_urlsafe(32))
        subprocess.run(
            ["docker", "run", "-d", "--name", name, "--network", "none",
             "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_PASSWORD",
             "-e", "POSTGRES_DB=restore_check", "pgvector/pgvector:pg17"],
            env=scratch_env, stdout=subprocess.DEVNULL, check=True,
        )
        try:
            for _ in range(60):
                ready = subprocess.run(
                    ["docker", "exec", name, "pg_isready", "-U", "postgres"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Scratch database did not become ready")
            with archive.open("rb") as source:
                subprocess.run(
                    ["docker", "exec", "-i", name, "pg_restore", "-U", "postgres",
                     "-d", "restore_check", "--no-owner", "--no-acl", "--exit-on-error"],
                    stdin=source, check=True,
                )
            restored_head = call(
                ["docker", "exec", name, "psql", "-U", "postgres", "-d", "restore_check",
                 "-At", "-c", "SELECT version_num FROM alembic_version"],
            )
            assert restored_head, "Restored DB is missing its Alembic revision"
            vector = call(
                ["docker", "exec", name, "psql", "-U", "postgres", "-d", "restore_check",
                 "-At", "-c", "SELECT extname FROM pg_extension WHERE extname='vector'"],
            )
            assert vector == "vector", "pgvector extension missing after restore"
        finally:
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, check=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        metadata = {"sha256": digest, "bytes": archive.stat().st_size,
                    "restored_revision": restored_head}
        report = archive.with_suffix(".json")
        fd = os.open(report, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(metadata, stream)
        if upload:
            # Use the EC2 role from an app container; no access keys are required.
            image = call(["docker", "compose", "images", "-q", "api"], cwd=ROOT)
            code = '''import boto3,os,hashlib
c=boto3.client("s3",region_name=os.getenv("AWS_DEFAULT_REGION","ap-northeast-2"))
b=os.environ.get("DALM_BACKUP_S3_BUCKET") or os.environ["DALM_S3_BUCKET"]
k="backups/postgres/"+os.path.basename(os.environ["BACKUP_FILE"])
p="/backup/"+os.environ["BACKUP_FILE"]
with open(p,"rb") as f: c.put_object(Bucket=b,Key=k,Body=f,ServerSideEncryption="AES256",IfNoneMatch="*")
expected=hashlib.sha256(open(p,"rb").read()).hexdigest()
actual=hashlib.sha256(c.get_object(Bucket=b,Key=k)["Body"].read()).hexdigest()
assert actual==expected
print("Private S3 backup round-trip SHA256: PASS")'''
            subprocess.run(
                ["docker", "run", "--rm", "--user", "0", "--env-file", str(ROOT / ".env"),
                 "-e", f"BACKUP_FILE={archive.name}", "-v", f"{directory}:/backup:ro",
                 image, "python", "-c", code], check=True,
            )
        print("Backup and isolated restore verified:", json.dumps(metadata))
    except BaseException:
        print("Backup did not pass validation; inspect the protected local archive")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/var/lib/dalm/backups"))
    parser.add_argument("--upload", action="store_true", help="Upload only after restore succeeds")
    args = parser.parse_args()
    backup(args.directory.resolve(), args.upload)
