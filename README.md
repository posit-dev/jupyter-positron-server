# Jupyter Positron Server

Run Positron Server inside your Jupyter environment using [jupyter-server-proxy](https://github.com/jupyterhub/jupyter-server-proxy).

## Requirements

- Python >= 3.9
- [positron-server](https://github.com/posit-dev/positron) installed and available in your PATH
- A valid Positron license key file and signing key

## Configuration

Setup includes installing a proxy for running Positron and a verifier service to check license validity. The setup flow looks like:

1. Email [academic-licenses@posit.co](mailto:academic-licenses@posit.co) to request a **signing key** (`signing-key.pem`) and **license file** (`license.lic`). Free for currently enrolled students using Positron for coursework — see the [Positron Education License Rider](https://github.com/posit-dev/positron/blob/main/LICENSE.txt) for eligibility.
2. Download the Positron Server binary and extract it to `/opt/positron-server` in the single-user image, then place `license.lic` at `resources/activation/linux/<arch>/license.lic` (`chmod 600`, root-only).
3. Install `jupyter-positron-server` in the single-user image.
4. Install `jupyter-positron-verifier` in the Hub's Python environment, and store `signing-key.pem` at `/etc/positron/signing-key.pem` (root-only).
5. Register `jupyter-positron-verifier` as a JupyterHub service in `jupyterhub_config.py`, and point `c.Spawner.environment` at its minting endpoint.
6. Restart JupyterHub, then click the "Positron" icon in the JupyterLab launcher.

See the [Get Started guide](https://posit-dev.github.io/jupyter-positron-server/get_started.html) for the full walkthrough, including the exact `jupyterhub_config.py` snippets.
