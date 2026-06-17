"""
jupyter-positron-server: Run Positron Server inside your Jupyter environment.

This package provides a jupyter-server-proxy extension that enables running
Positron Server within JupyterHub.
"""

from shutil import which
from urllib.parse import urlparse, urlunparse
import json
import logging
import os
import platform
import re
import secrets
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))

# Generate token once at module load so it is consistent
_CONNECTION_TOKEN = os.environ.get("POSITRON_CONNECTION_TOKEN", secrets.token_hex(16))


def _make_positron_path_pattern():
    """Build a compiled regex matching ``<base_url>/user/<name>/positron[/…]``."""
    base_url = os.environ.get("JUPYTERHUB_BASE_URL", "").strip("/")
    prefix = f"/{base_url}" if base_url else ""
    return re.compile(rf"^{re.escape(prefix)}/user/[^/]+/positron(/.*)?$")


def _make_mappath():
    """
    Create a mappath function that strips the doubled base_url prefix from paths.

    positron-server generates relative URLs like
    ./user/admin/positron/oss-dev/... instead of ./oss-dev/...

    When browser requests /user/admin/positron/user/admin/positron/oss-dev/...,
    the proxy strips its prefix /user/admin/positron/ and mappath receives:
    /user/admin/positron/oss-dev/...

    This function strips that extra prefix to get: /oss-dev/...
    """
    pattern = _make_positron_path_pattern()

    def mappath(path):
        match = pattern.match(path)
        if match:
            rest = match.group(1) or "/"
            logger.debug(f"mappath: {path} -> {rest}")
            return rest
        logger.debug(f"mappath: {path} (no match)")
        return path

    return mappath


def rewrite_response(response, request):
    """
    Fix positron-server redirect Location headers.

    positron-server returns Location: /user/X/positron when it should return /
    Then jupyter-server-proxy adds the prefix, causing doubling.

    This strips the prefix so jupyter-server-proxy adds it correctly once.
    """
    rewrite_pattern = _make_positron_path_pattern()
    for header, v in list(response.headers.items()):
        if header.lower() == "location":
            u = urlparse(v)
            match = rewrite_pattern.match(u.path)
            if match:
                fixed_path = match.group(1) if match.group(1) else "/"
                logger.debug(f"rewrite_response: {u.path} -> {fixed_path}")
                response.headers[header] = urlunparse(u._replace(path=fixed_path))
    return response


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
    found = which(prog)
    if found:
        return found

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


def _fetch_license_from_hub(
    minting_endpoint: str, connection_token: str
) -> "str | None":
    """
    Fetch a signed Positron license from the Hub minting endpoint.

    Calls the endpoint authenticated with JUPYTERHUB_API_TOKEN, sending the
    connection token so the Hub can sign a license bound to this session.
    Returns the license JSON string, or None if the fetch fails.
    """
    api_token = os.environ.get("JUPYTERHUB_API_TOKEN")
    if not api_token:
        logger.warning(
            "JUPYTERHUB_API_TOKEN not set; cannot fetch license from Hub minting endpoint"
        )
        return None

    payload = json.dumps({"connection_token": connection_token}).encode()
    req = urllib.request.Request(
        minting_endpoint,
        data=payload,
        headers={
            "Authorization": f"token {api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            license_json = data.get("license")
            if not license_json:
                logger.error("Hub minting endpoint returned no 'license' field")
                return None
            logger.info("Successfully fetched signed license from Hub minting endpoint")
            return license_json
    except (urllib.error.URLError, json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to fetch license from Hub minting endpoint: {e}")
        return None


def _resolve_license_source(minting_endpoint):
    """Resolve the license source for a direct launch.

    Returns the path to a signed-token file (``POSITRON_LICENSE_KEY_FILE``) or
    ``None`` when Hub minting is enabled (the token is fetched at launch instead).
    positron-server only accepts signed JSON license tokens; it no longer locates
    or validates a raw ``.lic`` file.
    """
    if minting_endpoint:
        logger.info(f"Hub license minting enabled: {minting_endpoint}")
        return None

    license_key_file = os.environ.get("POSITRON_LICENSE_KEY_FILE")
    if license_key_file:
        logger.info(f"POSITRON_LICENSE_KEY_FILE set to: {license_key_file}")
        if not os.path.exists(license_key_file):
            raise FileNotFoundError(
                f"Positron license token file not found at '{license_key_file}' "
                f"(specified by POSITRON_LICENSE_KEY_FILE environment variable). "
                f"Point POSITRON_LICENSE_KEY_FILE at a file containing a signed "
                f"license token, or set POSITRON_LICENSE_MINTING_ENDPOINT to mint "
                f"one from the Hub."
            )
    else:
        logger.warning(
            "Neither POSITRON_LICENSE_MINTING_ENDPOINT nor POSITRON_LICENSE_KEY_FILE "
            "is set; positron-server requires a signed license token and will fail "
            "to start without one."
        )
    return license_key_file


def _build_command_args(host, license_key_file):
    """Build the positron-server CLI arguments (excluding the binary and env)."""
    # JUPYTERHUB_SERVICE_PREFIX (e.g. /jh/user/alice/) already includes
    # JUPYTERHUB_BASE_URL as a leading segment — JupyterHub guarantees this.
    service_prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/").rstrip("/")
    server_base_path = service_prefix + "/positron"

    command_arguments = [
        "--accept-server-license-terms",
        "--host",
        host,
        "--port",
        "{port}",
        "--connection-token",
        _CONNECTION_TOKEN,
        "--server-base-path",
        server_base_path,
    ]

    # Only pass license file if one was found
    if license_key_file:
        command_arguments.extend(["--license-key-file", license_key_file])

    # Open Positron in the user's workspace directory.
    # JSP_DEFAULT_FOLDER overrides; JUPYTERHUB_ROOT_DIR is the standard JupyterHub
    # notebook directory env var; HOME is the fallback.
    default_folder = (
        os.environ.get("JSP_DEFAULT_FOLDER")
        or os.environ.get("JUPYTERHUB_ROOT_DIR")
        or os.environ.get("HOME")
    )
    if default_folder:
        if not os.path.isdir(default_folder):
            logger.warning(
                f"Default folder '{default_folder}' does not exist; "
                "--default-folder will not be passed to positron-server."
            )
        else:
            command_arguments.extend(["--default-folder", default_folder])

    return command_arguments


def _resolve_activation_path(positron_server_path):
    """Return the ``LD_LIBRARY_PATH`` positron-server needs for license validation.

    positron-server's bundled activation/validation libraries live at
    ``<root>/resources/activation/linux/<arch>/``, where ``<root>`` is two levels
    up from the binary.
    """
    # Resolve symlinks to get the real path
    real_path = os.path.realpath(positron_server_path)
    # positron-server is at <root>/bin/positron-server, so go up two levels
    positron_root = os.path.dirname(os.path.dirname(real_path))
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

    return f"/usr/local/lib:{activation_path}"


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

        - `new_browser_tab` (bool): Whether to open in a new browser tab
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
        "new_browser_tab": True,
        "timeout": 120,
        "mappath": _make_mappath(),
        "rewrite_response": rewrite_response,
        # Clear X-Forwarded-Prefix to prevent positron-server from doubling URLs
        "request_headers_override": {"X-Forwarded-Prefix": ""},
        "launcher_entry": {
            "enabled": False
            if os.environ.get("JSP_POSITRON_LAUNCHER_DISABLED")
            else True,
            "title": "Positron",
            "icon_path": os.path.join(_HERE, "icons/positron.svg"),
            "path_info": f"positron/?tkn={_CONNECTION_TOKEN}",
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
    minting_endpoint = os.environ.get("POSITRON_LICENSE_MINTING_ENDPOINT")

    license_key_file = _resolve_license_source(minting_endpoint)
    command_arguments = _build_command_args(host, license_key_file)

    positron_server_path = which_positron_server()
    ld_library_path = _resolve_activation_path(positron_server_path)

    if minting_endpoint:
        # Hub minting path: fetch a fresh signed license just before launch.
        # Capture variables for the closure.
        _ld_library_path = ld_library_path
        _positron_server_path = positron_server_path
        _command_arguments = command_arguments
        _minting_endpoint = minting_endpoint
        _connection_token = _CONNECTION_TOKEN

        def _get_hub_minted_command():
            license_json = _fetch_license_from_hub(_minting_endpoint, _connection_token)
            cmd = ["/usr/bin/env", f"LD_LIBRARY_PATH={_ld_library_path}"]
            if license_json:
                # Escape braces so jupyter-server-proxy's format_map() doesn't
                # interpret the JSON's { } as template variables.
                license_escaped = license_json.replace("{", "{{").replace("}", "}}")
                cmd.append(f"POSITRON_LICENSE_KEY={license_escaped}")
            else:
                logger.warning(
                    "Hub minting endpoint returned no license; "
                    "positron-server may fail license validation"
                )
            return cmd + [_positron_server_path] + _command_arguments

        proxy_config_dict["command"] = _get_hub_minted_command
        logger.info("Positron server command: Hub-minted license (callable)")
    else:
        # Direct launch: any signed-token --license-key-file is already included in
        # command_arguments. Use env to set LD_LIBRARY_PATH reliably.
        full_command = [
            "/usr/bin/env",
            f"LD_LIBRARY_PATH={ld_library_path}",
            positron_server_path,
        ] + command_arguments

        proxy_config_dict["command"] = full_command
        logger.info(f"Positron server command: {' '.join(full_command)}")

    return proxy_config_dict
