"""Small external CLI checks; separate from the frozen 16-method acceptance suite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


TIMEOUT_SECONDS = 30
REQUIRED_HEADERS = ("order_id", "quantity", "unit_price")
VERIFICATION_ROOT = Path(__file__).resolve().parent


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_check(
    candidate: Path, evidence_dir: Path, name: str, omitted_header: str | None = None
) -> dict[str, object]:
    case_dir = evidence_dir / name
    case_dir.mkdir()
    input_path = case_dir / "input.csv"
    if name != "missing_input":
        headers = [field for field in REQUIRED_HEADERS if field != omitted_header]
        values = {"order_id": " AUDIT, A ", "quantity": "2", "unit_price": "3.50"}
        with input_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerow([values[field] for field in headers])
    input_before = digest(input_path)
    command = [
        sys.executable, "-B", str(candidate), "--input", str(input_path),
        "--output-dir", str(case_dir / "result"),
    ]
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    returncode = None
    stdout = b""
    stderr = b""
    execution_error = None
    try:
        completed = subprocess.run(
            command, cwd=case_dir, capture_output=True, timeout=TIMEOUT_SECONDS, check=False
        )
        returncode = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b"", error.stderr or b""
        execution_error = f"Timed out after {TIMEOUT_SECONDS} seconds"
    except OSError as error:
        execution_error = f"Unable to start candidate: {error}"
    elapsed = time.monotonic() - started
    input_after = digest(input_path)
    (case_dir / "stdout.txt").write_bytes(stdout)
    (case_dir / "stderr.txt").write_bytes(stderr)
    problems: list[str] = []
    if execution_error:
        problems.append(execution_error)
    elif name == "input_unchanged":
        if returncode != 0:
            problems.append(f"Valid input returned {returncode}, expected 0")
    else:
        if returncode == 0:
            problems.append("File-level error returned 0, expected nonzero")
        if not stderr.strip():
            problems.append("File-level error needs a diagnostic on stderr")
    if input_before != input_after:
        problems.append("Input content or existence changed during execution")
    result = {
        "name": name,
        "status": "failed" if problems else "passed",
        "command": command,
        "cwd": str(case_dir),
        "started_at_utc": started_at,
        "elapsed_seconds": round(elapsed, 6),
        "returncode": returncode,
        "timeout_seconds": TIMEOUT_SECONDS,
        "input_sha256_before": input_before,
        "input_sha256_after": input_after,
        "input_unchanged": input_before == input_after,
        "problems": problems,
    }
    write_json(case_dir / "invocation.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    evidence_dir = args.evidence_dir.resolve()
    if not candidate.is_file():
        parser.error(f"Candidate does not exist: {candidate}")
    if not evidence_dir.is_relative_to(VERIFICATION_ROOT) or evidence_dir == VERIFICATION_ROOT:
        parser.error("Evidence must be in a dedicated directory under verification/")
    if evidence_dir.exists():
        parser.error("Evidence directory already exists; choose a new directory")
    evidence_dir.mkdir(parents=True)
    candidate_before = digest(candidate)
    script_before = digest(Path(__file__))
    results = [run_check(candidate, evidence_dir, "missing_input")]
    for header in REQUIRED_HEADERS:
        results.append(run_check(candidate, evidence_dir, f"missing_{header}_header", header))
    results.append(run_check(candidate, evidence_dir, "input_unchanged"))
    candidate_after = digest(candidate)
    script_after = digest(Path(__file__))
    successful = (
        all(result["status"] == "passed" for result in results)
        and candidate_before == candidate_after
        and script_before == script_after
    )
    summary = {
        "producer": "external independent supplementary validation; not a SoduWork run",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "candidate": str(candidate),
        "candidate_sha256_before": candidate_before,
        "candidate_sha256_after": candidate_after,
        "check_script_sha256_before": script_before,
        "check_script_sha256_after": script_after,
        "checks_run": len(results),
        "passed_checks": sum(result["status"] == "passed" for result in results),
        "failed_checks": sum(result["status"] == "failed" for result in results),
        "successful": successful,
        "checks": results,
    }
    write_json(evidence_dir / "results.json", summary)
    print(json.dumps({key: summary[key] for key in (
        "checks_run", "passed_checks", "failed_checks", "successful"
    )}, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
