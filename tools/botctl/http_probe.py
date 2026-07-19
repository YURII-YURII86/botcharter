from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from .model import API_VERSION, now_iso


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _validated_url(raw: str, allow_insecure_localhost: bool) -> tuple[str, str, int | None]:
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use http or https and include a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("URL credentials, query strings, and fragments are forbidden")
    localhost = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (localhost and allow_insecure_localhost):
        raise ValueError("HTTPS is required; localhost HTTP also needs --allow-insecure-localhost")
    return parsed.geturl(), parsed.hostname, parsed.port


def probe_http_health(*, url: str, confirm_network: bool, allow_insecure_localhost: bool = False, timeout: float = 5.0) -> dict[str, Any]:
    if not confirm_network:
        raise ValueError("network access requires --confirm-network")
    if not 1 <= timeout <= 30:
        raise ValueError("timeout must be between 1 and 30 seconds")
    safe_url, host, port = _validated_url(url, allow_insecure_localhost)
    request = urllib.request.Request(safe_url, method="HEAD")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    started = time.monotonic()
    status_code: int | None = None
    error: str | None = None
    try:
        response = opener.open(request, timeout=timeout)
        status_code = int(response.status)
        response.close()
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        error = "redirect_blocked" if 300 <= exc.code < 400 else "http_error"
        exc.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        error = "network_error"
    duration_ms = round((time.monotonic() - started) * 1000, 3)
    passed = status_code is not None and 200 <= status_code < 300
    state = "reachable" if passed else error or "unexpected_status"
    return {
        "apiVersion": API_VERSION,
        "kind": "BotHttpHealthProbe",
        "generated_at": now_iso(),
        "read_only": True,
        "scope": "explicit_http_head",
        "target": {"scheme": urlsplit(safe_url).scheme, "host": host, "port": port, "path": urlsplit(safe_url).path or "/"},
        "summary": {"status": "passed" if passed else "failed"},
        "check": {"method": "HEAD", "status_code": status_code, "state": state, "duration_ms": duration_ms, "timeout_seconds": timeout},
        "safety": {
            "network_explicitly_confirmed": True,
            "follows_redirects": False,
            "reads_response_body": False,
            "sends_authorization": False,
            "sends_cookies": False,
            "uses_environment_proxy": False,
            "writes_target": False,
        },
    }
