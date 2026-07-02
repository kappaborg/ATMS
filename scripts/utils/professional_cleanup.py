#!/usr/bin/env python3
"""
Professional Repository Cleanup Script
======================================

Identifies and removes:
1. Duplicate/outdated .md documentation files
2. Unused Python files
3. Temporary/test artifacts
4. Old deprecated scripts

Maintains project professionalism by keeping only essential files.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple
from datetime import datetime
import shutil

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Color codes
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text.center(80)}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}\n")

def print_success(text: str):
    print(f"{Colors.GREEN}✅ {text}{Colors.RESET}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.RESET}")

def print_error(text: str):
    print(f"{Colors.RED}❌ {text}{Colors.RESET}")

def print_info(text: str):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.RESET}")

class ProfessionalCleanup:
    """Professional repository cleanup"""
    
    def __init__(self, dry_run: bool = True):
        self.project_root = PROJECT_ROOT
        self.dry_run = dry_run
        self.files_to_remove: List[Path] = []
        self.files_to_keep: Set[Path] = set()
        self.cleanup_log: List[Dict] = []
        
    def identify_essential_files(self):
        """Identify essential files that must be kept"""
        essential = {
            # Core documentation
            "README.md",
            "PROFESSIONAL_SRS.md",  # Keep most recent SRS
            "QUICK_START.md",
            "TROUBLESHOOTING.md",
            "COMPREHENSIVE_PROJECT_REVIEW.md",  # Just created
            "VERIFICATION_OUTPUT_ANALYSIS.md",  # Just created
            "CAR_BRAND_EMISSION_SYSTEM_GUIDE.md",
            "VEHICLE_EMISSION_SYSTEM_GUIDE.md",
            "EMISSION_FUEL_DECISION_GUIDE.md",
            
            # System guides
            "TRAMWAY_DETECTION_SYSTEM.md",
            "TRAMWAY_TRAINING_QUICKSTART.md",
            "START_ALL_SERVICES.md",
            
            # Core Python files
            "ai_decision_system.py",
            "car_brand_classification_emission_system.py",
            "emission_calculation_system.py",
            "enhanced_vehicle_classification_emission_system.py",
            "integrated_brand_emission_system.py",
            "integrated_emission_decision_system.py",
            "multi_view_fusion_system.py",
            "trajectory_anomaly_detection.py",
            "trajectory_tracking_system.py",
            
            # Configuration
            "config/anomaly_config.json",
            "config/multi_view_config.json",
            
            # Scripts
            "scripts/verify_system_status.py",
            "scripts/professional_cleanup.py",  # This script
        }
        
        for name in essential:
            path = self.project_root / name
            if path.exists():
                self.files_to_keep.add(path)
    
    def find_duplicate_docs(self) -> List[Path]:
        """Find duplicate/outdated documentation files"""
        duplicates = []
        
        # SRS duplicates - keep only PROFESSIONAL_SRS.md (most recent)
        srs_files = [
            "COMPREHENSIVE_SRS_v3.0.md",
            "ATMS_COMPLETE_SRS_v4.0.md",
            "SRS_WHATS_NEW_v4.0.md",
            # Keep: PROFESSIONAL_SRS.md
        ]
        
        for srs_file in srs_files:
            path = self.project_root / srs_file
            if path.exists():
                duplicates.append(path)
        
        # Documentation index duplicates
        index_files = [
            "DOCUMENTATION_INDEX.md",  # Keep this one (more recent)
            "docs/historical/INDEX.md",  # Remove (old version)
        ]
        # We'll keep DOCUMENTATION_INDEX.md, remove old one
        
        # Database documentation duplicates
        db_docs = [
            "POSTGRESQL_SETUP_GUIDE.md",
            "PGADMIN_SETUP_GUIDE.md",
            "DATABASE_INTEGRATION_INDEX.md",
            "DATABASE_MIGRATION_COMPLETE.md",
            "DATABASE_SCHEMA_ANALYSIS.md",
            "MIGRATION_EXECUTION_SUMMARY.md",
            "APPLICATION_INTEGRATION_GUIDE.md",
            # Keep: database/MIGRATION_GUIDE.md (in proper location)
        ]
        
        # These are likely outdated or superseded
        for doc in db_docs:
            path = self.project_root / doc
            if path.exists() and path not in self.files_to_keep:
                duplicates.append(path)
        
        # Benchmark/test result files
        benchmark_files = [
            "COMPREHENSIVE_MODEL_BENCHMARK_20251028_181508.md",
            "UML_IMPLEMENTATION_VALIDATION.md",
            "MODEL_INTEGRATION_VERIFICATION.md",
        ]
        
        for benchmark in benchmark_files:
            path = self.project_root / benchmark
            if path.exists() and path not in self.files_to_keep:
                duplicates.append(path)
        
        return duplicates
    
    def find_unused_python_files(self) -> List[Path]:
        """Find unused Python files"""
        unused = []
        
        # Test/benchmark scripts (keep in tests/ or scripts/)
        root_python_files = [
            "benchmark_optimization.py",
            "comprehensive_model_benchmark.py",
            "verify_model_integration.py",
            "model_quantization_tensorrt.py",
        ]
        
        # Keep verify_model_integration.py if it's used
        for py_file in root_python_files:
            path = self.project_root / py_file
            if path.exists() and "verify_model_integration" not in py_file:
                # Check if it's referenced
                if not self.is_file_referenced(path):
                    unused.append(path)
        
        return unused
    
    def find_temporary_files(self) -> List[Path]:
        """Find temporary/test artifacts"""
        temp_files = []
        
        # Temporary test images
        temp_images = [
            "dummy_test_image.jpg",
        ]
        
        for img in temp_images:
            path = self.project_root / img
            if path.exists():
                temp_files.append(path)
        
        # Old setup scripts that might be superseded
        old_scripts = [
            "setup_postgres_direct.sh",  # If setup_postgresql.sh exists
            "fix_redis.sh",
            "install_filterpy.sh",
        ]
        
        for script in old_scripts:
            path = self.project_root / script
            if path.exists():
                # Check if there's a newer version
                if self.has_newer_version(path):
                    temp_files.append(path)
        
        return temp_files
    
    def is_file_referenced(self, file_path: Path) -> bool:
        """Check if file is referenced in README or other docs"""
        # Simple check - see if filename appears in key docs
        filename = file_path.name
        key_docs = ["README.md", "QUICK_START.md", "PROFESSIONAL_SRS.md"]
        
        for doc_name in key_docs:
            doc_path = self.project_root / doc_name
            if doc_path.exists():
                try:
                    content = doc_path.read_text()
                    if filename in content:
                        return True
                except:
                    pass
        return False
    
    def has_newer_version(self, file_path: Path) -> bool:
        """Check if there's a newer version of the script"""
        name_base = file_path.stem
        parent = file_path.parent
        
        # Look for similar named files
        for sibling in parent.iterdir():
            if sibling.is_file() and sibling != file_path:
                if name_base in sibling.name and sibling.suffix == file_path.suffix:
                    # Compare modification times
                    if sibling.stat().st_mtime > file_path.stat().st_mtime:
                        return True
        return False
    
    def analyze_cleanup(self) -> Dict:
        """Analyze what can be cleaned up"""
        print_header("Repository Cleanup Analysis")
        
        # Identify essential files first
        self.identify_essential_files()
        print_info(f"Identified {len(self.files_to_keep)} essential files to keep")
        
        # Find duplicates
        duplicates = self.find_duplicate_docs()
        print_warning(f"Found {len(duplicates)} duplicate/outdated documentation files")
        for dup in duplicates[:10]:  # Show first 10
            print(f"  - {dup.name}")
        
        # Find unused Python files
        unused_py = self.find_unused_python_files()
        print_warning(f"Found {len(unused_py)} potentially unused Python files")
        for py_file in unused_py:
            print(f"  - {py_file.name}")
        
        # Find temporary files
        temp_files = self.find_temporary_files()
        print_warning(f"Found {len(temp_files)} temporary/test files")
        for temp in temp_files:
            print(f"  - {temp.name}")
        
        return {
            "duplicates": duplicates,
            "unused_python": unused_py,
            "temporary": temp_files,
            "total": len(duplicates) + len(unused_py) + len(temp_files)
        }
    
    def perform_cleanup(self, files: List[Path], category: str):
        """Perform cleanup (dry-run or actual)"""
        for file_path in files:
            if file_path in self.files_to_keep:
                continue
            
            if self.dry_run:
                print_warning(f"[DRY RUN] Would remove: {file_path}")
            else:
                try:
                    file_path.unlink()
                    print_success(f"Removed: {file_path.name}")
                    self.cleanup_log.append({
                        "file": str(file_path),
                        "category": category,
                        "action": "removed",
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception as e:
                    print_error(f"Failed to remove {file_path.name}: {e}")
    
    def run_cleanup(self, auto_confirm: bool = False):
        """Run complete cleanup process"""
        print_header("Professional Repository Cleanup")
        
        if self.dry_run:
            print_warning("DRY RUN MODE - No files will be deleted")
        else:
            print_error("LIVE MODE - Files will be permanently deleted!")
            if not auto_confirm:
                response = input("Are you sure? (yes/no): ")
                if response.lower() != "yes":
                    print_info("Cleanup cancelled")
                    return
            else:
                print_warning("Auto-confirm enabled - proceeding with cleanup")
        
        # Analyze
        analysis = self.analyze_cleanup()
        
        if analysis["total"] == 0:
            print_success("No cleanup needed - repository is already clean!")
            return
        
        print_header("Cleanup Summary")
        print(f"Files to remove: {analysis['total']}")
        print(f"  - Duplicate docs: {len(analysis['duplicates'])}")
        print(f"  - Unused Python: {len(analysis['unused_python'])}")
        print(f"  - Temporary files: {len(analysis['temporary'])}")
        
        # Perform cleanup
        print_header("Performing Cleanup")
        
        self.perform_cleanup(analysis["duplicates"], "duplicate_docs")
        self.perform_cleanup(analysis["unused_python"], "unused_python")
        self.perform_cleanup(analysis["temporary"], "temporary_files")
        
        # Save cleanup log
        if self.cleanup_log:
            log_path = self.project_root / "cleanup_log.json"
            with open(log_path, 'w') as f:
                json.dump(self.cleanup_log, f, indent=2)
            print_info(f"Cleanup log saved to: {log_path}")
        
        print_header("Cleanup Complete")
        if self.dry_run:
            print_info("This was a dry run. Run with --live to perform actual cleanup.")
        else:
            print_success(f"Removed {len(self.cleanup_log)} files")

def main():
    import sys
    
    dry_run = True
    auto_confirm = False
    if "--live" in sys.argv:
        dry_run = False
    if "--yes" in sys.argv:
        auto_confirm = True
    
    cleaner = ProfessionalCleanup(dry_run=dry_run)
    cleaner.run_cleanup(auto_confirm=auto_confirm)

if __name__ == "__main__":
    main()

