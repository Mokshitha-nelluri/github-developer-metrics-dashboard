-- ================================================================================
-- AWS RDS POSTGRESQL SETUP DOCUMENTATION
-- GitHub Metrics Dashboard - Production Database Schema
-- ================================================================================
-- 
-- This file documents the complete AWS RDS PostgreSQL setup used for the
-- GitHub Metrics Dashboard production deployment. It serves as a reference
-- for database setup, schema creation, and maintenance procedures.
--
-- Created: August 2025
-- Environment: AWS RDS PostgreSQL (Production)
-- Purpose: Documentation and disaster recovery reference
-- ================================================================================

-- ================================================================================
-- TABLE OF CONTENTS
-- ================================================================================
-- 1. AWS RDS INSTANCE SETUP COMMANDS
-- 2. DATABASE SCHEMA CREATION
-- 3. PERFORMANCE INDEXES
-- 4. SCHEMA UPDATES AND FIXES
-- 5. MAINTENANCE PROCEDURES
-- 6. TROUBLESHOOTING QUERIES
-- ================================================================================

-- ================================================================================
-- 1. AWS RDS INSTANCE SETUP COMMANDS
-- ================================================================================
-- 
-- The following AWS CLI commands were used to create the RDS instance.
-- These are documented here for reference and disaster recovery purposes.
--
-- Command to create RDS PostgreSQL instance:
-- aws rds create-db-instance \
--     --db-instance-identifier github-metrics-prod \
--     --db-instance-class db.t3.micro \
--     --engine postgres \
--     --engine-version 14.9 \
--     --master-username postgres \
--     --master-user-password [SECURE_PASSWORD] \
--     --allocated-storage 20 \
--     --storage-type gp2 \
--     --vpc-security-group-ids sg-xxxxxxxxx \
--     --db-subnet-group-name default \
--     --backup-retention-period 7 \
--     --storage-encrypted \
--     --deletion-protection \
--     --region us-east-1
--
-- Security Group Configuration:
-- - Inbound: PostgreSQL (5432) from ECS security group
-- - Outbound: All traffic allowed
--
-- Environment Variables Required:
-- - DATABASE_URL=postgresql://postgres:[PASSWORD]@[RDS_ENDPOINT]:5432/postgres
-- - AWS_REGION=us-east-1
-- ================================================================================

-- ================================================================================
-- 2. DATABASE SCHEMA CREATION (CORE TABLES)
-- ================================================================================
-- This schema was optimized for AWS RDS without Row Level Security (RLS)
-- since authentication is handled at the application level.

-- Enable UUID extension for primary keys
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ================================
-- 2.1 USERS TABLE
-- ================================
CREATE TABLE IF NOT EXISTS users (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    github_token TEXT,
    github_username TEXT,
    last_sync TIMESTAMP WITH TIME ZONE,
    settings JSONB DEFAULT '{}'::jsonb
);

-- ================================
-- 2.2 REPOSITORIES TABLE
-- ================================
CREATE TABLE IF NOT EXISTS repos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT UNIQUE NOT NULL,
    description TEXT,
    url TEXT,
    clone_url TEXT,
    ssh_url TEXT,
    homepage TEXT,
    size INTEGER DEFAULT 0,
    stargazers_count INTEGER DEFAULT 0,
    watchers_count INTEGER DEFAULT 0,
    language TEXT,
    has_issues BOOLEAN DEFAULT TRUE,
    has_projects BOOLEAN DEFAULT TRUE,
    has_wiki BOOLEAN DEFAULT TRUE,
    has_pages BOOLEAN DEFAULT FALSE,
    forks_count INTEGER DEFAULT 0,
    archived BOOLEAN DEFAULT FALSE,
    disabled BOOLEAN DEFAULT FALSE,
    open_issues_count INTEGER DEFAULT 0,
    license JSONB,
    allow_forking BOOLEAN DEFAULT TRUE,
    is_template BOOLEAN DEFAULT FALSE,
    web_commit_signoff_required BOOLEAN DEFAULT FALSE,
    topics TEXT[],
    visibility TEXT DEFAULT 'public',
    default_branch TEXT DEFAULT 'main',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    pushed_at TIMESTAMP WITH TIME ZONE
);

-- ================================
-- 2.3 USER_REPOS JUNCTION TABLE
-- ================================
-- Links users to their repositories with role-based access
CREATE TABLE IF NOT EXISTS user_repos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    role TEXT DEFAULT 'owner',
    permissions JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, repo_id)
);

-- ================================
-- 2.4 USER METRICS TABLE
-- ================================
-- Stores daily aggregated metrics for each user
CREATE TABLE IF NOT EXISTS metrics_user (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    total_commits INTEGER DEFAULT 0,
    total_prs INTEGER DEFAULT 0,
    total_issues INTEGER DEFAULT 0,
    contributions_score DECIMAL(10,2) DEFAULT 0,
    repos_contributed INTEGER DEFAULT 0,
    languages JSONB DEFAULT '{}'::jsonb,
    activity_score DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- Additional columns added during schema evolution:
    metrics_data JSONB DEFAULT '{}'::jsonb,
    metric_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, date)
);

-- ================================
-- 2.5 REPOSITORY METRICS TABLE
-- ================================
-- Stores daily aggregated metrics for each repository
CREATE TABLE IF NOT EXISTS metrics_repo (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    watchers INTEGER DEFAULT 0,
    issues INTEGER DEFAULT 0,
    pull_requests INTEGER DEFAULT 0,
    contributors INTEGER DEFAULT 0,
    commits INTEGER DEFAULT 0,
    releases INTEGER DEFAULT 0,
    health_score DECIMAL(10,2) DEFAULT 0,
    activity_score DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(repo_id, date)
);

-- ================================================================================
-- 3. PERFORMANCE INDEXES
-- ================================================================================
-- These indexes are critical for query performance in production

-- User table indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_github_username ON users(github_username);
CREATE INDEX IF NOT EXISTS idx_users_last_sync ON users(last_sync);

-- Repository table indexes
CREATE INDEX IF NOT EXISTS idx_repos_full_name ON repos(full_name);
CREATE INDEX IF NOT EXISTS idx_repos_owner ON repos(owner);
CREATE INDEX IF NOT EXISTS idx_repos_language ON repos(language);
CREATE INDEX IF NOT EXISTS idx_repos_created_at ON repos(created_at);

-- Junction table indexes
CREATE INDEX IF NOT EXISTS idx_user_repos_user_id ON user_repos(user_id);
CREATE INDEX IF NOT EXISTS idx_user_repos_repo_id ON user_repos(repo_id);
CREATE INDEX IF NOT EXISTS idx_user_repos_role ON user_repos(role);

-- User metrics indexes (critical for dashboard performance)
CREATE INDEX IF NOT EXISTS idx_metrics_user_user_id ON metrics_user(user_id);
CREATE INDEX IF NOT EXISTS idx_metrics_user_date ON metrics_user(date);
CREATE INDEX IF NOT EXISTS idx_metrics_user_timestamp ON metrics_user(metric_timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_user_user_date ON metrics_user(user_id, date);

-- Repository metrics indexes
CREATE INDEX IF NOT EXISTS idx_metrics_repo_repo_id ON metrics_repo(repo_id);
CREATE INDEX IF NOT EXISTS idx_metrics_repo_date ON metrics_repo(date);
CREATE INDEX IF NOT EXISTS idx_metrics_repo_repo_date ON metrics_repo(repo_id, date);

-- JSONB indexes for faster queries on JSON columns
CREATE INDEX IF NOT EXISTS idx_users_settings_gin ON users USING GIN (settings);
CREATE INDEX IF NOT EXISTS idx_metrics_user_languages_gin ON metrics_user USING GIN (languages);
CREATE INDEX IF NOT EXISTS idx_metrics_user_data_gin ON metrics_user USING GIN (metrics_data);

-- ================================================================================
-- 4. SCHEMA UPDATES AND FIXES
-- ================================================================================
-- These updates were applied to fix issues discovered during development

-- Fix 1: Add missing metrics_data column for comprehensive metrics storage
-- Applied: During development phase
ALTER TABLE metrics_user ADD COLUMN IF NOT EXISTS metrics_data JSONB DEFAULT '{}'::jsonb;

-- Fix 2: Add metric_timestamp column for better time-based queries
-- Applied: During development phase
ALTER TABLE metrics_user ADD COLUMN IF NOT EXISTS metric_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Fix 3: Update existing records to have metric_timestamp
-- Applied: During development phase
UPDATE metrics_user 
SET metric_timestamp = updated_at 
WHERE metric_timestamp IS NULL;

-- ================================================================================
-- 5. MAINTENANCE PROCEDURES
-- ================================================================================

-- ================================
-- 5.1 DATABASE CLEANUP PROCEDURE
-- ================================
-- Use this to clear all data while preserving schema structure
-- CAUTION: This will delete ALL user data!

-- Clear metrics tables first (they have foreign keys)
-- DELETE FROM metrics_repo;
-- DELETE FROM metrics_user;
-- 
-- Clear junction table
-- DELETE FROM user_repos;
-- 
-- Clear main entity tables
-- DELETE FROM repos;
-- DELETE FROM users;

-- ================================
-- 5.2 DATA VERIFICATION QUERIES
-- ================================
-- Use these queries to verify database state after operations

-- Check table record counts
SELECT 
    'users' as table_name, COUNT(*) as record_count FROM users
UNION ALL
SELECT 
    'repos' as table_name, COUNT(*) as record_count FROM repos
UNION ALL
SELECT 
    'user_repos' as table_name, COUNT(*) as record_count FROM user_repos
UNION ALL
SELECT 
    'metrics_user' as table_name, COUNT(*) as record_count FROM metrics_user
UNION ALL
SELECT 
    'metrics_repo' as table_name, COUNT(*) as record_count FROM metrics_repo;

-- ================================
-- 5.3 VACUUM AND ANALYZE
-- ================================
-- Run periodically for optimal performance
-- VACUUM ANALYZE users;
-- VACUUM ANALYZE repos;
-- VACUUM ANALYZE user_repos;
-- VACUUM ANALYZE metrics_user;
-- VACUUM ANALYZE metrics_repo;

-- ================================================================================
-- 6. TROUBLESHOOTING QUERIES
-- ================================================================================

-- ================================
-- 6.1 USER DATA INSPECTION
-- ================================
-- Find users with missing GitHub tokens
SELECT id, email, github_username, github_token IS NOT NULL as has_token
FROM users
WHERE github_token IS NULL OR github_username IS NULL;

-- Check user metrics coverage
SELECT 
    u.email,
    u.github_username,
    COUNT(mu.id) as metrics_count,
    MAX(mu.date) as latest_metrics,
    MIN(mu.date) as earliest_metrics
FROM users u
LEFT JOIN metrics_user mu ON u.id = mu.user_id
GROUP BY u.id, u.email, u.github_username
ORDER BY metrics_count DESC;

-- ================================
-- 6.2 REPOSITORY DATA INSPECTION
-- ================================
-- Find repositories without metrics
SELECT r.full_name, r.owner, r.language, COUNT(mr.id) as metrics_count
FROM repos r
LEFT JOIN metrics_repo mr ON r.id = mr.repo_id
GROUP BY r.id, r.full_name, r.owner, r.language
HAVING COUNT(mr.id) = 0;

-- Check repository metrics trends
SELECT 
    r.full_name,
    COUNT(mr.id) as total_metrics,
    AVG(mr.stars) as avg_stars,
    AVG(mr.health_score) as avg_health_score,
    MAX(mr.date) as latest_metrics
FROM repos r
LEFT JOIN metrics_repo mr ON r.id = mr.repo_id
GROUP BY r.id, r.full_name
ORDER BY avg_health_score DESC NULLS LAST;

-- ================================
-- 6.3 PERFORMANCE MONITORING
-- ================================
-- Check index usage
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- Check table sizes
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size(tablename::regclass)) as total_size,
    pg_size_pretty(pg_relation_size(tablename::regclass)) as table_size,
    pg_size_pretty(pg_total_relation_size(tablename::regclass) - pg_relation_size(tablename::regclass)) as index_size
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(tablename::regclass) DESC;

-- ================================================================================
-- 7. BACKUP AND DISASTER RECOVERY
-- ================================================================================

-- ================================
-- 7.1 BACKUP STRATEGY
-- ================================
-- AWS RDS Automated Backups:
-- - Daily automated backups with 7-day retention
-- - Point-in-time recovery enabled
-- - Backup window: 03:00-04:00 UTC
-- - Maintenance window: Sun 04:00-05:00 UTC

-- Manual snapshot command (AWS CLI):
-- aws rds create-db-snapshot \
--     --db-instance-identifier github-metrics-prod \
--     --db-snapshot-identifier github-metrics-manual-$(date +%Y%m%d-%H%M%S) \
--     --region us-east-1

-- ================================
-- 7.2 DISASTER RECOVERY
-- ================================
-- To restore from backup:
-- 1. Create new RDS instance from snapshot
-- 2. Update DATABASE_URL environment variable
-- 3. Apply any schema updates if needed
-- 4. Restart application services

-- ================================================================================
-- 8. MONITORING AND ALERTS
-- ================================================================================

-- ================================
-- 8.1 KEY METRICS TO MONITOR
-- ================================
-- - Connection count: Should stay below 80% of max_connections
-- - CPU utilization: Target < 70%
-- - Free storage space: Alert when < 20%
-- - Read/Write IOPS: Monitor for bottlenecks
-- - Database connections: Monitor for connection leaks

-- ================================
-- 8.2 HEALTH CHECK QUERIES
-- ================================
-- Check current connections
SELECT 
    COUNT(*) as total_connections,
    COUNT(*) FILTER (WHERE state = 'active') as active_connections,
    COUNT(*) FILTER (WHERE state = 'idle') as idle_connections
FROM pg_stat_activity
WHERE datname = current_database();

-- Check long-running queries
SELECT 
    pid,
    now() - pg_stat_activity.query_start AS duration,
    query,
    state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes'
AND state = 'active'
ORDER BY duration DESC;

-- ================================================================================
-- END OF AWS RDS SETUP DOCUMENTATION
-- ================================================================================
-- 
-- This file serves as the complete reference for the AWS RDS PostgreSQL setup
-- used in the GitHub Metrics Dashboard production environment.
-- 
-- For questions or updates, refer to:
-- - config.py (application configuration)
-- - AWS_PRODUCTION_ARCHITECTURE.md (infrastructure overview)
-- - DEPLOYMENT_GUIDE.md (deployment procedures)
-- ================================================================================
