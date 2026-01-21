#!/usr/bin/env python3
"""Add artists to Lidarr using the Lidarr API from a CSV containing MBIDs.

Expected input CSV header (from resolve_musicbrainz_ids.py):
  name,mbid,...

Usage:
  python scripts/add_artists_to_lidarr.py --csv output/artists_with_mbid.csv --lidarr-url http://localhost:8686 --api-key <KEY> --root-folder "D:/Music" --quality-profile-id 1 --metadata-profile-id 1

Notes:
  - This uses Lidarr's /api/v1/artist endpoint.
  - Use --dry-run first.

"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class LidarrConfig:
    base_url: str
    api_key: str
    root_folder: str
    quality_profile_id: int
    metadata_profile_id: int
    monitor: str
    search_for_missing_albums: bool


def _post_json(url: str, api_key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if body else {}


def _read_mbids(csv_path: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if "mbid" not in (r.fieldnames or []):
            raise ValueError("CSV must contain a 'mbid' column")
        for row in r:
            name = (row.get("name") or "").strip()
            mbid = (row.get("mbid") or "").strip()
            if not mbid:
                continue
            items.append((name, mbid))
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Add artists to Lidarr by MBID")
    parser.add_argument("--csv", required=True, help="CSV file with 'mbid' column")
    parser.add_argument("--lidarr-url", required=True, help="Base URL, e.g. http://localhost:8686")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--root-folder", required=True, help="Root folder path configured in Lidarr")
    parser.add_argument("--quality-profile-id", required=True, type=int)
    parser.add_argument("--metadata-profile-id", required=True, type=int)
    parser.add_argument("--monitor", default="all", choices=["all", "future", "missing", "existing", "none"])
    parser.add_argument("--search", action="store_true", help="Search for missing albums immediately")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    cfg = LidarrConfig(
        base_url=args.lidarr_url.rstrip("/"),
        api_key=args.api_key,
        root_folder=args.root_folder,
        quality_profile_id=args.quality_profile_id,
        metadata_profile_id=args.metadata_profile_id,
        monitor=args.monitor,
        search_for_missing_albums=bool(args.search),
    )

    items = _read_mbids(args.csv)

    endpoint = f"{cfg.base_url}/api/v1/artist"

    for name, mbid in items:
        payload = {
            "foreignArtistId": mbid,
            "rootFolderPath": cfg.root_folder,
            "qualityProfileId": cfg.quality_profile_id,
            "metadataProfileId": cfg.metadata_profile_id,
            "monitor": cfg.monitor,
            "addOptions": {
                "searchForMissingAlbums": cfg.search_for_missing_albums,
            },
        }

        if args.dry_run:
            print(f"DRY-RUN add: {name} -> {mbid}")
            continue

        try:
            result = _post_json(endpoint, api_key=cfg.api_key, payload=payload)
            added_name = result.get("artistName") or result.get("name") or name
            print(f"ADDED: {added_name} ({mbid})")
        except Exception as ex:  # noqa: BLE001
            print(f"ERROR adding {name} ({mbid}): {ex}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
