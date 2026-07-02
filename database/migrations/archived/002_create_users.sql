-- Migration 002: Create USERS table
-- Purpose: User authentication and authorization
-- Dependencies: None
-- Author: ATMS Team
-- Date: 2025-10-13

-- Create USERS table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    full_name VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP,
    login_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- Create trigger for updated_at
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Create roles table
CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY,
    role_name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    permissions JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default roles
INSERT INTO user_roles (role_name, description, permissions) VALUES
    ('admin', 'System Administrator', '["read", "write", "delete", "manage_users", "manage_system"]'),
    ('operator', 'Traffic Operator', '["read", "write", "control_signals"]'),
    ('analyst', 'Data Analyst', '["read", "export_data", "view_analytics"]'),
    ('viewer', 'Read-only Viewer', '["read"]')
ON CONFLICT (role_name) DO NOTHING;

-- Insert default admin user (password: admin123 - CHANGE IN PRODUCTION!)
-- Password hash for 'admin123' using bcrypt
INSERT INTO users (username, email, password_hash, role, full_name)
VALUES ('admin', 'admin@atms.local', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyYuJq.dNfXS', 'admin', 'System Administrator')
ON CONFLICT (username) DO NOTHING;

-- Comments
COMMENT ON TABLE users IS 'User accounts for system authentication and authorization';
COMMENT ON COLUMN users.role IS 'User role: admin, operator, analyst, viewer';
COMMENT ON COLUMN users.password_hash IS 'Bcrypt hashed password';
COMMENT ON COLUMN users.login_attempts IS 'Failed login attempt counter';
COMMENT ON COLUMN users.locked_until IS 'Account lock expiration timestamp';

