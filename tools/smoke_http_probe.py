#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema


class Handler(BaseHTTPRequestHandler):
    seen: list[str] = []
    sensitive_headers_seen: list[str] = []

    def do_HEAD(self) -> None:
        self.seen.append(self.path)
        self.sensitive_headers_seen.extend(name for name in self.headers if name.lower() in {"authorization", "cookie", "proxy-authorization"})
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/destination")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "999999")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / "tools" / "botctl.py"), "probe-http"]
    blocked = subprocess.run(command + ["--url", "https://example.invalid/health"], cwd=root, text=True, capture_output=True)
    unsafe = subprocess.run(command + ["--url", "https://user:pass@example.invalid/health?q=token", "--confirm-network"], cwd=root, text=True, capture_output=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/health"
    result = subprocess.run(command + ["--url", url, "--confirm-network", "--allow-insecure-localhost", "--timeout", "2", "--format", "json"], cwd=root, text=True, capture_output=True)
    redirected = subprocess.run(command + ["--url", f"http://127.0.0.1:{server.server_port}/redirect", "--confirm-network", "--allow-insecure-localhost", "--format", "json"], cwd=root, text=True, capture_output=True)
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()
    payload = json.loads(result.stdout)
    schema = json.loads((root / "schemas" / "http-probe.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    redirected_payload = json.loads(redirected.stdout)
    local_ok = result.returncode == 0 and payload["check"]["method"] == "HEAD" and payload["safety"]["reads_response_body"] is False and Handler.sensitive_headers_seen == []
    redirect_ok = redirected.returncode != 0 and redirected_payload["check"]["state"] == "redirect_blocked" and Handler.seen == ["/health", "/redirect"]
    passed = blocked.returncode != 0 and unsafe.returncode != 0 and local_ok and redirect_ok
    print(f"http_probe_confirmation_guard_ok={blocked.returncode != 0}")
    print(f"http_probe_secret_url_guard_ok={unsafe.returncode != 0}")
    print(f"http_probe_local_head_only_ok={local_ok}")
    print(f"http_probe_redirect_guard_ok={redirect_ok}")
    print("http_probe_smoke=passed" if passed else "http_probe_smoke=failed")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
