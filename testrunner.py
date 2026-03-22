#!/usr/bin/env python3
"""Runs external tests against the Basalt service and pushes results to Loki."""

import importlib
import json
import os
import pkgutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure the script's directory is on the Python path so `tests` is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# When run as __main__, also register as "testrunner" so that
# `from testrunner import BaseTestSuite` in test files resolves to the same classes.
if __name__ == "__main__":
    sys.modules.setdefault("testrunner", sys.modules[__name__])

LOKI_URL = "http://127.0.0.1:3101/loki/api/v1/push"
INTERVAL = int(os.environ.get("TESTRUNNER_INTERVAL", "300"))
TARGET_URL = os.environ.get("HEALTHCHECK_TARGET_URL", "")
TRIGGER_PORT = int(os.environ.get("TESTRUNNER_TRIGGER_PORT", "8090"))
REQUEST_DELAY = float(os.environ.get("TESTRUNNER_REQUEST_DELAY", "0.1"))
HOSTNAME = socket.gethostname()

# Global request throttle — ensures all outgoing HTTP requests are spaced apart
_last_request_time = 0.0
_request_lock = threading.Lock()


def _throttle():
    """Sleep if needed to maintain REQUEST_DELAY spacing between HTTP requests."""
    global _last_request_time
    if REQUEST_DELAY <= 0:
        return
    with _request_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        _last_request_time = time.monotonic()

# Event to signal an immediate test run
trigger_event = threading.Event()

# Timestamp of the last completed test run (epoch seconds), shared across threads
last_run_time = None
last_run_results = []
is_running = False
last_run_lock = threading.Lock()


class TestResult:
    """Result of a single test case."""

    def __init__(self, suite, name, passed, duration_ms, detail=""):
        self.suite = suite
        self.name = name
        self.passed = passed
        self.duration_ms = duration_ms
        self.detail = detail


class BaseTestSuite:
    """Base class for test suites. Subclass and add test_* methods."""

    suite_name = "unnamed"

    def __init__(self, target_url):
        self.target_url = target_url

    def http_get(self, path, timeout=10):
        """Helper: GET request against the target service."""
        _throttle()
        url = self.target_url.rstrip("/") + path
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()

    def http_post(self, path, body=None, headers=None, timeout=10):
        """Helper: POST request against the target service."""
        _throttle()
        url = self.target_url.rstrip("/") + path
        data = json.dumps(body).encode() if body else None
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()

    def run_all(self):
        """Discover and run all test_* methods, returning TestResults."""
        results = []
        methods = sorted(m for m in dir(self) if m.startswith("test_"))
        for method_name in methods:
            start = time.monotonic()
            try:
                getattr(self, method_name)()
                elapsed = (time.monotonic() - start) * 1000
                results.append(TestResult(
                    suite=self.suite_name,
                    name=method_name,
                    passed=True,
                    duration_ms=round(elapsed, 1),
                ))
            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                results.append(TestResult(
                    suite=self.suite_name,
                    name=method_name,
                    passed=False,
                    duration_ms=round(elapsed, 1),
                    detail=f"{type(e).__name__}: {e}",
                ))
        return results


class TriggerHandler(BaseHTTPRequestHandler):
    """HTTP handler that triggers an immediate test run."""

    def do_POST(self, *_args):
        if self.path == "/run":
            trigger_event.set()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "triggered"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self, *_args):
        if self.path == "/run":
            trigger_event.set()
            self._json_response({"status": "triggered"})
        elif self.path == "/status":
            with last_run_lock:
                ts = last_run_time
                running = is_running
            self._json_response({"last_run_epoch": ts, "is_running": running})
        elif self.path == "/results":
            with last_run_lock:
                ts = last_run_time
                results = list(last_run_results)
            self._json_response({
                "last_run_epoch": ts,
                "tests": [
                    {"suite": r.suite, "test": r.name, "passed": r.passed,
                     "detail": r.detail}
                    for r in results
                ],
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self, *_args):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, _format, *_args):
        pass  # Suppress request logs


def start_trigger_server():
    """Run the HTTP trigger server in a background thread."""
    server = HTTPServer(("0.0.0.0", TRIGGER_PORT), TriggerHandler)
    print(f"Trigger server listening on port {TRIGGER_PORT}", flush=True)
    server.serve_forever()


def discover_suites():
    """Import all modules under the tests package and collect BaseTestSuite subclasses."""
    import tests  # noqa: F811
    suites = []
    for _importer, modname, _ispkg in pkgutil.walk_packages(
        tests.__path__, prefix="tests."
    ):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            traceback.print_exc()
            continue
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseTestSuite)
                and obj is not BaseTestSuite
            ):
                suites.append(obj)
    return suites


def push_results_to_loki(results):
    """Push test results to Loki."""
    streams = []
    ts = str(int(time.time() * 1e9))

    for r in results:
        line = json.dumps({
            "suite": r.suite,
            "test": r.name,
            "passed": r.passed,
            "duration_ms": r.duration_ms,
            "detail": r.detail[:500],
        })
        streams.append({
            "stream": {
                "app": "basalt-vultiserver",
                "service": "testrunner",
                "host": HOSTNAME,
                "level": "info" if r.passed else "error",
                "suite": r.suite,
                "test": r.name,
            },
            "values": [[ts, line]],
        })

    # Also push a summary entry
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    summary_line = json.dumps({
        "total": total,
        "passed": passed,
        "failed": failed,
        "suites": list({r.suite for r in results}),
    })
    streams.append({
        "stream": {
            "app": "basalt-vultiserver",
            "service": "testrunner",
            "host": HOSTNAME,
            "level": "info" if failed == 0 else "error",
            "test": "_summary",
        },
        "values": [[ts, summary_line]],
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
        print(f"Failed to push test results to Loki: {e}", flush=True)


def run_tests():
    """Discover and run all test suites, push results."""
    global is_running
    with last_run_lock:
        is_running = True
    suites = discover_suites()
    all_results = []

    for suite_cls in suites:
        try:
            suite = suite_cls(TARGET_URL)
            results = suite.run_all()
            all_results.extend(results)
        except Exception:
            traceback.print_exc()

    if all_results:
        passed = sum(1 for r in all_results if r.passed)
        failed = len(all_results) - passed
        print(
            f"Tests complete: {passed} passed, {failed} failed "
            f"({len(suites)} suites)",
            flush=True,
        )
        push_results_to_loki(all_results)

    with last_run_lock:
        global last_run_time, last_run_results
        last_run_time = time.time()
        last_run_results = all_results
        is_running = False

    if not all_results:
        print("No test suites found", flush=True)


def main():
    if not TARGET_URL:
        print("HEALTHCHECK_TARGET_URL not set, exiting", flush=True)
        return

    print(f"Test runner starting (interval={INTERVAL}s, target={TARGET_URL})", flush=True)

    # Start the trigger HTTP server in a background thread
    t = threading.Thread(target=start_trigger_server, daemon=True)
    t.start()

    while True:
        run_tests()
        # Wait for either the interval or a manual trigger
        trigger_event.wait(timeout=INTERVAL)
        trigger_event.clear()


if __name__ == "__main__":
    main()
