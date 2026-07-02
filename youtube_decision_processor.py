#!/usr/bin/env python3
"""DEPRECATED SHIM — the processor moved to
services/video-processor/tools/youtube_decision_processor.py (gap H3).
This shim delegates so existing invocations keep working; update your
scripts to the new path, this file will be removed.
"""
import runpy
import sys
from pathlib import Path

sys.stderr.write(
    "NOTE: youtube_decision_processor.py moved to "
    "services/video-processor/tools/ — update your invocation.\n"
)
runpy.run_path(
    str(Path(__file__).resolve().parent / "services/video-processor/tools/youtube_decision_processor.py"),
    run_name="__main__",
)
