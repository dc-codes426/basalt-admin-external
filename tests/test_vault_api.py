"""Vault API endpoint smoke tests.

These tests verify that the /vault/ API endpoints are reachable and
respond with expected status codes. They do NOT perform actual TSS
operations — just validate the API surface is alive.
"""

import json
from testrunner import BaseTestSuite


class VaultAPITestSuite(BaseTestSuite):
    suite_name = "vault_api"

    def test_get_vault_exist(self):
        """GET /vault/exist should be reachable (even if it returns an error for missing params)."""
        try:
            status, body = self.http_get("/vault/exist")
        except Exception as e:
            if hasattr(e, "code"):
                # Any HTTP response means the endpoint is routed
                assert e.code in (400, 404, 405), f"Unexpected status: {e.code}"
            else:
                raise

    def test_post_keygen_missing_body_returns_error(self):
        """POST /vault/keygen with no body should return 4xx, not 5xx."""
        try:
            self.http_post("/vault/keygen", body={})
        except Exception as e:
            if hasattr(e, "code"):
                assert 400 <= e.code < 500, f"Expected 4xx, got {e.code}"
            else:
                raise

    def test_post_keysign_missing_body_returns_error(self):
        """POST /vault/keysign with no body should return 4xx, not 5xx."""
        try:
            self.http_post("/vault/keysign", body={})
        except Exception as e:
            if hasattr(e, "code"):
                assert 400 <= e.code < 500, f"Expected 4xx, got {e.code}"
            else:
                raise

    def test_post_reshare_missing_body_returns_error(self):
        """POST /vault/reshare with no body should return 4xx, not 5xx."""
        try:
            self.http_post("/vault/reshare", body={})
        except Exception as e:
            if hasattr(e, "code"):
                assert 400 <= e.code < 500, f"Expected 4xx, got {e.code}"
            else:
                raise
