"""Fail closed unless every documented final-release gate covers this exact commit."""

import argparse
import json
from pathlib import Path


def check(path: Path, commit: str) -> list[str]:
    report = json.loads(path.read_text())
    failures = []
    if report.get("commit_sha") != commit:
        failures.append("Evidence does not cover the requested commit")
    gates = report.get("gates", {})
    for name in "ABCDEFGHIJ":
        if gates.get(name, {}).get("status") != "PASS":
            failures.append(f"Gate {name}: {gates.get(name, {}).get('status', 'MISSING')}")
    if report.get("recommendation") != "READY_FOR_BETA":
        failures.append("Recommendation is not READY_FOR_BETA")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument(
        "--report", type=Path, default=Path("docs/release-evidence/stage9-gates.json")
    )
    args = parser.parse_args()
    errors = check(args.report, args.commit)
    if errors:
        raise SystemExit("Release blocked:\n" + "\n".join(errors))
    print("Every final release gate passes for this commit")
