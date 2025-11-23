"""Database operations"""

import os
import sqlite3
import logging
from config.settings import CONFIG

logger = logging.getLogger(__name__)


def init_database():
    """Initialize SQLite database with all tables"""
    db_path = CONFIG["database_path"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    cursor.executescript(
        """
        -- ═══════════════════════════════════════════════════════════
        -- Core Tables (Next.js/Node.js Deployments)
        -- ═══════════════════════════════════════════════════════════
        
        CREATE TABLE IF NOT EXISTS domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain_name TEXT UNIQUE NOT NULL,
            port INTEGER UNIQUE,
            app_name TEXT,
            ssl_enabled BOOLEAN DEFAULT FALSE,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            port INTEGER,
            pid INTEGER,
            status TEXT DEFAULT 'stopped',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS deployment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain_name TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- ═══════════════════════════════════════════════════════════
        -- WordPress Tables (Docker-based WordPress Deployments)
        -- ═══════════════════════════════════════════════════════════
        
        CREATE TABLE IF NOT EXISTS wordpress_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_name TEXT UNIQUE NOT NULL,
            domain TEXT UNIQUE NOT NULL,
            port INTEGER UNIQUE NOT NULL,
            container_name TEXT UNIQUE NOT NULL,
            mysql_container TEXT NOT NULL,
            cli_container TEXT NOT NULL,
            admin_email TEXT NOT NULL,
            wp_version TEXT DEFAULT 'latest',
            php_version TEXT DEFAULT '8.1',
            status TEXT DEFAULT 'running',
            docker_compose_path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS wordpress_plugins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            plugin_name TEXT NOT NULL,
            plugin_version TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES wordpress_sites(id) ON DELETE CASCADE,
            UNIQUE(site_id, plugin_name)
        );
        
        CREATE TABLE IF NOT EXISTS wordpress_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            theme_name TEXT NOT NULL,
            is_active BOOLEAN DEFAULT FALSE,
            installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES wordpress_sites(id) ON DELETE CASCADE,
            UNIQUE(site_id, theme_name)
        );
        
        CREATE TABLE IF NOT EXISTS wordpress_cli_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            command TEXT NOT NULL,
            output TEXT,
            exit_code INTEGER,
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES wordpress_sites(id) ON DELETE CASCADE
        );
        
        -- ═══════════════════════════════════════════════════════════
        -- Indexes for Performance
        -- ═══════════════════════════════════════════════════════════
        
        CREATE INDEX IF NOT EXISTS idx_domains_status ON domains(status);
        CREATE INDEX IF NOT EXISTS idx_processes_status ON processes(status);
        CREATE INDEX IF NOT EXISTS idx_deployment_logs_domain ON deployment_logs(domain_name);
        CREATE INDEX IF NOT EXISTS idx_deployment_logs_action ON deployment_logs(action);
        
        CREATE INDEX IF NOT EXISTS idx_wp_sites_domain ON wordpress_sites(domain);
        CREATE INDEX IF NOT EXISTS idx_wp_sites_status ON wordpress_sites(status);
        CREATE INDEX IF NOT EXISTS idx_wp_plugins_site ON wordpress_plugins(site_id);
        CREATE INDEX IF NOT EXISTS idx_wp_themes_site ON wordpress_themes(site_id);
        CREATE INDEX IF NOT EXISTS idx_wp_cli_history_site ON wordpress_cli_history(site_id);
    """
    )

    conn.commit()
    conn.close()

    logger.info(f"✅ Database initialized: {db_path}")
    logger.info("   - Core tables: domains, processes, deployment_logs")
    logger.info(
        "   - WordPress tables: wordpress_sites, wordpress_plugins, wordpress_themes, wordpress_cli_history"
    )


def get_db():
    """Get database connection"""
    return sqlite3.connect(CONFIG["database_path"], timeout=30.0)
