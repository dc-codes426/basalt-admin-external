"""Basic API availability and response tests."""

import json
from testrunner import BaseTestSuite


class APIBasicsTestSuite(BaseTestSuite):
    suite_name = "api_basics"

    def test_ping_returns_200(self):
        status, body = self.http_get("/ping")
        assert status == 200, f"Expected 200, got {status}"

    def test_unknown_route_returns_404(self):
        try:
            self.http_get("/nonexistent-route-that-should-not-exist")
            assert False, "Expected HTTP error for unknown route"
        except Exception as e:
            if hasattr(e, "code"):
                assert e.code == 404, f"Expected 404, got {e.code}"
            else:
                raise
