#!/bin/bash
# Quick YouTube Test - Simple wrapper for testing

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -z "$1" ]; then
    echo "Usage: $0 <youtube_url>"
    echo ""
    echo "Example:"
    echo "  $0 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'"
    echo ""
    exit 1
fi

# Run the complete test script
exec ./scripts/test_youtube_complete.sh "$1" --duration 60

