# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Archive every currently-available match + telemetry for tracked players.

PUBG discards matches after ~14 days. This script exists to win that race
*before* the real ingestion pipeline is finished: it dumps raw match JSON and
gzipped telemetry to disk so nothing is lost while we build. The pipeline
later imports from these files instead of re-fetching.

Safe to re-run: already-downloaded matches are skipped, so this doubles as a
crude cron-able backstop.

Budget notes:
  - GET /players is rate limited (10/min) — we make exactly one call.
  - GET /matches/{id} is NOT rate limited.
  - The telemetry CDN is unauthenticated and NOT rate limited.
So the whole archive costs one token from the rate-limit bucket.

    uv run scripts/panic_archive.py
"""
from __future__ import annotations

import asyncio
import gzip
import json
import pathlib
import sys
import time

import httpx

REPO = pathlib.Path(__file__).resolve().parent.parent
MATCH_DIR = REPO / "data" / "matches"
TELE_DIR = REPO / "data" / "telemetry"
CONCURRENCY = 4          # polite; the CDN would tolerate far more
BASE = "https://api.pubg.com"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    envfile = REPO / ".env"
    if not envfile.exists():
        sys.exit("No .env — copy .env.example and fill in PUBG_API_KEY")
    for line in envfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
KEY = ENV.get("PUBG_API_KEY") or sys.exit("PUBG_API_KEY is empty in .env")
SHARD = ENV.get("PUBG_DEFAULT_SHARD", "steam")
NAMES = [n.strip() for n in ENV.get("PUBG_SEED_PLAYERS", "").split(",") if n.strip()]

HEADERS = {
    "Authorization": f"Bearer {KEY}",
    "Accept": "application/vnd.api+json",
    "Accept-Encoding": "gzip",
}

stats = {"matches": 0, "skipped": 0, "failed": 0, "bytes": 0}


async def archive_match(client: httpx.AsyncClient, match_id: str, sem: asyncio.Semaphore) -> None:
    match_path = MATCH_DIR / f"{match_id}.json"
    tele_path = TELE_DIR / f"{match_id}.json.gz"

    if match_path.exists() and tele_path.exists():
        stats["skipped"] += 1
        return

    async with sem:
        try:
            # --- match metadata (unlimited endpoint) ---
            if match_path.exists():
                match = json.loads(match_path.read_text(encoding="utf-8"))
            else:
                r = await client.get(f"{BASE}/shards/{SHARD}/matches/{match_id}", headers=HEADERS)
                r.raise_for_status()
                match = r.json()
                match_path.write_text(json.dumps(match), encoding="utf-8")

            attrs = match["data"]["attributes"]

            # --- telemetry (unauthenticated CDN) ---
            if not tele_path.exists():
                asset = next(
                    (i for i in match.get("included", []) if i["type"] == "asset"), None
                )
                # Casing is 'URL', not 'url'. Fall back defensively in case
                # PUBG ever normalizes it.
                url = None
                if asset:
                    url = asset["attributes"].get("URL") or asset["attributes"].get("url")
                if not url:
                    print(f"  ! {match_id[:8]} no telemetry asset")
                    stats["failed"] += 1
                    return

                # No Authorization header — the CDN is public and sending the
                # key would be a needless leak into someone else's access log.
                rt = await client.get(url, headers={"Accept-Encoding": "gzip"}, timeout=120.0)
                rt.raise_for_status()
                raw = rt.content
                tele_path.write_bytes(gzip.compress(raw, compresslevel=6))
                stats["bytes"] += tele_path.stat().st_size

            stats["matches"] += 1
            mb = tele_path.stat().st_size / 1024 / 1024
            print(
                f"  + {match_id[:8]}  {attrs.get('mapName','?'):<16}"
                f"{attrs.get('gameMode','?'):<10}{attrs.get('matchType','?'):<12}"
                f"{attrs.get('createdAt','?')[:16]}  {mb:.1f}MB"
            )
        except Exception as exc:  # noqa: BLE001 — best-effort archival
            stats["failed"] += 1
            print(f"  ! {match_id[:8]} {type(exc).__name__}: {exc}")


async def main() -> None:
    MATCH_DIR.mkdir(parents=True, exist_ok=True)
    TELE_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        print(f"Resolving {len(NAMES)} players on '{SHARD}' ...")
        r = await client.get(
            f"{BASE}/shards/{SHARD}/players",
            headers=HEADERS,
            params={"filter[playerNames]": ",".join(NAMES)},
        )
        r.raise_for_status()

        # Ordered dedup: teammates share matches, so ~131 refs collapse a lot.
        match_ids: dict[str, None] = {}
        for p in r.json()["data"]:
            refs = p.get("relationships", {}).get("matches", {}).get("data", [])
            print(f"  {p['attributes']['name']:<16} {len(refs)} matches")
            for m in refs:
                match_ids[m["id"]] = None

        ids = list(match_ids)
        have = sum(
            1 for i in ids
            if (MATCH_DIR / f"{i}.json").exists() and (TELE_DIR / f"{i}.json.gz").exists()
        )
        print(f"\n{len(ids)} unique matches ({have} already archived)\n")

        sem = asyncio.Semaphore(CONCURRENCY)
        await asyncio.gather(*(archive_match(client, i, sem) for i in ids))

    elapsed = time.time() - started
    total = sum(f.stat().st_size for f in TELE_DIR.glob("*.json.gz"))
    print(
        f"\nDone in {elapsed:.0f}s — {stats['matches']} archived, "
        f"{stats['skipped']} skipped, {stats['failed']} failed"
    )
    print(f"Telemetry on disk: {total/1024/1024:.0f} MB across {len(list(TELE_DIR.glob('*.json.gz')))} matches")


if __name__ == "__main__":
    asyncio.run(main())
