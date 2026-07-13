# Design: docker-compose deployment template for Positron on JupyterHub

## Goal

Provide a docker-compose stack that stands up Positron Server on JupyterHub, as
the Docker-native counterpart to `scripts/install-positron.sh` (which targets
TLJH). It is a **deployment template**: a starting point admins copy and adapt
for real deployments, not a throwaway local demo.

## Background

`scripts/install-positron.sh` installs Positron into a single-host TLJH
deployment where the hub env, user env, Positron Server binary, license, and
signing key all live together and are wired up via `SystemdSpawner` and
`jupyterhub_config.d`.

Docker-based JupyterHub splits this into two images that run as separate
containers:

- **Hub** (privileged): runs JupyterHub + DockerSpawner, holds the signing key
  and license, and runs `jupyter-positron-verifier` as a managed service to mint
  per-session license tokens.
- **Single-user**: runs the user session with the Positron Server binary and the
  `jupyter-positron-server` proxy extension. Holds no secrets — it fetches a
  minted token from the Hub at session start.

## Decisions

Settled during brainstorming:

- **Artifact**: a docker-compose stack (not a bare Dockerfile or a build script).
- **Purpose**: deployment template (secrets mounted, not baked; configurable).
- **Spawner**: `DockerSpawner` — the Hub spawns per-user single-user containers
  as siblings via the mounted docker socket, on a shared docker network.
- **Secrets & binary**: Positron Server binary baked into images at build (via
  version/arch build args); `license.lic` and `signing-key.pem` bind-mounted at
  runtime, never baked into image layers.
- **Minting endpoint routing** (fork 1): single-user sessions reach the verifier
  directly at `http://hub:10101/services/positron-license/mint` over the shared
  docker network — the closest mirror of the TLJH `127.0.0.1:10101` route, since
  the verifier already mounts itself at that path prefix. (Alternative, routing
  through the proxy at `hub:8000`, was rejected as unnecessary indirection.)
- **Authenticator** (fork 2): default to `DummyAuthenticator` with a prominent
  comment that admins MUST replace it before any real use.

## Directory layout

New top-level `docker/` directory (the stack is multi-file, so it does not
belong in `scripts/` beside the single shell script):

```
docker/
  docker-compose.yml
  .env.example              # POSITRON_VERSION, POSITRON_ARCH, ports, pkg specs, image tags
  .gitignore                # ignores .env and secrets/*
  hub/
    Dockerfile              # jupyterhub + dockerspawner + jupyter-positron-verifier + positron-server
    jupyterhub_config.py    # DockerSpawner + verifier service + spawner env
  singleuser/
    Dockerfile              # base notebook + jupyter-server-proxy + jupyter-positron-server + positron-server binary
  secrets/
    .gitkeep                # admin drops license.lic + signing-key.pem here (gitignored)
  README.md                 # usage, mirrors install-positron.sh's header comment
```

## Components

### single-user image (`singleuser/Dockerfile`)

- Base off a Jupyter notebook image (e.g. `quay.io/jupyter/base-notebook`).
- Install `jupyter-server-proxy` and `jupyter-positron-server` (package spec from
  a build arg, default PyPI); enable the `jupyter_server_proxy` server extension.
- Download and unpack the Positron Server tarball to `/opt/positron-server` using
  `POSITRON_VERSION` / `POSITRON_ARCH` build args. Reuse the install script's CDN
  URL pattern and the arch mapping (`arm64`→`aarch64`, `x64`→`x86_64` for the
  activation dir; download suffix stays `arm64`/`x64`).
- Holds **no secrets**: no `license.lic`, no signing key.

### hub image (`hub/Dockerfile`)

- Base off a Python image; install `jupyterhub`, `dockerspawner`, and
  `jupyter-positron-verifier` (package spec from a build arg, default PyPI).
- Unpack the Positron Server tarball (same build args) so `license-manager` is
  present under the activation dir for entitlement checks.
- `configurable-http-proxy` runs as the Hub's default subprocess inside this
  container.

### jupyterhub_config.py

The Docker analogue of the config the install script generates inline. Same three
pieces, adapted for containers:

1. **`c.JupyterHub.services`** — the `positron-license` managed service:
   - `url`: `http://0.0.0.0:10101` (bind on all interfaces so single-user
     containers on the docker network can reach it).
   - `command`: `["positron-verifier"]`.
   - `environment`: `POSITRON_MINTING_KEY_FILE=/etc/positron/signing-key.pem`,
     `POSITRON_LICENSE_MANAGER_PATH=/opt/positron-server/resources/activation/linux/<arch>/license-manager`,
     `PORT=10101`.
2. **`c.JupyterHub.load_roles`** — the `positron-license-service` role granting
   the service `read:users`.
3. **DockerSpawner + spawner env**:
   - `c.JupyterHub.spawner_class = 'dockerspawner.DockerSpawner'`.
   - `c.DockerSpawner.image` = single-user image tag (from env).
   - `c.DockerSpawner.network_name` = the compose network.
   - `c.JupyterHub.hub_ip = 'hub'` (or `0.0.0.0`) so spawned containers reach the
     Hub by service name.
   - `c.DockerSpawner.environment`:
     - `PATH` prefixed with `/opt/positron-server/bin`.
     - `POSITRON_LICENSE_MINTING_ENDPOINT=http://hub:10101/services/positron-license/mint`.
4. **Auth**: `c.JupyterHub.authenticator_class = 'jupyterhub.auth.DummyAuthenticator'`
   with a prominent comment to replace it before real use.

### docker-compose.yml

- **`hub`** service:
  - builds `hub/Dockerfile` with the shared build args.
  - mounts `/var/run/docker.sock` (so DockerSpawner can launch containers).
  - mounts `./secrets/signing-key.pem` → `/etc/positron/signing-key.pem` (read-only).
  - mounts `./secrets/license.lic` →
    `/opt/positron-server/resources/activation/linux/<arch>/license.lic` (read-only).
  - publishes the Hub port (default `8000`).
  - joins the shared network; sets `hostname: hub`.
- **shared network**: an explicit named bridge network so DockerSpawner's
  `network_name` matches and single-user containers can resolve `hub`.
- The single-user image is **built but not run** as a compose service (DockerSpawner
  launches it on demand). Compose builds it via a `build`-only entry or the README
  documents `docker compose build singleuser` / a dedicated build step.

### .env.example

Mirrors the install script's env-var configurability:

- `POSITRON_VERSION`, `POSITRON_ARCH` (build args).
- `POSITRON_SERVER_PKG`, `POSITRON_VERIFIER_PKG` (package specs; default PyPI).
- `VERIFIER_PORT` (default `10101`), `HUB_PORT` (default `8000`).
- Image tags for hub and single-user images.

## Data / token flow (unchanged from TLJH)

1. `jupyter-positron-server` (single-user) calls
   `http://hub:10101/services/positron-license/mint`, authenticated with its
   `JUPYTERHUB_API_TOKEN`, sending the session connection token.
2. `jupyter-positron-verifier` (hub) verifies the user token, confirms entitlement
   via `license-manager` (reading the mounted `license.lic`), and returns a signed
   license JSON bound to the session.
3. `jupyter-positron-server` starts `positron-server` with the license in
   `POSITRON_LICENSE_KEY`.
4. `positron-server` verifies the RSA signature with its embedded public key and
   starts.

## Notes / trade-offs

- Both images bake the full Positron Server tarball; the hub strictly needs only
  `license-manager`. Kept simple and correct for a template; image-size
  optimization (multi-stage / shared base) is a documented TODO, not in scope.
- Verification: per project guidance, a full `docker compose build` / `up` will
  not be run in this environment. Files will be authored and the user verifies
  manually.

## Out of scope

- TLS/HTTPS termination.
- A production authenticator (OAuth, native, etc.) — placeholder only.
- Persistent volumes for user home directories (can be added by admins).
- Image-size optimization via multi-stage builds.
