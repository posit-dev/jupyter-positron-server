import os
import pytest
from unittest.mock import MagicMock


class MockHeaders(dict):
    """Mock HTTP headers that supports items() like tornado HTTPHeaders."""

    def items(self):
        return list(super().items())


class TestRewriteResponse:
    """Tests for the rewrite_response() function."""

    def test_rewrite_location_strips_user_prefix(self):
        """Test that Location header with /user/X/positron prefix is stripped."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/user/admin/positron/"})
        request = MagicMock()

        result = rewrite_response(response, request)

        assert result.headers["Location"] == "/"

    def test_rewrite_location_with_path(self):
        """Test that Location header preserves path after prefix."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/user/admin/positron/some/path"})
        request = MagicMock()

        result = rewrite_response(response, request)

        assert result.headers["Location"] == "/some/path"

    def test_rewrite_location_different_usernames(self):
        """Test that rewrite works with various usernames."""
        from jupyter_positron_server import rewrite_response

        for username in ["testuser", "user-123", "admin"]:
            response = MagicMock()
            response.headers = MockHeaders({"Location": f"/user/{username}/positron/api/v1"})
            request = MagicMock()

            result = rewrite_response(response, request)

            assert result.headers["Location"] == "/api/v1"

    def test_rewrite_location_case_insensitive_header(self):
        """Test that Location header matching is case-insensitive."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({"location": "/user/admin/positron/test"})
        request = MagicMock()

        result = rewrite_response(response, request)

        assert result.headers["location"] == "/test"

    def test_rewrite_preserves_absolute_url_components(self):
        """Test that absolute URLs preserve scheme/host, only path is modified."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({
            "Location": "http://localhost:8080/user/admin/positron/dashboard?foo=bar"
        })
        request = MagicMock()

        result = rewrite_response(response, request)

        assert result.headers["Location"] == "http://localhost:8080/dashboard?foo=bar"

    def test_rewrite_no_match_unchanged(self):
        """Test that non-matching Location headers are unchanged."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/api/contents"})
        request = MagicMock()

        result = rewrite_response(response, request)

        assert result.headers["Location"] == "/api/contents"

    def test_rewrite_no_location_header(self):
        """Test that responses without Location header are unchanged."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({"Content-Type": "text/html"})
        request = MagicMock()

        result = rewrite_response(response, request)

        assert "Location" not in result.headers
        assert result.headers["Content-Type"] == "text/html"


class TestMakeMappath:
    """Tests for the _make_mappath() function."""

    def test_mappath_strips_doubled_prefix(self):
        """Test that mappath strips the doubled base_url prefix."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        result = mappath("/user/admin/positron/oss-dev/index.html")
        assert result == "/oss-dev/index.html"

    def test_mappath_handles_different_usernames(self):
        """Test that mappath works with various usernames."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/user/testuser/positron/api/v1") == "/api/v1"
        assert mappath("/user/user-name-123/positron/static/js/main.js") == "/static/js/main.js"

    def test_mappath_returns_root_for_positron_only(self):
        """Test that mappath returns / when path ends at positron."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        result = mappath("/user/admin/positron/")
        assert result == "/"

    def test_mappath_no_match_returns_original(self):
        """Test that non-matching paths are returned unchanged."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/api/contents") == "/api/contents"
        assert mappath("/static/file.js") == "/static/file.js"

    def test_mappath_partial_match_returns_original(self):
        """Test that partial matches don't strip incorrectly."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        # Missing /positron suffix
        assert mappath("/user/admin/other/path") == "/user/admin/other/path"
        # Not starting with /user
        assert mappath("/api/user/admin/positron/test") == "/api/user/admin/positron/test"


def test_which_positron_server_not_found(monkeypatch):
    """Test that FileNotFoundError is raised when positron-server is not in PATH."""
    monkeypatch.setenv("PATH", "")

    from importlib import reload
    import jupyter_positron_server

    reload(jupyter_positron_server)

    with pytest.raises(
        FileNotFoundError, match="Could not find positron-server executable"
    ):
        jupyter_positron_server.which_positron_server()


def test_which_positron_server_path_takes_priority(monkeypatch):
    """Test that PATH takes priority over known locations."""
    import jupyter_positron_server

    # Mock which() to return a value (found in PATH)
    monkeypatch.setattr(jupyter_positron_server, "which", lambda prog: prog)
    # Mock os.path.exists to return True for known locations
    monkeypatch.setattr(os.path, "exists", lambda path: True)

    result = jupyter_positron_server.which_positron_server()

    # Should return the prog name (from PATH), not a known location path
    assert result == "positron-server"


def test_which_positron_server_fallback_order(monkeypatch):
    """Test that known paths are checked in order."""
    import jupyter_positron_server

    # Mock which() to return None (not in PATH)
    monkeypatch.setattr(jupyter_positron_server, "which", lambda prog: None)
    # Mock os.path.exists to return True for all paths
    monkeypatch.setattr(os.path, "exists", lambda path: True)

    result = jupyter_positron_server.which_positron_server()

    # Should return the first known path
    assert result == "/usr/lib/positron-server/bin/positron-server"


def test_setup_positron_server_tcp_mode(monkeypatch):
    """Test setup returns correct config when JSP_POSITRON_PORT is set."""
    monkeypatch.setenv("JSP_POSITRON_PORT", "8080")

    from importlib import reload
    import jupyter_positron_server

    reload(jupyter_positron_server)

    config = jupyter_positron_server.setup_positron_server()

    assert config["port"] == 8080
    assert config["command"] == []
    assert config["timeout"] == 120
    assert "launcher_entry" in config
