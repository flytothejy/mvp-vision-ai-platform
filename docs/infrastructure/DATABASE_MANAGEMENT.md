# Database Management

This document describes the database architecture and management responsibilities for the Vision AI Training Platform.

## Architecture Overview

### Single PostgreSQL Instance, Multiple Databases

The platform uses **one PostgreSQL instance with three separate databases** for logical separation while maintaining resource efficiency.

```
PostgreSQL Instance (localhost:5432)
├── platform   (managed by Platform team)
├── users      (managed by Platform team, shared with Labeler)
└── labeler    (managed by Labeler team)
```

**Benefits of this approach:**
- ✅ Resource efficiency (one PostgreSQL process instead of three)
- ✅ Simplified management (one container, one backup/restore process)
- ✅ Standard PostgreSQL practice (most projects use this pattern)
- ✅ Logical isolation (databases cannot query each other directly)
- ✅ Simplified port management (single port 5432)

**When to use separate instances:**
- Multi-tenancy with strict data isolation requirements
- Compliance requirements (financial, healthcare)
- Extreme performance isolation needs

## Database Responsibilities

### Platform Team (우리)

**Infrastructure Management:**
- PostgreSQL instance operation (Docker Compose, production deployment)
- Database creation (empty databases for all teams)
- Backup and restoration policies
- Resource monitoring and optimization
- Access credential management

**Schema Management:**
1. **`platform` database**
   - Purpose: Platform metadata and operations
   - Tables: training_jobs, experiments, sessions, messages, metrics, logs, validation_results, test_runs, inference_jobs, export_jobs, deployments
   - Migration tool: `platform/backend/init_db.py`

2. **`users` database**
   - Purpose: User authentication (shared with Labeler)
   - Tables: users, organizations, invitations, project_members
   - Migration tool: `platform/backend/init_db.py`
   - Access: Platform (full), Labeler (read-only for auth)

### Labeler Team

**Schema Management:**
- **`labeler` database**
  - Purpose: Dataset annotations and labeling operations
  - Tables: datasets, annotations, splits, etc. (Labeler schema)
  - Migration tool: `labeler/init_db.py` (Labeler team maintains)
  - Access: Platform cannot directly query this database (API-only communication)

## Connection Information

### Local Development

```bash
# Platform Database
DATABASE_URL=postgresql://admin:devpass@localhost:5432/platform

# Users Database (shared)
USER_DATABASE_URL=postgresql://admin:devpass@localhost:5432/users

# Labeler Database (Labeler team)
LABELER_DATABASE_URL=postgresql://admin:devpass@localhost:5432/labeler
```

### Production

Production uses the same single-instance pattern:

```bash
# Example: AWS RDS
RDS_ENDPOINT=vision-platform-prod.xxxxx.rds.amazonaws.com:5432

# Platform Database
DATABASE_URL=postgresql://platform_user:***@${RDS_ENDPOINT}/platform

# Users Database
USER_DATABASE_URL=postgresql://users_user:***@${RDS_ENDPOINT}/users

# Labeler Database
LABELER_DATABASE_URL=postgresql://labeler_user:***@${RDS_ENDPOINT}/labeler
```

**Production Best Practices:**
- Use separate credentials for each database (platform_user, users_user, labeler_user)
- Grant minimum required privileges (e.g., Labeler gets read-only on `users`)
- Enable SSL connections
- Configure connection pooling (PgBouncer recommended)

## Database Initialization

### Local Development Setup

**1. Start Infrastructure (Platform team)**

```bash
cd platform/infrastructure
docker-compose up -d
```

This automatically creates all three databases via `init-databases.sh`:
- ✅ `platform` (default database)
- ✅ `users` (created by init script)
- ✅ `labeler` (created by init script)

**2. Initialize Platform Schemas (Platform team)**

```bash
cd platform/backend

# Initialize both Platform and Users databases
python init_db.py

# Or initialize selectively
python init_db.py --platform-only
python init_db.py --user-only
```

**3. Initialize Labeler Schema (Labeler team)**

```bash
cd labeler

# Labeler team runs their own migration
python init_db.py  # or their equivalent tool
```

### Production Deployment

**1. Create PostgreSQL Instance**

```bash
# Example: AWS RDS
aws rds create-db-instance \
  --db-instance-identifier vision-platform-prod \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --engine-version 16.1 \
  --master-username admin \
  --master-user-password <secure-password> \
  --allocated-storage 100
```

**2. Create Databases**

```sql
-- Connect to default database
psql -h vision-platform-prod.xxxxx.rds.amazonaws.com -U admin -d postgres

-- Create databases
CREATE DATABASE platform;
CREATE DATABASE users;
CREATE DATABASE labeler;

-- Create users with specific privileges
CREATE USER platform_user WITH PASSWORD '<secure-password>';
CREATE USER users_user WITH PASSWORD '<secure-password>';
CREATE USER labeler_user WITH PASSWORD '<secure-password>';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE platform TO platform_user;
GRANT ALL PRIVILEGES ON DATABASE users TO users_user;
GRANT ALL PRIVILEGES ON DATABASE labeler TO labeler_user;

-- Grant Labeler read-only access to users database
GRANT CONNECT ON DATABASE users TO labeler_user;
\c users
GRANT USAGE ON SCHEMA public TO labeler_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO labeler_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO labeler_user;
```

**3. Initialize Schemas**

```bash
# Platform team
DATABASE_URL=postgresql://platform_user:***@<rds-endpoint>:5432/platform \
USER_DATABASE_URL=postgresql://users_user:***@<rds-endpoint>:5432/users \
python platform/backend/init_db.py

# Labeler team
DATABASE_URL=postgresql://labeler_user:***@<rds-endpoint>:5432/labeler \
python labeler/init_db.py
```

## Backup and Restoration

### Backup All Databases

```bash
# Local development
docker exec platform-postgres pg_dumpall -U admin > backup_all.sql

# Or backup individual databases
docker exec platform-postgres pg_dump -U admin -d platform > backup_platform.sql
docker exec platform-postgres pg_dump -U admin -d users > backup_users.sql
docker exec platform-postgres pg_dump -U admin -d labeler > backup_labeler.sql
```

### Restore Databases

```bash
# Restore all databases
docker exec -i platform-postgres psql -U admin < backup_all.sql

# Or restore individual databases
docker exec -i platform-postgres psql -U admin -d platform < backup_platform.sql
```

### Production Backup (AWS RDS Example)

```bash
# Automated snapshots (configured in RDS)
aws rds create-db-snapshot \
  --db-instance-identifier vision-platform-prod \
  --db-snapshot-identifier vision-platform-backup-$(date +%Y%m%d)

# Export to S3 for long-term storage
aws rds start-export-task \
  --export-task-identifier vision-platform-export-$(date +%Y%m%d) \
  --source-arn <snapshot-arn> \
  --s3-bucket-name vision-platform-backups \
  --iam-role-arn <iam-role-arn> \
  --kms-key-id <kms-key-id>
```

## Monitoring

### Local Development

```bash
# Check database status
docker exec platform-postgres psql -U admin -c "\l"

# Check table sizes
docker exec platform-postgres psql -U admin -d platform -c "
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"

# Check active connections
docker exec platform-postgres psql -U admin -c "
SELECT datname, count(*) as connections
FROM pg_stat_activity
GROUP BY datname;
"
```

### Production Monitoring

**Key Metrics:**
- Connection count per database
- Query performance (slow queries)
- Disk usage and I/O
- Cache hit ratio
- Replication lag (if using read replicas)

**Tools:**
- AWS CloudWatch (for RDS)
- PostgreSQL pg_stat_statements extension
- pgAdmin or similar GUI tools
- Custom monitoring dashboards (Grafana + Prometheus)

## Migration Strategy

### From Current Setup (3 containers → 1 instance)

**1. Backup Current Data**

```bash
# Backup Platform DB (port 5432)
docker exec platform-postgres pg_dump -U admin -d platform > backup_platform.sql

# Backup Users DB (port 5433)
docker exec platform-postgres-users pg_dump -U admin -d users > backup_users.sql
```

**2. Stop Old Containers**

```bash
cd platform/infrastructure
docker-compose down
```

**3. Update Configuration**

- ✅ Update `docker-compose.yml` (use new single-instance version)
- ✅ Update `.env` (change USER_DATABASE_URL port to 5432)
- ✅ Add `postgres/init-databases.sh`

**4. Start New Infrastructure**

```bash
docker-compose up -d
# Wait for PostgreSQL to be healthy
```

**5. Restore Data**

```bash
# Restore Platform database
docker exec -i platform-postgres psql -U admin -d platform < backup_platform.sql

# Restore Users database
docker exec -i platform-postgres psql -U admin -d users < backup_users.sql
```

**6. Verify**

```bash
# Check databases exist
docker exec platform-postgres psql -U admin -c "\l"

# Check tables
docker exec platform-postgres psql -U admin -d platform -c "\dt"
docker exec platform-postgres psql -U admin -d users -c "\dt"
```

## Troubleshooting

### Database Not Created

**Problem:** `labeler` database doesn't exist after starting Docker Compose.

**Solution:**
```bash
# Check if init script ran
docker logs platform-postgres | grep "init-databases.sh"

# If not, manually create databases
docker exec platform-postgres psql -U admin -d platform -c "CREATE DATABASE labeler;"
```

### Connection Refused

**Problem:** Cannot connect to PostgreSQL.

**Solution:**
```bash
# Check if container is running
docker ps | grep platform-postgres

# Check logs
docker logs platform-postgres

# Verify health check
docker inspect platform-postgres | grep -A 10 Health
```

### Permission Denied

**Problem:** User cannot access a database.

**Solution:**
```bash
# Grant necessary privileges
docker exec platform-postgres psql -U admin -c "
GRANT ALL PRIVILEGES ON DATABASE platform TO admin;
GRANT ALL PRIVILEGES ON DATABASE users TO admin;
GRANT ALL PRIVILEGES ON DATABASE labeler TO admin;
"
```

### Disk Space Issues

**Problem:** PostgreSQL container runs out of disk space.

**Solution:**
```bash
# Check volume usage
docker system df -v

# Clean up old data
docker volume prune

# For production, increase RDS storage
aws rds modify-db-instance \
  --db-instance-identifier vision-platform-prod \
  --allocated-storage 200 \
  --apply-immediately
```

## Security Best Practices

### Development

- ✅ Use default credentials (`admin/devpass`) - acceptable for local dev
- ✅ Don't expose PostgreSQL port publicly (only localhost)
- ✅ Keep Docker daemon updated

### Production

- ✅ Use strong, unique passwords for each database user
- ✅ Enable SSL/TLS for all connections
- ✅ Use separate credentials per database (platform_user, users_user, labeler_user)
- ✅ Grant minimum required privileges
- ✅ Enable audit logging
- ✅ Use AWS Secrets Manager or similar for credential management
- ✅ Rotate credentials regularly
- ✅ Restrict network access (VPC, security groups)
- ✅ Enable automated backups
- ✅ Enable point-in-time recovery

## Summary

### Key Principles

1. **Single Instance, Multiple Databases**: Resource efficient, standard practice
2. **Clear Ownership**: Each team manages their own database schema
3. **API-Only Communication**: Teams don't query each other's databases directly
4. **Infrastructure Sharing**: Platform team provides PostgreSQL instance
5. **Schema Independence**: Each team uses their own migration tools

### Quick Reference

| Aspect | Platform Team | Labeler Team |
|--------|--------------|--------------|
| **Infrastructure** | ✅ Manages | ❌ Uses |
| **`platform` DB** | ✅ Full control | ❌ No access |
| **`users` DB** | ✅ Full control | ✅ Read-only |
| **`labeler` DB** | ❌ No access | ✅ Full control |
| **Backup/Restore** | ✅ Responsible | ❌ Not responsible |
| **Migration Tool** | `init_db.py` | `labeler/init_db.py` |

### Contact

For database infrastructure questions, contact the Platform team.
For Labeler schema questions, contact the Labeler team.
