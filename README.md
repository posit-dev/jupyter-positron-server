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

### Required

Have `positron-server` installed and accessible in your system's PATH.
Set the `POSITRON_LICENSE_KEY_FILE` environment variable to the path of your license key file:

```bash
export POSITRON_LICENSE_KEY_FILE=/path/to/your/license.key
```

## Usage

1. Start Jupyter Lab:

```bash
jupyter lab
```

2. Click the "Positron" icon in the Jupyter Lab launcher.
