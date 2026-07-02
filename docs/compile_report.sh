#!/bin/bash
# Compile LaTeX Project Report
# This script compiles the PROJECT_REPORT.tex file to PDF

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="$SCRIPT_DIR/PROJECT_REPORT.tex"
OUTPUT_DIR="$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════════════════"
echo "📄 Compiling Project Report (LaTeX → PDF)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Check if pdflatex is available
if ! command -v pdflatex &> /dev/null; then
    echo "❌ Error: pdflatex is not installed"
    echo ""
    echo "Installation instructions:"
    echo "  macOS: brew install --cask mactex"
    echo "  Ubuntu: sudo apt-get install texlive-full"
    echo "  Windows: Install MiKTeX or TeX Live"
    exit 1
fi

# Check if report file exists
if [ ! -f "$REPORT_FILE" ]; then
    echo "❌ Error: Report file not found: $REPORT_FILE"
    exit 1
fi

echo "📝 Report file: $REPORT_FILE"
echo "📁 Output directory: $OUTPUT_DIR"
echo ""

# Change to script directory
cd "$SCRIPT_DIR"

# Compile LaTeX document (run twice for references)
echo "🔄 First compilation pass..."
pdflatex -interaction=nonstopmode -output-directory="$OUTPUT_DIR" "$REPORT_FILE" > /dev/null 2>&1

echo "🔄 Second compilation pass (for references)..."
pdflatex -interaction=nonstopmode -output-directory="$OUTPUT_DIR" "$REPORT_FILE" > /dev/null 2>&1

# Check if PDF was created
PDF_FILE="$OUTPUT_DIR/PROJECT_REPORT.pdf"
if [ -f "$PDF_FILE" ]; then
    echo ""
    echo "✅ PDF generated successfully!"
    echo "📄 Output: $PDF_FILE"
    echo ""
    echo "📊 File size: $(du -h "$PDF_FILE" | cut -f1)"
    echo ""
    echo "💡 To view the PDF:"
    echo "   open $PDF_FILE"
    echo ""
else
    echo ""
    echo "❌ Error: PDF generation failed"
    echo "   Check the log file for errors"
    exit 1
fi

# Clean up auxiliary files (optional)
echo "🧹 Cleaning up auxiliary files..."
rm -f "$OUTPUT_DIR/PROJECT_REPORT.aux" \
      "$OUTPUT_DIR/PROJECT_REPORT.log" \
      "$OUTPUT_DIR/PROJECT_REPORT.out" \
      "$OUTPUT_DIR/PROJECT_REPORT.toc"

echo "✅ Compilation complete!"
echo "═══════════════════════════════════════════════════════════════"

