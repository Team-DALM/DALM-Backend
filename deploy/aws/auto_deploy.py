"""Pull public main releases only after the exact commit's CI succeeds."""
import json
import os
import subprocess
import urllib.request
from pathlib import Path


def run(*args: str, cwd: Path) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def deploy(root: Path) -> None:
    # The host lock covers fetch/checkout as well as the deployment itself.
    if run("git", "status", "--porcelain", cwd=root):
        raise RuntimeError("Refusing to overwrite a modified checkout")
    run("git", "fetch", "--quiet", "origin", "main", cwd=root)
    target = run("git", "rev-parse", "origin/main", cwd=root)
    marker = root / "deploy/aws/.deployed-sha"
    if marker.exists() and marker.read_text().strip() == target:
        return
    # Pre-migration main has no AWS release script; never downgrade to it.
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{target}:deploy/aws/auto_deploy.py"],
        cwd=root, capture_output=True, check=False,
    )
    if exists.returncode:
        print("Main does not contain the AWS deployment yet; waiting for merge")
        return
    request = urllib.request.Request(
        "https://api.github.com/repos/Team-DALM/DALM-Backend/actions/workflows/ci.yml/runs"
        "?branch=main&event=push&status=success&per_page=10",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "dalm-deployer"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        runs = json.load(response)["workflow_runs"]
    if not any(item["head_sha"] == target and item["conclusion"] == "success" for item in runs):
        print("Waiting for successful CI on main")
        return
    run("git", "checkout", "--quiet", "--detach", target, cwd=root)
    env = dict(os.environ, DALM_ENABLE_HTTP="true")
    subprocess.run(["bash", "deploy/aws/deploy.sh"], cwd=root, env=env, check=True)
    marker.write_text(target + "\n")
    print("Deployed", target)


if __name__ == "__main__":
    import fcntl

    checkout = Path(__file__).resolve().parents[2]
    with open("/run/lock/dalm-auto-deploy.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another automatic deployment is running") from None
        deploy(checkout)
