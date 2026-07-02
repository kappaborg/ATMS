#!/bin/bash

# ATMS Database Migration Script (Docker Version)
# Purpose: Execute all database migrations using Docker PostgreSQL
# Author: ATMS Team
# Date: 2025-10-13

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Database configuration
CONTAINER_NAME="atms-postgres"
DB_NAME="atms"
DB_USER="atms_user"
DB_PASSWORD="atms_password"

# Migration directory
MIGRATION_DIR="$(dirname "$0")/migrations"

# Functions
print_header() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                                      ║${NC}"
    echo -e "${CYAN}║         ${BLUE}ATMS DATABASE MIGRATION SYSTEM (Docker)${CYAN}                   ║${NC}"
    echo -e "${CYAN}║                                                                      ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_info() {
    echo -e "${BLUE}ℹ${NC}  $1"
}

print_success() {
    echo -e "${GREEN}✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

check_docker() {
    print_info "Checking Docker container..."
    
    if ! docker ps | grep -q "$CONTAINER_NAME"; then
        print_error "Docker container '$CONTAINER_NAME' is not running"
        print_info "Start it with: docker start $CONTAINER_NAME"
        exit 1
    fi
    
    print_success "Docker container is running"
}

check_postgres() {
    print_info "Checking PostgreSQL connection..."
    
    if ! docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" > /dev/null 2>&1; then
        print_error "Cannot connect to PostgreSQL database"
        print_info "Connection details:"
        echo "  Container: $CONTAINER_NAME"
        echo "  Database: $DB_NAME"
        echo "  User: $DB_USER"
        exit 1
    fi
    
    print_success "PostgreSQL connection successful"
}

create_backup() {
    local backup_file="backup_$(date +%Y%m%d_%H%M%S).sql"
    
    print_info "Creating database backup: $backup_file"
    
    docker exec "$CONTAINER_NAME" pg_dump -U "$DB_USER" "$DB_NAME" > "$backup_file" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        print_success "Backup created: $backup_file"
        echo "$backup_file"
    else
        print_warning "Backup skipped (database might be empty)"
    fi
}

execute_migration() {
    local migration_file=$1
    local migration_name=$(basename "$migration_file" .sql)
    
    print_info "Executing migration: $migration_name"
    
    docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" \
        -v ON_ERROR_STOP=1 < "$migration_file" > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        print_success "Migration $migration_name completed"
        
        # Record migration in database
        docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" \
            -c "INSERT INTO schema_migrations (migration_name, success) VALUES ('$migration_name', TRUE) ON CONFLICT (migration_name) DO NOTHING" \
            > /dev/null 2>&1 || true
        
        return 0
    else
        print_error "Migration $migration_name failed"
        
        # Record failure
        docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" \
            -c "INSERT INTO schema_migrations (migration_name, success, error_message) VALUES ('$migration_name', FALSE, 'See logs for details') ON CONFLICT (migration_name) DO NOTHING" \
            > /dev/null 2>&1 || true
        
        return 1
    fi
}

run_migrations() {
    local backup_file=""
    
    print_header
    
    # Check Docker and PostgreSQL
    check_docker
    check_postgres
    
    # Create backup (optional for empty database)
    create_backup
    
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}                    EXECUTING MIGRATIONS                               ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    # Execute master migration setup
    print_info "Setting up migration system..."
    execute_migration "$MIGRATION_DIR/000_master_migration.sql"
    
    # Execute migrations in order
    local migrations=(
        "001_create_intersections.sql"
        "002_create_users.sql"
        "003_create_sensor_devices.sql"
        "004_create_traffic_detections.sql"
        "005_create_trajectories.sql"
        "006_create_emissions.sql"
        "007_create_traffic_lights.sql"
        "008_create_system_monitoring.sql"
        "009_create_analytics_config.sql"
    )
    
    local failed=0
    
    for migration in "${migrations[@]}"; do
        if ! execute_migration "$MIGRATION_DIR/$migration"; then
            failed=$((failed + 1))
        fi
    done
    
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}                    MIGRATION SUMMARY                                  ${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    if [ $failed -eq 0 ]; then
        print_success "All migrations completed successfully!"
        
        # Display migration status
        echo ""
        print_info "Migration status:"
        docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" \
            -c "SELECT * FROM migration_status ORDER BY execution_order;" 2>/dev/null || true
        
        echo ""
        print_info "Database tables:"
        docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" \
            -c "\dt" 2>/dev/null | grep -E "public \|" || true
        
        echo ""
        echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║                                                                      ║${NC}"
        echo -e "${GREEN}║              🎉 MIGRATIONS COMPLETED SUCCESSFULLY! 🎉               ║${NC}"
        echo -e "${GREEN}║                                                                      ║${NC}"
        echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        
        return 0
    else
        print_error "$failed migration(s) failed"
        return 1
    fi
}

# Run migrations
run_migrations

