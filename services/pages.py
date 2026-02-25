"""
services/pages.py

Page registry service for hosting-mvp.

Manages the pages table — a per-site record of pages created during
Next.js deployments (page name, slug, template, metadata).

Previously the page creation logic lived as a nested function inside
routes/deployment.py:register_routes(). Moving it here means it can
be imported, tested, and reused independently of the route layer.
"""

import json
import logging
from services.database import get_db

logger = logging.getLogger(__name__)


def init_pages_table():
    """
    Ensure the pages table exists.

    Called before any page operation — safe to call multiple times
    as it uses CREATE TABLE IF NOT EXISTS.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id     TEXT NOT NULL,
            page_name   TEXT NOT NULL,
            slug        TEXT NOT NULL,
            template_id TEXT,
            sections    TEXT DEFAULT '{}',
            metadata    TEXT DEFAULT '{}',
            published   BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(site_id, slug)
        )
    """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pages_site_id ON pages(site_id)")
    conn.commit()
    conn.close()


def create_pages_for_site(domain: str, pages: list[dict], site_name: str) -> int:
    """
    Create page records for a site after deployment.

    Called during Next.js deployment when the client sends a selectedPages
    list. Pages already existing (same site_id + slug) are skipped.

    Args:
        domain:    Domain used as the site_id key (e.g. mysite.com)
        pages:     List of page dicts from the deploy payload:
                     {pageName, slug, templateId, published}
        site_name: Human-readable site name for metadata titles

    Returns:
        Number of pages created (skipped pages are not counted)
    """
    if not pages or not domain:
        return 0

    init_pages_table()

    conn = get_db()
    cursor = conn.cursor()
    created = 0

    try:
        for page in pages:
            slug = page.get("slug")
            if not slug:
                logger.warning(f"Skipping page with no slug: {page}")
                continue

            # Skip if already exists for this site
            cursor.execute(
                "SELECT id FROM pages WHERE site_id = ? AND slug = ?",
                (domain, slug),
            )
            if cursor.fetchone():
                logger.debug(f"  Page already exists, skipping: {slug}")
                continue

            cursor.execute(
                """
                INSERT INTO pages
                    (site_id, page_name, slug, template_id, sections, metadata, published)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    domain,
                    page.get("pageName", slug),
                    slug,
                    page.get("templateId"),
                    json.dumps({}),
                    json.dumps(
                        {"title": f"{page.get('pageName', slug)} - {site_name}"}
                    ),
                    page.get("published", True),
                ),
            )
            created += 1
            logger.info(f"  ✅ Page created: {page.get('pageName')} ({slug})")

        conn.commit()
        logger.info(f"Created {created} pages for {domain}")
        return created

    except Exception as e:
        logger.error(f"Error creating pages for {domain}: {e}")
        conn.rollback()
        return 0

    finally:
        conn.close()


def get_pages_for_site(domain: str) -> list[dict]:
    """Return all pages registered for a given domain."""
    init_pages_table()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, page_name, slug, template_id, sections, metadata, published, created_at
        FROM pages WHERE site_id = ? ORDER BY created_at ASC
        """,
        (domain,),
    )
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "page_name": row[1],
            "slug": row[2],
            "template_id": row[3],
            "sections": json.loads(row[4] or "{}"),
            "metadata": json.loads(row[5] or "{}"),
            "published": bool(row[6]),
            "created_at": row[7],
        }
        for row in rows
    ]


def delete_pages_for_site(domain: str) -> int:
    """
    Remove all page records for a domain.

    Called when a site is deleted to keep the pages table clean.
    Returns number of rows deleted.
    """
    init_pages_table()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pages WHERE site_id = ?", (domain,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"Deleted {deleted} pages for {domain}")
    return deleted
