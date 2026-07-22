"""Read-only HTTP API over the ingested archive.

Only `players` and `ingest` mutate anything; everything else is a projection of
what the poller, worker and parser have already produced.
"""

from __future__ import annotations
