"""Supplementary regression test for the human-returned near-half defect.

Standalone, additive only: the original acceptance_tests.py is untouched and
still covers its own 16 methods. Run with:

    python3 near_half_regression.py --candidate candidate.py --evidence-dir evidence/near-half-regression

Exit code 0 on pass, 1 on failure. Every invocation keeps its own evidence:
input.csv, stdout.txt, stderr.txt, invocation.json, result/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

HEADER = ["order_id", "quantity", "unit_price"]


class NearHalfRegression(unittest.TestCase):
    candidate: Path
    evidence_dir: Path
    invocation_count = 0

    def run_case(self, rows: list[list[str]], label: str) -> dict[str, object]:
        cls = type(self)
        cls.invocation_count += 1
        case_dir = cls.evidence_dir / f"{cls.invocation_count:02d}-{label}"
        case_dir.mkdir(parents=True)
        input_path = case_dir / "input.csv"
        with input_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            writer.writerows(rows)
        output_dir = case_dir / "result"
        command = [
            sys.executable, str(cls.candidate),
            "--input", str(input_path), "--output-dir", str(output_dir),
        ]
        started = time.monotonic()
        completed = subprocess.run(
            command, cwd=case_dir, capture_output=True, text=True,
            encoding="utf-8", timeout=30, check=False,
        )
        (case_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (case_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        (case_dir / "invocation.json").write_text(json.dumps({
            "command": command,
            "cwd": str(case_dir),
            "returncode": completed.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 6),
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(
            completed.returncode, 0,
            f"run must succeed. Evidence: {case_dir}\n{completed.stderr}",
        )
        self.assertTrue((output_dir / "summary.json").is_file())
        summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8-sig"))
        with (output_dir / "valid_orders.csv").open(encoding="utf-8-sig", newline="") as stream:
            valid = list(csv.DictReader(stream))
        with (output_dir / "rejected_rows.csv").open(encoding="utf-8-sig", newline="") as stream:
            rejected = list(csv.DictReader(stream))
        return {"summary": summary, "valid": valid, "rejected": rejected}

    def test_01_returned_counterexample(self) -> None:
        """The exact row from the human review: 1.004999... must round DOWN to 1.00."""
        outcome = self.run_case(
            [["NEAR-HALF", "1", "1.004999999999999999999999999999"]],
            "returned-counterexample",
        )
        self.assertEqual(outcome["valid"][0]["line_total"], "1.00")
        self.assertEqual(outcome["summary"]["total_amount"], "1.00")
        self.assertIs(type(outcome["summary"]["total_amount"]), str)
        self.assertEqual(outcome["rejected"], [])

    def test_02_genuine_half_still_rounds_up(self) -> None:
        """A true half must not regress while fixing the near-half case."""
        outcome = self.run_case(
            [["HALF", "1", "1.005"], ["HALF-2", "1", "0.005"], ["HALF-3", "3", "0.335"]],
            "genuine-half",
        )
        self.assertEqual(
            [row["line_total"] for row in outcome["valid"]], ["1.01", "0.01", "1.01"]
        )
        self.assertEqual(outcome["summary"]["total_amount"], "2.03")

    def test_03_just_below_half_long_fraction(self) -> None:
        outcome = self.run_case(
            [
                ["P1", "1", "1.00499999999999999999999999999"],
                ["P2", "7", "0.142857142857142857142857142857"],
                ["P3", "1", "2.674999999999999999999999999999"],
            ],
            "off-half-variants",
        )
        self.assertEqual(
            [row["line_total"] for row in outcome["valid"]], ["1.00", "1.00", "2.67"]
        )
        self.assertEqual(outcome["summary"]["total_amount"], "4.67")

    def test_04_large_quantity_high_precision(self) -> None:
        """Multiplication must stay exact for big ints and long decimals."""
        outcome = self.run_case(
            [["BIG", "999999999999", "0.004999999999999999999999999"]],
            "large-quantity",
        )
        self.assertEqual(outcome["valid"][0]["line_total"], "4999999999.99")
        self.assertEqual(outcome["summary"]["total_amount"], "4999999999.99")

    def test_05_mixed_with_invalid_rows_still_continues(self) -> None:
        outcome = self.run_case(
            [
                ["NEAR-HALF", "1", "1.004999999999999999999999999999"],
                ["BAD-Q", "x", "1.00"],
                ["NEAR-HALF", "2", "1.00"],
                ["NAN", "1", "NaN"],
            ],
            "mixed-invalid",
        )
        self.assertEqual(len(outcome["valid"]), 1)
        self.assertEqual(len(outcome["rejected"]), 3)
        self.assertEqual(outcome["summary"]["records_total"], 4)
        self.assertEqual(outcome["summary"]["total_amount"], "1.00")


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.statuses: dict[str, str] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        self.statuses[test.id()] = "running"
        super().startTest(test)

    def addSuccess(self, test: unittest.TestCase) -> None:
        self.statuses[test.id()] = "passed"
        super().addSuccess(test)

    def addFailure(self, test: unittest.TestCase, err: tuple) -> None:
        self.statuses[test.id()] = "failed"
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err: tuple) -> None:
        self.statuses[test.id()] = "error"
        super().addError(test, err)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    evidence_dir = args.evidence_dir.resolve()
    if not candidate.is_file():
        parser.error(f"candidate does not exist: {candidate}")
    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        parser.error("evidence directory must be new or empty; existing evidence is not overwritten")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    NearHalfRegression.candidate = candidate
    NearHalfRegression.evidence_dir = evidence_dir
    NearHalfRegression.invocation_count = 0
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NearHalfRegression)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
    metadata = {
        "purpose": "supplementary regression for human-returned near-half defect",
        "candidate": str(candidate),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "test_methods_run": result.testsRun,
        "passed_test_methods": sum(s == "passed" for s in result.statuses.values()),
        "candidate_invocations": NearHalfRegression.invocation_count,
        "successful": result.wasSuccessful(),
        "tests": result.statuses,
    }
    (evidence_dir / "results.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
