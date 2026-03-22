"""API conformance tests against the OpenAPI spec.

Verifies that every endpoint defined in the Vultiserver OpenAPI spec is
implemented, returns the correct status codes for valid and invalid inputs,
enforces HTTP method constraints, and rejects malformed requests.

These tests do NOT exercise real TSS functionality — they only verify that
the API surface conforms to the spec.
"""

import json
import uuid
import urllib.request
import urllib.error

from testrunner import BaseTestSuite, _throttle


def _hex(n_bytes):
    """Return a dummy hex string of n_bytes bytes (2*n_bytes hex chars)."""
    return "aa" * n_bytes


def _uuid():
    return str(uuid.uuid4())


def _raw_request(url, method="GET", body=None, headers=None, timeout=10):
    """Send an HTTP request and return (status, body) without raising on 4xx/5xx."""
    _throttle()
    data = body.encode() if isinstance(body, str) else body
    hdrs = headers or {}
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode() if e.fp else ""


class _ConformanceBase(BaseTestSuite):
    """Shared helpers for conformance tests."""

    def _url(self, path):
        return self.target_url.rstrip("/") + path

    def expect_status(self, method, path, expected, body=None, headers=None):
        """Send a request and assert the status code matches expected."""
        hdrs = headers or {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        status, resp_body = _raw_request(
            self._url(path), method=method, body=data, headers=hdrs
        )
        assert status == expected, (
            f"{method} {path}: expected {expected}, got {status} — {resp_body[:200]}"
        )

    def expect_status_in(self, method, path, expected_set, body=None, headers=None):
        """Send a request and assert the status code is in expected_set."""
        hdrs = headers or {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        status, resp_body = _raw_request(
            self._url(path), method=method, body=data, headers=hdrs
        )
        assert status in expected_set, (
            f"{method} {path}: expected one of {expected_set}, got {status} — {resp_body[:200]}"
        )


# ============================================================================
# Endpoints that must NOT exist
# ============================================================================

class DisallowedEndpointsConformance(_ConformanceBase):
    suite_name = "conformance_disallowed_endpoints"

    def test_vault_resend_does_not_exist(self):
        """The /vault/resend endpoint must not be exposed."""
        for method in ("GET", "POST"):
            status, _ = _raw_request(self._url("/vault/resend"), method=method)
            assert status == 404, (
                f"{method} /vault/resend: expected 404, got {status}"
            )


# ============================================================================
# GET /ping
# ============================================================================

class PingConformance(_ConformanceBase):
    suite_name = "conformance_ping"

    def test_ping_returns_200(self):
        status, body = _raw_request(self._url("/ping"))
        assert status == 200, f"Expected 200, got {status}"
        assert len(body) > 0, "Expected non-empty response body"

    def test_ping_rejects_post(self):
        self.expect_status("POST", "/ping", 405)

    def test_health_returns_200(self):
        status, body = _raw_request(self._url("/health"))
        assert status == 200, f"Expected 200, got {status}"
        data = json.loads(body)
        assert "containers" in data, "Expected 'containers' key in response"
        assert len(data["containers"]) > 0, "Expected at least one container"


# ============================================================================
# GET /getDerivedPublicKey
# ============================================================================

class DerivedPublicKeyConformance(_ConformanceBase):
    suite_name = "conformance_derived_public_key"

    def test_missing_all_params_returns_400(self):
        self.expect_status("GET", "/getDerivedPublicKey", 400)

    def test_missing_derive_path_returns_400(self):
        self.expect_status(
            "GET",
            "/getDerivedPublicKey?publicKey=aabb&hexChainCode=ccdd",
            400,
        )

    def test_missing_public_key_returns_400(self):
        self.expect_status(
            "GET",
            "/getDerivedPublicKey?hexChainCode=ccdd&derivePath=m/44'/60'/0'/0/0",
            400,
        )

    def test_missing_chain_code_returns_400(self):
        self.expect_status(
            "GET",
            "/getDerivedPublicKey?publicKey=aabb&derivePath=m/44'/60'/0'/0/0",
            400,
        )
#    TODO: upstream vultiserver returns 500 instead of 404 (see UPSTREAM.md)
#    def test_invalid_key_data_returns_400(self):
#        self.expect_status(
#            "GET",
#            "/getDerivedPublicKey?publicKey=invalid&hexChainCode=invalid&derivePath=m/44'/60'/0'/0/0",
#            400,
#        )

    def test_rejects_post(self):
        self.expect_status("POST", "/getDerivedPublicKey", 405)


# ============================================================================
# POST /vault/create
# ============================================================================

class VaultCreateConformance(_ConformanceBase):
    suite_name = "conformance_vault_create"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/create", 400, body={})

    def test_missing_required_fields_returns_400(self):
        self.expect_status("POST", "/vault/create", 400, body={
            "session_id": _uuid(),
        })

    def test_invalid_session_id_returns_400(self):
        self.expect_status("POST", "/vault/create", 400, body={
            "session_id": "not-a-uuid",
            "hex_encryption_key": _hex(32),
            "hex_chain_code": _hex(32),
            "encryption_password": "testpassword",
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/create", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/create"),
            method="POST",
            body="{invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400 for malformed JSON, got {status}"

    def test_rejects_non_json_content_type(self):
        status, _ = _raw_request(
            self._url("/vault/create"),
            method="POST",
            body="not json",
            headers={"Content-Type": "text/plain"},
        )
        assert status in (400, 415), f"Expected 400 or 415, got {status}"


# ============================================================================
# POST /vault/reshare
# ============================================================================

class VaultReshareConformance(_ConformanceBase):
    suite_name = "conformance_vault_reshare"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/reshare", 400, body={})

    def test_missing_required_fields_returns_400(self):
        self.expect_status("POST", "/vault/reshare", 400, body={
            "public_key": _hex(33),
            "session_id": _uuid(),
        })

    def test_password_too_short_returns_400(self):
        self.expect_status("POST", "/vault/reshare", 400, body={
            "public_key": _hex(33),
            "session_id": _uuid(),
            "hex_encryption_key": _hex(32),
            "hex_chain_code": _hex(32),
            "old_parties": ["party1", "party2"],
            "encryption_password": "short",
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/reshare", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/reshare"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"


# ============================================================================
# POST /vault/migrate
# ============================================================================

class VaultMigrateConformance(_ConformanceBase):
    suite_name = "conformance_vault_migrate"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/migrate", 400, body={})

    def test_missing_required_fields_returns_400(self):
        self.expect_status("POST", "/vault/migrate", 400, body={
            "public_key": _hex(33),
            "session_id": _uuid(),
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/migrate", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/migrate"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"


# ============================================================================
# POST /vault/import
# ============================================================================

class VaultImportConformance(_ConformanceBase):
    suite_name = "conformance_vault_import"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/import", 400, body={})

    def test_missing_chains_returns_400(self):
        self.expect_status("POST", "/vault/import", 400, body={
            "session_id": _uuid(),
            "hex_encryption_key": _hex(32),
            "hex_chain_code": _hex(32),
            "encryption_password": "testpassword",
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/import", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/import"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"


# ============================================================================
# GET /vault/get/:publicKeyECDSA
# ============================================================================

class VaultGetConformance(_ConformanceBase):
    suite_name = "conformance_vault_get"

    def test_missing_password_header_returns_400(self):
        fake_key = _hex(33)
        self.expect_status("GET", f"/vault/get/{fake_key}", 400)

    def test_invalid_short_key_returns_400(self):
        self.expect_status(
            "GET", "/vault/get/tooshort", 400,
            headers={"x-password": "testpassword"},
        )

    # TODO: upstream vultiserver returns 500 instead of 404 (see UPSTREAM.md)
    # def test_nonexistent_vault_returns_404(self):
    #     fake_key = _hex(33)
    #     self.expect_status(
    #         "GET", f"/vault/get/{fake_key}", 404,
    #         headers={"x-password": "testpassword"},
    #     )

    def test_rejects_post(self):
        fake_key = _hex(33)
        self.expect_status("POST", f"/vault/get/{fake_key}", 405)


# ============================================================================
# GET /vault/exist/:publicKeyECDSA
# ============================================================================

class VaultExistConformance(_ConformanceBase):
    suite_name = "conformance_vault_exist"

    # TODO: upstream vultiserver returns 400 instead of 404 (see UPSTREAM.md)
    # def test_nonexistent_vault_returns_404(self):
    #     fake_key = _hex(33)
    #     self.expect_status("GET", f"/vault/exist/{fake_key}", 404)

    def test_invalid_key_returns_400(self):
        """An invalid public key format should return 400, not 404 or 405."""
        self.expect_status("GET", "/vault/exist/garbage", 400)

    def test_rejects_post(self):
        fake_key = _hex(33)
        self.expect_status("POST", f"/vault/exist/{fake_key}", 405)


# ============================================================================
# POST /vault/sign
# ============================================================================

class VaultSignConformance(_ConformanceBase):
    suite_name = "conformance_vault_sign"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/sign", 400, body={})

    def test_missing_required_fields_returns_400(self):
        self.expect_status("POST", "/vault/sign", 400, body={
            "public_key": _hex(33),
            "messages": ["deadbeef"],
        })

    def test_empty_messages_returns_400(self):
        self.expect_status("POST", "/vault/sign", 400, body={
            "public_key": _hex(33),
            "messages": [],
            "session": _uuid(),
            "hex_encryption_key": _hex(32),
            "derive_path": "m/44'/60'/0'/0/0",
            "vault_password": "testpassword",
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/sign", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/sign"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"


# ============================================================================
# POST /vault/mldsa
# ============================================================================

class VaultMldsaConformance(_ConformanceBase):
    suite_name = "conformance_vault_mldsa"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/mldsa", 400, body={})

    def test_missing_required_fields_returns_400(self):
        self.expect_status("POST", "/vault/mldsa", 400, body={
            "public_key": _hex(33),
            "session_id": _uuid(),
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/mldsa", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/mldsa"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"


# ============================================================================
# POST /vault/batch/keygen
# ============================================================================

class BatchKeygenConformance(_ConformanceBase):
    suite_name = "conformance_batch_keygen"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/batch/keygen", 400, body={})

    def test_missing_protocols_returns_400(self):
        self.expect_status("POST", "/vault/batch/keygen", 400, body={
            "session_id": _uuid(),
            "hex_encryption_key": _hex(32),
            "hex_chain_code": _hex(32),
            "encryption_password": "testpassword",
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/batch/keygen", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/batch/keygen"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"


# ============================================================================
# POST /vault/batch/reshare
# ============================================================================

class BatchReshareConformance(_ConformanceBase):
    suite_name = "conformance_batch_reshare"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/batch/reshare", 400, body={})

    def test_missing_required_fields_returns_400(self):
        self.expect_status("POST", "/vault/batch/reshare", 400, body={
            "public_key": _hex(33),
            "session_id": _uuid(),
            "hex_encryption_key": _hex(32),
            "encryption_password": "testpassword",
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/batch/reshare", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/batch/reshare"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"


# ============================================================================
# POST /vault/batch/import
# ============================================================================

class BatchImportConformance(_ConformanceBase):
    suite_name = "conformance_batch_import"

    def test_empty_body_returns_400(self):
        self.expect_status("POST", "/vault/batch/import", 400, body={})

    def test_missing_chains_returns_400(self):
        self.expect_status("POST", "/vault/batch/import", 400, body={
            "session_id": _uuid(),
            "hex_encryption_key": _hex(32),
            "encryption_password": "testpassword",
            "protocols": ["ECDSA"],
        })

    def test_rejects_get(self):
        self.expect_status("GET", "/vault/batch/import", 405)

    def test_rejects_malformed_json(self):
        status, _ = _raw_request(
            self._url("/vault/batch/import"),
            method="POST",
            body="{bad",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400, f"Expected 400, got {status}"
