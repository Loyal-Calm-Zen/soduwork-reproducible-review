"""Run the packaged checks in a new directory, without rewriting historical evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SUITE_TIMEOUT_SECONDS = 660
EXPECTED_SAMPLE = {
    "records_total": 8, "valid_count": 4, "rejected_count": 4, "total_amount": "57.31"
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def invoke(command: list[str], directory: Path, label: str) -> dict[str, object]:
    record: dict[str, object] = {
        "command": command, "cwd": str(directory),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "timeout_seconds": SUITE_TIMEOUT_SECONDS, "returncode": None,
    }
    stdout, stderr = b"", b""
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True,
                                timeout=SUITE_TIMEOUT_SECONDS, check=False)
        stdout, stderr = result.stdout, result.stderr
        record["returncode"] = result.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b"", error.stderr or b""
        record["error"] = "Suite timeout; partial output retained"
    except OSError as error:
        record["error"] = str(error)
    (directory / f"{label}-stdout.txt").write_bytes(stdout)
    (directory / f"{label}-stderr.txt").write_bytes(stderr)
    write_json(directory / f"{label}-invocation.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--run-name", default=datetime.now(timezone.utc).strftime("reader-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", args.run_name):
        parser.error("run name must be a simple filename, up to 80 ASCII characters")
    code = args.code_dir.resolve()
    candidate = code / "candidate.py"
    sample = code / "sample_orders.csv"
    checks = {
        "acceptance": code / "acceptance_tests.py",
        "supplemental": code / "verification/supplemental_checks.py",
        "contract-checks": code / "verification/contract_checks.py",
    }
    product_regression = code / "near_half_regression.py"
    if product_regression.is_file():
        checks["product-regression"] = product_regression
    inputs = [candidate, sample, code / "SPEC.md", code / "starter.py", *checks.values()]
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        parser.error("Missing packaged files: " + ", ".join(missing))
    run = code / "verification/reader-runs" / args.run_name
    if run.exists():
        parser.error("Run directory exists; choose a new name. No existing result was changed.")
    run.mkdir(parents=True)
    before = {str(path.relative_to(code)): digest(path) for path in inputs}
    records = {}
    for label, script in checks.items():
        command = [sys.executable, "-B", str(script), "--candidate", str(candidate),
                   "--evidence-dir", str(run / label)]
        records[label] = invoke(command, run, label)
    records["sample"] = invoke(
        [sys.executable, "-B", str(candidate), "--input", str(sample),
         "--output-dir", str(run / "sample")], run, "sample")
    problems: list[str] = []
    summary_paths = {name: run / name / "results.json" for name in checks}
    expected_counts = {"acceptance": ("test_methods_run", 16),
                       "supplemental": ("checks_run", 5), "contract-checks": ("checks_run", 3),
                       "product-regression": ("test_methods_run", 5)}
    suite_summaries = {}
    for name, path in summary_paths.items():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            suite_summaries[name] = value
            field, count = expected_counts[name]
            if value.get(field) != count or value.get("successful") is not True:
                problems.append(f"{name}: expected {count} checks and successful=true; inspect raw results")
        except (OSError, ValueError) as error:
            problems.append(f"{name}: unavailable results: {error}")
    try:
        observed_sample = json.loads((run / "sample/summary.json").read_text(encoding="utf-8"))
        if observed_sample != EXPECTED_SAMPLE:
            problems.append("sample summary differs from the frozen expected values")
    except (OSError, ValueError) as error:
        observed_sample = None
        problems.append(f"sample summary unavailable: {error}")
    after = {str(path.relative_to(code)): digest(path) for path in inputs if path.is_file()}
    if before != after:
        problems.append("One or more packaged input/code/check files changed during execution")
    for name, record in records.items():
        if record["returncode"] != 0:
            problems.append(f"{name}: command exit was {record['returncode']}")
    report = {
        "producer": "reader-side reproduction outside SoduWork; not historical product execution",
        "python": platform.python_version(), "platform": platform.platform(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": before["candidate.py"], "inputs_before": before, "inputs_after": after,
        "commands": records, "suite_results": suite_summaries,
        "suite_origins": {
            "acceptance": "author-prepared frozen 16-method suite",
            "supplemental": "external verifier's 5 supplementary checks",
            "contract-checks": "external verifier's 3 SPEC coverage checks",
            "product-regression": "5 methods added by SoduWork during repair; run only when packaged",
        },
        "optional_product_regression_present": "product-regression" in checks,
        "sample_observed": observed_sample, "sample_expected": EXPECTED_SAMPLE,
        "successful": not problems, "problems": problems,
        "count_note": "16 original methods, 5 external supplementary checks, 3 external contract checks and optional 5 product-added regression methods are separate sets; no aggregate coverage claim",
    }
    write_json(run / "reproduction.json", report)
    print(json.dumps({"report": str(run / "reproduction.json"), "successful": not problems,
                      "problems": problems}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
