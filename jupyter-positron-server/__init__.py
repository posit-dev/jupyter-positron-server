"""
jupyter-positron-server: Run Positron Server inside your Jupyter environment.

This package provides a jupyter-server-proxy extension that enables running
Positron Server within JupyterHub or JupyterLab.
"""

from shutil import which
import os
import secrets

_HERE = os.path.dirname(os.path.abspath(__file__))

# Generate token once at module load so it is consistent
_CONNECTION_TOKEN = os.environ.get("POSITRON_CONNECTION_TOKEN", secrets.token_hex(16))


def which_positron_server():
    """
    Locate the positron-server executable.

    Searches for the `positron-server` command in the system PATH, falling back
    to a default installation location if not found.

    Returns
    -------
    str
        The absolute path to the positron-server executable.

    Raises
    ------
    FileNotFoundError
        If positron-server cannot be found in PATH or at the default location.

    Examples
    --------
    >>> from jupyter_positron_server import which_positron_server
    >>> path = which_positron_server()
    >>> print(path)
    '/usr/local/bin/positron-server'
    """
    command = which("positron-server")
    if not command:
        # Fall back to known location
        default_path = "/opt/vscode-reh-web-server-linux-arm64/bin/positron-server"
        if os.path.exists(default_path):
            return default_path
        raise FileNotFoundError("Could not find executable positron-server!")
    return command


def setup_positron_server():
    """
    Configure jupyter-server-proxy to run Positron Server.

    Returns a configuration dictionary that jupyter-server-proxy uses to launch
    or connect to a Positron Server instance. The behavior depends on environment
    variables:

    - If `JSP_POSITRON_PORT` is set, connects to an existing server on that TCP port
    - If `JSP_POSITRON_SOCKET` is set, connects to an existing server via UNIX socket
    - Otherwise, starts a new positron-server process

    Returns
    -------
    dict
        Configuration dictionary containing:

        - `new_browser_window` (bool): Whether to open in a new browser window
        - `timeout` (int): Server startup timeout in seconds
        - `launcher_entry` (dict): JupyterLab launcher configuration
        - `command` (list): Command to start server (empty if connecting to existing)
        - `port` (int) or `unix_socket` (str): Connection details (if applicable)
        - `environment` (dict): Environment variables for the server process

    See Also
    --------
    which_positron_server : Locates the positron-server executable.

    Examples
    --------
    >>> from jupyter_positron_server import setup_positron_server
    >>> config = setup_positron_server()
    >>> config['launcher_entry']['title']
    'Positron'
    """
    proxy_config_dict = {
        "new_browser_window": True,
        "timeout": 120,
        "launcher_entry": {
            "enabled": False if os.environ.get("JSP_POSITRON_LAUNCHER_DISABLED") else True,
            "title": "Positron",
            "path_info": f"positron?tkn={_CONNECTION_TOKEN}",
            "icon_path": os.path.join(_HERE, "icons/positron.svg")
            },
        }

    # if positron-server is already running and listening to TCP port
    positron_port = os.environ.get("JSP_POSITRON_PORT", None)
    if positron_port:
        proxy_config_dict.update({
            "command": [],
            "port": int(positron_port)
            })
        return proxy_config_dict

    # if positron-server is already running and listening to UNIX socket
    positron_socket = os.environ.get("JSP_POSITRON_SOCKET", None)
    if positron_socket:
        proxy_config_dict.update({
            "command": [],
            "unix_socket": positron_socket
            })
        return proxy_config_dict

    host = os.environ.get("POSITRON_HOST", "127.0.0.1")

    command_arguments = [
        "--accept-server-license-terms",
        "--host", host,
        "--port", "{port}",
        "--connection-token", _CONNECTION_TOKEN,
        "--server-base-path", "/positron/",
    ]

    full_command = [which_positron_server()] + command_arguments
    
    # Set up environment with license file
    env = {}
    license_key_file = os.environ.get("POSITRON_LICENSE_KEY_FILE", "/opt/license.lic")
    env["POSITRON_LICENSE_KEY_FILE"] = license_key_file
    env["LD_LIBRARY_PATH"] = "/usr/local/lib:/opt/vscode-reh-web-server-linux-arm64/resources/activation/linux/aarch64"
    
    proxy_config_dict.update({
        "command": full_command,
        "environment": env,
        })

    return proxy_config_dict
