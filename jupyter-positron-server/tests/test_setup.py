import os
import pytest


def test_which_positron_server_not_found(monkeypatch):
    """Test that FileNotFoundError is raised when positron-server is not in PATH."""
    monkeypatch.setenv('PATH', '')

    from importlib import reload
    import jupyter_positron_server
    reload(jupyter_positron_server)

    with pytest.raises(FileNotFoundError, match='Could not find executable positron-server'):
        jupyter_positron_server.which_positron_server()


def test_setup_positron_server_tcp_mode(monkeypatch):
    """Test setup returns correct config when JSP_POSITRON_PORT is set."""
    monkeypatch.setenv('JSP_POSITRON_PORT', '8080')

    from importlib import reload
    import jupyter_positron_server
    reload(jupyter_positron_server)

    config = jupyter_positron_server.setup_positron_server()

    assert config['port'] == 8080
    assert config['command'] == []
    assert config['timeout'] == 30
    assert 'launcher_entry' in config