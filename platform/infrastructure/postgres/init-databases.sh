#!/bin/bash
# ================================
# PostgreSQL Database Initialization Script
# ================================
#
# This script creates multiple databases in a single PostgreSQL instance.
# It runs automatically when the container starts for the first time.
#
# Databases created:
#   - platform: Platform metadata (managed by Platform team)
#   - users: User authentication (managed by Platform team, shared with Labeler)
#   - labeler: Dataset annotations (managed by Labeler team)

set -e

echo "================================"
echo "Initializing PostgreSQL databases"
echo "================================"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- ==========================================
    -- Platform Team Databases
    -- ==========================================

    -- Users Database (shared authentication)
    CREATE DATABASE users;
    GRANT ALL PRIVILEGES ON DATABASE users TO $POSTGRES_USER;

    -- ==========================================
    -- Labeler Team Database
    -- ==========================================

    -- Labeler Database (schema managed by Labeler team)
    CREATE DATABASE labeler;
    GRANT ALL PRIVILEGES ON DATABASE labeler TO $POSTGRES_USER;

    -- ==========================================
    -- Summary
    -- ==========================================

    \echo ''
    \echo '✅ Databases created successfully:'
    \echo ''
    \echo '  1. platform (default) - Platform metadata'
    \echo '     - Managed by: Platform team'
    \echo '     - Tables: training_jobs, experiments, metrics, etc.'
    \echo ''
    \echo '  2. users - User authentication'
    \echo '     - Managed by: Platform team'
    \echo '     - Shared with: Labeler (read-only access)'
    \echo '     - Tables: users, organizations, invitations, etc.'
    \echo ''
    \echo '  3. labeler - Dataset annotations'
    \echo '     - Managed by: Labeler team'
    \echo '     - Tables: datasets, annotations, etc. (Labeler schema)'
    \echo ''
    \echo 'Connection URLs:'
    \echo '  - Platform: postgresql://admin:devpass@localhost:5432/platform'
    \echo '  - Users:    postgresql://admin:devpass@localhost:5432/users'
    \echo '  - Labeler:  postgresql://admin:devpass@localhost:5432/labeler'
    \echo ''
EOSQL

echo ""
echo "================================"
echo "Database initialization complete"
echo "================================"
