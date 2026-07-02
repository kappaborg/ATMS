#!/usr/bin/env python3
"""
Professional Project Cleanup Script
===================================
Safely removes unnecessary files and folders to improve maintainability.
Creates a detailed report of what was removed.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set
import json

class ProjectCleanup:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.removed_files: List[str] = []
        self.removed_dirs: List[str] = []
        self.total_size_freed = 0
        self.report_path = project_root / "docs" / "CLEANUP_REPORT.md"
        
    def get_size(self, path: Path) -> int:
        """Get size of file or directory in bytes"""
        try:
            if path.is_file():
                return path.stat().st_size
            elif path.is_dir():
                return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        except:
            pass
        return 0
    
    def safe_remove(self, path: Path, reason: str = "") -> bool:
        """Safely remove a file or directory"""
        try:
            if not path.exists():
                return False
            
            size = self.get_size(path)
            
            if path.is_file():
                path.unlink()
                self.removed_files.append(str(path.relative_to(self.project_root)))
                self.total_size_freed += size
                return True
            elif path.is_dir():
                shutil.rmtree(path)
                self.removed_dirs.append(str(path.relative_to(self.project_root)))
                self.total_size_freed += size
                return True
        except Exception as e:
            print(f"⚠️  Error removing {path}: {e}")
        return False
    
    def cleanup_build_artifacts(self):
        """Remove Python build artifacts"""
        print("🧹 Cleaning build artifacts...")
        
        patterns = [
            "**/__pycache__",
            "**/*.pyc",
            "**/*.pyo",
            "**/.DS_Store",
            "**/*.egg-info",
            "**/.pytest_cache",
            "**/.mypy_cache",
            "**/.ruff_cache",
            "**/htmlcov",
            "**/.coverage",
        ]
        
        for pattern in patterns:
            for path in self.project_root.rglob(pattern):
                if path.is_file() or path.is_dir():
                    self.safe_remove(path, "Build artifact")
    
    def cleanup_debug_files(self):
        """Remove debug and test output files"""
        print("🧹 Cleaning debug files...")
        
        debug_files = [
            "debug_frame.jpg",
            "output.mp4",
            "services/ai-perception/test_detection_result.jpg",
            "services/ai-perception/test_full_pipeline_result.jpg",
            "services/ai-perception/test_frame.jpg",
        ]
        
        for file_path in debug_files:
            path = self.project_root / file_path
            if path.exists():
                self.safe_remove(path, "Debug file")
    
    def cleanup_old_tests(self):
        """Archive old test results"""
        print("🧹 Cleaning old test results...")
        
        old_test_dirs = [
            "archived_tests",
        ]
        
        for dir_path in old_test_dirs:
            path = self.project_root / dir_path
            if path.exists() and path.is_dir():
                # Check size - if too large, just report
                size_mb = self.get_size(path) / (1024 * 1024)
                if size_mb < 500:  # Only remove if < 500MB
                    self.safe_remove(path, "Old test results")
                else:
                    print(f"  ⚠️  Skipping {dir_path} (too large: {size_mb:.1f}MB)")
    
    def consolidate_documentation(self):
        """Identify redundant documentation files"""
        print("📚 Analyzing documentation...")
        
        # Files to consolidate/remove
        redundant_docs = [
            "docs/ALL_FIXES_APPLIED.md",  # Consolidated into IMPLEMENTATION_SUMMARY
            "docs/FIXES_APPLIED.md",  # Consolidated into IMPLEMENTATION_SUMMARY
            "docs/FIX_MONITORING_IMPORT.md",  # Temporary fix doc
            "docs/PROMETHEUS_CONNECTION_FIX.md",  # Temporary fix doc
            "docs/PROMETHEUS_STATUS.md",  # Temporary status doc
            "docs/GRAFANA_QUICK_FIX.md",  # Consolidated into GRAFANA_TROUBLESHOOTING
            "docs/DECISION_DEBUGGING.md",  # Can be merged into main docs
        ]
        
        for doc_path in redundant_docs:
            path = self.project_root / doc_path
            if path.exists():
                # Move to archived instead of deleting
                archived_dir = self.project_root / "docs" / "archived"
                archived_dir.mkdir(exist_ok=True)
                archived_path = archived_dir / path.name
                if not archived_path.exists():
                    shutil.move(str(path), str(archived_path))
                    print(f"  📦 Archived: {doc_path}")
    
    def identify_unused_scripts(self):
        """Identify potentially unused scripts"""
        print("🔍 Analyzing scripts...")
        
        # Scripts that might be redundant
        potentially_unused = [
            "realtime_video_processor.py",  # Superseded by youtube_decision_processor.py
        ]
        
        for script in potentially_unused:
            path = self.project_root / script
            if path.exists():
                print(f"  ⚠️  Potentially unused: {script} (review manually)")
    
    def generate_report(self):
        """Generate cleanup report"""
        print("\n📊 Generating cleanup report...")
        
        report = f"""# Project Cleanup Report

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary

- **Files Removed**: {len(self.removed_files)}
- **Directories Removed**: {len(self.removed_dirs)}
- **Total Size Freed**: {self.total_size_freed / (1024 * 1024):.2f} MB

## Removed Files

"""
        
        if self.removed_files:
            report += "### Files\n\n"
            for file in sorted(self.removed_files)[:50]:  # Limit to first 50
                report += f"- `{file}`\n"
            if len(self.removed_files) > 50:
                report += f"\n... and {len(self.removed_files) - 50} more files\n"
        
        if self.removed_dirs:
            report += "\n### Directories\n\n"
            for dir in sorted(self.removed_dirs):
                report += f"- `{dir}/`\n"
        
        report += f"""
## Recommendations

1. **Large Datasets**: Consider archiving `Car_Recognition/` if not actively used for training
2. **Documentation**: Review `docs/historical/` for outdated content
3. **Scripts**: Review scripts in `scripts/` for duplicates
4. **Docker Configs**: Verify which docker-compose files are actively used

## Next Steps

1. Review this report
2. Test the system to ensure nothing critical was removed
3. Update `.gitignore` to prevent future build artifacts
4. Consider archiving large datasets to external storage
"""
        
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(report)
        print(f"  ✅ Report saved to: {self.report_path}")
    
    def run(self):
        """Run complete cleanup"""
        print("🚀 Starting Professional Project Cleanup")
        print("=" * 60)
        print()
        
        self.cleanup_build_artifacts()
        self.cleanup_debug_files()
        self.cleanup_old_tests()
        self.consolidate_documentation()
        self.identify_unused_scripts()
        
        print()
        print("=" * 60)
        print(f"✅ Cleanup Complete!")
        print(f"   Removed {len(self.removed_files)} files")
        print(f"   Removed {len(self.removed_dirs)} directories")
        print(f"   Freed {self.total_size_freed / (1024 * 1024):.2f} MB")
        print()
        
        self.generate_report()
        
        return {
            'files_removed': len(self.removed_files),
            'dirs_removed': len(self.removed_dirs),
            'size_freed_mb': self.total_size_freed / (1024 * 1024)
        }

if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    cleanup = ProjectCleanup(project_root)
    results = cleanup.run()
    
    print("\n" + "=" * 60)
    print("📋 Cleanup Summary:")
    print(f"   Files: {results['files_removed']}")
    print(f"   Directories: {results['dirs_removed']}")
    print(f"   Space Freed: {results['size_freed_mb']:.2f} MB")
    print("\n✅ Done! Review the report in docs/CLEANUP_REPORT.md")

