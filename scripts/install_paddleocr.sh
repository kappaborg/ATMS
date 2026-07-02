#!/bin/bash
# Install PaddleOCR for better license plate recognition

echo "🔧 Installing PaddleOCR for Advanced OCR System"
echo "=" | head -c 60 && echo ""

cd services/ai-perception
source venv/bin/activate

echo "📦 Installing PaddleOCR..."
pip install paddleocr 2>&1 | tail -20

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ PaddleOCR installed successfully!"
    echo ""
    echo "📋 Next steps:"
    echo "1. Test on your plate images:"
    echo "   python ../../scripts/test_advanced_ocr.py plate_1_80x22.jpg"
    echo ""
    echo "2. Compare with current system:"
    echo "   python ../../scripts/diagnose_ocr_issue.py ../../test_frame.jpg"
    echo ""
    echo "3. If results are better, the system will automatically use PaddleOCR"
else
    echo ""
    echo "❌ Installation failed. Try manually:"
    echo "   pip install paddleocr==2.7.0.3"
fi

