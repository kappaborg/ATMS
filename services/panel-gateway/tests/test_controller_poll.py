"""Controller-URL mapping parsing + /health mode fetch."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from controller_poll import _fetch_mode, parse_mapping


def test_parse_mapping_bare_url():
    assert parse_mapping("http://host:8010") == {"1": "http://host:8010"}


def test_parse_mapping_with_ids():
    m = parse_mapping("1=http://a:8010, 2=http://b:8010/")
    assert m == {"1": "http://a:8010", "2": "http://b:8010"}


def test_parse_mapping_empty():
    assert parse_mapping("") == {}


def _serve_mode(mode_value):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"status": "healthy", "mode": mode_value}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_fetch_mode_reads_health():
    srv = _serve_mode("all_red_flash")
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        assert _fetch_mode(url) == "all_red_flash"
    finally:
        srv.shutdown()
