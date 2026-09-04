#!/usr/bin/env python3
"""Exercise the shared confirmation helper and kindnet entry point under POSIX sh."""

from __future__ import annotations

import json
import os
import pathlib
import shlex
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLUSTER_COMMON = ROOT / "scripts/lib/cluster-common.sh"
RECOVERY = ROOT / "scripts/kindnet-policy-recover.sh"
IMAGE = "docker.io/kindest/kindnetd:v20251212-v0.29.0-alpha-105-g20ccfc88"
IMAGE_ID = "sha256:" + "1" * 64
NODES = (
    "platform-engineering-lab-control-plane",
    "platform-engineering-lab-worker",
    "platform-engineering-lab-worker2",
)
UIDS = ("uid-control-plane", "uid-worker", "uid-worker2")
EXPECTED = "kind-platform-engineering-lab/kindnet/ds-uid/" + ",".join(UIDS)


def fixture():
    daemonset = {
        "metadata": {"name": "kindnet", "namespace": "kube-system", "uid": "ds-uid", "generation": 1},
        "spec": {
            "selector": {"matchLabels": {"app": "kindnet"}},
            "template": {
                "metadata": {"labels": {"app": "kindnet", "k8s-app": "kindnet", "tier": "node"}},
                "spec": {"containers": [{"image": IMAGE}]},
            },
        },
        "status": {"desiredNumberScheduled": 3, "currentNumberScheduled": 3, "numberReady": 3},
    }
    pods = []
    for index, (node, uid) in enumerate(zip(NODES, UIDS)):
        pods.append({
            "metadata": {
                "name": f"kindnet-{index}", "uid": uid,
                "labels": {"app": "kindnet", "k8s-app": "kindnet", "tier": "node"},
                "ownerReferences": [{
                    "apiVersion": "apps/v1", "kind": "DaemonSet", "name": "kindnet",
                    "uid": "ds-uid", "controller": True,
                }],
            },
            "spec": {"nodeName": node, "containers": [{"image": IMAGE}]},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "image": IMAGE, "imageID": IMAGE_ID, "ready": True, "restartCount": 0,
                }],
            },
        })
    return daemonset, {"items": pods}


def pty_run(command: list[str], value: str | None, environment: dict[str, str]) -> subprocess.CompletedProcess:
    shell_command = " ".join(shlex.quote(item) for item in command)
    supplied = None if value is None else (value + "\n")
    return subprocess.run(
        ["script", "-qefc", shell_command, "/dev/null"], input=supplied,
        text=True, capture_output=True, env=environment, check=False, timeout=15,
    )


def callers_load_shared_helper(helper_text: str) -> bool:
    if "confirm_exact()" not in helper_text:
        return False
    for path in sorted((ROOT / "scripts").glob("*.sh")):
        if not os.access(path, os.X_OK):
            continue
        content = path.read_text(encoding="utf-8")
        if "confirm_exact " in content and '. "$SCRIPT_DIR/lib/cluster-common.sh"' not in content:
            return False
    return True


def main() -> None:
    if not pathlib.Path("/bin/sh").exists() or not shutil_which("script"):
        raise SystemExit("POSIX /bin/sh and util-linux script are required for confirmation tests")
    helper = CLUSTER_COMMON.read_text(encoding="utf-8")
    assert callers_load_shared_helper(helper)
    assert not callers_load_shared_helper(helper.replace("confirm_exact()", "removed_helper()", 1))
    assert "confirm_exact()" not in (ROOT / "scripts/lib/app-common.sh").read_text(encoding="utf-8")
    assert "IFS= read -r confirmation" in helper and '[ -n "$expected" ]' in helper

    with tempfile.TemporaryDirectory(prefix="confirmation-entrypoint-") as directory:
        temporary = pathlib.Path(directory)
        direct = temporary / "application-confirmation.sh"
        direct.write_text(
            "#!/bin/sh\nset -eu\n"
            f". {shlex.quote(str(CLUSTER_COMMON))}\n"
            f". {shlex.quote(str(ROOT / 'scripts/lib/app-common.sh'))}\n"
            "confirm_exact application-confirmation 'Application confirmation fixture.'\n"
            "printf 'confirmed\\n'\n",
            encoding="utf-8",
        )
        direct.chmod(0o755)
        environment = dict(os.environ)
        for supplied in ("", "application", " application-confirmation", "application-confirmation ",
                         "application-confirmation-extra", "stale-confirmation"):
            result = pty_run(["/bin/sh", str(direct)], supplied, environment)
            assert result.returncode != 0 and "confirmed" not in result.stdout
        eof = pty_run(["/bin/sh", str(direct)], None, environment)
        assert eof.returncode != 0 and "confirmed" not in eof.stdout
        exact = pty_run(["/bin/sh", str(direct)], "application-confirmation", environment)
        assert exact.returncode == 0 and "confirmed" in exact.stdout

        daemonset, pods = fixture()
        (temporary / "daemonset.json").write_text(json.dumps(daemonset), encoding="utf-8")
        (temporary / "pods.json").write_text(json.dumps(pods), encoding="utf-8")
        for pod in pods["items"]:
            (temporary / f"{pod['metadata']['name']}.json").write_text(json.dumps(pod), encoding="utf-8")
        delete_log = temporary / "delete.log"
        mock_bin = temporary / "bin"
        mock_bin.mkdir()
        kubectl = mock_bin / "kubectl"
        kubectl.write_text(
            """#!/bin/sh
set -eu
case " $* " in
  *" config current-context "*) printf '%s\n' kind-platform-engineering-lab ;;
  *" get daemonset kindnet -n kube-system -o json "*) cat "$MOCK_ROOT/daemonset.json" ;;
  *" get pods -n kube-system -l app=kindnet -o json "*) cat "$MOCK_ROOT/pods.json" ;;
  *" logs -n kube-system -l app=kindnet "*) printf '%s\n' 'kindnet watcher healthy' ;;
  *" get pod "*)
    previous=''
    for token in "$@"; do
      if [ "$previous" = pod ]; then cat "$MOCK_ROOT/$token.json"; exit 0; fi
      previous=$token
    done
    exit 2 ;;
  *" logs kindnet-"*) printf '%s\n' 'kindnet watcher healthy' ;;
  *" describe pod kindnet-"*) printf '%s\n' 'mock description' ;;
  *" get events "*) printf '%s\n' '{"items":[]}' ;;
  *" delete pod "*) printf '%s\n' "$*" >>"$MOCK_DELETE_LOG"; printf '%s\n' 'mock delete stopped' >&2; exit 1 ;;
  *) printf 'unsupported kubectl fixture: %s\n' "$*" >&2; exit 2 ;;
esac
""",
            encoding="utf-8",
        )
        kubectl.chmod(0o755)
        environment.update({
            "PATH": str(mock_bin) + os.pathsep + environment["PATH"],
            "MOCK_ROOT": str(temporary), "MOCK_DELETE_LOG": str(delete_log),
        })
        for supplied in ("wrong", EXPECTED + " "):
            delete_log.unlink(missing_ok=True)
            result = pty_run(["/bin/sh", str(RECOVERY)], supplied, environment)
            assert result.returncode != 0 and not delete_log.exists()
            assert f"Required confirmation: {EXPECTED}" in result.stdout.replace("\r", "")
        delete_log.unlink(missing_ok=True)
        result = pty_run(["/bin/sh", str(RECOVERY)], None, environment)
        assert result.returncode != 0 and not delete_log.exists()
        delete_log.unlink(missing_ok=True)
        result = pty_run(["/bin/sh", str(RECOVERY)], EXPECTED, environment)
        assert result.returncode != 0 and delete_log.is_file()
        assert len(delete_log.read_text(encoding="utf-8").splitlines()) == 1
        uninterrupted = [line for line in result.stdout.replace("\r", "").splitlines() if line.startswith("Required confirmation:")]
        assert uninterrupted == [f"Required confirmation: {EXPECTED}"]

    recovery = RECOVERY.read_text(encoding="utf-8")
    assert recovery.index("validate-kindnet-recovery.py\" preflight") < recovery.index('confirm_exact "$kpr_confirmation"')
    assert recovery.index('confirm_exact "$kpr_confirmation"') < recovery.index("cleanup-kubernetes-resource.py")
    print("PASS  shared POSIX confirmation rejects empty, EOF, whitespace, partial, extra, and stale input before deletion.")
    print("PASS  exact kindnet confirmation reaches the mocked post-confirmation path and every executable caller loads the helper.")


def shutil_which(command: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = pathlib.Path(directory) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    main()
