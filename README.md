# Jupyter Positron Server

Run Positron Server inside your Jupyter environment using [jupyter-server-proxy](https://github.com/jupyterhub/jupyter-server-proxy).

## Requirements

- Python >= 3.9
- [positron-server](https://github.com/posit-dev/positron) installed and available in your PATH
- A Positron license file (`license.lic`), requested from [academic-licenses@posit.co](mailto:academic-licenses@posit.co)
- At least 2.5 GB of RAM per session

## Which setup applies to your version

Positron Server changed how it verifies a license twice, so the setup steps depend on the version you install. Find your version below, then follow the guide in the last column.

| Positron Server version | How the license is verified | What to install | Setup guide |
|---|---|---|---|
| 2026.09.0 and newer | `positron-server` validates `license.lic` in its own activation directory | [Get started](https://posit-dev.github.io/jupyter-positron-server/get_started.html) |
| 2026.07.0 through 2026.08.2 | A Hub service mints a signed, per-session token from a signing key. No license file is read by the session | `jupyter-positron-server` and `jupyter-positron-verifier` | [Verifier setup](https://posit-dev.github.io/jupyter-positron-server/verifier_get_started.html) |
| 2026.06.1 and older | `positron-server` validates `license.lic` in its own activation directory | `jupyter-positron-server` | [Get started](https://posit-dev.github.io/jupyter-positron-server/get_started.html) |

The signing key is a former way of working, scoped to Positron Server 2026.07.0 through 2026.08.2, and **not recommended** for a new deployment. See the [Verifier setup guide](https://posit-dev.github.io/jupyter-positron-server/verifier_get_started.html) only if you are deploying that exact version range.

The two license file rows differ in one detail: on 2026.06.1 and older, install `jupyter-positron-server` version 0.0.4, and on 2026.09.0 and newer, install version 0.0.5 or newer.

## Setup

For Positron Server 2026.09.0 and newer, the setup is:

1. Email [academic-licenses@posit.co](mailto:academic-licenses@posit.co) to request a license file (`license.lic`). Free for currently enrolled students using Positron for coursework. See the [Positron Education License Rider](https://github.com/posit-dev/positron/blob/main/LICENSE.txt) for eligibility.
2. Download the Positron Server binary and extract it to `/opt/positron-server` in the single-user image.
3. Place `license.lic` next to the `license-manager` binary, at `/opt/positron-server/resources/activation/linux/<arch>/license.lic`, with mode `644` so each session can read it. `<arch>` is `x86_64` or `aarch64`.
4. Install `jupyter-positron-server` in the single-user image.
5. Add `/opt/positron-server/bin` to `c.Spawner.environment["PATH"]` in `jupyterhub_config.py`.
6. Restart JupyterHub, then select the "Positron" tile in the JupyterLab launcher.

See the [Get started guide](https://posit-dev.github.io/jupyter-positron-server/get_started.html) for the full walkthrough, including the exact `jupyterhub_config.py` snippets and how to move an existing verifier deployment off the signing key.
