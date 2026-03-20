#!/usr/bin/env python3
"""Polls Vultiserver health endpoints and pushes results to Loki."""

import json
import os
import socket
import time
import urllib.request
import urllib.error

LOKI_URL = "http://127.0.0.1:3101/loki/api/v1/push"
INTERVAL = int(os.environ.get("HEALTHCHECK_INTERVAL", "30"))
TARGET_URL = os.environ.get("HEALTHCHECK_TARGET_URL", "")

ENDPOINTS = [
    ("/ping", "ping"),
]

HOSTNAME = socket.gethostname()


def check_endpoint(base_url, path):
    url = base_url.rstrip("/") + path
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except Exception as e:
        return 0, str(e)


def push_to_loki(entries):
    streams = []
    ts = str(int(time.time() * 1e9))

    for endpoint, status, body, healthy in entries:
        line = json.dumps({
            "endpoint": endpoint,
            "status": status,
            "healthy": healthy,
            "response": body[:200],
        })
        streams.append({
            "stream": {
                "app": "basalt-vultiserver",
                "service": "healthcheck",
                "host": HOSTNAME,
                "level": "info" if healthy else "error",
                "endpoint": endpoint,
            },
            "values": [[ts, line]],
        })

    payload = json.dumps({"streams": streams}).encode()
    req = urllib.request.Request(
        LOKI_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        print(f"Failed to push to Loki: {e}", flush=True)


def main():
    if not TARGET_URL:
        print("HEALTHCHECK_TARGET_URL not set, exiting", flush=True)
        return

    while True:
        entries = []
        for path, name in ENDPOINTS:
            status, body = check_endpoint(TARGET_URL, path)
            healthy = 200 <= status < 300
            entries.append((name, status, body, healthy))

        push_to_loki(entries)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
