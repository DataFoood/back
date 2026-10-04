"""Nominatim falso pra testes locais: /search devolve o centro de Marília,
/reverse devolve "Centro, Marília". Porta 11600.
    uv run python final-tests/fake_nominatim.py &
    export NOMINATIM_URL=http://127.0.0.1:11600
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/search"):
            body = [{"lat": "-22.2139", "lon": "-49.9458"}]
        else:
            body = {"address": {"suburb": "Centro", "city": "Marília"}}
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a): pass

ThreadingHTTPServer(("127.0.0.1", 11600), H).serve_forever()
