#!/bin/bash

cat << 'EOF'

╔══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║     🧪 TESTING AI PERCEPTION SERVICE                                 ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝

EOF

# Wait for service to be ready
echo "⏳ Waiting for service to start..."
sleep 2

# Test 1: Health Check
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🏥 TEST 1: Health Check"
echo ""
curl -s http://localhost:8001/health | python3 -m json.tool
echo ""

# Test 2: Detector Stats
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 TEST 2: Detector Stats"
echo ""
curl -s http://localhost:8001/detector/stats | python3 -m json.tool
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ SERVICE IS RUNNING!"
echo ""
echo "🎯 TO TEST OBJECT DETECTION:"
echo ""
echo "1. Take a photo with your iPhone camera"
echo "2. Upload it using this command:"
echo ""
echo "   curl -X POST http://localhost:8001/detect/test \\"
echo "     -F 'file=@/path/to/your/image.jpg' | python3 -m json.tool"
echo ""
echo "3. Or use this web interface:"
echo "   Open: http://localhost:8001/docs"
echo "   Click: POST /detect/test"
echo "   Try it out: Upload an image"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""


