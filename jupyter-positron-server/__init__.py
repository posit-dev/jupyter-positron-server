from shutil import which
import os
import secrets

_HERE = os.path.dirname(os.path.abspath(__file__))

# Generate token once at module load so it's consistent
_CONNECTION_TOKEN = os.environ.get('POSITRON_CONNECTION_TOKEN', secrets.token_hex(16))


def which_positron_server():
    command = which('positron-server')
    if not command:
        raise FileNotFoundError('Could not find executable positron-server!')
    return command


def setup_positron_server():
    proxy_config_dict = {
        "new_browser_window": True,
        "timeout": 30,
        "launcher_entry": {
            "enabled": False if os.environ.get('JSP_POSITRON_LAUNCHER_DISABLED') else True,
            "title": "Positron",
            "path_info": f"positron?tkn={_CONNECTION_TOKEN}",
            "icon_path": os.path.join(_HERE, 'icons/positron.svg')
            },
        }

    # if positron-server is already running and listening to TCP port
    positron_port = os.environ.get('JSP_POSITRON_PORT', None)
    if positron_port:
        proxy_config_dict.update({
            "command": [],
            "port": int(positron_port)
            })
        return proxy_config_dict

    # if positron-server is already running and listening to UNIX socket
    positron_socket = os.environ.get('JSP_POSITRON_SOCKET', None)
    if positron_socket:
        proxy_config_dict.update({
            "command": [],
            "unix_socket": positron_socket
            })
        return proxy_config_dict

    working_directory = os.environ.get('POSITRON_WORKING_DIRECTORY', None)
    if not working_directory:
        working_directory = os.environ.get('JUPYTERHUB_ROOT_DIR', os.environ.get('JUPYTER_SERVER_ROOT', os.environ.get('HOME')))

    # License key file - required for positron-server
    license_key_file = os.environ.get('POSITRON_LICENSE_KEY_FILE', None)
    if not license_key_file:
        raise EnvironmentError(
            'POSITRON_LICENSE_KEY_FILE environment variable must be set to the path of your license key file.'
        )

    host = os.environ.get('POSITRON_HOST', '127.0.0.1')

    command_arguments = [
        '--license-key-file', license_key_file,
        '--host', host,
        '--port', '{port}',
        '--connection-token', _CONNECTION_TOKEN,
        '--server-base-path', '/positron/',
    ]

    full_command = [which_positron_server()] + command_arguments
    proxy_config_dict.update({
        "command": full_command,
        })

    return proxy_config_dict