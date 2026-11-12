"""Independent black-box acceptance tests for the fictional CSV order task.

The expected results below are fixed examples, not a second implementation of
the candidate's calculation algorithm. All candidate runs retain their evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


class OrderAcceptance(unittest.TestCase):
    candidate: Path
    evidence_dir: Path
    invocation_count = 0

    def run_case(
        self, rows: list[list[str]], *, bom: bool = False
    ) -> tuple[dict[str, object], list[dict[str, str]], list[dict[str, str]]]:
        cls = type(self)
        cls.invocation_count += 1
        case_dir = cls.evidence_dir / f"{cls.invocation_count:02d}-{self._testMethodName}"
        case_dir.mkdir(parents=True)
        input_path = case_dir / "input.csv"
        with input_path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["order_id", "quantity", "unit_price"])
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
        elapsed = time.monotonic() - started
        (case_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (case_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        (case_dir / "invocation.json").write_text(json.dumps({
            "command": command,
            "cwd": str(case_dir),
            "returncode": completed.returncode,
            "elapsed_seconds": round(elapsed, 6),
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(
            completed.returncode, 0,
            f"A row error must not abort the CSV run. Evidence: {case_dir}\n{completed.stderr}",
        )
        for filename in ("summary.json", "valid_orders.csv", "rejected_rows.csv"):
            self.assertTrue((output_dir / filename).is_file(), f"Missing output: {filename}")
        summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8-sig"))
        with (output_dir / "valid_orders.csv").open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, ["source_row", "order_id", "quantity", "line_total"])
            valid = list(reader)
        with (output_dir / "rejected_rows.csv").open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, ["source_row", "order_id", "quantity", "unit_price", "reason"])
            rejected = list(reader)
        for key in ("records_total", "valid_count", "rejected_count"):
            self.assertIs(type(summary[key]), int, f"{key} must be a JSON integer")
        self.assertIsInstance(summary["total_amount"], str)
        self.assertEqual(summary["records_total"], len(rows))
        self.assertEqual(summary["valid_count"], len(valid))
        self.assertEqual(summary["rejected_count"], len(rejected))
        self.assertEqual(len(valid) + len(rejected), len(rows))
        self.assertRegex(summary["total_amount"], r"^\d+\.\d{2}$")
        for record in valid:
            self.assertRegex(record["line_total"], r"^\d+\.\d{2}$")
        for record in rejected:
            self.assertTrue(record["reason"].strip(), "A rejected row needs an explanation")
        return summary, valid, rejected

    def assert_rejected(self, rows: list[list[str]]) -> None:
        summary, valid, rejected = self.run_case(rows)
        self.assertEqual(valid, [])
        self.assertEqual(len(rejected), len(rows))
        self.assertEqual(summary["total_amount"], "0.00")

    def test_01_normal_orders(self) -> None:
        summary, valid, rejected = self.run_case([["A", "2", "19.90"], ["B", "1", "5.25"]])
        self.assertEqual(summary["total_amount"], "45.05")
        self.assertEqual([row["line_total"] for row in valid], ["39.80", "5.25"])
        self.assertEqual(rejected, [])

    def test_02_utf8_bom(self) -> None:
        summary, valid, _ = self.run_case([["虚构订单甲", "2", "3.25"]], bom=True)
        self.assertEqual(summary["total_amount"], "6.50")
        self.assertEqual(valid[0]["order_id"], "虚构订单甲")

    def test_03_zero_price_is_valid(self) -> None:
        summary, valid, rejected = self.run_case([["GIFT", "3", "0"]])
        self.assertEqual(len(valid), 1)
        self.assertEqual(rejected, [])
        self.assertEqual(summary["total_amount"], "0.00")

    def test_04_zero_quantity_is_valid(self) -> None:
        summary, valid, rejected = self.run_case([["ZERO-QTY", "0", "9.90"]])
        self.assertEqual(len(valid), 1)
        self.assertEqual(rejected, [])
        self.assertEqual(summary["total_amount"], "0.00")

    def test_05_whitespace_and_quoted_comma(self) -> None:
        summary, valid, _ = self.run_case([["  DEMO, A  ", " 2 ", " 3.50 "]])
        self.assertEqual(summary["total_amount"], "7.00")
        self.assertEqual(valid[0]["order_id"], "DEMO, A")

    def test_06_empty_required_fields(self) -> None:
        for field in range(3):
            with self.subTest(field=field):
                row = ["A", "1", "9.90"]
                row[field] = "  "
                self.assert_rejected([row])

    def test_07_invalid_quantity(self) -> None:
        for quantity in ("two", "2.5"):
            with self.subTest(quantity=quantity):
                self.assert_rejected([["A", quantity, "9.90"]])

    def test_08_nonnumeric_price(self) -> None:
        self.assert_rejected([["A", "1", "free"]])

    def test_09_nonfinite_price(self) -> None:
        self.assert_rejected([
            ["A", "1", "NaN"], ["B", "1", "Infinity"], ["C", "1", "-Infinity"],
        ])

    def test_10_negative_quantity(self) -> None:
        self.assert_rejected([["A", "-1", "9.90"]])

    def test_11_negative_price(self) -> None:
        self.assert_rejected([["A", "1", "-0.01"]])

    def test_12_duplicate_id_preserves_first_valid_record(self) -> None:
        summary, valid, rejected = self.run_case([["DUP", "2", "3.50"], [" DUP ", "1", "99"]])
        self.assertEqual(summary["total_amount"], "7.00")
        self.assertEqual(len(valid), 1)
        self.assertEqual(rejected[0]["source_row"], "3")
        self.assertEqual(rejected[0]["order_id"], "DUP")

    def test_13_decimal_half_up(self) -> None:
        summary, valid, _ = self.run_case([["A", "3", "0.335"], ["B", "1", "2.675"]])
        self.assertEqual([row["line_total"] for row in valid], ["1.01", "2.68"])
        self.assertEqual(summary["total_amount"], "3.69")

    def test_14_sum_rounded_line_amounts(self) -> None:
        summary, valid, _ = self.run_case([
            ["A", "1", "0.005"], ["B", "1", "0.005"], ["C", "1", "0.005"],
        ])
        self.assertEqual([row["line_total"] for row in valid], ["0.01", "0.01", "0.01"])
        self.assertEqual(summary["total_amount"], "0.03")

    def test_15_continue_after_invalid_row_and_do_not_reserve_invalid_id(self) -> None:
        summary, valid, rejected = self.run_case([
            ["A", "1", "4.50"],
            ["RETRY", "not-a-number", "2.00"],
            ["RETRY", "3", "2.00"],
            ["B", "1", "1.25"],
        ])
        self.assertEqual(summary["total_amount"], "11.75")
        self.assertEqual([row["order_id"] for row in valid], ["A", "RETRY", "B"])
        self.assertEqual([row["source_row"] for row in valid], ["2", "4", "5"])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["source_row"], "3")

    def test_16_header_only_csv(self) -> None:
        summary, valid, rejected = self.run_case([])
        self.assertEqual(summary, {
            "records_total": 0, "valid_count": 0, "rejected_count": 0, "total_amount": "0.00",
        })
        self.assertEqual(valid, [])
        self.assertEqual(rejected, [])


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

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase, err: tuple | None) -> None:
        if err is not None:
            self.statuses[test.id()] = "failed"
        super().addSubTest(test, subtest, err)


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
    OrderAcceptance.candidate = candidate
    OrderAcceptance.evidence_dir = evidence_dir
    OrderAcceptance.invocation_count = 0
    log = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OrderAcceptance)
    result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=RecordedResult).run(suite)
    transcript = log.getvalue()
    print(transcript, end="")
    (evidence_dir / "unittest.txt").write_text(transcript, encoding="utf-8")
    metadata = {
        "producer": "external fixture preparation / independent validation; not a SoduWork run",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": str(candidate),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "acceptance_test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "test_methods_run": result.testsRun,
        "passed_test_methods": sum(status == "passed" for status in result.statuses.values()),
        "failed_or_errored_test_methods": sum(status in ("failed", "error") for status in result.statuses.values()),
        "candidate_invocations": OrderAcceptance.invocation_count,
        "successful": result.wasSuccessful(),
        "tests": result.statuses,
    }
    (evidence_dir / "results.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
