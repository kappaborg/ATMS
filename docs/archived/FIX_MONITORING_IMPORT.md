# 🔧 Fix: Monitoring Not Available Despite Installed Packages

## Problem
Packages are installed in `services/ai-perception/venv` but script can't import them.

## Root Cause
The script is running with system Python, but packages are in a virtual environment.

## Solutions

### Solution 1: Install in System Python (Quick Fix)
```bash
# Use system python3 (not venv)
python3 -m pip install prometheus-client psutil
```

### Solution 2: Use the Virtual Environment (Recommended)
```bash
# Activate the venv first
source services/ai-perception/venv/bin/activate

# Then run the script
python3 youtube_decision_processor.py <url>
```

### Solution 3: Install in Current Environment
```bash
# Check which Python you're using
which python3

# Install in that Python
python3 -m pip install prometheus-client psutil
```

## Verify Installation
```bash
python3 -c "from prometheus_client import start_http_server; import psutil; print('✅ Dependencies available')"
```

## Check Your Environment
```bash
# Check if in venv
python3 -c "import sys; print('In venv:', hasattr(sys, 'real_prefix') or sys.base_prefix != sys.prefix)"

# Check Python path
python3 -c "import sys; print(sys.executable)"
```
