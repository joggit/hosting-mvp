#!/usr/bin/env python3
"""
scripts/migrate_drop_legacy_tables.py

One-time migration: drop pre-Docker WordPress tables from hosting-mvp's SQLite DB.

Background:
  hosting-mvp originally had a non-Docker WordPress approach that created
  four tables: wordpress_sites, wordpress_plugins, wordpress_themes,
  wordpress_cli_history. These were superseded by wordpress_docker_sites
  and are entirely unused. They add schema noise and false impressions
  about what the system does.

Tables removed:
  - wordpress_sites          (pre-Docker site registry — replaced by wordpress_docker_sites)
  - wordpress_plugins        (plugin registry per wordpress_sites — unused)
  - wordpress_themes         (theme registry per wordpress_sites — unused)
  - wordpress_cli_history    (WP-CLI audit log per wordpress_sites — unused)

Safe to run:
  - Checks each table exists before dropping
  - Backs up the database first
  - Dry-run mode shows what would be dropped without touching anything
  - Idempotent — safe to run multiple times

Usage:
  python3 scripts/migrate_drop_legacy_tables.py
  python3 scripts/migrate_drop_legacy_tables.py --dry-run
  python3 scripts/migrate_drop_legacy_tables.py --db-path /custom/path/hosting.db
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


LEGACY_TABLES = [
    "wordpress_cli_history",  # drop dependents first (FK child)
    "wordpress_plugins",  # drop dependents first (FK child)
    "wordpress_themes",  # drop dependents first (FK child)
    "wordpress_sites",  # drop parent last
]

DEFAULT_DB_PATH = Path("/var/data/hosting.db")


def find_db(path: Path) -> Path:
    if path.exists():
        return path
    # Try common alternative locations
    for candidate in [
        Path("/var/data/hosting.db"),
        Path("/var/www/hosting-mvp/hosting.db"),
        Path.home() / "hosting-mvp" / "hosting.db",
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Database not found at {path}.\n"
        "Use --db-path to specify the correct location."
    )


def backup_db(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.stem}-before-migration-{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def get_existing_tables(conn: sqlite3.Connection) -> set:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall()}


def get_row_counts(conn: sqlite3.Connection, tables: list) -> dict:
    counts = {}
    for table in tables:
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            counts[table] = None  # table doesn't exist
    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Drop legacy pre-Docker WordPress tables from hosting-mvp database"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be dropped without making any changes",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip database backup (not recommended)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 55)
    print("  hosting-mvp — Drop Legacy WordPress Tables")
    print("=" * 55)

    # ── Find database ─────────────────────────────────────────────────────────
    try:
        db_path = find_db(args.db_path)
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        sys.exit(1)

    print(f"\n  Database: {db_path}")
    print(f"  Size:     {db_path.stat().st_size // 1024}KB")

    # ── Connect and inspect ───────────────────────────────────────────────────
    conn = sqlite3.connect(str(db_path))
    existing = get_existing_tables(conn)
    counts = get_row_counts(conn, LEGACY_TABLES)

    tables_to_drop = [t for t in LEGACY_TABLES if t in existing]
    already_gone = [t for t in LEGACY_TABLES if t not in existing]

    if already_gone:
        print(f"\n  Already removed: {', '.join(already_gone)}")

    if not tables_to_drop:
        print("\n  ✅ Nothing to do — all legacy tables already removed")
        conn.close()
        return

    print(f"\n  Tables to drop:")
    for table in tables_to_drop:
        count = counts.get(table)
        row_info = f"{count} rows" if count is not None else "?"
        print(f"    - {table:40} ({row_info})")

    # ── Warn if rows exist ────────────────────────────────────────────────────
    nonempty = [t for t in tables_to_drop if counts.get(t, 0) > 0]
    if nonempty:
        print(f"\n  ⚠️  These tables contain data:")
        for table in nonempty:
            print(f"     {table}: {counts[table]} rows")
        print(
            "\n  This data is from the pre-Docker WordPress approach and is no longer\n"
            "  used by hosting-mvp. It is safe to drop.\n"
            "  A backup will be created before proceeding."
        )

    if args.dry_run:
        print("\n  DRY RUN — no changes made")
        print("  Run without --dry-run to apply")
        conn.close()
        return

    # ── Confirm ───────────────────────────────────────────────────────────────
    print()
    confirm = input("  Proceed? [y/N] ").strip().lower()
    if confirm != "y":
        print("  Aborted")
        conn.close()
        sys.exit(0)

    # ── Backup ────────────────────────────────────────────────────────────────
    if not args.no_backup:
        backup_path = backup_db(db_path)
        print(f"\n  ✅ Backup created: {backup_path}")
    else:
        print("\n  ⚠️  Skipping backup (--no-backup)")

    # ── Drop tables ───────────────────────────────────────────────────────────
    print()
    for table in tables_to_drop:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()
            print(f"  ✅ Dropped: {table}")
        except sqlite3.OperationalError as e:
            print(f"  ❌ Failed to drop {table}: {e}")
            conn.rollback()
            conn.close()
            sys.exit(1)

    # ── Remove orphaned indexes ───────────────────────────────────────────────
    legacy_indexes = [
        "idx_wp_sites_domain",
        "idx_wp_sites_status",
        "idx_wp_plugins_site",
        "idx_wp_themes_site",
        "idx_wp_cli_history_site",
    ]
    for index in legacy_indexes:
        try:
            conn.execute(f"DROP INDEX IF EXISTS {index}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    print("  ✅ Removed orphaned indexes")

    # ── Vacuum to reclaim space ───────────────────────────────────────────────
    print("\n  Running VACUUM to reclaim disk space...")
    conn.execute("VACUUM")
    conn.close()
    print(f"  ✅ Database vacuumed")
    print(f"  New size: {db_path.stat().st_size // 1024}KB")

    # ── Verify ────────────────────────────────────────────────────────────────
    conn = sqlite3.connect(str(db_path))
    remaining = get_existing_tables(conn)
    conn.close()

    still_present = [t for t in LEGACY_TABLES if t in remaining]
    if still_present:
        print(f"\n  ❌ Still present: {still_present}")
        sys.exit(1)

    print("\n" + "=" * 55)
    print("  ✅ Migration complete")
    print(f"\n  Remaining tables:")
    for table in sorted(remaining):
        print(f"    - {table}")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
