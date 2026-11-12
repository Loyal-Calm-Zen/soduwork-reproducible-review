"""Fictional CSV order tool with deliberately seeded evaluation defects.

This is an intentionally imperfect starting point, not a reference solution.
See README.md for the disclosed defect classes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path


REQUIRED_FIELDS = ("order_id", "quantity", "unit_price")
VALID_FIELDS = ("source_row", "order_id", "quantity", "line_total")
REJECTED_FIELDS = (*REQUIRED_FIELDS, "reason")


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(input_path: Path, output_dir: Path) -> None:
    valid: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    seen: set[str] = set()
    total = 0.0
    records_total = 0

    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(REQUIRED_FIELDS).issubset(reader.fieldnames):
            raise ValueError("CSV is missing required headers: order_id,quantity,unit_price")

        for source_row, raw in enumerate(reader, start=2):
            records_total += 1
            fields = {name: (raw.get(name) or "").strip() for name in REQUIRED_FIELDS}
            quantity = int(fields["quantity"])
            price = float(fields["unit_price"])
            try:
                if not all(fields.values()):
                    raise ValueError("required field is empty")
                if quantity < 0:
                    raise ValueError("quantity must not be negative")
                if not math.isfinite(price) or price < 0:
                    raise ValueError("unit_price must be finite and nonnegative")
                if not price:
                    raise ValueError("unit_price is missing")
                if fields["order_id"] in seen:
                    raise ValueError("duplicate order_id")
            except ValueError as error:
                rejected.append({"source_row": source_row, **fields, "reason": str(error)})
                continue

            seen.add(fields["order_id"])
            line_total = round(quantity * price, 2)
            total += line_total
            valid.append({
                "source_row": source_row,
                "order_id": fields["order_id"],
                "quantity": quantity,
                "line_total": f"{line_total:.2f}",
            })

    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "records_total": records_total,
        "valid_count": len(valid),
        "rejected_count": len(rejected),
        "total_amount": f"{total:.2f}",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(output_dir / "valid_orders.csv", VALID_FIELDS, valid)
    write_csv(output_dir / "rejected_rows.csv", ("source_row", *REJECTED_FIELDS), rejected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        summarize(args.input, args.output_dir)
    except (OSError, ValueError, csv.Error) as error:
        print(f"order audit failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
