"""Run the workflow shell and PR gate against disposable Git state, without GitHub writes."""

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest
import yaml

WORKFLOW: Final = Path(__file__).resolve().parents[1] / ".github/workflows/release.yml"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Workflow test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize(
    "scenario",
    [
        (2, "", False),
        (1, "data/release.json", False),
        (0, "", False),
        (0, "unrelated.txt", False),
        (0, "data/release.json", True),
    ],
    ids=[
        "hard-failure",
        "partial-write-failure",
        "not-published-or-unchanged",
        "unrelated-change",
        "new-release",
    ],
)
def test_release_pr_boundary_preserves_pending_branch(
    tmp_path: Path,
    scenario: tuple[int, str, bool],
) -> None:
    exit_code, changed_path, opens_pr = scenario
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["fetch"]["steps"]
    fetch = next(step for step in steps if step.get("id") == "fetch")
    pr = next(step for step in steps if "create-pull-request" in step.get("uses", ""))

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    (repo / "data").mkdir()
    (repo / "data/release.json").write_text('{"period":"old"}\n', encoding="utf-8")
    git(repo, "add", "data/release.json")
    git(repo, "commit", "-m", "baseline")
    git(repo, "checkout", "-b", "auto/release-update")
    (repo / "data/release.json").write_text('{"period":"pending"}\n', encoding="utf-8")
    git(repo, "commit", "-am", "pending review")
    pending_sha = git(repo, "rev-parse", "auto/release-update")
    git(repo, "checkout", "main")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    collector = bin_dir / "python"
    collector.write_text(
        "#!/bin/bash\n"
        'if [[ -n "$CHANGED_PATH" ]]; then printf "new release\\n" > "$CHANGED_PATH"; fi\n'
        'exit "$COLLECTOR_EXIT"\n',
        encoding="utf-8",
    )
    collector.chmod(0o755)
    output = tmp_path / "outputs"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "RELEASE_DATE": "2026-11-01",
        "COLLECTOR_EXIT": str(exit_code),
        "CHANGED_PATH": changed_path,
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", fetch["run"]],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == exit_code
    changed = (
        dict(line.split("=", 1) for line in output.read_text().splitlines())
        if output.exists()
        else {}
    )

    # Evaluate the YAML expression in Bash using controlled runner outcome/output values.
    successful = result.returncode == 0 or fetch.get("continue-on-error", False)
    condition = pr.get("if", "success()")
    condition = condition.removeprefix("${{").removesuffix("}}").strip()
    condition = condition.replace("success()", "1 == 1" if successful else "1 == 0")
    condition = condition.replace("steps.fetch.outputs.changed", repr(changed.get("changed", "")))
    gate = subprocess.run(
        ["bash", "-c", f"[[ {condition} ]]"],
        capture_output=True,
        text=True,
        check=False,
    )
    may_run = successful and gate.returncode == 0
    assert may_run is opens_pr, "PR action must run only after successful release.json changes"
    if not may_run:
        assert git(repo, "rev-parse", "auto/release-update") == pending_sha
        assert git(repo, "show", "auto/release-update:data/release.json") == '{"period":"pending"}'


def test_release_workflow_serializes_writes_and_keeps_review_branches() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["concurrency"] == {"group": "release-auto-update", "cancel-in-progress": False}
    steps = workflow["jobs"]["fetch"]["steps"]
    fetch = next(step for step in steps if step.get("id") == "fetch")
    assert not fetch.get("continue-on-error", False)
    pr = next(step for step in steps if "create-pull-request" in step.get("uses", ""))
    assert pr["with"]["delete-branch"] is False
    # PyYAML's YAML 1.1 loader treats the unquoted GitHub key `on` as True.
    assert workflow[True]["schedule"] == [{"cron": "0 0-8 1-5,11-15,21-25 * *"}]
