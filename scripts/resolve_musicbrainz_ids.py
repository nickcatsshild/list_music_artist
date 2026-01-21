#!/usr/bin/env python3
"""Resolve MusicBrainz Artist IDs (MBIDs) from a JSON list of artist names.

Input format expected:
  [ {"name": "Artist"}, {"name": "Another"} ]

Outputs:
  - output/artists_with_mbid.csv
  - output/ambiguous_or_missing.csv

Notes:
  - MusicBrainz requires a descriptive User-Agent.
  - Rate-limit: this script enforces at most 1 request/second.
  - Caching: responses are cached under cache/musicbrainz/.

Usage examples:
  python scripts/resolve_musicbrainz_ids.py --input artistas_nacionais_rock_pop.json
  python scripts/resolve_musicbrainz_ids.py --input artistas_nacionais_rock_pop.json --country BR

"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


MB_API_BASE = "https://musicbrainz.org/ws/2"
DEFAULT_CACHE_DIR = os.path.join("cache", "musicbrainz")
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_USER_AGENT = "list_music_artist/1.0 (please set --user-agent with contact)"


@dataclass(frozen=True)
class Candidate:
    mbid: str
    name: str
    score: int
    country: str | None
    disambiguation: str | None
    type: str | None


def _normalize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    return name


def _cache_path(cache_dir: str, url: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, f"{digest}.json")


def _fetch_json(url: str, user_agent: str, cache_dir: str, timeout_s: int = 30) -> Any:
    cache_file = _cache_path(cache_dir, url)
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        payload = resp.read().decode("utf-8")

    data = json.loads(payload)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    return data


def _query_artists(name: str, user_agent: str, cache_dir: str) -> list[Candidate]:
    # Use Lucene query syntax; quote name to reduce noise.
    query = f'artist:"{name}"'
    params = {
        "query": query,
        "fmt": "json",
        "limit": "10",
    }
    url = f"{MB_API_BASE}/artist?{urllib.parse.urlencode(params)}"
    data = _fetch_json(url, user_agent=user_agent, cache_dir=cache_dir)

    candidates: list[Candidate] = []
    for item in data.get("artists", []) or []:
        candidates.append(
            Candidate(
                mbid=item.get("id", ""),
                name=item.get("name", ""),
                score=int(item.get("score", 0) or 0),
                country=item.get("country"),
                disambiguation=item.get("disambiguation"),
                type=item.get("type"),
            )
        )

    # Sort highest score first, stable.
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def _pick_best(candidates: list[Candidate], preferred_country: str | None) -> tuple[Candidate | None, str | None]:
    if not candidates:
        return None, "no_results"

    # If country preference exists, boost those candidates.
    if preferred_country:
        preferred = [c for c in candidates if (c.country or "").upper() == preferred_country.upper()]
        if preferred:
            # If top preferred is clearly better, accept.
            preferred.sort(key=lambda c: c.score, reverse=True)
            best = preferred[0]
            if len(preferred) == 1:
                return best, None
            # If scores are close, keep ambiguous.
            if preferred[0].score - preferred[1].score >= 10:
                return best, None
            return best, "ambiguous_multiple_preferred"

    # No country filter, use score heuristic.
    best = candidates[0]
    if len(candidates) == 1:
        return best, None

    # If top is clearly better than 2nd, accept.
    if best.score - candidates[1].score >= 15:
        return best, None

    return best, "ambiguous"


def _load_names(json_path: str) -> list[str]:
    # PowerShell/Windows frequentemente escreve UTF-8 com BOM; aceite ambos.
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    names: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "name" in item:
                names.append(str(item["name"]))
            elif isinstance(item, str):
                names.append(item)
            else:
                raise ValueError(f"Unexpected item in list: {item!r}")
    else:
        raise ValueError("Expected top-level JSON array")

    normalized: list[str] = []
    seen: set[str] = set()
    for n in names:
        nn = _normalize_name(n)
        if nn and nn not in seen:
            seen.add(nn)
            normalized.append(nn)
    return normalized


def _write_csv(path: str, header: list[str], rows: Iterable[list[str]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve MusicBrainz Artist IDs (MBIDs) from artist names")
    parser.add_argument("--input", required=True, help="Input JSON file with artist names")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("MUSICBRAINZ_USER_AGENT", DEFAULT_USER_AGENT),
        help="MusicBrainz User-Agent header (recommended to include contact)",
    )
    parser.add_argument(
        "--country",
        default=os.environ.get("MUSICBRAINZ_PREFERRED_COUNTRY"),
        help="Preferred country code to disambiguate (e.g. BR)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=float(os.environ.get("MUSICBRAINZ_SLEEP_SECONDS", "1.1")),
        help="Seconds to sleep between API requests (default ~1.1)",
    )

    args = parser.parse_args()

    names = _load_names(args.input)
    ok_rows: list[list[str]] = []
    ambiguous_rows: list[list[str]] = []

    for i, name in enumerate(names, start=1):
        candidates = _query_artists(name, user_agent=args.user_agent, cache_dir=args.cache_dir)
        best, reason = _pick_best(candidates, preferred_country=args.country)

        if best is None:
            ambiguous_rows.append([name, "", "", "", "", "", "no_results", ""])
        elif reason is None:
            ok_rows.append([name, best.mbid, str(best.score), best.country or "", best.type or "", best.disambiguation or "", "", ""])
        else:
            # Put top 3 candidates for manual review.
            top = candidates[:3]
            cand_str = " | ".join(
                [
                    f"{c.mbid}::{c.name}::{c.score}::{(c.country or '')}::{(c.disambiguation or '')}"
                    for c in top
                ]
            )
            ambiguous_rows.append(
                [
                    name,
                    best.mbid,
                    str(best.score),
                    best.country or "",
                    best.type or "",
                    best.disambiguation or "",
                    reason,
                    cand_str,
                ]
            )

        # Rate-limit friendly.
        if i != len(names):
            time.sleep(max(0.0, float(args.sleep)))

    ok_path = os.path.join(args.output_dir, "artists_with_mbid.csv")
    amb_path = os.path.join(args.output_dir, "ambiguous_or_missing.csv")

    _write_csv(
        ok_path,
        header=["name", "mbid", "score", "country", "type", "disambiguation", "issue", "candidates"],
        rows=ok_rows,
    )
    _write_csv(
        amb_path,
        header=["name", "mbid", "score", "country", "type", "disambiguation", "issue", "candidates"],
        rows=ambiguous_rows,
    )

    print(f"Wrote: {ok_path} ({len(ok_rows)} resolved)")
    print(f"Wrote: {amb_path} ({len(ambiguous_rows)} ambiguous/missing)")

    if args.user_agent == DEFAULT_USER_AGENT:
        print("WARNING: Set a real --user-agent (with contact) for MusicBrainz.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
