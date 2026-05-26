# Profilarr Combined Database

A ready-to-use database for [Profilarr](https://github.com/Dictionarry-Hub/profilarr) that combines two of the best community sources into one place, so you don't have to choose between them.

## What is this?

If you use **Radarr** (for movies) or **Sonarr** (for TV shows), you know that getting the best quality downloads depends on having good **quality profiles** and **custom formats**. These tell your apps which releases to grab and which to skip.

The community has built two excellent databases of these profiles and formats:

- **[Dictionarry](https://github.com/Dictionarry-Hub/database)** by the Dictionarry-Hub team -- 11 quality profiles covering everything from 720p to 2160p Remux
- **[Dumpstarr](https://github.com/Dumpstarr/Database)** by Dumpstarr -- 9 quality profiles including specialized options like Anime and separate Movie/TV profiles

Normally you'd have to pick one or the other. **This repo merges both databases together** so you can use profiles from either source in a single Radarr/Sonarr setup.

## How to use it

In Profilarr (v2.0.0 or later), add this as a database:

```
https://github.com/serversathome/profilarr
```

Leave the branch field blank. That's it -- you'll have access to all 20 profiles, 410+ custom formats, and 900+ regex patterns from both sources.

## What's inside

| Source | Profiles |
|--------|----------|
| **Dictionarry** | 720p Quality, 1080p Balanced, 1080p Compact, 1080p Efficient, 1080p Quality, 1080p Quality HDR, 1080p Remux, 2160p Balanced, 2160p Efficient, 2160p Quality, 2160p Remux |
| **Dumpstarr** | LQ 1080p, Anime 1080p, BETA - Anime 1080p, Movies 1080p, Movies 1080p HQ, Movies 2160p, Movies 2160p HQ, TV 1080p, TV 2160p |

## How does it handle conflicts?

Sometimes both databases define something with the same name but different settings. When that happens, the Dumpstarr version gets a `[Dumpstarr]` tag added to its name. For example, if both define a custom format called `3D`, you'll see:

- `3D` (from Dictionarry)
- `3D [Dumpstarr]` (from Dumpstarr)

This way nothing gets lost or overwritten, and both sources score your releases exactly as their authors intended.

When both databases define something identically, it's kept as a single entry with no duplication.

## How does it stay up to date?

A GitHub Actions workflow runs automatically once a day. It pulls the latest data from both upstream databases, merges them together, and commits the result. You don't need to do anything -- your Profilarr setup will pick up changes on its own.

## Good to know

- **Updates not showing up?** Try re-linking the database in Profilarr.
- **Want to change the `[Dumpstarr]` tag?** Edit the `NAMESPACE_SUFFIX` setting in `.github/scripts/build_merged.py`.
- **Have feedback on the profiles themselves?** Those are maintained by the upstream projects -- contribute directly to [Dictionarry](https://github.com/Dictionarry-Hub/database) or [Dumpstarr](https://github.com/Dumpstarr/Database).

## Credits

This project wouldn't exist without the hard work of these communities:

- **[Dictionarry-Hub](https://github.com/Dictionarry-Hub)** -- for the database, schema, and Profilarr itself
- **[Dumpstarr](https://github.com/Dumpstarr)** -- for the additional profiles and custom formats

This repo is just the glue that brings them together. All the real work happens upstream.
