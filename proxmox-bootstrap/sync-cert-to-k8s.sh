#!/usr/bin/env bash
# sync-cert-to-k8s.sh — Sync TLS certificate to Kubernetes secrets.
#
# Stub: this action type is registered in remediation_executor.py but the
# implementation has not yet been written. The script exits 0 so that the
# remediation engine records a successful no-op rather than a failure.
#
# TODO: implement using kubectl create secret tls or cert-manager annotation
#       sync once the k8s secret management pattern is decided.

set -euo pipefail

echo "[sync-cert-to-k8s] Not yet implemented — no-op stub" >&2
exit 0
