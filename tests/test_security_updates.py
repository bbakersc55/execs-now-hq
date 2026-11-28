"""The routine that keeps dependencies current (2026-11-27,
docs/security_updates.md), held in place: base images pinned by digest, a
fresh system-package step on every build, Dependabot against `dev`, and the
gate's audit before the suites. These read files; nothing is built."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()


def test_every_base_image_is_pinned_by_digest():
    froms = re.findall(r"(?m)^FROM\s+(\S+)", DOCKERFILE)
    assert len(froms) == 2
    for image in froms:
        assert re.fullmatch(r"[a-z0-9./-]+:[\w.-]+@sha256:[0-9a-f]{64}", image), image


def test_the_system_package_step_runs_afresh_for_every_commit():
    """A changed ARG that a RUN uses is a cache miss: the commit Railway passes
    makes the apt step run again for each build, with `apt-get upgrade`, and
    leave its record in /etc/enhq-system-packages."""
    app_stage = DOCKERFILE.split("FROM python:", 1)[1]
    arg = app_stage.index("ARG RAILWAY_GIT_COMMIT_SHA")
    apt = app_stage.index("RUN echo \"system packages for commit ${RAILWAY_GIT_COMMIT_SHA}\"")
    assert arg < apt
    step = app_stage[apt:app_stage.index("rm -rf /var/lib/apt/lists/*", apt)]
    assert "apt-get update" in step and "apt-get upgrade -y" in step
    assert step.index("apt-get upgrade") < step.index("apt-get install")
    assert "/etc/enhq-system-packages" in step and "still_upgradable=" in step


def test_dependabot_covers_python_the_frontend_and_the_base_images_against_dev():
    text = (ROOT / ".github" / "dependabot.yml").read_text()
    blocks = re.split(r"(?m)^  - package-ecosystem: ", text)[1:]
    by = {b.split("\n", 1)[0].strip('"'): b for b in blocks}
    assert set(by) == {"pip", "npm", "docker"}
    assert 'directory: "/frontend"' in by["npm"]
    for block in by.values():
        assert 'target-branch: "dev"' in block


def test_the_gate_audits_before_the_suites():
    gate = (ROOT / "scripts" / "gate.sh").read_text()
    audit = gate.index("scripts/dependency_audit.py")
    assert audit < gate.index('"${PYTEST[@]}"')
    assert 'fail "the dependency audit"' in gate
