#!/usr/bin/env python3
"""
build_merged.py — Combine Dictionarry-Hub/database@v2 and Dumpstarr/Database@stable
                  into a single Profilarr-v2-compliant snapshot.

Conflict handling
-----------------
The two upstreams share ~58 custom_format names and ~154 regex names, but the
majority of those overlapping names have different content. To preserve every
author's intent, we *namespace* Dumpstarr's conflicting entities with a
" [Dumpstarr]" suffix and rewrite all of Dumpstarr's internal references in
lockstep. Result: both sources' profiles score releases exactly the way their
authors designed.

Entities that are byte-for-byte identical across the two sources are NOT
namespaced — they collapse into a single entry.

How it works
------------
  1. Play each upstream's full op chain on top of the base schema to build
     that source's final state (in-memory SQLite).
  2. Fingerprint every Dumpstarr custom_format and regular_expression and
     compare against Dictionarry's. Where fingerprints differ, mint a rename:
         "3D"           → "3D [Dumpstarr]"
         "5.1 Surround" → "5.1 Surround [Dumpstarr]"
     For custom_formats the fingerprint includes the resolved patterns of any
     regex they reference, so a CF whose surface matches but whose regex
     diverges still gets namespaced.
  3. Emit a single ops/0.merged-snapshot.sql containing INSERT OR IGNORE
     statements for both states. When emitting Dumpstarr's rows, apply the
     rename map to:
         - `name` column on custom_formats / regular_expressions
         - any `custom_format_name` column (8 condition_* tables + others)
         - any `regular_expression_name` column (condition_patterns, regex_tags)
  4. PRAGMA foreign_keys OFF/ON wraps the bulk load; integrity validated at end.

Auto-increment `id` columns are NOT preserved — every FK in the schema is
name-based, so SQLite can reassign IDs freely on reload.
"""
import sqlite3, os, glob, sys, json, hashlib
from datetime import datetime, timezone

SCHEMA_DIR = "_sources/schema/ops"
DICT_DIR   = "_sources/dictionarry/ops"
DUMP_DIR   = "_sources/dumpstarr/ops"
OUT_SQL    = "ops/0.merged-snapshot.sql"
OUT_MANIFEST = "pcd.json"

NAMESPACE_SUFFIX = " [Dumpstarr]"

# Columns that reference an entity name and must be rewritten when its parent
# entity is namespaced.
NAME_REF_COLUMNS = {
    'custom_format_name':      'cf',
    'regular_expression_name': 're',
}

# Tables that ARE the entity (their own `name` column gets rewritten).
ENTITY_TABLES = {
    'custom_formats':      'cf',
    'regular_expressions': 're',
}


def apply_chain(con, path):
    files = sorted(glob.glob(f"{path}/*.sql"),
                   key=lambda f: int(os.path.basename(f).split('.')[0]))
    fails = []
    for f in files:
        try:
            with open(f) as fh:
                con.executescript(fh.read())
        except sqlite3.Error as e:
            fails.append((os.path.basename(f), str(e)[:160]))
    return fails


def build_state(ops_dirs):
    con = sqlite3.connect(':memory:')
    con.execute("PRAGMA foreign_keys = ON")
    fails = []
    for d in ops_dirs:
        fails += apply_chain(con, d)
    return con, fails


def get_autoincrement_pk(con, table):
    row = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()
    if not row or 'AUTOINCREMENT' not in row[0]:
        return None
    for c in con.execute(f"PRAGMA table_info({table})").fetchall():
        if c[5]:
            return c[1]
    return None


# ----------------------------------------------------------------------------
# Fingerprints
# ----------------------------------------------------------------------------
def cf_fingerprint(con, cf_name, re_lookup):
    """Resolve full behavior of a CF: row + all conditions + type-specific
    condition data + actual patterns of referenced regex."""
    cf_row = con.execute(
        "SELECT description, include_in_rename FROM custom_formats WHERE name=?",
        (cf_name,)
    ).fetchone()
    conds = con.execute("""
        SELECT name, type, arr_type, negate, required
          FROM custom_format_conditions
         WHERE custom_format_name=? ORDER BY name, type
    """, (cf_name,)).fetchall()
    detail = []
    for c in conds:
        cname = c[0]
        patterns_named = con.execute(
            "SELECT regular_expression_name FROM condition_patterns "
            "WHERE custom_format_name=? AND condition_name=? ORDER BY 1",
            (cf_name, cname)
        ).fetchall()
        # Resolve each regex name to its actual pattern for deep comparison
        patterns_resolved = tuple(re_lookup.get(p[0], ('?MISSING', '')) for p in patterns_named)
        sub = (
            tuple(patterns_resolved),
            tuple(con.execute("SELECT source FROM condition_sources WHERE custom_format_name=? AND condition_name=? ORDER BY 1", (cf_name, cname)).fetchall()),
            tuple(con.execute("SELECT min_bytes, max_bytes FROM condition_sizes WHERE custom_format_name=? AND condition_name=?", (cf_name, cname)).fetchall()),
            tuple(con.execute("SELECT resolution FROM condition_resolutions WHERE custom_format_name=? AND condition_name=? ORDER BY 1", (cf_name, cname)).fetchall()),
            tuple(con.execute("SELECT release_type FROM condition_release_types WHERE custom_format_name=? AND condition_name=? ORDER BY 1", (cf_name, cname)).fetchall()),
            tuple(con.execute("SELECT quality_modifier FROM condition_quality_modifiers WHERE custom_format_name=? AND condition_name=? ORDER BY 1", (cf_name, cname)).fetchall()),
            tuple(con.execute("SELECT min_year, max_year FROM condition_years WHERE custom_format_name=? AND condition_name=?", (cf_name, cname)).fetchall()),
            tuple(con.execute("SELECT flag FROM condition_indexer_flags WHERE custom_format_name=? AND condition_name=? ORDER BY 1", (cf_name, cname)).fetchall()),
            tuple(con.execute("SELECT language_name, except_language FROM condition_languages WHERE custom_format_name=? AND condition_name=? ORDER BY 1", (cf_name, cname)).fetchall()),
        )
        detail.append((c, sub))
    return (cf_row, tuple(detail))


# ----------------------------------------------------------------------------
# Dumping with name rewriting
# ----------------------------------------------------------------------------
def dump_table(con, t, mode="OR IGNORE", cf_rename=None, re_rename=None):
    cf_rename = cf_rename or {}
    re_rename = re_rename or {}

    auto_pk = get_autoincrement_pk(con, t)
    cols_info = con.execute(f"PRAGMA table_info({t})").fetchall()
    skip = {auto_pk, 'created_at', 'updated_at'} - {None}
    cols = [c[1] for c in cols_info if c[1] not in skip]
    if not cols:
        return ""
    col_list = ", ".join(f'"{c}"' for c in cols)
    rows = con.execute(f'SELECT {col_list} FROM "{t}"').fetchall()
    if not rows:
        return ""

    rewrites = {}
    entity_kind = ENTITY_TABLES.get(t)
    for i, col in enumerate(cols):
        if entity_kind and col == 'name':
            rewrites[i] = cf_rename if entity_kind == 'cf' else re_rename
        elif col in NAME_REF_COLUMNS:
            ref_kind = NAME_REF_COLUMNS[col]
            rewrites[i] = cf_rename if ref_kind == 'cf' else re_rename

    out = [f"-- {t}: {len(rows)} rows"]
    for r in rows:
        vals = []
        for i, v in enumerate(r):
            if i in rewrites and isinstance(v, str) and v in rewrites[i]:
                v = rewrites[i][v]
            if v is None:
                vals.append("NULL")
            elif isinstance(v, (int, float)):
                vals.append(str(v))
            else:
                vals.append("'" + str(v).replace("'", "''") + "'")
        out.append(f'INSERT {mode} INTO "{t}" ({col_list}) VALUES ({", ".join(vals)});')
    out.append("")
    return "\n".join(out)


TABLES = [
    'tags', 'languages', 'qualities', 'regular_expressions', 'custom_formats',
    'delay_profiles', 'quality_profiles',
    'quality_api_mappings',
    'radarr_quality_definitions', 'sonarr_quality_definitions',
    'radarr_media_settings', 'sonarr_media_settings',
    'radarr_naming', 'sonarr_naming',
    'quality_groups', 'quality_group_members',
    'quality_profile_qualities', 'quality_profile_languages',
    'quality_profile_custom_formats', 'quality_profile_tags',
    'custom_format_conditions',
    'condition_patterns', 'condition_languages', 'condition_indexer_flags',
    'condition_quality_modifiers', 'condition_release_types',
    'condition_resolutions', 'condition_sizes', 'condition_sources',
    'condition_years',
    'custom_format_tags', 'custom_format_tests',
    'regular_expression_tags',
    'test_entities', 'test_releases',
]


def gitsha(repo_path):
    head = os.path.join(repo_path, ".git/HEAD")
    if not os.path.exists(head):
        return "?"
    h = open(head).read().strip()
    if h.startswith('ref: '):
        ref_path = os.path.join(repo_path, ".git", h[5:])
        if os.path.exists(ref_path):
            return open(ref_path).read().strip()[:8]
        packed = os.path.join(repo_path, ".git/packed-refs")
        if os.path.exists(packed):
            ref = h[5:]
            for line in open(packed):
                if line.endswith(" " + ref + "\n"):
                    return line.split()[0][:8]
    return h[:8]


def build_rename_maps(dict_con, dump_con):
    """Return (cf_renames, re_renames) of {original: namespaced} for Dumpstarr
    entities whose content differs from Dictionarry's same-named entity."""
    dict_re = {r[0]: (r[1], r[2]) for r in dict_con.execute("SELECT name, pattern, description FROM regular_expressions")}
    dump_re = {r[0]: (r[1], r[2]) for r in dump_con.execute("SELECT name, pattern, description FROM regular_expressions")}
    re_renames = {}
    for name in set(dict_re) & set(dump_re):
        if dict_re[name] != dump_re[name]:
            re_renames[name] = name + NAMESPACE_SUFFIX

    dict_cfs = {r[0] for r in dict_con.execute("SELECT name FROM custom_formats")}
    dump_cfs = {r[0] for r in dump_con.execute("SELECT name FROM custom_formats")}
    cf_renames = {}
    for name in dict_cfs & dump_cfs:
        if cf_fingerprint(dict_con, name, dict_re) != cf_fingerprint(dump_con, name, dump_re):
            cf_renames[name] = name + NAMESPACE_SUFFIX

    return cf_renames, re_renames


def main():
    print("[1/6] Loading Dictionarry chain...")
    dict_con, dict_fails = build_state([SCHEMA_DIR, DICT_DIR])
    if dict_fails:
        print(f"  WARNING: {len(dict_fails)} ops failed")
        for n, e in dict_fails[:5]: print(f"    {n}: {e}")

    print("[2/6] Loading Dumpstarr chain...")
    dump_con, dump_fails = build_state([SCHEMA_DIR, DUMP_DIR])
    if dump_fails:
        print(f"  WARNING: {len(dump_fails)} ops failed")
        for n, e in dump_fails[:5]: print(f"    {n}: {e}")

    print("[3/6] Computing conflict rename map...")
    cf_renames, re_renames = build_rename_maps(dict_con, dump_con)
    print(f"  custom_formats to namespace:      {len(cf_renames)}")
    print(f"  regular_expressions to namespace: {len(re_renames)}")

    print("[4/6] Conflict report:")
    for t in ['tags', 'custom_formats', 'regular_expressions', 'quality_profiles']:
        d = {r[0] for r in dict_con.execute(f"SELECT name FROM {t}").fetchall()}
        s = {r[0] for r in dump_con.execute(f"SELECT name FROM {t}").fetchall()}
        print(f"  {t:25s} dict={len(d):5d}  dump={len(s):5d}  overlap={len(d&s):5d}  dump-only={len(s-d):5d}")

    print(f"[5/6] Writing {OUT_SQL}...")
    os.makedirs(os.path.dirname(OUT_SQL), exist_ok=True)
    dict_sha = gitsha("_sources/dictionarry")
    dump_sha = gitsha("_sources/dumpstarr")
    schema_sha = gitsha("_sources/schema")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    with open(OUT_SQL, 'w') as f:
        f.write(f"""-- ============================================================================
-- Merged Profilarr v2 snapshot
-- Generated: {ts}
-- Sources:
--   Dictionarry-Hub/schema    ({schema_sha})
--   Dictionarry-Hub/database  @ v2     ({dict_sha})
--   Dumpstarr/Database        @ stable ({dump_sha})
--
-- Conflict handling: Dumpstarr entities whose content differs from
-- Dictionarry's same-named entity are namespaced with "{NAMESPACE_SUFFIX}".
-- Identical entities collapse into a single entry. Both sources' profiles
-- score releases exactly as their authors designed.
--   Namespaced custom_formats:      {len(cf_renames)}
--   Namespaced regular_expressions: {len(re_renames)}
-- ============================================================================

PRAGMA foreign_keys = OFF;

""")
        f.write("-- ===== Layer 1: Dictionarry (unmodified) =====\n\n")
        for t in TABLES:
            f.write(dump_table(dict_con, t))
            f.write("\n")
        f.write(f"\n-- ===== Layer 2: Dumpstarr (with {len(cf_renames)+len(re_renames)} entities namespaced) =====\n\n")
        for t in TABLES:
            f.write(dump_table(dump_con, t, cf_rename=cf_renames, re_rename=re_renames))
            f.write("\n")
        f.write("\nPRAGMA foreign_keys = ON;\n")

    size = os.path.getsize(OUT_SQL)
    sha = hashlib.sha256(open(OUT_SQL, 'rb').read()).hexdigest()[:12]
    print(f"  {size:,} bytes, sha256:{sha}")

    print(f"[6/6] Writing {OUT_MANIFEST}...")
    manifest = {
        "name": "Servers@Home Combined Database",
        "version": "2.0.0",
        "description": "Merged Dictionarry + Dumpstarr database for Profilarr v2. Conflicting entities are namespaced with [Dumpstarr] suffix so both sources' profiles score releases as their authors intended.",
        "arr_types": ["radarr", "sonarr"],
        "dependencies": {"https://github.com/Dictionarry-Hub/schema": "1.1.0"},
        "authors": [{"name": "serversathome"}],
        "license": "MIT",
        "repository": "https://github.com/serversathome/profilarr",
        "links": {
            "homepage": "https://serversatho.me",
            "issues": "https://github.com/serversathome/profilarr/issues"
        },
        "profilarr": {"minimum_version": "2.0.0"},
        "tags": ["dictionarry", "dumpstarr", "combined"],
        "upstream": {
            "dictionarry": {"repo": "https://github.com/Dictionarry-Hub/database", "branch": "v2",     "sha": dict_sha},
            "dumpstarr":   {"repo": "https://github.com/Dumpstarr/Database",       "branch": "stable", "sha": dump_sha},
            "synced_at": ts,
            "namespaced_custom_formats":      len(cf_renames),
            "namespaced_regular_expressions": len(re_renames),
        }
    }
    with open(OUT_MANIFEST, 'w') as f:
        json.dump(manifest, f, indent=2)

    # Verify
    print("\n=> Verifying merged snapshot...")
    v = sqlite3.connect(':memory:')
    apply_chain(v, SCHEMA_DIR)
    with open(OUT_SQL) as fh:
        v.executescript(fh.read())
    v.execute("PRAGMA foreign_keys = ON")

    counts = {t: v.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ['tags', 'custom_formats', 'regular_expressions',
                        'quality_profiles', 'qualities', 'languages']}
    print(f"  Entity counts: {counts}")

    orphans = v.execute("""
        SELECT qpcf.quality_profile_name, qpcf.custom_format_name
          FROM quality_profile_custom_formats qpcf
     LEFT JOIN custom_formats cf ON cf.name = qpcf.custom_format_name
         WHERE cf.name IS NULL
    """).fetchall()
    if orphans:
        print(f"  ✗ {len(orphans)} orphaned profile->CF references")
        for p, c in orphans[:5]: print(f"     profile {p!r} -> missing CF {c!r}")
        sys.exit(1)
    print("  ✓ All profile -> CF references resolve")

    orphans_re = v.execute("""
        SELECT cp.custom_format_name, cp.regular_expression_name
          FROM condition_patterns cp
     LEFT JOIN regular_expressions r ON r.name = cp.regular_expression_name
         WHERE r.name IS NULL
    """).fetchall()
    if orphans_re:
        print(f"  ✗ {len(orphans_re)} orphaned CF->regex references")
        for c, r in orphans_re[:5]: print(f"     CF {c!r} -> missing regex {r!r}")
        sys.exit(1)
    print("  ✓ All CF condition -> regex references resolve")

    fk = v.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        print(f"  ✗ {len(fk)} FK violations")
        sys.exit(1)
    print("  ✓ FK integrity OK")

    print("\n=> Quality profiles in merged DB:")
    for r in v.execute("SELECT name FROM quality_profiles ORDER BY name").fetchall():
        print(f"   - {r[0]}")

    if cf_renames:
        print(f"\n=> Sample namespaced custom_formats (first 10 of {len(cf_renames)}):")
        for old in sorted(cf_renames)[:10]:
            print(f"   {old!r} → {cf_renames[old]!r}")
    print("\n  ✓ Merge complete.")


if __name__ == "__main__":
    main()