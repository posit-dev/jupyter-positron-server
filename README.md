# Jupyter Positron Server

Run Positron Server inside your Jupyter environment using [jupyter-server-proxy](https://github.com/jupyterhub/jupyter-server-proxy).

## Requirements

- Python >= 3.9
- [positron-server](https://github.com/posit-dev/positron) installed and available in your PATH
- A valid Positron license key file, set as a `POSITRON_LICENSE_KEY_FILE` environment variable

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

Download the Positron Server binary for your Linux architecture. For the latest release of Positron (April 2026), you can find the downloads here:

- **x64**: https://cdn.posit.co/positron/releases/server/x86_64/positron-server-linux-x64-2026.04.0-269.tar.gz
- **arm64**: https://cdn.posit.co/positron/releases/server/arm64/positron-server-linux-arm64-2026.04.0-269.tar.gz

After downloading, untar the archive and add it to your PATH.

### Set the License Key

Set the `POSITRON_LICENSE_KEY_FILE` environment variable to the path of your license key file:

```bash
export POSITRON_LICENSE_KEY_FILE=/path/to/your/license.key
```

## Usage

1. Start JupyterLab:

```bash
jupyter lab
```

2. Click the "Positron" icon in the JupyterLab launcher.
