#!/usr/bin/env python3
"""
hatchery_receiver.py — Hatchery-side failure package receiver.

Receives failure packages from broodlings (over network or USB mount) and
stores them in a known location for analysis. When run as a server, listens
for POST /api/failure-packages from broodlings that have network connectivity.

Provides:
  receive_failure_package()    — store a failure package from bytes/file
  list_received_packages()     — list stored packages with metadata
  analyze_all_unanalyzed()     — batch-analyze unanalyzed packages
  HatcheryReceiverConfig       — server configuration
  run_receiver_server()        — start simple HTTP receiver (stdlib http.server)

Stdlib only.
"""

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

from failure_package_analyzer import analyze_failure_package, FailureDiagnosis


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class HatcheryReceiverConfig:
    storage_dir:    str  = "/var/lib/broodforge/failure-packages"
    listen_host:    str  = "0.0.0.0"
    listen_port:    int  = 9321
    max_package_mb: int  = 50
    auth_token:     str  = ""   # if set, require X-Broodforge-Token header on every POST
    verbose:        bool = False  # if True, log all requests to stderr


# ---------------------------------------------------------------------------
# Store + list
# ---------------------------------------------------------------------------

def receive_failure_package(
    data:           bytes,
    filename:       str,
    storage_dir:    str = "/var/lib/broodforge/failure-packages",
    received_from:  Optional[str] = None,
) -> str:
    """
    Store a received failure package and return the stored path.

    Creates storage_dir if it does not exist.
    Appends a receipt metadata file alongside the package.
    """
    os.makedirs(storage_dir, exist_ok=True)
    dest = os.path.join(storage_dir, filename)
    with open(dest, "wb") as f:
        f.write(data)

    receipt = {
        "filename":      filename,
        "received_at":   datetime.now(timezone.utc).isoformat(),
        "size_bytes":    len(data),
        "received_from": received_from,
        "analyzed":      False,
    }
    receipt_path = dest + ".receipt.json"
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)

    return dest


def list_received_packages(storage_dir: str) -> list[dict]:
    """
    List all received failure packages with their receipt metadata.

    Returns a list of dicts sorted by received_at descending.
    """
    if not os.path.isdir(storage_dir):
        return []
    results = []
    for entry in os.scandir(storage_dir):
        if entry.name.endswith(".tar.gz"):
            receipt_path = entry.path + ".receipt.json"
            metadata: dict = {"filename": entry.name, "path": entry.path}
            if os.path.exists(receipt_path):
                with open(receipt_path) as f:
                    metadata.update(json.load(f))
            results.append(metadata)
    results.sort(key=lambda x: x.get("received_at", ""), reverse=True)
    return results


def mark_analyzed(package_path: str, diagnosis: FailureDiagnosis) -> None:
    """Update the receipt file to mark a package as analyzed."""
    receipt_path = package_path + ".receipt.json"
    if not os.path.exists(receipt_path):
        return
    with open(receipt_path) as f:
        receipt = json.load(f)
    receipt["analyzed"]      = True
    receipt["analyzed_at"]   = diagnosis.analyzed_at
    receipt["error_type"]    = diagnosis.error_type
    receipt["failed_phase"]  = diagnosis.failed_phase
    receipt["can_regenerate"] = diagnosis.can_regenerate
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)


def analyze_all_unanalyzed(
    storage_dir: str,
    output_dir:  Optional[str] = None,
) -> list[FailureDiagnosis]:
    """
    Analyze all unanalyzed packages in storage_dir.

    Saves a human-readable diagnosis alongside each package.
    Returns list of FailureDiagnosis objects.
    """
    results: list[FailureDiagnosis] = []
    for pkg in list_received_packages(storage_dir):
        if pkg.get("analyzed"):
            continue
        path = pkg.get("path", "")
        if not path or not os.path.exists(path):
            continue
        try:
            diagnosis = analyze_failure_package(path)
            mark_analyzed(path, diagnosis)
            if output_dir:
                out = os.path.join(output_dir, pkg["filename"] + ".analysis.md")
                with open(out, "w") as f:
                    f.write(diagnosis.to_markdown())
            results.append(diagnosis)
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# HTTP receiver server
# ---------------------------------------------------------------------------

class _ReceiverHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that accepts POST /api/failure-packages."""

    _config: HatcheryReceiverConfig = HatcheryReceiverConfig()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/failure-packages":
            self.send_error(404)
            return

        # Token authentication — check X-Broodforge-Token if configured
        expected_token = self._config.auth_token
        if expected_token:
            provided = self.headers.get("X-Broodforge-Token", "")
            if not provided or not secrets.compare_digest(provided, expected_token):
                self.send_error(401, "Unauthorized — missing or invalid X-Broodforge-Token")
                return

        content_length = int(self.headers.get("Content-Length", 0))
        max_bytes = self._config.max_package_mb * 1024 * 1024
        if content_length > max_bytes:
            self.send_error(413, "Package too large")
            return

        data = self.rfile.read(content_length)
        filename = self.headers.get("X-Package-Name") or (
            f"failure-{int(time.time())}.tar.gz"
        )
        # Sanitise filename
        filename = os.path.basename(filename)
        if not filename.endswith(".tar.gz"):
            filename += ".tar.gz"

        client_ip = self.client_address[0]
        try:
            path = receive_failure_package(
                data,
                filename,
                storage_dir=self._config.storage_dir,
                received_from=client_ip,
            )
            response = json.dumps({
                "status":   "received",
                "filename": filename,
                "path":     path,
                "size":     len(data),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        except Exception as e:
            self.send_error(500, str(e))

    def log_message(self, fmt: str, *args: object) -> None:
        if self._config.verbose:
            import sys as _sys
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            print(f"[receiver] {ts} {fmt % args}", file=_sys.stderr)


def run_receiver_server(config: HatcheryReceiverConfig) -> None:
    """
    Start the failure package receiver HTTP server.

    Blocks until interrupted. Run as a background service during active spawns.
    """
    os.makedirs(config.storage_dir, exist_ok=True)

    class _Handler(_ReceiverHandler):
        _config = config

    server = HTTPServer((config.listen_host, config.listen_port), _Handler)
    print(
        f"[receiver] Listening on {config.listen_host}:{config.listen_port} "
        f"— packages stored in {config.storage_dir}"
    )

    # WAN exposure warning: if binding 0.0.0.0 and bootstrap-state indicates wan profile
    if config.listen_host == "0.0.0.0":
        _state_candidates = [
            "/var/lib/broodforge/bootstrap-state.json",
            os.path.join(os.path.dirname(__file__), "bootstrap-state.json"),
        ]
        _profile = None
        for _p in _state_candidates:
            if os.path.exists(_p):
                try:
                    import sys as _sys
                    with open(_p) as _f:
                        _s = json.load(_f)
                    _profile = (_s.get("network_topology") or {}).get("profile")
                except Exception:
                    pass
                break
        if _profile == "wan":
            import sys as _sys
            print(
                "\n"
                "[receiver] WARNING: Receiver is listening on 0.0.0.0 with network_profile=wan.\n"
                "[receiver] WARNING: This exposes the failure package endpoint to the WAN.\n"
                "[receiver] WARNING: Set a strong auth_token (--token) or restrict listen_host.\n",
                file=_sys.stderr,
            )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# CLI (python3 hatchery_receiver.py [--serve] [--analyze <dir>])
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Broodforge hatchery failure package receiver")
    p.add_argument("--serve",   action="store_true", help="Start HTTP receiver server")
    p.add_argument("--analyze", metavar="DIR", help="Analyze all unanalyzed packages in DIR")
    p.add_argument("--list",    metavar="DIR", help="List received packages in DIR")
    p.add_argument("--port",    type=int, default=9321)
    p.add_argument("--storage", default="/var/lib/broodforge/failure-packages")
    p.add_argument("--token",   default="", help="Require X-Broodforge-Token header (recommended for WAN)")
    p.add_argument("--verbose", action="store_true", help="Log all HTTP requests to stderr")
    args = p.parse_args()

    if args.serve:
        cfg = HatcheryReceiverConfig(
            storage_dir=args.storage, listen_port=args.port,
            auth_token=getattr(args, "token", ""),
            verbose=getattr(args, "verbose", False),
        )
        run_receiver_server(cfg)
    elif args.analyze:
        diagnoses = analyze_all_unanalyzed(args.analyze)
        for d in diagnoses:
            print(d.to_markdown())
            print("---")
    elif args.list:
        for pkg in list_received_packages(args.list):
            analyzed = "✓" if pkg.get("analyzed") else "·"
            print(f"  [{analyzed}] {pkg['filename']} ({pkg.get('received_at','?')})")
    else:
        p.print_help()
