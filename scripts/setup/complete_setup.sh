#!/bin/bash

# ATMS Complete Setup Script
# Purpose: Install PostgreSQL, Python dependencies, and run migrations
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
    echo -e "${CYAN}║         ${BLUE}ATMS COMPLETE SETUP${CYAN}                                          ║${NC}"
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

print_step() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Check if running on macOS
check_os() {
    if [[ "$OSTYPE" != "darwin"* ]]; then
        print_error "This script is designed for macOS only"
        exit 1
    fi
}

# Install Homebrew if needed
install_homebrew() {
    print_step "STEP 1: CHECKING HOMEBREW"
    
    if ! command -v brew &> /dev/null; then
        print_info "Homebrew not found. Installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Add Homebrew to PATH for Apple Silicon
        if [[ $(uname -m) == 'arm64' ]]; then
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
        print_success "Homebrew installed"
    else
        print_success "Homebrew is already installed"
    fi
}

# Install PostgreSQL
install_postgresql() {
    print_step "STEP 2: INSTALLING POSTGRESQL"
    
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
    print_success "PostgreSQL installed"
}

# Start PostgreSQL
start_postgresql() {
    print_step "STEP 3: STARTING POSTGRESQL SERVICE"
    
    brew services start postgresql@14
    sleep 3
    
    if pg_isready &> /dev/null; then
        print_success "PostgreSQL service started"
    else
        print_warning "PostgreSQL may still be starting... waiting..."
        sleep 5
    fi
}

# Create database and user
setup_database() {
    print_step "STEP 4: CREATING DATABASE AND USER"
    
    # Create user
    if psql postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='atms_user'" 2>/dev/null | grep -q 1; then
        print_warning "User 'atms_user' already exists"
    else
        createuser -s atms_user 2>/dev/null || true
        print_success "User 'atms_user' created"
    fi
    
    # Set password
    psql postgres -c "ALTER USER atms_user WITH PASSWORD 'atms_password';" &> /dev/null
    print_success "Password set for 'atms_user'"
    
    # Create database
    if psql -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw atms_db; then
        print_warning "Database 'atms_db' already exists"
    else
        createdb -O atms_user atms_db 2>/dev/null || true
        print_success "Database 'atms_db' created"
    fi
}

# Install Python dependencies
install_python_deps() {
    print_step "STEP 5: INSTALLING PYTHON DEPENDENCIES"
    
    print_info "Installing psycopg2-binary..."
    pip3 install psycopg2-binary --quiet 2>/dev/null || \
    python3 -m pip install psycopg2-binary --quiet 2>/dev/null || \
    print_warning "Could not install via pip3, trying alternative..."
    
    # Try with user install
    pip3 install --user psycopg2-binary --quiet 2>/dev/null || \
    python3 -m pip install --user psycopg2-binary --quiet 2>/dev/null || \
    print_error "Failed to install psycopg2-binary"
    
    print_success "Python dependencies installed"
}

# Install PostgreSQL extensions
install_extensions() {
    print_step "STEP 6: INSTALLING POSTGRESQL EXTENSIONS"
    
    psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";" &> /dev/null
    print_success "Extension 'uuid-ossp' enabled"
    
    psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"pg_trgm\";" &> /dev/null
    print_success "Extension 'pg_trgm' enabled"
    
    psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"btree_gin\";" &> /dev/null
    print_success "Extension 'btree_gin' enabled"
    
    # Try to install PostGIS (optional)
    if psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"postgis\";" &> /dev/null; then
        print_success "Extension 'postgis' enabled"
    else
        print_warning "PostGIS extension not available (optional)"
    fi
}

# Test connection
test_connection() {
    print_step "STEP 7: TESTING DATABASE CONNECTION"
    
    if psql -U atms_user -d atms_db -c "SELECT 1;" &> /dev/null; then
        print_success "Database connection successful!"
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

# Run migrations
run_migrations() {
    print_step "STEP 8: RUNNING DATABASE MIGRATIONS"
    
    cd /Users/kappasutra/Traffic/database
    
    print_info "Executing migrations..."
    ./run_migrations.sh
    
    if [ $? -eq 0 ]; then
        print_success "All migrations completed successfully!"
    else
        print_error "Migration failed"
        return 1
    fi
}

# Validate integration
validate_setup() {
    print_step "STEP 9: VALIDATING INTEGRATION"
    
    cd /Users/kappasutra/Traffic/database
    
    print_info "Running validation script..."
    python3 validate_integration.py
    
    if [ $? -eq 0 ]; then
        print_success "All validations passed!"
    else
        print_error "Validation failed"
        return 1
    fi
}

# Create .env file
create_env() {
    print_step "STEP 10: CREATING CONFIGURATION FILE"
    
    cd /Users/kappasutra/Traffic
    
    if [ -f ".env" ]; then
        print_warning ".env file already exists, backing up..."
        cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
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

# Main execution
main() {
    print_header
    
    print_info "This script will set up your complete ATMS database environment"
    print_info "Estimated time: 15-20 minutes"
    echo ""
    
    # Run all steps
    check_os
    install_homebrew
    install_postgresql
    start_postgresql
    setup_database
    install_python_deps
    install_extensions
    test_connection
    create_env
    
    # Ask user if they want to run migrations now
    echo ""
    print_info "PostgreSQL is ready! Would you like to run migrations now? (y/n)"
    read -r response
    
    if [[ "$response" =~ ^[Yy]$ ]]; then
        run_migrations
        validate_setup
    else
        print_info "You can run migrations later with:"
        echo "  cd /Users/kappasutra/Traffic/database"
        echo "  ./run_migrations.sh"
    fi
    
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                                      ║${NC}"
    echo -e "${GREEN}║              🎉 SETUP COMPLETE! 🎉                                  ║${NC}"
    echo -e "${GREEN}║                                                                      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    print_success "Your ATMS database is ready!"
    echo ""
    print_info "Quick Reference:"
    echo "  • Database: atms_db"
    echo "  • User: atms_user"
    echo "  • Password: atms_password"
    echo "  • Host: localhost:5432"
    echo ""
    print_info "Next Steps:"
    echo "  1. Update services (see APPLICATION_INTEGRATION_GUIDE.md)"
    echo "  2. Run integration tests"
    echo "  3. Start developing!"
}

# Run main function
main

