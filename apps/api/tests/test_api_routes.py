"""
Tests that an unknown API path says so.

The single-page app is served by a catch-all route, which by construction
matches every path the real routes did not. That included paths under
/api -- so a mistyped, renamed or withdrawn endpoint did not 404. It
returned the entire HTML application with a 200, and the caller, expecting
JSON, died on "<" at character 0.

That error sends you to look at the parser, or at the serialisation, or at
the network tab wondering why the body is a web page. It does not send you
to look at the URL, which is where the mistake is. `GET /api/field//summary`
-- a field id that came through empty -- behaved exactly this way, and read
as a successful request.

The frontend builds URLs from state. An empty id is a plausible bug there,
so it needs an unambiguous answer from the server.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
for pkg in ("apps/api", "packages/agronomy", "packages/geo", "packages/rag"):
    sys.path.insert(0, str(ROOT / pkg))

from agrin_api.main import app, _WEB_DIST  # noqa: E402

client = TestClient(app)

# The catch-all only exists when a build is present; without one there is
# nothing to shadow the API and nothing to test.
needs_frontend = pytest.mark.skipif(
    not _WEB_DIST.exists(), reason="no built frontend, so no catch-all route"
)


@needs_frontend
class TestUnknownApiPaths:
    def test_an_unknown_api_path_is_404_not_the_web_page(self):
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404

    def test_the_body_is_json_so_the_caller_can_read_it(self):
        response = client.get("/api/does-not-exist")
        assert "text/html" not in response.headers.get("content-type", "")
        assert response.json()["detail"]

    def test_an_empty_path_parameter_does_not_look_like_success(self):
        """The case that prompted this: a field id that came through empty."""
        response = client.get("/api/field//summary")
        assert response.status_code == 404

    def test_bare_api_is_also_not_the_web_page(self):
        assert client.get("/api").status_code == 404


@needs_frontend
class TestTheAppIsStillServed:
    """The guard above must not break the thing the catch-all is for."""

    def test_the_root_serves_the_application(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_a_client_side_route_serves_the_application(self):
        """Deep links are handled by the browser, so they must return the
        page rather than a 404."""
        response = client.get("/some/client/route")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_a_path_merely_containing_api_is_not_caught(self):
        """The guard matches the /api prefix, not the substring. A client
        route like /rapid or /apiary is not an endpoint."""
        for path in ("/apiary", "/rapid-advice"):
            assert client.get(path).status_code == 200


@needs_frontend
class TestRealEndpointsStillWork:
    def test_health_is_unaffected(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
