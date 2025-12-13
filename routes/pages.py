"""
Pages endpoints - Page Builder System
Handles page creation, editing, and management for custom site pages
"""

from flask import request, jsonify
import json
from datetime import datetime
from services.database import get_db


def init_pages_table():
    """Initialize the pages table in the database"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id TEXT NOT NULL,
            page_name TEXT NOT NULL,
            slug TEXT NOT NULL,
            template_id TEXT NOT NULL,
            sections TEXT NOT NULL,
            metadata TEXT,
            published BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(site_id, slug)
        )
    """
    )

    conn.commit()
    conn.close()


def register_routes(app):
    """Register page management routes"""

    # Initialize the pages table
    init_pages_table()

    # ============================================================
    # GET: List all pages for a site
    # ============================================================
    @app.route("/api/pages", methods=["GET"])
    def get_pages():
        """Get all pages for a site"""
        site_id = request.args.get("site_id", type=str)

        if not site_id:
            return jsonify({"error": "site_id is required"}), 400

        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, page_name, slug, template_id, published, created_at, updated_at
                FROM pages
                WHERE site_id = ?
                ORDER BY created_at DESC
            """,
                (site_id,),
            )

            pages = []
            for row in cursor.fetchall():
                pages.append(
                    {
                        "id": row[0],
                        "pageName": row[1],
                        "slug": row[2],
                        "templateId": row[3],
                        "published": bool(row[4]),
                        "createdAt": row[5],
                        "updatedAt": row[6],
                    }
                )

            conn.close()
            return jsonify(pages)

        except Exception as e:
            app.logger.error(f"Error fetching pages: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # GET: Get a specific page by ID
    # ============================================================
    @app.route("/api/pages/<int:page_id>", methods=["GET"])
    def get_page(page_id):
        """Get a specific page by ID"""
        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM pages WHERE id = ?", (page_id,))
            row = cursor.fetchone()
            conn.close()

            if not row:
                return jsonify({"error": "Page not found"}), 404

            page_data = {
                "id": row[0],
                "siteId": row[1],
                "pageName": row[2],
                "slug": row[3],
                "templateId": row[4],
                "sections": json.loads(row[5]),
                "metadata": json.loads(row[6]) if row[6] else None,
                "published": bool(row[7]),
                "createdAt": row[8],
                "updatedAt": row[9],
            }

            return jsonify(page_data)

        except Exception as e:
            app.logger.error(f"Error fetching page {page_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # POST: Create a new page
    # ============================================================
    @app.route("/api/pages", methods=["POST"])
    def create_page():
        """Create a new page"""
        data = request.json

        # Validate required fields
        required_fields = ["siteId", "pageName", "slug", "templateId", "sections"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400

        try:
            conn = get_db()
            cursor = conn.cursor()

            # Check if slug already exists for this site
            cursor.execute(
                "SELECT id FROM pages WHERE site_id = ? AND slug = ?",
                (data["siteId"], data["slug"]),
            )

            if cursor.fetchone():
                conn.close()
                return jsonify({"error": "A page with this slug already exists"}), 400

            # Insert new page
            cursor.execute(
                """
                INSERT INTO pages (
                    site_id, page_name, slug, template_id, sections, metadata, published
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    data["siteId"],
                    data["pageName"],
                    data["slug"],
                    data["templateId"],
                    json.dumps(data["sections"]),
                    json.dumps(data.get("metadata")) if data.get("metadata") else None,
                    data.get("published", False),
                ),
            )

            page_id = cursor.lastrowid
            conn.commit()
            conn.close()

            app.logger.info(f"✅ Page created: {data['pageName']} (ID: {page_id})")

            return jsonify({"id": page_id, "message": "Page created successfully"}), 201

        except Exception as e:
            app.logger.error(f"Error creating page: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # PUT: Update an existing page
    # ============================================================
    @app.route("/api/pages/<int:page_id>", methods=["PUT"])
    def update_page(page_id):
        """Update an existing page"""
        data = request.json

        try:
            conn = get_db()
            cursor = conn.cursor()

            # Check if page exists
            cursor.execute("SELECT id, site_id FROM pages WHERE id = ?", (page_id,))
            existing = cursor.fetchone()

            if not existing:
                conn.close()
                return jsonify({"error": "Page not found"}), 404

            site_id = existing[1]

            # If slug is being updated, check for conflicts
            if "slug" in data:
                cursor.execute(
                    """
                    SELECT id FROM pages 
                    WHERE site_id = ? AND slug = ? AND id != ?
                """,
                    (site_id, data["slug"], page_id),
                )

                if cursor.fetchone():
                    conn.close()
                    return (
                        jsonify({"error": "A page with this slug already exists"}),
                        400,
                    )

            # Build update query dynamically based on provided fields
            update_fields = []
            update_values = []

            field_mapping = {
                "pageName": "page_name",
                "slug": "slug",
                "templateId": "template_id",
                "sections": "sections",
                "metadata": "metadata",
                "published": "published",
            }

            for json_field, db_field in field_mapping.items():
                if json_field in data:
                    update_fields.append(f"{db_field} = ?")

                    if json_field in ["sections", "metadata"]:
                        update_values.append(json.dumps(data[json_field]))
                    else:
                        update_values.append(data[json_field])

            # Always update the updated_at timestamp
            update_fields.append("updated_at = ?")
            update_values.append(datetime.now().isoformat())

            # Add page_id for WHERE clause
            update_values.append(page_id)

            # Execute update
            query = f"UPDATE pages SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, update_values)

            conn.commit()
            conn.close()

            app.logger.info(f"✅ Page updated: ID {page_id}")

            return jsonify({"id": page_id, "message": "Page updated successfully"})

        except Exception as e:
            app.logger.error(f"Error updating page {page_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # DELETE: Delete a page
    # ============================================================
    @app.route("/api/pages/<int:page_id>", methods=["DELETE"])
    def delete_page(page_id):
        """Delete a page"""
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Check if page exists
            cursor.execute("SELECT page_name FROM pages WHERE id = ?", (page_id,))
            existing = cursor.fetchone()

            if not existing:
                conn.close()
                return jsonify({"error": "Page not found"}), 404

            page_name = existing[0]

            # Delete the page
            cursor.execute("DELETE FROM pages WHERE id = ?", (page_id,))
            conn.commit()
            conn.close()

            app.logger.info(f"✅ Page deleted: {page_name} (ID: {page_id})")

            return jsonify({"message": "Page deleted successfully"})

        except Exception as e:
            app.logger.error(f"Error deleting page {page_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # POST: Publish or unpublish a page
    # ============================================================
    @app.route("/api/pages/<int:page_id>/publish", methods=["POST"])
    def publish_page(page_id):
        """Publish or unpublish a page"""
        data = request.json
        published = data.get("published", True)

        try:
            conn = get_db()
            cursor = conn.cursor()

            # Check if page exists
            cursor.execute("SELECT page_name FROM pages WHERE id = ?", (page_id,))
            existing = cursor.fetchone()

            if not existing:
                conn.close()
                return jsonify({"error": "Page not found"}), 404

            page_name = existing[0]

            # Update published status
            cursor.execute(
                """
                UPDATE pages 
                SET published = ?, updated_at = ?
                WHERE id = ?
            """,
                (published, datetime.now().isoformat(), page_id),
            )

            conn.commit()
            conn.close()

            status = "published" if published else "unpublished"
            app.logger.info(f"✅ Page {status}: {page_name} (ID: {page_id})")

            return jsonify({"message": f"Page {status} successfully"})

        except Exception as e:
            app.logger.error(f"Error publishing page {page_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # GET: Get page by slug (for rendering on the website)
    # ============================================================
    @app.route("/api/pages/by-slug", methods=["GET"])
    def get_page_by_slug():
        """Get a page by site ID and slug (for rendering)"""
        site_id = request.args.get("site_id", type=str)
        slug = request.args.get("slug", type=str)

        if not site_id or not slug:
            return jsonify({"error": "site_id and slug are required"}), 400

        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM pages 
                WHERE site_id = ? AND slug = ? AND published = 1
            """,
                (site_id, slug),
            )

            row = cursor.fetchone()
            conn.close()

            if not row:
                return jsonify({"error": "Page not found"}), 404

            page_data = {
                "id": row[0],
                "siteId": row[1],
                "pageName": row[2],
                "slug": row[3],
                "templateId": row[4],
                "sections": json.loads(row[5]),
                "metadata": json.loads(row[6]) if row[6] else None,
                "published": bool(row[7]),
            }

            return jsonify(page_data)

        except Exception as e:
            app.logger.error(f"Error fetching page by slug: {e}")
            return jsonify({"error": str(e)}), 500
