#!/bin/bash

# ATMS Database Migration Script
# Purpose: Execute all database migrations
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
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-atms_db}"
DB_USER="${DB_USER:-atms_user}"
DB_PASSWORD="${DB_PASSWORD:-atms_password}"

# Migration directory
MIGRATION_DIR="$(dirname "$0")/migrations"

# Functions
print_header() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                                      ║${NC}"
    echo -e "${CYAN}║         ${BLUE}ATMS DATABASE MIGRATION SYSTEM${CYAN}                             ║${NC}"
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

check_postgres() {
    print_info "Checking PostgreSQL connection..."
    
    if ! PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "SELECT 1" > /dev/null 2>&1; then
        print_error "Cannot connect to PostgreSQL database"
        print_info "Connection details:"
        echo "  Host: $DB_HOST"
        echo "  Port: $DB_PORT"
        echo "  Database: $DB_NAME"
        echo "  User: $DB_USER"
        exit 1
    fi
    
    print_success "PostgreSQL connection successful"
}

create_backup() {
    local backup_file="backup_$(date +%Y%m%d_%H%M%S).sql"
    
    print_info "Creating database backup: $backup_file"
    
    PGPASSWORD=$DB_PASSWORD pg_dump -h $DB_HOST -p $DB_PORT -U $DB_USER $DB_NAME > "$backup_file"
    
    if [ $? -eq 0 ]; then
        print_success "Backup created: $backup_file"
        echo "$backup_file"
    else
        print_error "Backup failed"
        exit 1
    fi
}

execute_migration() {
    local migration_file=$1
    local migration_name=$(basename "$migration_file" .sql)
    
    print_info "Executing migration: $migration_name"
    
    PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
        -v ON_ERROR_STOP=1 \
        -f "$migration_file" > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        print_success "Migration $migration_name completed"
        
        # Record migration in database
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
            -c "INSERT INTO schema_migrations (migration_name, success) VALUES ('$migration_name', TRUE) ON CONFLICT (migration_name) DO NOTHING" \
            > /dev/null 2>&1
        
        return 0
    else
        print_error "Migration $migration_name failed"
        
        # Record failure
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
            -c "INSERT INTO schema_migrations (migration_name, success, error_message) VALUES ('$migration_name', FALSE, 'See logs for details') ON CONFLICT (migration_name) DO NOTHING" \
            > /dev/null 2>&1
        
        return 1
    fi
}

run_migrations() {
    local backup_file=""
    
    print_header
    
    # Check PostgreSQL connection
    check_postgres
    
    # Create backup
    if [ "$NO_BACKUP" != "true" ]; then
        backup_file=$(create_backup)
    else
        print_warning "Skipping backup (NO_BACKUP=true)"
    fi
    
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
        
        if [ -n "$backup_file" ]; then
            print_info "Backup file: $backup_file"
        fi
        
        # Display migration status
        echo ""
        print_info "Migration status:"
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
            -c "SELECT * FROM migration_status ORDER BY execution_order;"
        
        echo ""
        print_info "Database tables:"
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
            -c "\dt" | grep -E "intersections|users|sensor_devices|traffic_detections|trajectories|emissions|traffic_lights|system_logs|alerts|analytics"
        
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
        
        if [ -n "$backup_file" ]; then
            print_info "To restore backup, run:"
            echo "  psql -h $DB_HOST -p $DB_PORT -U $DB_USER $DB_NAME < $backup_file"
        fi
        
        return 1
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-backup)
            NO_BACKUP=true
            shift
            ;;
        --rollback)
            print_warning "ROLLBACK MODE"
            print_warning "This will DELETE ALL tables and data!"
            read -p "Are you sure? (yes/no): " confirm
            if [ "$confirm" == "yes" ]; then
                create_backup
                execute_migration "$MIGRATION_DIR/999_rollback.sql"
            else
                print_info "Rollback cancelled"
            fi
            exit 0
            ;;
        --help)
            echo "ATMS Database Migration Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-backup    Skip database backup"
            echo "  --rollback     Rollback all migrations (WARNING: Deletes all data)"
            echo "  --help         Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  DB_HOST        Database host (default: localhost)"
            echo "  DB_PORT        Database port (default: 5432)"
            echo "  DB_NAME        Database name (default: atms_db)"
            echo "  DB_USER        Database user (default: atms_user)"
            echo "  DB_PASSWORD    Database password (default: atms_password)"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Run migrations
run_migrations

