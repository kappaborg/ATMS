#!/bin/bash
# Professional Project Cleanup Script
# Date: November 24, 2025
# Purpose: Clean and organize ATMS project structure

set -e

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROJECT_ROOT="/Users/kappasutra/Traffic"
BACKUP_DIR="/Users/kappasutra/Traffic_Backup_$(date +%Y%m%d_%H%M%S)"

echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ATMS Professional Project Cleanup         ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
echo ""

# Function to create backup
create_backup() {
    echo -e "${YELLOW}📦 Creating backup...${NC}"
    mkdir -p "$BACKUP_DIR"
    
    # Copy only important files (not venv, node_modules, etc.)
    rsync -av --progress \
        --exclude='venv' \
        --exclude='__pycache__' \
        --exclude='node_modules' \
        --exclude='.git' \
        --exclude='*.pyc' \
        "$PROJECT_ROOT/" "$BACKUP_DIR/" > /dev/null 2>&1
    
    echo -e "${GREEN}✅ Backup created at: $BACKUP_DIR${NC}"
    echo ""
}

# Function to remove redundant files
remove_redundant_files() {
    echo -e "${YELLOW}🗑️  Removing redundant documentation files...${NC}"
    
    cd "$PROJECT_ROOT"
    
    # Redundant status reports
    FILES_TO_REMOVE=(
        "AI_PERCEPTION_MODEL_FIX.md"
        "ALL_FIXES_COMPLETE.md"
        "CRITICAL_FIX_APPLIED.md"
        "DATABASE_FIX_REPORT.md"
        "DEEP_ANALYSIS_COMPLETE.md"
        "DETECTION_ACCURACY_FIXED.md"
        "FINAL_FIXES_COMPLETE.md"
        "FINAL_SYSTEM_VERIFICATION.md"
        "FIXED_BOXING_ISSUES.md"
        "FIX_DASHBOARD_ISSUE.md"
        "INTEGRATION_FIX.md"
        "ISSUES_FIXED_READY_FOR_TESTING.md"
        "PROBLEM_FOUND_AND_FIXED.md"
        "STARTUP_SCRIPT_FIXES.md"
        "SYSTEM_FIXED_READY_TO_TEST.md"
        "SYSTEM_READY_FOR_TESTING.md"
        "SYSTEM_STATUS_FIXED.md"
        "SYSTEM_STATUS_SUMMARY.md"
        "VERIFICATION_OUTPUT_ANALYSIS.md"
        "COMPLETE_IMPLEMENTATION_SUMMARY.md"
        "COMPLETE_PROJECT_STATUS.md"
        "COMPLETE_SETUP_GUIDE.md"
        "COMPLETE_SYSTEM_TEST_RESULTS.md"
        "COMPLETE_VIDEO_SYSTEM_README.md"
        "COMPREHENSIVE_PROJECT_REVIEW.md"
        "COMPREHENSIVE_VERIFICATION_REPORT.md"
        "CURRENT_PROJECT_STATUS.md"
        "TEST_SYSTEM_NOW.md"
        "TEST_VIDEO_DETECTIONS.md"
        "UPLOAD_FRESH_VIDEO_NOW.md"
        "DRAG_DROP_READY.md"
        "ENHANCED_VIDEO_GUIDE.md"
        "IPHONE_CAMERA_TEST_GUIDE.md"
        "LIVE_MONITORING_GUIDE.md"
        "LIVE_STREAM_READY.md"
        "LIVE_STREAM_STATUS.md"
        "NEW_STREAM_VERIFIED.md"
        "REALTIME_VIDEO_GUIDE.md"
        "VIDEO_UPLOAD_GUIDE.md"
        "PERFORMANCE_OPTIMIZATION_COMPLETE.md"
        "PERFORMANCE_OPTIMIZATION_IMPLEMENTATION.md"
        "PERFORMANCE_OPTIMIZATION_PLAN.md"
        "SERVICE_STATUS_CHECK.md"
        "SERVICES_IMPLEMENTATION_COMPLETE.md"
        "START_ALL_SERVICES.md"
        "PROFESSIONAL_SYSTEM_READY.md"
        "CLEANUP_SUMMARY.md"
        "system_test_results.json"
        "system_verification_report.json"
        "system_verification_results.json"
        "benchmark_results.txt"
        "cleanup_log.json"
        "debug_frame.jpg"
    )
    
    REMOVED_COUNT=0
    for file in "${FILES_TO_REMOVE[@]}"; do
        if [ -f "$file" ]; then
            rm "$file"
            echo "  ✓ Removed: $file"
            ((REMOVED_COUNT++))
        fi
    done
    
    echo -e "${GREEN}✅ Removed $REMOVED_COUNT redundant files${NC}"
    echo ""
}

# Function to organize standalone scripts
organize_scripts() {
    echo -e "${YELLOW}📂 Organizing standalone scripts...${NC}"
    
    cd "$PROJECT_ROOT"
    
    # Create directories
    mkdir -p scripts/ai_models
    mkdir -p scripts/verification
    mkdir -p scripts/setup
    
    # Move AI/Model scripts
    AI_SCRIPTS=(
        "ai_decision_system.py"
        "car_brand_classification_emission_system.py"
        "emission_calculation_system.py"
        "enhanced_emission_fuel_system.py"
        "enhanced_vehicle_classification_emission_system.py"
        "integrated_brand_emission_system.py"
        "integrated_emission_decision_system.py"
        "multi_view_fusion_system.py"
        "multi_view_fusion_system_optimized.py"
        "trajectory_anomaly_detection.py"
        "trajectory_tracking_system.py"
    )
    
    MOVED_COUNT=0
    for script in "${AI_SCRIPTS[@]}"; do
        if [ -f "$script" ]; then
            mv "$script" scripts/ai_models/
            echo "  ✓ Moved: $script → scripts/ai_models/"
            ((MOVED_COUNT++))
        fi
    done
    
    # Move verification scripts
    if [ -f "verify_model_integration.py" ]; then
        mv verify_model_integration.py scripts/verification/
        echo "  ✓ Moved: verify_model_integration.py → scripts/verification/"
        ((MOVED_COUNT++))
    fi
    
    # Move setup scripts to scripts/setup/
    SETUP_SCRIPTS=(
        "complete_setup.sh"
        "start_complete_system.sh"
        "stop_complete_system.sh"
        "setup_postgresql.sh"
        "setup_postgres_direct.sh"
        "start_database.sh"
        "start_kafka.sh"
        "fix_redis.sh"
        "install_filterpy.sh"
        "run_optimization.sh"
        "professional_cleanup.sh"
        "start_ai_for_live.sh"
        "start_ai_perception_only.sh"
    )
    
    for script in "${SETUP_SCRIPTS[@]}"; do
        if [ -f "$script" ]; then
            cp "$script" scripts/setup/
            echo "  ✓ Copied: $script → scripts/setup/"
        fi
    done
    
    echo -e "${GREEN}✅ Moved $MOVED_COUNT scripts${NC}"
    echo ""
}

# Function to organize documentation
organize_documentation() {
    echo -e "${YELLOW}📚 Organizing documentation...${NC}"
    
    cd "$PROJECT_ROOT"
    
    # Create docs structure
    mkdir -p docs/user-guides
    mkdir -p docs/technical
    mkdir -p docs/system-guides
    mkdir -p docs/optimization
    mkdir -p docs/archived
    
    # Move user guides
    USER_GUIDES=(
        "USAGE_GUIDE.md"
        "LOCAL_VIDEO_TESTING_READY.md"
        "TROUBLESHOOTING.md"
        "QUICK_START_INTEGRATED.md"
        "QUICK_START.md"
    )
    
    for guide in "${USER_GUIDES[@]}"; do
        if [ -f "$guide" ]; then
            mv "$guide" docs/user-guides/
            echo "  ✓ Moved: $guide → docs/user-guides/"
        fi
    done
    
    # Move technical docs
    if [ -d "UML" ] && [ ! -d "docs/technical/UML" ]; then
        mv UML docs/technical/
        echo "  ✓ Moved: UML → docs/technical/"
    fi
    
    TECHNICAL_DOCS=(
        "MASTER_ROADMAP_2025.md"
        "NEXT_STEPS_ROADMAP.md"
        "PROFESSIONAL_SRS.md"
        "ATSRS.pdf"
        "DOCUMENTATION_INDEX.md"
        "BENCHMARK_RESULTS.md"
    )
    
    for doc in "${TECHNICAL_DOCS[@]}"; do
        if [ -f "$doc" ]; then
            mv "$doc" docs/technical/
            echo "  ✓ Moved: $doc → docs/technical/"
        fi
    done
    
    # Move system guides
    SYSTEM_GUIDES=(
        "CAR_BRAND_EMISSION_SYSTEM_GUIDE.md"
        "EMISSION_FUEL_DECISION_GUIDE.md"
        "VEHICLE_EMISSION_SYSTEM_GUIDE.md"
        "TRAMWAY_DETECTION_SYSTEM.md"
        "TRAMWAY_TRAINING_QUICKSTART.md"
    )
    
    for guide in "${SYSTEM_GUIDES[@]}"; do
        if [ -f "$guide" ]; then
            mv "$guide" docs/system-guides/
            echo "  ✓ Moved: $guide → docs/system-guides/"
        fi
    done
    
    # Move optimization docs
    OPTIMIZATION_DOCS=(
        "ULTRA_SMOOTH_OPTIMIZATIONS.md"
        "SMOOTH_VIDEO_OPTIMIZATIONS.md"
        "PERFORMANCE_OPTIMIZATION_SUMMARY.md"
    )
    
    for doc in "${OPTIMIZATION_DOCS[@]}"; do
        if [ -f "$doc" ]; then
            mv "$doc" docs/optimization/
            echo "  ✓ Moved: $doc → docs/optimization/"
        fi
    done
    
    # Move all remaining status/model docs to archived
    STATUS_DOCS=(
        "ALL_MODELS_INTEGRATION_STATUS.md"
        "FINAL_TEST_INSTRUCTIONS.md"
    )
    
    for doc in "${STATUS_DOCS[@]}"; do
        if [ -f "$doc" ]; then
            mv "$doc" docs/archived/
            echo "  ✓ Archived: $doc"
        fi
    done
    
    echo -e "${GREEN}✅ Documentation organized${NC}"
    echo ""
}

# Function to create new README index
create_readme_index() {
    echo -e "${YELLOW}📄 Creating documentation index...${NC}"
    
    cd "$PROJECT_ROOT"
    
    cat > DOCUMENTATION_INDEX.md << 'EOF'
# 📚 ATMS Documentation Index

## 🚀 Quick Start
- [START HERE](START_HERE.md) - Begin here for setup
- [README](README.md) - Project overview
- [Quick Start Guide](docs/user-guides/QUICK_START_INTEGRATED.md)

## 👤 User Guides
- [Usage Guide](docs/user-guides/USAGE_GUIDE.md) - How to use the system
- [Local Video Testing](docs/user-guides/LOCAL_VIDEO_TESTING_READY.md) - Test with local videos
- [Troubleshooting](docs/user-guides/TROUBLESHOOTING.md) - Common issues

## 🔧 Technical Documentation
- [Professional SRS](docs/technical/PROFESSIONAL_SRS.md) - System requirements
- [UML Diagrams](docs/technical/UML/) - System architecture
- [Master Roadmap](docs/technical/MASTER_ROADMAP_2025.md) - Development plan
- [Benchmark Results](docs/technical/BENCHMARK_RESULTS.md) - Performance metrics

## 🤖 System Guides
- [Car Brand & Emission System](docs/system-guides/CAR_BRAND_EMISSION_SYSTEM_GUIDE.md)
- [Emission & Fuel Decision](docs/system-guides/EMISSION_FUEL_DECISION_GUIDE.md)
- [Vehicle Emission System](docs/system-guides/VEHICLE_EMISSION_SYSTEM_GUIDE.md)
- [Tramway Detection](docs/system-guides/TRAMWAY_DETECTION_SYSTEM.md)

## ⚡ Optimization
- [Ultra Smooth Optimizations](docs/optimization/ULTRA_SMOOTH_OPTIMIZATIONS.md)
- [Smooth Video Optimizations](docs/optimization/SMOOTH_VIDEO_OPTIMIZATIONS.md)
- [Performance Optimization](docs/optimization/PERFORMANCE_OPTIMIZATION_SUMMARY.md)

## 🗂️ Project Structure
```
/Traffic/
├── README.md                     # Project overview
├── START_HERE.md                 # Quick start
├── docs/                         # All documentation
│   ├── user-guides/             # User documentation
│   ├── technical/               # Technical specs
│   ├── system-guides/           # System-specific guides
│   └── optimization/            # Performance docs
├── scripts/                      # All scripts
│   ├── setup/                   # Setup scripts
│   ├── ai_models/               # AI model scripts
│   └── verification/            # Verification tools
├── services/                     # Microservices
├── models/                       # Trained models
├── data/                         # Datasets
└── tests/                        # Test suites
```

## 📞 Support
For issues or questions, refer to [Troubleshooting](docs/user-guides/TROUBLESHOOTING.md)
EOF

    echo -e "${GREEN}✅ Documentation index created${NC}"
    echo ""
}

# Function to show summary
show_summary() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║        Cleanup Complete! ✅                 ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Summary:${NC}"
    echo "  • Backup created: $BACKUP_DIR"
    echo "  • Redundant files removed: ~50 files"
    echo "  • Scripts organized: scripts/ai_models, scripts/verification"
    echo "  • Documentation organized: docs/ structure"
    echo "  • Documentation index: DOCUMENTATION_INDEX.md"
    echo ""
    echo -e "${GREEN}Next Steps:${NC}"
    echo "  1. Review organized structure"
    echo "  2. Test system functionality"
    echo "  3. Update any hardcoded paths in scripts"
    echo "  4. Commit changes to git"
    echo ""
    echo -e "${GREEN}Project Structure:${NC}"
    echo "  Root MD files: 3 (README, START_HERE, DOCUMENTATION_INDEX)"
    echo "  Documentation: Organized in docs/"
    echo "  Scripts: Organized in scripts/"
    echo "  Services: Unchanged (8 microservices)"
    echo ""
}

# Main execution
main() {
    # Confirm before proceeding
    echo -e "${YELLOW}⚠️  This will reorganize your project structure.${NC}"
    echo -e "${YELLOW}   A backup will be created automatically.${NC}"
    echo ""
    read -p "Continue? (y/n): " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${RED}Cleanup cancelled.${NC}"
        exit 1
    fi
    
    echo ""
    
    create_backup
    remove_redundant_files
    organize_scripts
    organize_documentation
    create_readme_index
    show_summary
}

# Run main function
main

