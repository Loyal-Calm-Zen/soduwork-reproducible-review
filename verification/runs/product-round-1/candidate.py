"""Fictional CSV order summariser (repaired implementation).

Repaired from starter.py against SPEC.md. Stdlib only. All amounts are handled
with decimal.Decimal and ROUND_HALF_UP; float is never used.

Usage:
    python3 candidate.py --input sample_orders.csv --output-dir result
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

REQUIRED_FIELDS = ("order_id", "quantity", "unit_price")
VALID_FIELDS = ("source_row", "order_id", "quantity", "line_total")
REJECTED_FIELDS = ("source_row", "order_id", "quantity", "unit_price", "reason")

CENT = Decimal("0.01")
ZERO = Decimal("0.00")

# quantity: non-negative integer written in decimal digits (no sign, no dot,
# no exponent). Leading zeros are tolerated ("007" -> 7).
QUANTITY_RE = re.compile(r"^[0-9]+$")
# unit_price: plain decimal notation, optional fraction, optional exponent.
# Deliberately excludes "NaN"/"Infinity"/"-Infinity" by shape, and the
# finiteness check below is a second safety net.
PRICE_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")


class FileLevelError(Exception):
    """Raised for file-level problems: missing input, bad header, unreadable CSV."""


def _clean(value: object) -> str:
    """Return a stripped string for a raw CSV cell (None becomes "")."""
    if value is None:
        return ""
    if isinstance(value, list):  # csv.DictReader uses a list for surplus cells
        return ",".join(str(part) for part in value).strip()
    return str(value).strip()


def parse_quantity(raw: str) -> int:
    if not raw:
        raise ValueError("quantity is empty")
    if not QUANTITY_RE.match(raw):
        raise ValueError(f"quantity is not a non-negative integer: {raw!r}")
    return int(raw)


def parse_price(raw: str) -> Decimal:
    if not raw:
        raise ValueError("unit_price is empty")
    if not PRICE_RE.match(raw):
        raise ValueError(f"unit_price is not a finite non-negative decimal: {raw!r}")
    try:
        price = Decimal(raw)
    except InvalidOperation as error:  # pragma: no cover - guarded by PRICE_RE
        raise ValueError(f"unit_price is not a decimal: {raw!r}") from error
    if not price.is_finite():
        raise ValueError(f"unit_price is not finite: {raw!r}")
    if price < 0:
        raise ValueError(f"unit_price is negative: {raw!r}")
    return price


def round_money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row[name] for name in fields})


def summarize(input_path: Path, output_dir: Path) -> dict[str, object]:
    valid: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    seen: set[str] = set()
    total = ZERO
    records_total = 0

    if not input_path.exists():
        raise FileLevelError(f"input file not found: {input_path}")
    if not input_path.is_file():
        raise FileLevelError(f"input path is not a regular file: {input_path}")

    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            header = reader.fieldnames
            if header is None:
                raise FileLevelError(
                    "CSV has no header row; expected columns: order_id,quantity,unit_price"
                )
            normalized = [name.strip().lstrip("\ufeff") for name in header]
            missing = [name for name in REQUIRED_FIELDS if name not in normalized]
            if missing:
                raise FileLevelError(
                    "CSV is missing required headers: " + ",".join(missing)
                    + f" (found: {','.join(header)})"
                )
            reader.fieldnames = normalized

            for source_row, raw in enumerate(reader, start=2):
                records_total += 1
                fields = {name: _clean(raw.get(name)) for name in REQUIRED_FIELDS}
                try:
                    if not fields["order_id"]:
                        raise ValueError("order_id is empty")
                    if not fields["quantity"]:
                        raise ValueError("quantity is empty")
                    if not fields["unit_price"]:
                        raise ValueError("unit_price is empty")
                    quantity = parse_quantity(fields["quantity"])
                    price = parse_price(fields["unit_price"])
                    if fields["order_id"] in seen:
                        raise ValueError(
                            "duplicate order_id (already accepted earlier in this file)"
                        )
                except ValueError as error:
                    rejected.append({**fields, "source_row": source_row, "reason": str(error)})
                    continue

                line_total = round_money(Decimal(quantity) * price)
                total += line_total
                seen.add(fields["order_id"])
                valid.append({
                    "source_row": source_row,
                    "order_id": fields["order_id"],
                    "quantity": quantity,
                    "line_total": f"{line_total:.2f}",
                })
    except UnicodeDecodeError as error:
        raise FileLevelError(f"input is not valid UTF-8: {error}") from error
    except csv.Error as error:
        raise FileLevelError(f"CSV parse error: {error}") from error
    except OSError as error:
        raise FileLevelError(f"cannot read input file: {error}") from error

    total = round_money(total)
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
    write_csv(output_dir / "rejected_rows.csv", REJECTED_FIELDS, rejected)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise a fictional order CSV.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        summary = summarize(args.input, args.output_dir)
    except FileLevelError as error:
        print(f"order audit failed: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"order audit failed: cannot write output: {error}", file=sys.stderr)
        return 3
    print(
        "order audit ok: "
        f"records={summary['records_total']} valid={summary['valid_count']} "
        f"rejected={summary['rejected_count']} total={summary['total_amount']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
