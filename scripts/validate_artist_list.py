#!/usr/bin/env python3
"""Validate/normalize an artist list JSON.

This repo stores lists as JSON arrays of objects like:
  [{"name": "Artist"}, ...]

This script:
  - validates structure
  - normalizes whitespace
  - reports duplicates (case-insensitive)
  - can write a normalized JSON
  - can write a sample subset JSON (useful for MBID resolution tests)

Usage:
  py -3 scripts/validate_artist_list.py --input artistas_nacionais_rock_pop.json
  py -3 scripts/validate_artist_list.py --input artistas_nacionais_rock_pop.json --normalized output/rock_pop_normalized.json
  py -3 scripts/validate_artist_list.py --input artistas_nacionais_rock_pop.json --sample 25 --sample-out output/sample_rock_pop_25.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    # Accept UTF-8 with or without BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    return name


@dataclass(frozen=True)
class ValidationResult:
    total: int
    unique: int
    empty: int
    duplicates: list[tuple[str, int, list[str]]]


def validate(data: Any) -> tuple[list[dict[str, str]], ValidationResult]:
    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON array")

    normalized_items: list[dict[str, str]] = []
    raw_names: list[str] = []

    for item in data:
        if isinstance(item, dict) and "name" in item:
            name = str(item["name"])
        elif isinstance(item, str):
            name = item
        else:
            raise ValueError(f"Unexpected item (expected dict with name or string): {item!r}")

        norm = _normalize_name(name)
        raw_names.append(norm)
        normalized_items.append({"name": norm})

    empty = sum(1 for n in raw_names if not n)

    c = Counter(n.casefold() for n in raw_names if n)
    dups = [(k, v) for k, v in c.items() if v > 1]

    dup_details: list[tuple[str, int, list[str]]] = []
    for k, v in sorted(dups, key=lambda t: (-t[1], t[0])):
        examples = [n for n in raw_names if n and n.casefold() == k][:5]
        dup_details.append((k, v, examples))

    result = ValidationResult(
        total=len(raw_names),
        unique=len(c),
        empty=empty,
        duplicates=dup_details,
    )

    return normalized_items, result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate/normalize artist list JSON")
    parser.add_argument("--input", required=True)
    parser.add_argument("--normalized", help="Write normalized JSON to this path")
    parser.add_argument("--sample", type=int, help="Write N first items to --sample-out")
    parser.add_argument("--sample-out", help="Path to write sample JSON")

    args = parser.parse_args()
    input_path = Path(args.input)

    data = _read_json(input_path)
    normalized_items, report = validate(data)

    print(f"total={report.total} unique={report.unique} empty={report.empty} duplicate_keys={len(report.duplicates)}")
    if report.duplicates:
        print("Top duplicates (case-insensitive):")
        for key, count, examples in report.duplicates[:30]:
            print(f"  {count}x  {examples}")

    if args.normalized:
        out = Path(args.normalized)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(normalized_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote normalized: {out.as_posix()}")

    if args.sample is not None:
        if not args.sample_out:
            raise ValueError("--sample-out is required when using --sample")
        out = Path(args.sample_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(normalized_items[: args.sample], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote sample: {out.as_posix()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
