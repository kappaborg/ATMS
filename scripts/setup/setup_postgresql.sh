#!/bin/bash

# ATMS PostgreSQL Setup Script
# Purpose: Automated PostgreSQL installation and configuration
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

print_header() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                                      ║${NC}"
    echo -e "${CYAN}║         ${BLUE}ATMS POSTGRESQL SETUP${CYAN}                                       ║${NC}"
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

check_homebrew() {
    print_info "Checking for Homebrew..."
    
    if ! command -v brew &> /dev/null; then
        print_error "Homebrew not found!"
        print_info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Add Homebrew to PATH for Apple Silicon
        if [[ $(uname -m) == 'arm64' ]]; then
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    else
        print_success "Homebrew is installed"
    fi
}

install_postgresql() {
    print_info "Checking for PostgreSQL..."
    
    if command -v psql &> /dev/null; then
        print_success "PostgreSQL is already installed"
        psql --version
        return 0
    fi
    
    print_info "Installing PostgreSQL 14..."
    brew install postgresql@14
    
    # Add to PATH
    if [[ $(uname -m) == 'arm64' ]]; then
        echo 'export PATH="/opt/homebrew/opt/postgresql@14/bin:$PATH"' >> ~/.zshrc
        export PATH="/opt/homebrew/opt/postgresql@14/bin:$PATH"
    else
        echo 'export PATH="/usr/local/opt/postgresql@14/bin:$PATH"' >> ~/.zshrc
        export PATH="/usr/local/opt/postgresql@14/bin:$PATH"
    fi
    
    source ~/.zshrc 2>/dev/null || true
    
    print_success "PostgreSQL installed successfully"
}

start_postgresql() {
    print_info "Starting PostgreSQL service..."
    
    brew services start postgresql@14
    
    # Wait for PostgreSQL to start
    sleep 3
    
    if pg_isready &> /dev/null; then
        print_success "PostgreSQL service started"
    else
        print_warning "PostgreSQL may still be starting..."
        sleep 5
    fi
}

create_database() {
    print_info "Creating ATMS database and user..."
    
    # Create user
    if psql postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='atms_user'" | grep -q 1; then
        print_warning "User 'atms_user' already exists"
    else
        createuser -s atms_user
        print_success "User 'atms_user' created"
    fi
    
    # Set password
    psql postgres -c "ALTER USER atms_user WITH PASSWORD 'atms_password';" &> /dev/null
    print_success "Password set for 'atms_user'"
    
    # Create database
    if psql -lqt | cut -d \| -f 1 | grep -qw atms_db; then
        print_warning "Database 'atms_db' already exists"
    else
        createdb -O atms_user atms_db
        print_success "Database 'atms_db' created"
    fi
}

install_extensions() {
    print_info "Installing PostgreSQL extensions..."
    
    # Install PostGIS
    if brew list | grep -q postgis; then
        print_success "PostGIS already installed"
    else
        print_info "Installing PostGIS..."
        brew install postgis
        print_success "PostGIS installed"
    fi
    
    # Enable extensions in database
    psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";" &> /dev/null
    print_success "Extension 'uuid-ossp' enabled"
    
    psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"pg_trgm\";" &> /dev/null
    print_success "Extension 'pg_trgm' enabled"
    
    psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"btree_gin\";" &> /dev/null
    print_success "Extension 'btree_gin' enabled"
    
    # Try to install PostGIS (may fail if not available)
    if psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"postgis\";" &> /dev/null; then
        print_success "Extension 'postgis' enabled"
    else
        print_warning "PostGIS extension not available (optional)"
    fi
}

test_connection() {
    print_info "Testing database connection..."
    
    if psql -U atms_user -d atms_db -c "SELECT 1;" &> /dev/null; then
        print_success "Database connection successful!"
        
        # Show connection details
        echo ""
        print_info "Connection Details:"
        echo "  Host: localhost"
        echo "  Port: 5432"
        echo "  Database: atms_db"
        echo "  User: atms_user"
        echo "  Password: atms_password"
    else
        print_error "Database connection failed!"
        return 1
    fi
}

create_env_file() {
    print_info "Creating .env file..."
    
    if [ -f ".env" ]; then
        print_warning ".env file already exists, backing up..."
        cp .env .env.backup
    fi
    
    cat > .env << EOF
# ATMS Database Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=atms_db
POSTGRES_USER=atms_user
POSTGRES_PASSWORD=atms_password

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
EOF
    
    print_success ".env file created"
}

main() {
    print_header
    
    print_info "This script will install and configure PostgreSQL for ATMS"
    echo ""
    
    # Check if running on macOS
    if [[ "$OSTYPE" != "darwin"* ]]; then
        print_error "This script is designed for macOS only"
        exit 1
    fi
    
    # Run setup steps
    check_homebrew
    install_postgresql
    start_postgresql
    create_database
    install_extensions
    test_connection
    create_env_file
    
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                                      ║${NC}"
    echo -e "${GREEN}║              🎉 POSTGRESQL SETUP COMPLETE! 🎉                       ║${NC}"
    echo -e "${GREEN}║                                                                      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    print_info "Next Steps:"
    echo "  1. Run migrations:"
    echo "     cd /Users/kappasutra/Traffic/database"
    echo "     ./run_migrations.sh"
    echo ""
    echo "  2. Validate integration:"
    echo "     python3 validate_integration.py"
    echo ""
    
    print_success "PostgreSQL is ready for ATMS!"
}

# Run main function
main

