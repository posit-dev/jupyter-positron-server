"""
jupyter-positron-server: Run Positron Server inside your Jupyter environment.

This package provides a jupyter-server-proxy extension that enables running
Positron Server within JupyterHub.
"""

from shutil import which
import logging
import os
import platform
import secrets

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))

# Generate token once at module load so it is consistent
_CONNECTION_TOKEN = os.environ.get("POSITRON_CONNECTION_TOKEN", secrets.token_hex(16))


def which_positron_server():
    """
    Locate the positron-server executable.

    Searches for the `positron-server` command in the system PATH, falling back
    to known installation locations if not found.

    Returns
    -------
    str
        The absolute path to the positron-server executable.

    Raises
    ------
    FileNotFoundError
        If positron-server cannot be found in PATH or at known locations.

    Examples
    --------
    >>> from jupyter_positron_server import which_positron_server
    >>> path = which_positron_server()
    >>> print(path)
    '/opt/positron-server/bin/positron-server'
    """
    prog = "positron-server"
    known_paths = [
        os.path.join("/usr/lib/positron-server/bin", prog),
        os.path.join("/opt/positron-server/bin", prog),
    ]

    # First check if it's in PATH
    if which(prog):
        return prog

    # Fall back to known locations
    for path in known_paths:
        if os.path.exists(path):
            return path

    paths_checked = "\n".join(f"  - {p} (not found)" for p in known_paths)
    raise FileNotFoundError(
        f"Could not find {prog} executable.\n\n"
        "Checked:\n"
        "  - System PATH (not found)\n"
        f"{paths_checked}\n\n"
        "Please ensure positron-server is installed and either:\n"
        "  1. Added to your system PATH, or\n"
        "  2. Extracted to /opt/positron-server/ or /usr/lib/positron-server/"
    )


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
    """
    proxy_config_dict = {
        "new_browser_window": True,
        "timeout": 120,
        # Don't send X-Forwarded-Prefix - positron-server uses it to generate
        # relative URLs which causes URL doubling in the browser.
        # Without this header, positron-server generates root-relative URLs
        # and jupyter-server-proxy handles the path rewriting automatically.
        "request_headers_override": {"X-Forwarded-Prefix": ""},
        "launcher_entry": {
            "enabled": False
            if os.environ.get("JSP_POSITRON_LAUNCHER_DISABLED")
            else True,
            "title": "Positron",
            "path_info": f"positron/?tkn={_CONNECTION_TOKEN}",
            "icon_path": os.path.join(_HERE, "icons/positron.svg"),
        },
    }

    # if positron-server is already running and listening to TCP port
    positron_port = os.environ.get("JSP_POSITRON_PORT", None)
    if positron_port:
        proxy_config_dict.update({"command": [], "port": int(positron_port)})
        return proxy_config_dict

    # if positron-server is already running and listening to UNIX socket
    positron_socket = os.environ.get("JSP_POSITRON_SOCKET", None)
    if positron_socket:
        proxy_config_dict.update({"command": [], "unix_socket": positron_socket})
        return proxy_config_dict

    host = os.environ.get("POSITRON_HOST", "127.0.0.1")

    # Find license file: check env var first, then default location
    # If no license file found, let positron-server use system license
    license_key_file = os.environ.get("POSITRON_LICENSE_KEY_FILE")
    if license_key_file:
        logger.info(f"POSITRON_LICENSE_KEY_FILE set to: {license_key_file}")
        if not os.path.exists(license_key_file):
            raise FileNotFoundError(
                f"Positron license file not found at '{license_key_file}' "
                f"(specified by POSITRON_LICENSE_KEY_FILE environment variable). "
                f"Please ensure the license file exists or set POSITRON_LICENSE_KEY_FILE "
                f"to the correct path."
            )
    else:
        default_license_path = "/opt/license.lic"
        if os.path.exists(default_license_path):
            license_key_file = default_license_path
            logger.info(f"Using default license file: {license_key_file}")
        else:
            logger.info(
                "No license file found, positron-server will use system license"
            )

    command_arguments = [
        "--accept-server-license-terms",
        "--host",
        host,
        "--port",
        "{port}",
        "--connection-token",
        _CONNECTION_TOKEN,
    ]

    # Only pass license file if one was found
    if license_key_file:
        command_arguments.extend(["--license-key-file", license_key_file])

    # Determine LD_LIBRARY_PATH from positron-server location
    positron_server_path = which_positron_server()
    # Resolve symlinks to get the real path
    real_path = os.path.realpath(positron_server_path)
    # positron-server is at <root>/bin/positron-server, so go up two levels
    positron_root = os.path.dirname(os.path.dirname(real_path))
    # Determine architecture
    arch = platform.machine()
    activation_path = os.path.join(
        positron_root, "resources", "activation", "linux", arch
    )

    # Validate activation libraries exist (required for license validation)
    if not os.path.isdir(activation_path):
        raise FileNotFoundError(
            f"Positron activation libraries not found at '{activation_path}'.\n\n"
            f"This usually means positron-server is not installed correctly for "
            f"your architecture ({arch}).\n"
            f"Expected directory structure: {positron_root}/resources/activation/linux/{arch}/"
        )

    ld_library_path = f"/usr/local/lib:{activation_path}"

    # Use env command to set LD_LIBRARY_PATH reliably
    full_command = [
        "/usr/bin/env",
        f"LD_LIBRARY_PATH={ld_library_path}",
        positron_server_path,
    ] + command_arguments

    proxy_config_dict.update(
        {
            "command": full_command,
        }
    )

    logger.info(f"Positron server command: {' '.join(full_command)}")
    return proxy_config_dict
