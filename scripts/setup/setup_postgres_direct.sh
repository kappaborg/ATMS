#!/bin/bash

# ATMS PostgreSQL Direct Setup (No Homebrew Required)
# Purpose: Install PostgreSQL using official installer or Docker
# Author: ATMS Team
# Date: 2025-10-13

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                                      ║${NC}"
    echo -e "${CYAN}║         ${BLUE}ATMS POSTGRESQL SETUP (macOS 26.0 Compatible)${CYAN}              ║${NC}"
    echo -e "${CYAN}║                                                                      ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_info() { echo -e "${BLUE}ℹ${NC}  $1"; }
print_success() { echo -e "${GREEN}✅${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC}  $1"; }
print_error() { echo -e "${RED}❌${NC} $1"; }

print_header

echo -e "${YELLOW}⚠  Detected macOS 26.0 - Homebrew is not compatible${NC}"
echo ""
echo "Please choose an installation method:"
echo ""
echo "  1) Docker (Recommended - Isolated & Easy)"
echo "  2) Postgres.app (GUI Application)"
echo "  3) Official PostgreSQL Installer"
echo "  4) Exit and install manually"
echo ""
read -p "Enter choice (1-4): " choice

case $choice in
    1)
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}DOCKER POSTGRESQL SETUP${NC}"
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
        echo ""
        
        # Check if Docker is installed
        if ! command -v docker &> /dev/null; then
            print_error "Docker is not installed"
            print_info "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
            print_info "After installation, run this script again"
            exit 1
        fi
        
        print_success "Docker is installed"
        
        # Check if container already exists
        if docker ps -a | grep -q atms-postgres; then
            print_warning "ATMS PostgreSQL container already exists"
            read -p "Remove and recreate? (y/n): " recreate
            if [[ "$recreate" =~ ^[Yy]$ ]]; then
                docker rm -f atms-postgres 2>/dev/null || true
                print_success "Old container removed"
            else
                print_info "Starting existing container..."
                docker start atms-postgres
                exit 0
            fi
        fi
        
        print_info "Creating PostgreSQL container..."
        
        docker run -d \
          --name atms-postgres \
          -e POSTGRES_USER=atms_user \
          -e POSTGRES_PASSWORD=atms_password \
          -e POSTGRES_DB=atms_db \
          -p 5432:5432 \
          -v atms-postgres-data:/var/lib/postgresql/data \
          postgres:14
        
        print_success "PostgreSQL container created and started!"
        
        # Wait for PostgreSQL to be ready
        print_info "Waiting for PostgreSQL to be ready..."
        sleep 5
        
        # Test connection
        if docker exec atms-postgres psql -U atms_user -d atms_db -c "SELECT 1" &> /dev/null; then
            print_success "Database connection successful!"
        else
            print_warning "Database may still be initializing..."
            sleep 5
        fi
        
        # Install extensions
        print_info "Installing PostgreSQL extensions..."
        docker exec atms-postgres psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";" &> /dev/null
        docker exec atms-postgres psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"pg_trgm\";" &> /dev/null
        docker exec atms-postgres psql -U atms_user -d atms_db -c "CREATE EXTENSION IF NOT EXISTS \"btree_gin\";" &> /dev/null
        print_success "Extensions installed"
        
        # Install Python package
        print_info "Installing Python package psycopg2-binary..."
        pip3 install psycopg2-binary --quiet 2>/dev/null || \
        python3 -m pip install psycopg2-binary --quiet 2>/dev/null || \
        pip3 install --user psycopg2-binary --quiet 2>/dev/null
        print_success "Python package installed"
        
        # Create .env file
        cat > .env << EOF
# ATMS Database Configuration (Docker)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=atms_db
POSTGRES_USER=atms_user
POSTGRES_PASSWORD=atms_password
EOF
        print_success ".env file created"
        
        echo ""
        print_success "PostgreSQL is ready via Docker!"
        echo ""
        print_info "Useful Docker commands:"
        echo "  • Stop:    docker stop atms-postgres"
        echo "  • Start:   docker start atms-postgres"
        echo "  • Logs:    docker logs atms-postgres"
        echo "  • Connect: docker exec -it atms-postgres psql -U atms_user -d atms_db"
        ;;
        
    2)
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}POSTGRES.APP SETUP${NC}"
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
        echo ""
        
        print_info "Postgres.app Setup Instructions:"
        echo ""
        echo "1. Download Postgres.app from: https://postgresapp.com/"
        echo "2. Move to Applications folder"
        echo "3. Open Postgres.app"
        echo "4. Click 'Initialize' to create a server"
        echo "5. Add to PATH:"
        echo "   export PATH=\"/Applications/Postgres.app/Contents/Versions/latest/bin:\$PATH\""
        echo "   echo 'export PATH=\"/Applications/Postgres.app/Contents/Versions/latest/bin:\$PATH\"' >> ~/.zshrc"
        echo ""
        echo "6. Then create database:"
        echo "   createuser -s atms_user"
        echo "   psql postgres -c \"ALTER USER atms_user WITH PASSWORD 'atms_password';\""
        echo "   createdb -O atms_user atms_db"
        echo ""
        echo "7. Install Python package:"
        echo "   pip3 install psycopg2-binary"
        echo ""
        echo "8. Run migrations:"
        echo "   cd /Users/kappasutra/Traffic/database"
        echo "   ./run_migrations.sh"
        ;;
        
    3)
        echo ""
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
        echo -e "${CYAN}OFFICIAL POSTGRESQL INSTALLER${NC}"
        echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
        echo ""
        
        print_info "PostgreSQL Official Installer Instructions:"
        echo ""
        echo "1. Download from: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads"
        echo "2. Download PostgreSQL 14 for macOS"
        echo "3. Run the installer (.dmg file)"
        echo "4. During installation:"
        echo "   - Set password for 'postgres' user"
        echo "   - Use port 5432"
        echo "   - Install Stack Builder (optional)"
        echo ""
        echo "5. After installation, add to PATH:"
        echo "   export PATH=\"/Library/PostgreSQL/14/bin:\$PATH\""
        echo "   echo 'export PATH=\"/Library/PostgreSQL/14/bin:\$PATH\"' >> ~/.zshrc"
        echo ""
        echo "6. Create database and user:"
        echo "   createuser -U postgres -s atms_user"
        echo "   psql -U postgres -c \"ALTER USER atms_user WITH PASSWORD 'atms_password';\""
        echo "   createdb -U postgres -O atms_user atms_db"
        echo ""
        echo "7. Install Python package:"
        echo "   pip3 install psycopg2-binary"
        echo ""
        echo "8. Run migrations:"
        echo "   cd /Users/kappasutra/Traffic/database"
        echo "   ./run_migrations.sh"
        ;;
        
    4)
        print_info "Exiting..."
        exit 0
        ;;
        
    *)
        print_error "Invalid choice"
        exit 1
        ;;
esac

echo ""
read -p "Would you like to run migrations now? (y/n): " run_migrations

if [[ "$run_migrations" =~ ^[Yy]$ ]]; then
    echo ""
    print_info "Running migrations..."
    cd /Users/kappasutra/Traffic/database
    ./run_migrations.sh
    
    if [ $? -eq 0 ]; then
        print_info "Validating integration..."
        python3 validate_integration.py
    fi
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                                      ║${NC}"
echo -e "${GREEN}║              🎉 SETUP COMPLETE! 🎉                                  ║${NC}"
echo -e "${GREEN}║                                                                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════╝${NC}"

