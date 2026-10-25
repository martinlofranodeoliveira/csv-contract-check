"""Run a clean project copy read-only in bubblewrap; never install anything."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


def source_hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("staged source must not contain symlinks")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def sandbox_command(root, bwrap):
    command = [bwrap, "--die-with-parent", "--unshare-all", "--new-session", "--clearenv", "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr"]
    for name in ("/bin", "/lib", "/lib64"):
        path = Path(name)
        if path.is_symlink():
            command.extend(("--symlink", str(path.readlink()), name))
        elif path.exists():
            command.extend(("--ro-bind", name, name))
    command.extend(("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/home", "--dir", "/home/sandbox"))
    for key, value in {
        "HOME": "/home/sandbox", "PATH": "/usr/bin", "LC_ALL": "C.UTF-8",
        "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
    }.items():
        command.extend(("--setenv", key, value))
    command.extend(("--ro-bind", str(root), "/project", "--chdir", "/project", "/usr/bin/python3", "-B"))
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="clean staged project directory, without .git or .venv")
    parser.add_argument("--bwrap", default=shutil.which("bwrap"), help="bubblewrap executable")
    parser.add_argument("--allow-github-sudo", action="store_true", help="namespace fallback only on a GitHub-hosted ephemeral runner")
    args = parser.parse_args()
    root = args.source.resolve()
    if not sys.platform.startswith("linux") or not args.bwrap:
        parser.error("Linux with bubblewrap is required; no tools are installed by this script")
    if not root.is_dir() or any((root / name).exists() for name in (".git", ".venv")):
        parser.error("source must be a clean staged directory without .git or .venv")
    if args.allow_github_sudo and not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    ):
        parser.error("sudo fallback is restricted to an ephemeral GitHub-hosted runner")
    before = source_hashes(root)
    command = sandbox_command(root, str(Path(args.bwrap).resolve()))
    environment = {"PATH": "/usr/bin:/bin"}
    preflight = subprocess.run(command + ["-c", "pass"], env=environment, capture_output=True, text=True, timeout=15)
    if preflight.returncode:
        detail = preflight.stderr.lower()
        if args.allow_github_sudo and ("namespace" in detail or "operation not permitted" in detail):
            print("Unprivileged namespace creation was blocked; using sudo only for bubblewrap on this ephemeral GitHub runner.", flush=True)
            command = ["/usr/bin/sudo", "-n", "--", *command]
        else:
            sys.stderr.write(preflight.stderr)
            return preflight.returncode
    print(f"Source SHA-256 before: {hashlib.sha256(repr(before).encode()).hexdigest()} ({len(before)} files)", flush=True)
    result = subprocess.run(command + ["scripts/run_isolated_suite.py"], env=environment, timeout=60, check=False)
    after = source_hashes(root)
    if before != after:
        raise SystemExit("FAIL: source hashes changed during sandbox tests")
    print(f"Source SHA-256 after:  {hashlib.sha256(repr(after).encode()).hexdigest()} (unchanged)", flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
