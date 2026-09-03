# Positron Server on JupyterHub: docker-compose deployment template

The Docker-native counterpart to [`scripts/install-positron.sh`](../install-positron.sh)
(which targets The Littlest JupyterHub). This is a **deployment template**: a
starting point you copy and adapt for a real deployment.

> **Targets Positron Server 2026.09.0-256** and `jupyter-positron-server>=0.0.6`,
> which validate `license.lic` directly through the bundled `license-manager`.
> If you are instead deploying Positron Server 2026.07.0 through 2026.08.2
> (which validate a Hub-minted signing token, a former way of working), follow
> the [Verifier setup](https://posit-dev.github.io/jupyter-positron-server/verifier_get_started.html)
> guide by hand. No script in this repository automates that flow.

Two images run as separate containers on a shared docker network:

- **hub** (privileged): JupyterHub + DockerSpawner. Holds no Positron-specific
  secrets itself. It bind-mounts `license.lic` into each single-user container
  it spawns.
- **single-user**: the user session. Positron Server binary plus the
  `jupyter-positron-server` proxy extension. Receives `license.lic` as a
  read-only bind mount from DockerSpawner at session start. DockerSpawner
  launches these containers on demand, so the image is built but not run by
  compose.

## Prerequisites

- Docker Engine with the Compose plugin, on an x86_64 or arm64 Linux host.
- From Posit (send email to academic-licenses@posit.co): a **license file**
  (`license.lic`). See the project README for eligibility.

## Setup

1. **Configure.** Copy the example env and edit as needed:
   ```bash
   cp .env.example .env
   ```
   Set `POSITRON_ARCH` / `POSITRON_ACTIVATION_ARCH` together for your host
   architecture (`x64`/`x86_64` or `arm64`/`aarch64`), pick a `POSITRON_VERSION`,
   and adjust ports/tags if needed.

2. **Add the secret.** Drop the license into `secrets/` (git-ignored), and make
   it world-readable so the single-user session can read it as the student:
   ```bash
   cp /path/to/license.lic secrets/license.lic
   chmod 644 secrets/license.lic
   ```
   It is bind-mounted read-only wherever it is needed. It is never baked into
   an image and never committed.

3. **Build both images** (the single-user image must be named explicitly because
   it is behind a build-only profile):
   ```bash
   docker compose build hub singleuser
   ```

4. **Start the hub**, from this directory (`scripts/docker/`). The compose
   file resolves `${PWD}` to derive the host path DockerSpawner mounts the
   license from:
   ```bash
   docker compose up -d
   ```

5. Open `http://localhost:8000` (or your `HUB_PORT`). With the default
   `DummyAuthenticator` you can log in with any username/password, then launch
   Positron from the JupyterLab launcher.

## ⚠️ Before any real use: replace the authenticator

The template ships with `DummyAuthenticator`, which accepts any username and
any password. Edit `hub/jupyterhub_config.py` to use a real authenticator
(OAuth, native, LDAP, and so on) and rebuild the hub image before exposing
this to anyone.

## How it works

1. The hub checks at boot that `secrets/license.lic` exists and is non-empty,
   so a forgotten secret fails fast with a clear message instead of a cryptic
   per-session error later.
2. When a session spawns, DockerSpawner creates the single-user container and
   bind-mounts `secrets/license.lic`, read-only, straight into the activation
   directory `positron-server` expects
   (`resources/activation/linux/<arch>/license.lic`). The mount source is a
   **host**-absolute path, because DockerSpawner talks to the host docker
   daemon through the socket mounted into the hub container, not to the hub
   container's own filesystem.
3. `positron-server` validates the mounted license itself, through the bundled
   `license-manager`, and starts. No token is minted, and no environment
   variable carries the license. `jupyter-positron-server` needs none.

## Configuration reference

All values live in `.env` (see `.env.example` for defaults and comments):

| Variable | Purpose |
|----------|---------|
| `POSITRON_VERSION` | Positron Server release to bake into both images |
| `POSITRON_ARCH` | Download arch suffix: `x64` or `arm64` |
| `POSITRON_ACTIVATION_ARCH` | Activation dir name: `x86_64` or `aarch64` (pairs with `POSITRON_ARCH`). Also where DockerSpawner mounts `license.lic` in each session |
| `POSITRON_SERVER_PKG` | `jupyter-positron-server` spec (PyPI, or `git+https://github.com/org/repo@branch`) |
| `HUB_PORT` | Host port the hub is published on |
| `HUB_IMAGE` / `SINGLEUSER_IMAGE` | Image tags |
| `DOCKER_NETWORK` | Shared network name (must match the `network_name` DockerSpawner uses) |
