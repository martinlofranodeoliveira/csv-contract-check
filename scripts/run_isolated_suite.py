"""Probe the Linux sandbox, then run the tests inside it. Use test_isolated.py."""

import errno
import os
from pathlib import Path
import socket
import sys
import unittest


ROOT = Path("/project")


def main():
    if Path(__file__).resolve().parents[1] != ROOT:
        raise SystemExit("Run scripts/test_isolated.py; this probe only runs at /project.")
    expected_environment = {
        "HOME", "PATH", "PWD", "LC_ALL", "PYTHONUTF8", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE",
    }
    assert set(os.environ) == expected_environment, "unexpected inherited environment"
    assert os.environ["PWD"] == "/project", "unexpected working directory"
    assert set(Path("/home").iterdir()) == {Path("/home/sandbox")}, "host home visible"
    assert not list(Path("/home/sandbox").iterdir()), "home is not empty"
    assert not any(Path(name).exists() for name in ("/root", "/run", "/etc")), "host files visible"
    assert {name for _, name in socket.if_nameindex()} == {"lo"}, "external network interface"
    assert len(Path("/proc/net/route").read_text().splitlines()) == 1, "network route present"
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    for name in ("CapEff", "CapPrm", "CapInh", "CapBnd", "CapAmb"):
        assert int(status[name].strip(), 16) == 0, f"{name} is not zero"
    assert status["NoNewPrivs"].strip() == "1", "NoNewPrivs is disabled"
    probe = ROOT / ".isolation-write-probe"
    try:
        descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as error:
        assert error.errno == errno.EROFS, f"unexpected write failure: {error}"
    else:
        os.close(descriptor)
        probe.unlink()
        raise AssertionError("source is writable")
    print("Isolation verified: source=read-only; home=empty; environment=clean; network=loopback-only; capabilities=0; NoNewPrivs=1", flush=True)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
