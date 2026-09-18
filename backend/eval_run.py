"""Live eval scoreboard — POST /eval/run (M6, Phase 8 demo close).

Runs the pytest suite in a subprocess with TEAMGEN_OFFLINE=1 (deterministic,
no network) and returns pass/fail counts. Tests use isolated scopes/users, so
running the suite against the live DB is side-effect-safe by design.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_eval(timeout: int = 300) -> dict:
    env = dict(os.environ, TEAMGEN_OFFLINE="1")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line",
             "-p", "no:warnings"],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env,
        )
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-8:]
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": 0, "total": 0, "status": "timeout",
                "output": ["eval timed out"]}
    except Exception as e:
        return {"passed": 0, "failed": 0, "total": 0, "status": f"error: {e}",
                "output": []}
    m = None
    for line in reversed(tail):
        m = re.search(r"(\d+) passed(?:, (\d+) failed)?", line)
        if m:
            break
    passed = int(m.group(1)) if m else 0
    failed = int(m.group(2) or 0) if m else 0
    return {"passed": passed, "failed": failed, "total": passed + failed,
            "status": "green" if m and failed == 0 and passed else "red",
            "output": tail}
