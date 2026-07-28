# Care-package icons

PUBG's own, from
[`pubg/api-assets`](https://github.com/pubg/api-assets/tree/master/Assets/Icons/CarePackage)
— `Assets/Icons/CarePackage/`. Same source as the map tiles
(`scripts/fetch_map_assets.py`), and the same licensing position: the assets
repo is published for API developers, and this is a self-hosted dashboard for
three people.

Committed rather than fetched at build time, like the self-hosted fonts in
`public/fonts/`. 29 KB for all three, no CDN, no runtime dependency on GitHub
being up. They are **not** Git-LFS pointers (the High_Res map PNGs in that repo
are, which is the trap `fetch_map_assets.py` documents) — `file` reports real
PNG data.

| file | used for |
|---|---|
| `CarePackage_Flying.png` | 144x200, parachute above the crate — the ~54 s fall |
| `CarePackage_Normal.png` | 144x136, landed and untouched |
| `CarePackage_Open.png` | 144x136, **not used yet** — see below |

`CarePackage_Open.png` is here because the signal for it exists:
`LogItemPickupFromCarepackage` fires ~31 times a match, so "has anyone taken
anything out of this crate" is answerable. Wiring it up needs a parser bump and
a reparse, so it is deliberately left for later rather than half-done.

**Do not tint these.** They already carry PUBG's red/blue/white; `tint`
multiplies, so any tint muddies them. Rarity is expressed by size instead —
which is also why the drawn-glyph fallback in `Renderer.ts` exists: it is
monochrome and *can* be tinted.
