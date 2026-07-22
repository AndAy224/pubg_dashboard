# Running the poller and worker as services

These are **user** units, not system units. Installing them needs no root:
`loginctl enable-linger` is permitted for one's own account by the default
polkit rules, and that is what makes them start at boot with nobody logged in.

```bash
cp deploy/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
loginctl enable-linger "$USER"          # survive logout and reboot
systemctl --user enable --now pubgd-worker pubgd-poller
```

Check on them:

```bash
systemctl --user status pubgd-worker pubgd-poller
journalctl --user -u pubgd-poller -f
pubgd jobs                               # queue depth by kind and state
```

## Why the poller matters most

PUBG discards match history after ~14 days. The poller is the only thing that
notices a new match in time; anything it misses is gone permanently. Everything
downstream (`/matches/{id}`, the telemetry CDN) is free and unmetered, so the
whole pipeline costs **one rate-limited request per cycle** for all tracked
players combined.

## Notes that are easy to get wrong

* **`StartLimitIntervalSec` is a `[Unit]` directive.** Under `[Service]`
  systemd logs "Unknown key" and ignores it — which was the case here at first.
  Without it, a dependency that is slow at boot trips the default
  5-starts-in-10s limit and the unit stays dead until somebody notices.
* **Postgres and MinIO are Docker containers**, and a *user* unit cannot order
  itself after the system `docker.service`. The dependency is handled by
  `Restart=always` plus a `RestartSec` backoff instead: `pubgd` exits non-zero
  with an actionable message when the database is unreachable, so systemd
  simply retries until the containers are up.
* **`MemoryMax` on the worker is deliberate.** A single parse peaks at
  **269 MB RSS** — the ~2.4 MB gzipped telemetry expands to ~37 MB of JSON that
  orjson materialises into Python objects. (BUILD-SPEC §3.7 estimates 40-60 MB;
  that is off by roughly 5x.) At concurrency 2 that is ~590 MB on a 1.6 GB box
  where Postgres is configured with 512 MB of shared buffers. Bounding the
  worker means a runaway parse kills only the worker — and the job is simply
  retried — instead of inviting the global OOM killer, whose most attractive
  target is Postgres.
* `TimeoutStopSec` exceeds the worker's own 30 s drain grace, or a parse gets
  SIGKILLed mid-write and retries for nothing.

## Verified behaviour

* `SIGKILL` the worker -> restarted with a new PID within `RestartSec`.
* `systemctl --user stop` -> logs `worker.stopped` and drains; not SIGKILLed.
* Deleting a match row and waiting -> the poller re-enqueued it on the next
  cycle and the worker restored it end to end through the **live** API
  (`fetch_match` -> `fetch_telemetry` -> `parse_telemetry`), with byte-identical
  telemetry content. It took one full `POLL_INTERVAL_SECONDS`, not less,
  because `select_due_players` honours the per-player backoff rather than
  spending rate-limit budget on a player polled moments ago.
