-- ================================
-- GITHUB METRICS DASHBOARD - COMPLETE DATABASE SCHEMA
-- ================================
-- This file contains all SQL queries and schema definitions for the GitHub Metrics Dashboard
-- Compatible with both Supabase PostgreSQL and AWS RDS PostgreSQL
-- Version: 2.0
-- Last Updated: 2025-01-31

-- ================================
-- 0. REQUIRED EXTENSIONS
-- ================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ================================
-- 1. USERS TABLE
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

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Drop existing policies first
DROP POLICY IF EXISTS "Users can view own data" ON users;
DROP POLICY IF EXISTS "Users can update own data" ON users;
DROP POLICY IF EXISTS "Users can insert own data" ON users;

-- Recreate policies with service_role access
CREATE POLICY "Users can view own data" ON users
    FOR SELECT USING (auth.role() = 'service_role' OR auth.jwt() ->> 'email' = email);

CREATE POLICY "Users can update own data" ON users
    FOR UPDATE USING (auth.role() = 'service_role' OR auth.jwt() ->> 'email' = email);

CREATE POLICY "Users can insert own data" ON users
    FOR INSERT WITH CHECK (auth.role() = 'service_role' OR auth.jwt() ->> 'email' = email);

-- ================================
-- 2. REPOSITORIES TABLE
-- ================================
CREATE TABLE IF NOT EXISTS repos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT UNIQUE NOT NULL,
    description TEXT,
    private BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_fetched TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb,
    UNIQUE(owner, name)
);

ALTER TABLE repos ENABLE ROW LEVEL SECURITY;

-- Drop existing policies
DROP POLICY IF EXISTS "Authenticated users can view repos" ON repos;
DROP POLICY IF EXISTS "Authenticated users can insert repos" ON repos;
DROP POLICY IF EXISTS "Authenticated users can update repos" ON repos;

-- Recreate policies
CREATE POLICY "Authenticated users can view repos" ON repos
    FOR SELECT USING (auth.role() = 'service_role' OR auth.role() = 'authenticated');

CREATE POLICY "Authenticated users can insert repos" ON repos
    FOR INSERT WITH CHECK (auth.role() = 'service_role' OR auth.role() = 'authenticated');

CREATE POLICY "Authenticated users can update repos" ON repos
    FOR UPDATE USING (auth.role() = 'service_role' OR auth.role() = 'authenticated');

-- ================================
-- 3. USER_REPOS TABLE
-- ================================
CREATE TABLE IF NOT EXISTS user_repos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    settings JSONB DEFAULT '{}'::jsonb,
    UNIQUE(user_id, repo_id)
);

ALTER TABLE user_repos ENABLE ROW LEVEL SECURITY;

-- Drop existing policies
DROP POLICY IF EXISTS "Users can view own repo associations" ON user_repos;
DROP POLICY IF EXISTS "Users can manage own repo associations" ON user_repos;

-- Recreate policies
CREATE POLICY "Users can view own repo associations" ON user_repos
    FOR SELECT USING (
        auth.role() = 'service_role' OR
        user_id IN (
            SELECT id FROM users WHERE email = auth.jwt() ->> 'email'
        )
    );

CREATE POLICY "Users can manage own repo associations" ON user_repos
    FOR ALL USING (
        auth.role() = 'service_role' OR
        user_id IN (
            SELECT id FROM users WHERE email = auth.jwt() ->> 'email'
        )
    );

-- ================================
-- 4. METRICS_USER TABLE
-- ================================
CREATE TABLE IF NOT EXISTS metrics_user (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metrics_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE metrics_user ENABLE ROW LEVEL SECURITY;

-- Drop existing policies
DROP POLICY IF EXISTS "Users can view own metrics" ON metrics_user;
DROP POLICY IF EXISTS "Users can insert own metrics" ON metrics_user;

-- Recreate policies
CREATE POLICY "Users can view own metrics" ON metrics_user
    FOR SELECT USING (
        auth.role() = 'service_role' OR
        user_id IN (
            SELECT id FROM users WHERE email = auth.jwt() ->> 'email'
        )
    );

CREATE POLICY "Users can insert own metrics" ON metrics_user
    FOR INSERT WITH CHECK (
        auth.role() = 'service_role' OR
        user_id IN (
            SELECT id FROM users WHERE email = auth.jwt() ->> 'email'
        )
    );

-- ================================
-- 5. METRICS_REPO TABLE
-- ================================
CREATE TABLE IF NOT EXISTS metrics_repo (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metrics_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

ALTER TABLE metrics_repo ENABLE ROW LEVEL SECURITY;

-- Drop existing policies
DROP POLICY IF EXISTS "Users can view metrics for their repos" ON metrics_repo;
DROP POLICY IF EXISTS "Users can insert metrics for their repos" ON metrics_repo;

-- Recreate policies
CREATE POLICY "Users can view metrics for their repos" ON metrics_repo
    FOR SELECT USING (
        auth.role() = 'service_role' OR
        user_id IN (
            SELECT id FROM users WHERE email = auth.jwt() ->> 'email'
        )
    );

CREATE POLICY "Users can insert metrics for their repos" ON metrics_repo
    FOR INSERT WITH CHECK (
        auth.role() = 'service_role' OR
        user_id IN (
            SELECT id FROM users WHERE email = auth.jwt() ->> 'email'
        )
    );

-- ================================
-- 6. AWS/DIRECT POSTGRESQL TABLES (for AWS deployment)
-- ================================
-- Alternative table structures for direct PostgreSQL access (without Supabase auth)

-- Alternative user metrics table for AWS deployment
CREATE TABLE IF NOT EXISTS user_metrics (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    metrics_data JSONB NOT NULL,
    metric_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Alternative user repos table for AWS deployment (with embedded repo data)
CREATE TABLE IF NOT EXISTS user_repos_aws (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    repo_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, (repo_data->>'full_name'))
);

-- ================================
-- 7. INDEXES
-- ================================
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_github_username ON users(github_username);
CREATE INDEX IF NOT EXISTS idx_repos_full_name ON repos(full_name);
CREATE INDEX IF NOT EXISTS idx_repos_owner_name ON repos(owner, name);
CREATE INDEX IF NOT EXISTS idx_user_repos_user_id ON user_repos(user_id);
CREATE INDEX IF NOT EXISTS idx_user_repos_repo_id ON user_repos(repo_id);
CREATE INDEX IF NOT EXISTS idx_metrics_user_user_id ON metrics_user(user_id);
CREATE INDEX IF NOT EXISTS idx_metrics_user_timestamp ON metrics_user(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_repo_repo_id ON metrics_repo(repo_id);
CREATE INDEX IF NOT EXISTS idx_metrics_repo_user_id ON metrics_repo(user_id);
CREATE INDEX IF NOT EXISTS idx_metrics_repo_timestamp ON metrics_repo(timestamp DESC);

-- AWS deployment indexes
CREATE INDEX IF NOT EXISTS idx_user_metrics_user_id ON user_metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_user_metrics_timestamp ON user_metrics(metric_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_user_repos_aws_user_id ON user_repos_aws(user_id);
CREATE INDEX IF NOT EXISTS idx_user_repos_aws_repo_name ON user_repos_aws USING GIN ((repo_data->>'full_name'));

-- ================================
-- 8. TRIGGERS
-- ================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_repos_updated_at ON repos;
CREATE TRIGGER update_repos_updated_at 
    BEFORE UPDATE ON repos 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_user_repos_aws_updated_at ON user_repos_aws;
CREATE TRIGGER update_user_repos_aws_updated_at 
    BEFORE UPDATE ON user_repos_aws 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- ================================
-- 9. STORED PROCEDURES - SUPABASE COMPATIBLE
-- ================================

-- Drop existing functions first to avoid return type conflicts
DROP FUNCTION IF EXISTS save_user_repo(TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS save_repo_metrics(TEXT, TEXT, TEXT, JSONB);

-- Save user metrics
CREATE OR REPLACE FUNCTION save_user_metrics(
    user_email TEXT,
    metrics_data JSONB
) RETURNS TABLE(status TEXT, user_id UUID) AS $$
DECLARE
    current_user_id UUID;
BEGIN
    SELECT id INTO current_user_id FROM users WHERE email = user_email;

    IF current_user_id IS NULL THEN
        INSERT INTO users (email) VALUES (user_email) RETURNING id INTO current_user_id;
    END IF;

    UPDATE users SET last_sync = NOW(), updated_at = NOW() WHERE id = current_user_id;

    IF metrics_data IS NOT NULL AND metrics_data != '{}'::jsonb THEN
        INSERT INTO metrics_user (user_id, metrics_data) 
        VALUES (current_user_id, metrics_data);
    END IF;

    RETURN QUERY SELECT 'success'::TEXT, current_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Save user-repo association
CREATE OR REPLACE FUNCTION save_user_repo(
    user_email TEXT,
    repo_owner TEXT,
    repo_name TEXT
) RETURNS TABLE(status TEXT, result_repo_id UUID) AS $$
DECLARE
    current_user_id UUID;
    current_repo_id UUID;
    repo_full_name TEXT;
BEGIN
    SELECT id INTO current_user_id FROM users WHERE email = user_email;

    IF current_user_id IS NULL THEN
        RETURN QUERY SELECT 'user_not_found'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    repo_full_name := repo_owner || '/' || repo_name;

    SELECT id INTO current_repo_id FROM repos WHERE full_name = repo_full_name;

    IF current_repo_id IS NULL THEN
        INSERT INTO repos (owner, name, full_name) 
        VALUES (repo_owner, repo_name, repo_full_name)
        RETURNING id INTO current_repo_id;
    END IF;

    INSERT INTO user_repos (user_id, repo_id)
    VALUES (current_user_id, current_repo_id)
    ON CONFLICT (user_id, repo_id) DO NOTHING;

    RETURN QUERY SELECT 'success'::TEXT, current_repo_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Save repository metrics
CREATE OR REPLACE FUNCTION save_repo_metrics(
    user_email TEXT,
    repo_owner TEXT,
    repo_name TEXT,
    metrics_data JSONB
) RETURNS TABLE(status TEXT, result_repo_id UUID) AS $$
DECLARE
    current_user_id UUID;
    current_repo_id UUID;
    repo_full_name TEXT;
BEGIN
    SELECT id INTO current_user_id FROM users WHERE email = user_email;

    IF current_user_id IS NULL THEN
        RETURN QUERY SELECT 'user_not_found'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    repo_full_name := repo_owner || '/' || repo_name;

    SELECT id INTO current_repo_id FROM repos WHERE full_name = repo_full_name;

    IF current_repo_id IS NULL THEN
        INSERT INTO repos (owner, name, full_name)
        VALUES (repo_owner, repo_name, repo_full_name)
        RETURNING id INTO current_repo_id;
    END IF;

    IF metrics_data IS NOT NULL AND metrics_data != '{}'::jsonb THEN
        INSERT INTO metrics_repo (user_id, repo_id, metrics_data)
        VALUES (current_user_id, current_repo_id, metrics_data);
    END IF;

    RETURN QUERY SELECT 'success'::TEXT, current_repo_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get GitHub token
CREATE OR REPLACE FUNCTION get_user_github_token(
    user_email TEXT
) RETURNS TEXT AS $$
DECLARE
    token TEXT;
BEGIN
    SELECT github_token INTO token FROM users WHERE email = user_email;
    RETURN token;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get user metrics (bypasses RLS)
CREATE OR REPLACE FUNCTION get_user_metrics_data(
    user_email TEXT,
    limit_count INTEGER DEFAULT 1
) RETURNS TABLE(
    id UUID,
    user_id UUID,
    metric_timestamp TIMESTAMP WITH TIME ZONE,
    metrics_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT m.id, m.user_id, m.timestamp, m.metrics_data, m.created_at
    FROM metrics_user m
    JOIN users u ON m.user_id = u.id
    WHERE u.email = user_email
    ORDER BY m.timestamp DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get user repos (bypasses RLS)
CREATE OR REPLACE FUNCTION get_user_repos_data(
    user_email TEXT
) RETURNS TABLE(
    user_repo_id UUID,
    repo_id UUID,
    owner TEXT,
    name TEXT,
    full_name TEXT,
    repo_created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT ur.id, r.id, r.owner, r.name, r.full_name, ur.created_at
    FROM user_repos ur
    JOIN repos r ON ur.repo_id = r.id
    JOIN users u ON ur.user_id = u.id
    WHERE u.email = user_email;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get user by email (bypasses RLS)
CREATE OR REPLACE FUNCTION get_user_by_email(
    user_email TEXT
) RETURNS TABLE(
    id UUID,
    email TEXT,
    github_username TEXT,
    user_created_at TIMESTAMP WITH TIME ZONE,
    last_sync TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT u.id, u.email, u.github_username, u.created_at, u.last_sync
    FROM users u
    WHERE u.email = user_email;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Delete user repo association by ID (bypasses RLS)
CREATE OR REPLACE FUNCTION delete_user_repo_by_id(
    user_email TEXT,
    user_repo_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    repo_id_to_cleanup UUID;
    user_id_found UUID;
    deletion_count INTEGER;
    remaining_associations INTEGER;
BEGIN
    -- Get user ID from email
    SELECT id INTO user_id_found FROM users WHERE email = user_email;
    
    IF user_id_found IS NULL THEN
        RAISE NOTICE 'User not found for email: %', user_email;
        RETURN FALSE;
    END IF;
    
    -- Get repo_id for potential cleanup before deletion
    SELECT repo_id INTO repo_id_to_cleanup 
    FROM user_repos 
    WHERE id = user_repo_id AND user_id = user_id_found;
    
    IF repo_id_to_cleanup IS NULL THEN
        RAISE NOTICE 'User repo association not found or does not belong to user: %', user_repo_id;
        RETURN FALSE;
    END IF;
    
    -- Delete the user-repo association
    DELETE FROM user_repos 
    WHERE id = user_repo_id AND user_id = user_id_found;
    
    GET DIAGNOSTICS deletion_count = ROW_COUNT;
    
    IF deletion_count = 0 THEN
        RAISE NOTICE 'No rows deleted for user_repo_id: %', user_repo_id;
        RETURN FALSE;
    END IF;
    
    -- Check if repo has any remaining associations
    SELECT COUNT(*) INTO remaining_associations 
    FROM user_repos 
    WHERE repo_id = repo_id_to_cleanup;
    
    -- If no remaining associations, delete the repository
    IF remaining_associations = 0 THEN
        DELETE FROM repos WHERE id = repo_id_to_cleanup;
        RAISE NOTICE 'Cleaned up unused repository: %', repo_id_to_cleanup;
    END IF;
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ================================
-- 10. AWS/DIRECT POSTGRESQL UTILITIES
-- ================================

-- Ensure user exists and get ID (for AWS deployment)
CREATE OR REPLACE FUNCTION ensure_user_exists(
    user_email TEXT
) RETURNS UUID AS $$
DECLARE
    user_id UUID;
BEGIN
    SELECT id INTO user_id FROM users WHERE email = user_email;
    
    IF user_id IS NULL THEN
        INSERT INTO users (email, created_at, updated_at)
        VALUES (user_email, NOW(), NOW())
        RETURNING id INTO user_id;
    END IF;
    
    RETURN user_id;
END;
$$ LANGUAGE plpgsql;

-- Save user metrics (AWS version)
CREATE OR REPLACE FUNCTION save_user_metrics_aws(
    user_email TEXT,
    metrics_data JSONB
) RETURNS BOOLEAN AS $$
DECLARE
    user_id UUID;
BEGIN
    user_id := ensure_user_exists(user_email);
    
    INSERT INTO user_metrics (user_id, metrics_data, metric_timestamp, created_at)
    VALUES (user_id, metrics_data, NOW(), NOW());
    
    RETURN TRUE;
EXCEPTION
    WHEN OTHERS THEN
        RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- Get user metrics (AWS version)
CREATE OR REPLACE FUNCTION get_user_metrics_aws(
    user_id UUID,
    limit_count INTEGER DEFAULT 10
) RETURNS TABLE(
    metrics_data JSONB,
    metric_timestamp TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT um.metrics_data, um.metric_timestamp, um.created_at
    FROM user_metrics um
    WHERE um.user_id = get_user_metrics_aws.user_id
    ORDER BY um.created_at DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;

-- Add user repository (AWS version)
CREATE OR REPLACE FUNCTION add_user_repository_aws(
    user_id UUID,
    repo_data JSONB
) RETURNS BOOLEAN AS $$
BEGIN
    INSERT INTO user_repos_aws (user_id, repo_data, created_at, updated_at)
    VALUES (user_id, repo_data, NOW(), NOW())
    ON CONFLICT (user_id, (repo_data->>'full_name'))
    DO UPDATE SET
        repo_data = EXCLUDED.repo_data,
        updated_at = EXCLUDED.updated_at;
    
    RETURN TRUE;
EXCEPTION
    WHEN OTHERS THEN
        RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- Delete user repository (AWS version)
CREATE OR REPLACE FUNCTION delete_user_repository_aws(
    user_id UUID,
    repo_full_name TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    DELETE FROM user_repos_aws
    WHERE user_repos_aws.user_id = delete_user_repository_aws.user_id
    AND repo_data->>'full_name' = repo_full_name;
    
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Get user repositories (AWS version)
CREATE OR REPLACE FUNCTION get_user_repos_aws(
    user_id UUID
) RETURNS TABLE(
    repo_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT ura.repo_data, ura.created_at
    FROM user_repos_aws ura
    WHERE ura.user_id = get_user_repos_aws.user_id
    ORDER BY ura.created_at DESC;
END;
$$ LANGUAGE plpgsql;

-- ================================
-- 11. UTILITY QUERIES (Common Operations)
-- ================================

-- Check if user exists by email
CREATE OR REPLACE FUNCTION user_exists_by_email(
    user_email TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS(SELECT 1 FROM users WHERE email = user_email);
END;
$$ LANGUAGE plpgsql;

-- Get user ID by email
CREATE OR REPLACE FUNCTION get_user_id_by_email(
    user_email TEXT
) RETURNS UUID AS $$
DECLARE
    user_id UUID;
BEGIN
    SELECT id INTO user_id FROM users WHERE email = user_email;
    RETURN user_id;
END;
$$ LANGUAGE plpgsql;

-- Clean old metrics (retention policy)
CREATE OR REPLACE FUNCTION cleanup_old_metrics(
    retention_days INTEGER DEFAULT 90
) RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Clean old user metrics
    DELETE FROM metrics_user 
    WHERE created_at < NOW() - INTERVAL '1 day' * retention_days;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    -- Clean old repo metrics
    DELETE FROM metrics_repo 
    WHERE created_at < NOW() - INTERVAL '1 day' * retention_days;
    
    -- Clean old AWS metrics
    DELETE FROM user_metrics 
    WHERE created_at < NOW() - INTERVAL '1 day' * retention_days;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Get database statistics
CREATE OR REPLACE FUNCTION get_database_stats()
RETURNS TABLE(
    table_name TEXT,
    row_count BIGINT,
    size_pretty TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        schemaname||'.'||tablename as table_name,
        n_tup_ins - n_tup_del as row_count,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size_pretty
    FROM pg_stat_user_tables 
    WHERE schemaname = 'public'
    ORDER BY n_tup_ins - n_tup_del DESC;
END;
$$ LANGUAGE plpgsql;

-- ================================
-- 12. GRANTS AND PERMISSIONS
-- ================================
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated, anon, service_role;

-- Supabase tables
GRANT ALL ON users TO authenticated, service_role;
GRANT ALL ON repos TO authenticated, service_role;
GRANT ALL ON user_repos TO authenticated, service_role;
GRANT ALL ON metrics_user TO authenticated, service_role;
GRANT ALL ON metrics_repo TO authenticated, service_role;

-- AWS tables
GRANT ALL ON user_metrics TO authenticated, service_role;
GRANT ALL ON user_repos_aws TO authenticated, service_role;

-- Functions
GRANT EXECUTE ON FUNCTION save_user_metrics(TEXT, JSONB) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION save_user_repo(TEXT, TEXT, TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION save_repo_metrics(TEXT, TEXT, TEXT, JSONB) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_user_github_token(TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_user_metrics_data(TEXT, INTEGER) TO authenticated, anon, service_role;
GRANT EXECUTE ON FUNCTION get_user_repos_data(TEXT) TO authenticated, anon, service_role;
GRANT EXECUTE ON FUNCTION get_user_by_email(TEXT) TO authenticated, anon, service_role;
GRANT EXECUTE ON FUNCTION delete_user_repo_by_id(TEXT, UUID) TO authenticated, service_role;

-- AWS functions
GRANT EXECUTE ON FUNCTION ensure_user_exists(TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION save_user_metrics_aws(TEXT, JSONB) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_user_metrics_aws(UUID, INTEGER) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION add_user_repository_aws(UUID, JSONB) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION delete_user_repository_aws(UUID, TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_user_repos_aws(UUID) TO authenticated, service_role;

-- Utility functions
GRANT EXECUTE ON FUNCTION user_exists_by_email(TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_user_id_by_email(TEXT) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION cleanup_old_metrics(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION get_database_stats() TO authenticated, service_role;

-- ================================
-- 13. COMMENTS AND DOCUMENTATION
-- ================================
COMMENT ON TABLE users IS 'User accounts and authentication data';
COMMENT ON TABLE repos IS 'GitHub repositories being tracked';
COMMENT ON TABLE user_repos IS 'Association between users and their tracked repositories';
COMMENT ON TABLE metrics_user IS 'User-level metrics data (Supabase version)';
COMMENT ON TABLE metrics_repo IS 'Repository-level metrics data (Supabase version)';
COMMENT ON TABLE user_metrics IS 'User-level metrics data (AWS/Direct PostgreSQL version)';
COMMENT ON TABLE user_repos_aws IS 'User repositories with embedded JSON data (AWS version)';

COMMENT ON FUNCTION save_user_metrics(TEXT, JSONB) IS 'Save user metrics with Supabase RLS support';
COMMENT ON FUNCTION save_user_metrics_aws(TEXT, JSONB) IS 'Save user metrics for direct PostgreSQL access';
COMMENT ON FUNCTION cleanup_old_metrics(INTEGER) IS 'Clean up metrics older than specified days';
COMMENT ON FUNCTION get_database_stats() IS 'Get table statistics for monitoring';

-- ================================
-- END OF SCHEMA
-- ================================
