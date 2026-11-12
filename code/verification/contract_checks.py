"""Three additional SPEC-based examples, separate from the frozen acceptance suite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict


TIMEOUT_SECONDS = 30
ROOT = Path(__file__).resolve().parent
VALID_FIELDS = ["source_row", "order_id", "quantity", "line_total"]
REJECTED_FIELDS = ["source_row", "order_id", "quantity", "unit_price", "reason"]


class Case(TypedDict):
    name: str
    rows: list[list[str]]
    summary: dict[str, int | str]
    valid: list[list[str]]
    rejected: list[list[str]]


# Fixed, hand-checkable examples. They do not implement the candidate algorithm.
CASES: list[Case] = [
    {
        "name": "case_sensitive_ids",
        "rows": [["A", "1", "2.00"], ["a", "2", "3.00"]],
        "summary": {"records_total": 2, "valid_count": 2, "rejected_count": 0, "total_amount": "8.00"},
        "valid": [["2", "A", "1", "2.00"], ["3", "a", "2", "6.00"]],
        "rejected": [],
    },
    {
        "name": "preserve_trimmed_fields_and_order",
        "rows": [
            ["   KEEP   ", " 2 ", " 3.50 "],
            [" KEEP ", " 3 ", " 4.25 "],
            ["  BAD, A  ", " 2.5 ", " 7.00 "],
            ["  NEXT  ", " 3 ", " 2.00 "],
            ["  NEG  ", " -1 ", " 8.50 "],
        ],
        "summary": {"records_total": 5, "valid_count": 2, "rejected_count": 3, "total_amount": "13.00"},
        "valid": [["2", "KEEP", "2", "7.00"], ["5", "NEXT", "3", "6.00"]],
        "rejected": [
            ["3", "KEEP", "3", "4.25"],
            ["4", "BAD, A", "2.5", "7.00"],
            ["6", "NEG", "-1", "8.50"],
        ],
    },
    {
        "name": "decimal_just_below_half_cent",
        "rows": [["NEAR-HALF", "1", "1.004999999999999999999999999999"]],
        "summary": {"records_total": 1, "valid_count": 1, "rejected_count": 0, "total_amount": "1.00"},
        "valid": [["2", "NEAR-HALF", "1", "1.00"]],
        "rejected": [],
    },
]


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_case(candidate: Path, evidence_dir: Path, case: Case) -> dict[str, object]:
    case_dir = evidence_dir / case["name"]
    case_dir.mkdir()
    input_path = case_dir / "input.csv"
    with input_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["order_id", "quantity", "unit_price"])
        writer.writerows(case["rows"])
    write_json(case_dir / "expectations.json", case)
    before = digest(input_path)
    output_dir = case_dir / "result"
    command = [sys.executable, "-B", str(candidate), "--input", str(input_path), "--output-dir", str(output_dir)]
    started = datetime.now(timezone.utc).isoformat()
    stdout, stderr = b"", b""
    returncode = None
    problems: list[str] = []
    try:
        completed = subprocess.run(command, cwd=case_dir, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
        stdout, stderr = completed.stdout, completed.stderr
        returncode = completed.returncode
        if returncode != 0:
            problems.append(f"Expected exit 0; received {returncode}")
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b"", error.stderr or b""
        problems.append(f"Timed out after {TIMEOUT_SECONDS} seconds")
    except OSError as error:
        problems.append(f"Unable to start candidate: {error}")
    (case_dir / "stdout.txt").write_bytes(stdout)
    (case_dir / "stderr.txt").write_bytes(stderr)
    after = digest(input_path)
    if before != after:
        problems.append("Input content changed")
    observed: dict[str, object] = {}
    if returncode == 0:
        try:
            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8-sig"))
            with (output_dir / "valid_orders.csv").open(encoding="utf-8-sig", newline="") as stream:
                valid_table = list(csv.reader(stream))
            with (output_dir / "rejected_rows.csv").open(encoding="utf-8-sig", newline="") as stream:
                rejected_table = list(csv.reader(stream))
            observed = {"summary": summary, "valid_csv": valid_table, "rejected_csv": rejected_table}
            if summary != case["summary"]:
                problems.append("summary.json differs from the specified expected values")
            if valid_table != [VALID_FIELDS, *case["valid"]]:
                problems.append("Valid CSV fields, order or values differ from expectations")
            if not rejected_table or rejected_table[0] != REJECTED_FIELDS:
                problems.append("Rejected CSV header differs from SPEC")
            elif [row[:4] for row in rejected_table[1:]] != case["rejected"]:
                problems.append("Rejected CSV input fields, row numbers or order differ from expectations")
            if any(len(row) != len(REJECTED_FIELDS) or not row[-1].strip() for row in rejected_table[1:]):
                problems.append("Rejected CSV needs one nonempty reason per row")
        except (OSError, UnicodeError, ValueError, csv.Error) as error:
            problems.append(f"Unable to read required output: {error}")
    write_json(case_dir / "observed.json", observed)
    result = {
        "name": case["name"], "status": "failed" if problems else "passed",
        "command": command, "cwd": str(case_dir), "started_at_utc": started,
        "returncode": returncode, "timeout_seconds": TIMEOUT_SECONDS,
        "input_sha256_before": before, "input_sha256_after": after,
        "problems": problems,
    }
    write_json(case_dir / "invocation.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    candidate, evidence_dir = args.candidate.resolve(), args.evidence_dir.resolve()
    if not candidate.is_file():
        parser.error(f"Candidate does not exist: {candidate}")
    if not evidence_dir.is_relative_to(ROOT) or evidence_dir == ROOT:
        parser.error("Evidence must be in a dedicated directory under verification/")
    if evidence_dir.exists():
        parser.error("Evidence directory already exists; choose a new directory")
    evidence_dir.mkdir(parents=True)
    before = digest(candidate)
    script_before = digest(Path(__file__))
    results = [run_case(candidate, evidence_dir, case) for case in CASES]
    after = digest(candidate)
    script_after = digest(Path(__file__))
    successful = all(item["status"] == "passed" for item in results) and before == after and script_before == script_after
    summary = {
        "producer": "external independent SPEC coverage checks; not product self-tests",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "candidate": str(candidate), "candidate_sha256_before": before, "candidate_sha256_after": after,
        "check_script_sha256_before": script_before, "check_script_sha256_after": script_after,
        "checks_run": len(results), "passed_checks": sum(item["status"] == "passed" for item in results),
        "failed_checks": sum(item["status"] == "failed" for item in results), "successful": successful, "checks": results,
    }
    write_json(evidence_dir / "results.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
