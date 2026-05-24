
# serversathome/profilarr
Merged Profilarr v2 database combining Dictionarry and Dumpstarr into one repo, so I can use profiles from both against a single Radarr/Sonarr instance.
Sources: Dictionarry-Hub/database (v2 branch) and Dumpstarr/Database (stable branch).
## Use it
In Profilarr, add this URL as a database and leave the branch field blank:
https://github.com/serversathome/profilarr
## What's inside
20 quality profiles, 410 custom formats, 924 regex patterns, plus tags, qualities, and languages.
**Dictionarry profiles (11):** 720p Quality, 1080p Balanced, 1080p Compact, 1080p Efficient, 1080p Quality, 1080p Quality HDR, 1080p Remux, 2160p Balanced, 2160p Efficient, 2160p Quality, 2160p Remux.
**Dumpstarr profiles (9):** LQ 1080p, Anime 1080p, BETA - Anime 1080p, Movies 1080p, Movies 1080p HQ, Movies 2160p, Movies 2160p HQ, TV 1080p, TV 2160p.
## Conflicts
When both sources define an entity with the same name but different content, Dumpstarr's gets renamed with a `[Dumpstarr]` suffix (e.g. `3D` and `3D [Dumpstarr]` coexist). All of Dumpstarr's internal references update in lockstep, so both sources' profiles score releases exactly as their authors intended.
Identical entities collapse to one entry — no needless duplication.
## How it syncs
GitHub Actions runs nightly at 05:00 UTC. It replays each upstream's SQL migration chain to build their final state, computes the conflict rename map, and emits a fresh merged snapshot at `ops/0.merged-snapshot.sql`.
Manual run: Actions tab, Sync from upstreams, Run workflow.
## Caveats
Each sync overwrites `0.merged-snapshot.sql` in place. If updates stop showing up in Profilarr, re-link the database.
`[Dumpstarr]` shows up as plain text in your arr's UI. Change `NAMESPACE_SUFFIX` in `build_merged.py` if you want a different marker.
This is downstream-only. PRs about profile content go to the upstreams.
