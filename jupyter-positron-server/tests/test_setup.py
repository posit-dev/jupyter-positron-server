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

    # Mock which() to return the full path (found in PATH)
    monkeypatch.setattr(
        jupyter_positron_server,
        "which",
        lambda prog: "/usr/local/bin/positron-server",
    )
    # Mock os.path.exists to return True for known locations
    monkeypatch.setattr(os.path, "exists", lambda path: True)

    result = jupyter_positron_server.which_positron_server()

    # Should return the full path from which(), not a known location path
    assert result == "/usr/local/bin/positron-server"


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


def test_which_positron_server_returns_full_path(monkeypatch):
    """Test that which_positron_server returns the full path, not the bare program name."""
    import jupyter_positron_server

    monkeypatch.setattr(
        jupyter_positron_server,
        "which",
        lambda prog: "/opt/vscode-reh-web-linux-x64/bin/positron-server",
    )

    result = jupyter_positron_server.which_positron_server()

    assert result == "/opt/vscode-reh-web-linux-x64/bin/positron-server"
    assert os.path.isabs(result)


class TestMakeMappathWithBaseUrl:
    """Tests for _make_mappath() with JUPYTERHUB_BASE_URL prefix."""

    def test_mappath_with_base_url_prefix(self, monkeypatch):
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        mappath = jupyter_positron_server._make_mappath()

        assert mappath("/jh/user/testuser/positron/") == "/"
        assert mappath("/jh/user/testuser/positron/foo") == "/foo"

    def test_mappath_with_base_url_no_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        mappath = jupyter_positron_server._make_mappath()

        assert mappath("/jh/user/testuser/positron") == "/"

    def test_mappath_without_base_url_still_works(self, monkeypatch):
        monkeypatch.delenv("JUPYTERHUB_BASE_URL", raising=False)
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        mappath = jupyter_positron_server._make_mappath()

        assert mappath("/user/admin/positron/oss-dev/index.html") == "/oss-dev/index.html"
        assert mappath("/user/admin/positron/") == "/"
        assert mappath("/user/admin/positron") == "/"

    def test_mappath_base_url_no_match_without_prefix(self, monkeypatch):
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        mappath = jupyter_positron_server._make_mappath()

        assert mappath("/user/testuser/positron/foo") == "/user/testuser/positron/foo"


class TestRewriteResponseWithBaseUrl:
    """Tests for rewrite_response() with JUPYTERHUB_BASE_URL prefix."""

    def test_rewrite_with_base_url(self, monkeypatch):
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/jh/user/testuser/positron/"})
        request = MagicMock()

        result = jupyter_positron_server.rewrite_response(response, request)
        assert result.headers["Location"] == "/"

    def test_rewrite_with_base_url_and_path(self, monkeypatch):
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/jh/user/testuser/positron/api/v1"})
        request = MagicMock()

        result = jupyter_positron_server.rewrite_response(response, request)
        assert result.headers["Location"] == "/api/v1"

    def test_rewrite_with_base_url_no_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/jh/user/testuser/positron"})
        request = MagicMock()

        result = jupyter_positron_server.rewrite_response(response, request)
        assert result.headers["Location"] == "/"


class TestServerBasePath:
    """Tests for --server-base-path in setup_positron_server()."""

    def test_server_base_path_with_service_prefix(self, monkeypatch):
        monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/jh/user/testuser/")
        monkeypatch.delenv("JSP_POSITRON_PORT", raising=False)
        monkeypatch.delenv("JSP_POSITRON_SOCKET", raising=False)
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        monkeypatch.setattr(
            jupyter_positron_server,
            "which_positron_server",
            lambda: "/opt/positron-server/bin/positron-server",
        )
        monkeypatch.setattr(
            os.path, "isdir", lambda path: True
        )
        monkeypatch.setattr(
            os.path, "realpath", lambda path: path
        )

        config = jupyter_positron_server.setup_positron_server()

        cmd = config["command"]
        idx = cmd.index("--server-base-path")
        assert cmd[idx + 1] == "/jh/user/testuser/positron"

    def test_server_base_path_default(self, monkeypatch):
        monkeypatch.delenv("JUPYTERHUB_SERVICE_PREFIX", raising=False)
        monkeypatch.delenv("JSP_POSITRON_PORT", raising=False)
        monkeypatch.delenv("JSP_POSITRON_SOCKET", raising=False)
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        monkeypatch.setattr(
            jupyter_positron_server,
            "which_positron_server",
            lambda: "/opt/positron-server/bin/positron-server",
        )
        monkeypatch.setattr(
            os.path, "isdir", lambda path: True
        )
        monkeypatch.setattr(
            os.path, "realpath", lambda path: path
        )

        config = jupyter_positron_server.setup_positron_server()

        cmd = config["command"]
        idx = cmd.index("--server-base-path")
        assert cmd[idx + 1] == "/positron"


class TestMappathAdversarial:
    """Adversarial tests for mappath — paths that look similar but shouldn't match."""

    def test_positron_as_username(self):
        """'positron' in the username slot should not be treated as the app name."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/user/positron/something") == "/user/positron/something"

    def test_positron_substring_in_path(self):
        """Paths containing 'positron' as a substring should not match."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/user/admin/positron-ide/foo") == "/user/admin/positron-ide/foo"
        assert mappath("/user/admin/not-positron/foo") == "/user/admin/not-positron/foo"

    def test_extra_segments_before_user(self):
        """Extra path segments before /user/ should not match (without base_url)."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/extra/user/admin/positron/foo") == "/extra/user/admin/positron/foo"

    def test_wrong_base_url_prefix(self, monkeypatch):
        """A different base_url prefix than configured should not match."""
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        mappath = jupyter_positron_server._make_mappath()

        assert mappath("/other/user/admin/positron/foo") == "/other/user/admin/positron/foo"
        assert mappath("/jhx/user/admin/positron/foo") == "/jhx/user/admin/positron/foo"

    def test_base_url_with_regex_special_chars(self, monkeypatch):
        """base_url containing regex metacharacters should be escaped properly."""
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/hub.v2/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        mappath = jupyter_positron_server._make_mappath()

        assert mappath("/hub.v2/user/admin/positron/foo") == "/foo"
        # The dot should NOT be a wildcard — /hubXv2/ should not match
        assert mappath("/hubXv2/user/admin/positron/foo") == "/hubXv2/user/admin/positron/foo"

    def test_deeply_nested_base_url(self, monkeypatch):
        """Multi-segment base_url should work."""
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/org/team/hub/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        mappath = jupyter_positron_server._make_mappath()

        assert mappath("/org/team/hub/user/admin/positron/foo") == "/foo"
        assert mappath("/org/team/hub/user/admin/positron") == "/"
        assert mappath("/org/team/user/admin/positron/foo") == "/org/team/user/admin/positron/foo"

    def test_empty_string_path(self):
        """Empty path should pass through unchanged."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("") == ""

    def test_slash_only_path(self):
        """Root path should pass through unchanged."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/") == "/"

    def test_username_with_special_chars(self):
        """Usernames with dots, underscores, etc. should still match."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/user/john.doe/positron/foo") == "/foo"
        assert mappath("/user/user_name/positron/foo") == "/foo"
        assert mappath("/user/user@domain/positron/foo") == "/foo"

    def test_username_cannot_contain_slash(self):
        """A slash in the username position should not match as a single username."""
        from jupyter_positron_server import _make_mappath

        mappath = _make_mappath()
        assert mappath("/user/ad/min/positron/foo") == "/user/ad/min/positron/foo"


class TestRewriteResponseAdversarial:
    """Adversarial tests for rewrite_response."""

    def test_rewrite_does_not_match_positron_substring(self):
        """Location with 'positron-ide' should not be rewritten."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/user/admin/positron-ide/foo"})
        request = MagicMock()

        result = rewrite_response(response, request)
        assert result.headers["Location"] == "/user/admin/positron-ide/foo"

    def test_rewrite_wrong_base_url(self, monkeypatch):
        """Location with a different base_url should not be rewritten."""
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/jh/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/wrong/user/admin/positron/foo"})
        request = MagicMock()

        result = jupyter_positron_server.rewrite_response(response, request)
        assert result.headers["Location"] == "/wrong/user/admin/positron/foo"

    def test_rewrite_with_regex_chars_in_base_url(self, monkeypatch):
        """base_url with regex metacharacters should be escaped in rewrite too."""
        monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/hub.v2/")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)

        response = MagicMock()
        response.headers = MockHeaders({"Location": "/hub.v2/user/admin/positron/foo"})
        request = MagicMock()
        result = jupyter_positron_server.rewrite_response(response, request)
        assert result.headers["Location"] == "/foo"

        # Dot should not be a wildcard
        response2 = MagicMock()
        response2.headers = MockHeaders({"Location": "/hubXv2/user/admin/positron/foo"})
        result2 = jupyter_positron_server.rewrite_response(response2, request)
        assert result2.headers["Location"] == "/hubXv2/user/admin/positron/foo"

    def test_rewrite_preserves_non_location_headers(self):
        """Other headers should never be touched even if they contain matching paths."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({
            "X-Custom": "/user/admin/positron/secret",
            "Location": "/user/admin/positron/foo",
        })
        request = MagicMock()

        result = rewrite_response(response, request)
        assert result.headers["X-Custom"] == "/user/admin/positron/secret"
        assert result.headers["Location"] == "/foo"

    def test_rewrite_multiple_location_headers(self):
        """If multiple headers exist, only Location should be touched."""
        from jupyter_positron_server import rewrite_response

        response = MagicMock()
        response.headers = MockHeaders({
            "Location": "/user/admin/positron/foo",
            "Content-Location": "/user/admin/positron/bar",
        })
        request = MagicMock()

        result = rewrite_response(response, request)
        assert result.headers["Location"] == "/foo"
        assert result.headers["Content-Location"] == "/user/admin/positron/bar"


class TestWhichPositronServerAdversarial:
    """Adversarial tests for which_positron_server."""

    def test_which_returns_path_with_spaces(self, monkeypatch):
        """Paths with spaces should be returned correctly."""
        import jupyter_positron_server

        monkeypatch.setattr(
            jupyter_positron_server,
            "which",
            lambda prog: "/opt/my apps/positron-server/bin/positron-server",
        )

        result = jupyter_positron_server.which_positron_server()
        assert result == "/opt/my apps/positron-server/bin/positron-server"

    def test_which_returns_symlinked_path(self, monkeypatch):
        """The raw which() result should be returned (caller does realpath)."""
        import jupyter_positron_server

        monkeypatch.setattr(
            jupyter_positron_server,
            "which",
            lambda prog: "/usr/local/bin/positron-server",
        )

        result = jupyter_positron_server.which_positron_server()
        assert result == "/usr/local/bin/positron-server"
        assert result != "positron-server"

    def test_which_none_falls_through_to_known_paths(self, monkeypatch):
        """When which() returns None, known paths should be checked."""
        import jupyter_positron_server

        monkeypatch.setattr(jupyter_positron_server, "which", lambda prog: None)
        monkeypatch.setattr(os.path, "exists", lambda path: path == "/opt/positron-server/bin/positron-server")

        result = jupyter_positron_server.which_positron_server()
        assert result == "/opt/positron-server/bin/positron-server"

    def test_which_none_no_known_paths_raises(self, monkeypatch):
        """When which() returns None and no known paths exist, should raise."""
        import jupyter_positron_server

        monkeypatch.setattr(jupyter_positron_server, "which", lambda prog: None)
        monkeypatch.setattr(os.path, "exists", lambda path: False)

        with pytest.raises(FileNotFoundError, match="Could not find positron-server"):
            jupyter_positron_server.which_positron_server()


class TestServerBasePathAdversarial:
    """Adversarial tests for --server-base-path construction."""

    def _make_config(self, monkeypatch):
        from importlib import reload
        import jupyter_positron_server

        monkeypatch.delenv("JSP_POSITRON_PORT", raising=False)
        monkeypatch.delenv("JSP_POSITRON_SOCKET", raising=False)
        reload(jupyter_positron_server)
        monkeypatch.setattr(
            jupyter_positron_server,
            "which_positron_server",
            lambda: "/opt/positron-server/bin/positron-server",
        )
        monkeypatch.setattr(os.path, "isdir", lambda path: True)
        monkeypatch.setattr(os.path, "realpath", lambda path: path)
        return jupyter_positron_server.setup_positron_server()

    def test_service_prefix_no_trailing_slash(self, monkeypatch):
        """JUPYTERHUB_SERVICE_PREFIX without trailing slash should still work."""
        monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/user/testuser")
        config = self._make_config(monkeypatch)
        cmd = config["command"]
        idx = cmd.index("--server-base-path")
        assert cmd[idx + 1] == "/user/testuser/positron"

    def test_service_prefix_multiple_trailing_slashes(self, monkeypatch):
        """Multiple trailing slashes should be stripped cleanly."""
        monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/user/testuser///")
        config = self._make_config(monkeypatch)
        cmd = config["command"]
        idx = cmd.index("--server-base-path")
        # rstrip("/") removes all trailing slashes
        assert cmd[idx + 1] == "/user/testuser/positron"

    def test_service_prefix_root_only(self, monkeypatch):
        """Service prefix of just '/' should produce '/positron'."""
        monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/")
        config = self._make_config(monkeypatch)
        cmd = config["command"]
        idx = cmd.index("--server-base-path")
        assert cmd[idx + 1] == "/positron"

    def test_service_prefix_deeply_nested(self, monkeypatch):
        """Deeply nested service prefix should be passed through correctly."""
        monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/org/team/jh/user/longusername/")
        config = self._make_config(monkeypatch)
        cmd = config["command"]
        idx = cmd.index("--server-base-path")
        assert cmd[idx + 1] == "/org/team/jh/user/longusername/positron"

    def test_server_base_path_always_present_in_command(self, monkeypatch):
        """--server-base-path should always appear in the command."""
        monkeypatch.delenv("JUPYTERHUB_SERVICE_PREFIX", raising=False)
        config = self._make_config(monkeypatch)
        assert "--server-base-path" in config["command"]

    def test_server_base_path_not_in_tcp_mode(self, monkeypatch):
        """TCP mode (pre-running server) should not include --server-base-path."""
        monkeypatch.setenv("JSP_POSITRON_PORT", "9999")
        from importlib import reload
        import jupyter_positron_server

        reload(jupyter_positron_server)
        config = jupyter_positron_server.setup_positron_server()
        assert config["command"] == []


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
