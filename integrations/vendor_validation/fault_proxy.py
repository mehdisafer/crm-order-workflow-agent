#!/usr/bin/env python3
"""HTTPS response-loss shim for an explicitly authorized synthetic vendor test.

Forward the real write to MuleSoft, persist its response, then close the local
client socket once. This does not simulate a successful Salesforce mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class State:
    def __init__(self, upstream: str, token: str, receipt: Path, ca_file: str | None):
        self.upstream = upstream.rstrip("/")
        self.token = token
        self.receipt = receipt
        self.opener = urllib.request.build_opener(
            NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca_file))
        )
        self.lock = threading.Lock()
        self.armed: str | None = None
        self.in_flight: str | None = None
        self.evidence: dict | None = None

    def persist(self, evidence: dict) -> None:
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        with self.receipt.open("w", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.evidence = evidence


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass  # Do not log headers, URLs, or OAuth information.

    def respond(self, status: int, value: dict) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self) -> None:
        state: State = self.server.state
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 8192:
                return self.respond(413, {"error": "body_limit"})
            body = self.rfile.read(length)
            if self.path.startswith("/__p06_faults/"):
                supplied = self.headers.get("Authorization", "")
                if not hmac.compare_digest(supplied, f"Bearer {state.token}"):
                    return self.respond(401, {"error": "fault_control_unauthorized"})
                if self.path == "/__p06_faults/arm" and self.command == "POST":
                    key = json.loads(body)["effect_key"]
                    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key):
                        return self.respond(400, {"error": "invalid_effect_key"})
                    with state.lock:
                        if state.armed or state.in_flight or state.evidence:
                            return self.respond(409, {"error": "one_fault_per_process"})
                        state.armed = key
                    return self.respond(200, {"armed_effect_key": key})
                if self.path == "/__p06_faults/state" and self.command == "GET":
                    with state.lock:
                        return self.respond(
                            200,
                            {"armed": state.armed, "in_flight": state.in_flight, "evidence": state.evidence},
                        )
                return self.respond(404, {"error": "not_found"})
            path = unquote(urlsplit(self.path).path)
            if not re.fullmatch(
                r"/v1/(capabilities|customers|orders|orders/[A-Za-z0-9]{15,18}(/effects)?|effects/[A-Za-z0-9_.:-]{1,128})",
                path,
            ):
                return self.respond(404, {"error": "path_not_allowed"})
            candidate = json.loads(body) if self.command == "POST" else None
            should_drop = False
            with state.lock:
                if candidate and state.armed == candidate.get("effect_key"):
                    if state.in_flight:
                        return self.respond(503, {"error": "fault_request_in_flight"})
                    should_drop = True
                    state.in_flight = state.armed
            headers = {
                name: self.headers[name]
                for name in ("Authorization", "X-Correlation-ID", "Content-Type")
                if self.headers.get(name)
            }
            request = urllib.request.Request(
                state.upstream + self.path,
                data=body if self.command == "POST" else None,
                headers=headers,
                method=self.command,
            )
            try:
                response = state.opener.open(request, timeout=20)
            except urllib.error.HTTPError as rejected:
                response = rejected
            with response:
                payload = response.read(1048577)
                status = response.status
                response_headers = dict(response.headers)
            if len(payload) > 1048576:
                raise ValueError("upstream_payload_limit")
            if should_drop and 200 <= status < 300:
                evidence = {
                    "fault": "real_mule_success_response_dropped",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "effect_key": candidate["effect_key"],
                    "request": candidate,
                    "request_sha256": hashlib.sha256(body).hexdigest(),
                    "upstream_status": status,
                    "upstream_response": json.loads(payload),
                    "forwarded_to_real_mule": True,
                    "fault_location": "local_proxy_after_real_upstream_response",
                }
                with state.lock:
                    state.persist(evidence)
                    state.armed = None
                    state.in_flight = None
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
            with state.lock:
                if should_drop:
                    state.in_flight = None
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for header in ("Retry-After", "X-Correlation-ID"):
                if response_headers.get(header):
                    self.send_header(header, response_headers[header])
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError, KeyError, OSError, urllib.error.URLError):
            # No retry here. The caller must reconcile an unknown write.
            self.respond(503, {"error": "upstream_result_uncertain"})

    do_GET = handle_request
    do_POST = handle_request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--upstream-ca")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("P06_LIVE_SCOPE") != "synthetic_nonproduction":
        raise SystemExit("Set P06_LIVE_SCOPE=synthetic_nonproduction for the authorized fixture only")
    if args.receipt.exists():
        raise SystemExit("Use a new receipt file; existing fault evidence is never overwritten")
    upstream = os.environ["P06_MULE_DIRECT_URL"]
    parsed = urlsplit(upstream)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise SystemExit("P06_MULE_DIRECT_URL must be the authorized HTTPS Mule origin")
    token = os.environ["P06_FAULT_CONTROL_TOKEN"]
    if len(token) < 32:
        raise SystemExit("A separate external fault control token of at least 32 characters is required")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.state = State(upstream, token, args.receipt, args.upstream_ca)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(
        json.dumps({"status": "LISTENING", "bound_to": f"127.0.0.1:{args.port}", "armed": False}), flush=True
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
