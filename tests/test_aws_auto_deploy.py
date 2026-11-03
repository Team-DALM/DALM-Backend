import io
import json
from unittest.mock import Mock

import pytest

from deploy.aws import auto_deploy


def setup(monkeypatch, tmp_path, *, dirty=False, exists=True, ci_sha="new"):
    (tmp_path / "deploy/aws").mkdir(parents=True)
    calls = []

    def git(*args, cwd):
        calls.append(args)
        if args[1] == "status":
            return " M app/main.py" if dirty else ""
        if args[1] == "rev-parse":
            return "new"
        return ""

    process = Mock(returncode=0 if exists else 1)
    runner = Mock(return_value=process)
    monkeypatch.setattr(auto_deploy, "run", git)
    monkeypatch.setattr(auto_deploy.subprocess, "run", runner)
    data = {"workflow_runs": [{"head_sha": ci_sha, "conclusion": "success"}]}
    opener = Mock(return_value=io.StringIO(json.dumps(data)))
    monkeypatch.setattr(auto_deploy.urllib.request, "urlopen", opener)
    return calls, runner, opener


def test_modified_checkout_is_never_overwritten(monkeypatch, tmp_path):
    calls, runner, _ = setup(monkeypatch, tmp_path, dirty=True)
    with pytest.raises(RuntimeError, match="modified checkout"):
        auto_deploy.deploy(tmp_path)
    assert not runner.called
    assert len(calls) == 1


def test_pre_migration_main_cannot_replace_running_aws_release(monkeypatch, tmp_path):
    calls, runner, opener = setup(monkeypatch, tmp_path, exists=False)
    auto_deploy.deploy(tmp_path)
    assert not opener.called
    assert not any("checkout" in c for c in calls)
    assert runner.call_count == 1


def test_success_on_different_commit_does_not_authorize_release(monkeypatch, tmp_path):
    calls, runner, _ = setup(monkeypatch, tmp_path, ci_sha="old")
    auto_deploy.deploy(tmp_path)
    assert not any("checkout" in c for c in calls)
    assert runner.call_count == 1


def test_exact_ci_success_deploys_and_marks_only_after_success(monkeypatch, tmp_path):
    calls, runner, _ = setup(monkeypatch, tmp_path)
    auto_deploy.deploy(tmp_path)
    assert ("git", "checkout", "--quiet", "--detach", "new") in calls
    assert runner.call_args.args[0] == ["bash", "deploy/aws/deploy.sh"]
    assert runner.call_args.kwargs["check"] is True
    assert (tmp_path / "deploy/aws/.deployed-sha").read_text().strip() == "new"
