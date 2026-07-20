# Positron Server on JupyterHub — docker-compose deployment template

The Docker-native counterpart to [`scripts/install-positron.sh`](../scripts/install-positron.sh)
(which targets The Littlest JupyterHub). This is a **deployment template**: a
starting point you copy and adapt for a real deployment.

Two images run as separate containers on a shared docker network:

- **hub** (privileged) — JupyterHub + DockerSpawner, holds the signing key and
  license, and runs `jupyter-positron-verifier` as a managed service that mints
  per-session license tokens.
- **single-user** — the user session: Positron Server binary +
  `jupyter-positron-server` proxy extension. Holds no secrets; it fetches a
  minted token from the hub at session start. DockerSpawner launches these
  containers on demand, so the image is *built but not run* by compose.

## Prerequisites

- Docker Engine with the Compose plugin, on an x86_64 or arm64 Linux host.
- From Posit (email academic-licenses@posit.co): a **signing key**
  (`signing-key.pem`) and a **license file** (`license.lic`). See the project
  README for eligibility.

## Setup

1. **Configure.** Copy the example env and edit as needed:
   ```bash
   cp .env.example .env
   ```
   Set `POSITRON_ARCH` / `POSITRON_ACTIVATION_ARCH` together for your host
   architecture (`x64`/`x86_64` or `arm64`/`aarch64`), pick a `POSITRON_VERSION`,
   and adjust ports/tags if needed.

2. **Add secrets.** Drop the two files into `secrets/` (git-ignored):
   ```bash
   cp /path/to/signing-key.pem secrets/signing-key.pem
   cp /path/to/license.lic     secrets/license.lic
   ```
   They are bind-mounted read-only into the hub; they are never baked into an
   image and never committed.

3. **Build both images** (the single-user image must be named explicitly because
   it is behind a build-only profile):
   ```bash
   docker compose build hub singleuser
   ```

4. **Start the hub:**
   ```bash
   docker compose up -d
   ```

5. Open `http://localhost:8000` (or your `HUB_PORT`). With the default
   `DummyAuthenticator` you can log in with any username/password, then launch
   Positron from the JupyterLab launcher.

## ⚠️ Before any real use: replace the authenticator

The template ships with `DummyAuthenticator`, which accepts **any username and
any password**. Edit `hub/jupyterhub_config.py` to use a real authenticator
(OAuth, native, LDAP, …) and rebuild the hub image before exposing this to
anyone.

## How it works

1. `jupyter-positron-server` (single-user) calls
   `http://hub:${VERIFIER_PORT}/services/positron-license/mint`, authenticated
   with its `JUPYTERHUB_API_TOKEN`, sending the session connection token.
2. `jupyter-positron-verifier` (hub) verifies the user token, confirms
   entitlement via `license-manager` (reading the mounted `license.lic`), and
   returns a signed license JSON bound to the session.
3. `jupyter-positron-server` starts `positron-server` with the license in
   `POSITRON_LICENSE_KEY`.
4. `positron-server` verifies the RSA signature with its embedded public key and
   starts.

## Configuration reference

All values live in `.env` (see `.env.example` for defaults and comments):

| Variable | Purpose |
|----------|---------|
| `POSITRON_VERSION` | Positron Server release to bake into both images |
| `POSITRON_ARCH` | Download arch suffix: `x64` or `arm64` |
| `POSITRON_ACTIVATION_ARCH` | Activation dir name: `x86_64` or `aarch64` (pairs with `POSITRON_ARCH`) |
| `POSITRON_SERVER_PKG` | `jupyter-positron-server` spec (PyPI, or `git+https://…@branch`) |
| `POSITRON_VERIFIER_PKG` | `jupyter-positron-verifier` spec |
| `HUB_PORT` | Host port the hub is published on |
| `VERIFIER_PORT` | Internal minting-service port (not published) |
| `HUB_IMAGE` / `SINGLEUSER_IMAGE` | Image tags |
| `DOCKER_NETWORK` | Shared network name (must match DockerSpawner's `network_name`) |

