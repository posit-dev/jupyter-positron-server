# Jupyter Positron Server

Run Positron Server inside your Jupyter environment using [jupyter-server-proxy](https://github.com/jupyterhub/jupyter-server-proxy).

## Requirements

- Python >= 3.9
- [positron-server](https://github.com/posit-dev/positron) installed and available in your PATH
- A valid Positron license key file

## Installation

```bash
pip install jupyter-positron-server
```

Or install from source:

```bash
git clone https://github.com/posit-dev/jupyter-positron-server.git
cd jupyter-positron-server
pip install -e .
```

## Configuration

### Download Positron Server

Download the Positron Server binary for your Linux architecture. For the latest release of Positron (May 2026), you can find the downloads here:

- [Download Linux x64 build](https://cdn.posit.co/positron/releases/server/x86_64/positron-server-linux-x64-2026.05.0-179.tar.gz)
- [Download Linux arm64 build](https://cdn.posit.co/positron/releases/server/arm64/positron-server-linux-arm64-2026.05.0-179.tar.gz)

After downloading, untar the archive and add it to your PATH.

If you're using `curl`, this step might look something like:

```zsh
# Download Positron server to temporary directory
# Note: this is the url for x64 architecture machines
curl -L "https://cdn.posit.co/positron/dailies/server/arm64/positron-server-linux-arm64-2026.05.0-179.tar.gz" -o /tmp/positron-server.tar.gz

# Create directory
mkdir -p /opt/positron-server

# Unpack Positron Server into newly created directory
tar -xzf /tmp/positron-server.tar.gz -C /opt/positron-server --strip-components=1
```

### Get a License

Positron Server is available for educational use only. Free licenses are available for currently enrolled students using Positron for coursework. Review the [Positron Education License Rider](https://github.com/posit-dev/positron/blob/main/LICENSE.txt) for full eligibility terms.

To request a license, email [academic-licenses@posit.co](mailto:academic-licenses@posit.co).

### Set the License Key

Place your license at `<positron_root>/resources/activation/linux/{ARCH}/license.lic`, where `{ARCH}` is `x86_64` or `aarch64`.

### Install the `jupyter-positron-server` package

Install `jupyter-positron-server` in an environment that is available to all users of your JupyterHub server.

```shell
pip install jupyter-positron-server
```

### Start your Jupyter server

1. Start or restart your Jupyter server. In JupyterHub, you can do this by selecting `File` > `Hub Control Panel`, then clicking `Stop My Server` and `Start My Server`.

2. Click the "Positron" icon in the JupyterLab launcher.
