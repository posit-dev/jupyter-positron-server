# Docker-Compose Deployment Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `docker/` deployment template that stands up Positron Server on JupyterHub with DockerSpawner, as the Docker-native counterpart to `scripts/install-positron.sh` (TLJH).

**Architecture:** A docker-compose stack with two images. The **hub** container (built from the official `jupyterhub/jupyterhub` image) runs JupyterHub + DockerSpawner + the `jupyter-positron-verifier` managed service that mints per-session license tokens; it holds the signing key and license (bind-mounted read-only). The **single-user** container (built from `jupyter/base-notebook`) runs the session with the Positron Server binary + `jupyter-positron-server` proxy extension and holds no secrets. DockerSpawner launches single-user containers as siblings via the mounted docker socket on a shared named bridge network; they reach the verifier at `http://hub:<port>/services/positron-license/mint`.

**Tech Stack:** docker-compose, JupyterHub 5, DockerSpawner, jupyter-server-proxy, Positron Server, Python.

## Global Constraints

- All new files live under a new top-level `docker/` directory. **Do not modify** `scripts/install-positron.sh` or any existing file.
- Secrets (`license.lic`, `signing-key.pem`) are bind-mounted **read-only at runtime, never baked into image layers and never committed.** `docker/.gitignore` must exclude `.env` and `secrets/*` (except `.gitkeep`).
- **Positron Server arch representations differ across three places (verified against the CDN — do not "simplify" them to one value):**

  | `POSITRON_ARCH` | CDN path segment | download filename suffix | activation dir (`POSITRON_ACTIVATION_ARCH`) |
  |-----------------|------------------|--------------------------|---------------------------------------------|
  | `x64`           | `x86_64`         | `x64`                    | `x86_64`                                     |
  | `arm64`         | `arm64`          | `arm64`                  | `aarch64`                                    |

  Download URL: `https://cdn.posit.co/positron/releases/server/<CDN path segment>/positron-server-linux-<download suffix>-<POSITRON_VERSION>.tar.gz`
- **Defaults** (all overridable via `.env`): `POSITRON_VERSION=2026.07.0-365`, `POSITRON_ARCH=x64`, `POSITRON_ACTIVATION_ARCH=x86_64`, `VERIFIER_PORT=10101`, `HUB_PORT=8000`, `POSITRON_SERVER_PKG=jupyter-positron-server>=0.0.5`, `POSITRON_VERIFIER_PKG=jupyter-positron-verifier`, `HUB_IMAGE=jupyter-positron-hub:latest`, `SINGLEUSER_IMAGE=jupyter-positron-singleuser:latest`, `DOCKER_NETWORK=jupyter-positron`.
- Positron Server is unpacked to `/opt/positron-server` in both images.
- **Verification limitation (per project guidance + design):** a full `docker compose build`/`up` is NOT run in this environment. Each task's verification is a static check (`docker compose config`, `python3 -m ast`); the end-to-end build/run is verified manually by the user.

---

### Task 1: Config surface — `.env.example`, `.gitignore`, `secrets/.gitkeep`

Defines the env-var contract every other file references, plus the gitignore that keeps secrets out of git. Do this first so later tasks have concrete variable names.

**Files:**
- Create: `docker/.env.example`
- Create: `docker/.gitignore`
- Create: `docker/secrets/.gitkeep`

**Interfaces:**
- Produces: the variable names `POSITRON_VERSION`, `POSITRON_ARCH`, `POSITRON_ACTIVATION_ARCH`, `POSITRON_SERVER_PKG`, `POSITRON_VERIFIER_PKG`, `HUB_PORT`, `VERIFIER_PORT`, `HUB_IMAGE`, `SINGLEUSER_IMAGE`, `DOCKER_NETWORK` — consumed by Tasks 2–5.

- [ ] **Step 1: Write `docker/.env.example`**

```dotenv
# Copy this file to `.env` and adjust. docker compose reads `.env` automatically.

# ---------------------------------------------------------------------------
# Positron Server release
# ---------------------------------------------------------------------------
# POSITRON_ARCH is the download filename suffix. POSITRON_ACTIVATION_ARCH is the
# activation directory name (where license.lic + license-manager live) and
# differs from POSITRON_ARCH. Set the two as a matching pair:
#
#   x64   -> POSITRON_ARCH=x64    POSITRON_ACTIVATION_ARCH=x86_64
#   arm64 -> POSITRON_ARCH=arm64  POSITRON_ACTIVATION_ARCH=aarch64
#
POSITRON_VERSION=2026.07.0-365
POSITRON_ARCH=x64
POSITRON_ACTIVATION_ARCH=x86_64

# ---------------------------------------------------------------------------
# Python package specs (a PyPI spec, or git+https://...@branch for a dev build)
# ---------------------------------------------------------------------------
POSITRON_SERVER_PKG=jupyter-positron-server>=0.0.5
POSITRON_VERIFIER_PKG=jupyter-positron-verifier

# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
# HUB_PORT is published to the host. VERIFIER_PORT stays internal to the docker
# network (single-user containers reach the verifier at http://hub:VERIFIER_PORT).
HUB_PORT=8000
VERIFIER_PORT=10101

# ---------------------------------------------------------------------------
# Image tags and shared network
# ---------------------------------------------------------------------------
HUB_IMAGE=jupyter-positron-hub:latest
SINGLEUSER_IMAGE=jupyter-positron-singleuser:latest
DOCKER_NETWORK=jupyter-positron
```

- [ ] **Step 2: Write `docker/.gitignore`**

```gitignore
# Local env overrides and real secrets must never be committed.
.env
secrets/*
!secrets/.gitkeep
```

- [ ] **Step 3: Create empty `docker/secrets/.gitkeep`**

Create an empty file (0 bytes) so the otherwise-gitignored `secrets/` directory is tracked.

- [ ] **Step 4: Verify the example env parses and covers every variable**

Run:
```bash
set -a && . docker/.env.example && set +a && \
for v in POSITRON_VERSION POSITRON_ARCH POSITRON_ACTIVATION_ARCH POSITRON_SERVER_PKG \
         POSITRON_VERIFIER_PKG HUB_PORT VERIFIER_PORT HUB_IMAGE SINGLEUSER_IMAGE DOCKER_NETWORK; do
  printf '%-26s = %s\n' "$v" "${!v:?missing $v}"
done
```
Expected: prints all ten variables with their values, no "missing" error.

- [ ] **Step 5: Confirm secrets are ignored**

Run: `git check-ignore docker/.env docker/secrets/license.lic docker/secrets/signing-key.pem`
Expected: all three paths echoed back (they are ignored). `git check-ignore docker/secrets/.gitkeep` prints nothing (it is tracked).

- [ ] **Step 6: Commit**

```bash
git add docker/.env.example docker/.gitignore docker/secrets/.gitkeep
git commit -m "feat(docker): add config surface for docker-compose template"
```

---

### Task 2: Single-user image (`singleuser/Dockerfile`)

The per-session image: Positron Server binary + `jupyter-positron-server` proxy extension. Holds no secrets.

**Files:**
- Create: `docker/singleuser/Dockerfile`

**Interfaces:**
- Consumes (build args): `POSITRON_VERSION`, `POSITRON_ARCH`, `POSITRON_SERVER_PKG` (from Task 1's `.env`, wired in Task 5).
- Produces: an image with `positron-server` on `PATH` (via `ENV PATH`), `jupyter_server_proxy` enabled, and `jupyterhub-singleuser` available (from the base image) so DockerSpawner can launch it.

- [ ] **Step 1: Write `docker/singleuser/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# Single-user Positron session image. Holds NO secrets — it fetches a minted
# license token from the Hub at session start. Launched on demand by
# DockerSpawner, so it is built (Task 5 / README) but never run as a compose
# service.
ARG BASE_IMAGE=quay.io/jupyter/base-notebook:latest
FROM ${BASE_IMAGE}

ARG POSITRON_VERSION=2026.07.0-365
ARG POSITRON_ARCH=x64
ARG POSITRON_SERVER_PKG="jupyter-positron-server>=0.0.5"

ENV POSITRON_SERVER_DIR=/opt/positron-server

USER root

# curl for the tarball download (not guaranteed present in the base image).
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Positron Server binary. The CDN path segment differs from the download filename
# suffix (x64 -> x86_64, arm64 -> arm64); derive it here.
RUN set -eux; \
    case "${POSITRON_ARCH}" in \
      x64)   cdn_arch=x86_64 ;; \
      arm64) cdn_arch=arm64 ;; \
      *)     cdn_arch="${POSITRON_ARCH}" ;; \
    esac; \
    mkdir -p "${POSITRON_SERVER_DIR}"; \
    curl -fL "https://cdn.posit.co/positron/releases/server/${cdn_arch}/positron-server-linux-${POSITRON_ARCH}-${POSITRON_VERSION}.tar.gz" \
      -o /tmp/positron-server.tar.gz; \
    tar -xzf /tmp/positron-server.tar.gz -C "${POSITRON_SERVER_DIR}" --strip-components=1; \
    rm -f /tmp/positron-server.tar.gz

# Proxy extension + Positron launcher. jupyter-server-proxy is a dependency of
# jupyter-positron-server; enable it as a server extension so the launcher tile
# appears. (jupyterhub-singleuser, which DockerSpawner runs, ships with the
# base-notebook image and must be version-compatible with the hub's JupyterHub.)
RUN pip install --no-cache-dir "${POSITRON_SERVER_PKG}" && \
    jupyter server extension enable --sys-prefix jupyter_server_proxy

# positron-server on PATH for the session. DockerSpawner does NOT override PATH
# (that would drop the base image's conda PATH and break jupyterhub-singleuser),
# so setting it here in the image is how the binary becomes discoverable.
ENV PATH="${POSITRON_SERVER_DIR}/bin:${PATH}"

USER ${NB_UID}
```

- [ ] **Step 2: Verify the Dockerfile syntax parses**

Run: `docker compose -f docker/docker-compose.yml config >/dev/null` is deferred to Task 5. For now, sanity-check the arch derivation logic in isolation:
```bash
for a in x64 arm64; do
  case "$a" in x64) c=x86_64;; arm64) c=arm64;; esac
  code=$(curl -s -o /dev/null -I -w '%{http_code}' \
    "https://cdn.posit.co/positron/releases/server/${c}/positron-server-linux-${a}-2026.07.0-365.tar.gz")
  echo "$a -> $c : HTTP $code"
done
```
Expected: both print `HTTP 200` (the derived URLs resolve).

- [ ] **Step 3: Commit**

```bash
git add docker/singleuser/Dockerfile
git commit -m "feat(docker): add single-user Positron session image"
```

---

### Task 3: Hub image (`hub/Dockerfile`)

The privileged Hub image: JupyterHub + DockerSpawner + the verifier service, plus the Positron Server unpack so `license-manager` is present for entitlement checks.

**Files:**
- Create: `docker/hub/Dockerfile`

**Interfaces:**
- Consumes (build args): `POSITRON_VERSION`, `POSITRON_ARCH`, `POSITRON_VERIFIER_PKG`.
- Consumes (build context): `hub/jupyterhub_config.py` from Task 4 (COPYed in). **Task 4 must exist before this image builds**, but the Dockerfile can be authored first.
- Produces: an image whose default command runs `jupyterhub -f /srv/jupyterhub/jupyterhub_config.py`, with `positron-verifier` and `license-manager` on disk.

- [ ] **Step 1: Write `docker/hub/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# JupyterHub image (privileged). Runs JupyterHub + DockerSpawner and the
# jupyter-positron-verifier managed service that mints per-session license
# tokens. The signing key + license are bind-mounted at runtime (see
# docker-compose.yml), never baked in.
#
# Based on the official JupyterHub image, which already bundles JupyterHub,
# node, and configurable-http-proxy (the design's "Python image + CHP
# subprocess", provided ready-made).
ARG BASE_IMAGE=quay.io/jupyterhub/jupyterhub:5
FROM ${BASE_IMAGE}

ARG POSITRON_VERSION=2026.07.0-365
ARG POSITRON_ARCH=x64
ARG POSITRON_VERIFIER_PKG="jupyter-positron-verifier"

ENV POSITRON_SERVER_DIR=/opt/positron-server
ENV DEBIAN_FRONTEND=noninteractive

# curl for the tarball download.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# DockerSpawner (launches single-user containers via the docker socket) and the
# license minting service (provides the `positron-verifier` console script).
RUN pip install --no-cache-dir dockerspawner "${POSITRON_VERIFIER_PKG}"

# Positron Server — the hub needs license-manager (under the activation dir) to
# confirm entitlement against the mounted license.lic. Same CDN arch derivation
# as the single-user image (x64 -> x86_64, arm64 -> arm64).
RUN set -eux; \
    case "${POSITRON_ARCH}" in \
      x64)   cdn_arch=x86_64 ;; \
      arm64) cdn_arch=arm64 ;; \
      *)     cdn_arch="${POSITRON_ARCH}" ;; \
    esac; \
    mkdir -p "${POSITRON_SERVER_DIR}"; \
    curl -fL "https://cdn.posit.co/positron/releases/server/${cdn_arch}/positron-server-linux-${POSITRON_ARCH}-${POSITRON_VERSION}.tar.gz" \
      -o /tmp/positron-server.tar.gz; \
    tar -xzf /tmp/positron-server.tar.gz -C "${POSITRON_SERVER_DIR}" --strip-components=1; \
    rm -f /tmp/positron-server.tar.gz

COPY jupyterhub_config.py /srv/jupyterhub/jupyterhub_config.py
WORKDIR /srv/jupyterhub

EXPOSE 8000
CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
```

- [ ] **Step 2: Verify the base image tag exists on the registry**

Run: `curl -s -o /dev/null -w '%{http_code}\n' https://quay.io/v2/jupyterhub/jupyterhub/manifests/5`
Expected: `200` (auth-gated registries may return `401`; if so, note it and rely on the user's build to confirm). A `404` means the tag is wrong — fix it.

- [ ] **Step 3: Commit**

```bash
git add docker/hub/Dockerfile
git commit -m "feat(docker): add JupyterHub image with DockerSpawner + verifier"
```

---

### Task 4: Hub config (`hub/jupyterhub_config.py`)

The Docker analogue of the config `install-positron.sh` generates inline: the verifier service, its role, DockerSpawner wiring, spawner env, and the placeholder authenticator.

**Files:**
- Create: `docker/hub/jupyterhub_config.py`

**Interfaces:**
- Consumes (runtime env, set on the `hub` service in Task 5): `VERIFIER_PORT`, `SINGLEUSER_IMAGE`, `DOCKER_NETWORK`, `POSITRON_ACTIVATION_ARCH`; optionally `POSITRON_SERVER_DIR` (defaults to `/opt/positron-server`).
- Produces: a JupyterHub config that spawned containers rely on — the minting endpoint `http://hub:<VERIFIER_PORT>/services/positron-license/mint` injected into `c.DockerSpawner.environment`.

- [ ] **Step 1: Write `docker/hub/jupyterhub_config.py`**

```python
# JupyterHub config for the Positron docker-compose deployment template.
# The Docker analogue of the inline config generated by
# scripts/install-positron.sh. Values come from the environment (see .env /
# docker-compose.yml) so the same image works for any deployment.
import os

verifier_port = os.environ.get("VERIFIER_PORT", "10101")
singleuser_image = os.environ.get("SINGLEUSER_IMAGE", "jupyter-positron-singleuser:latest")
docker_network = os.environ.get("DOCKER_NETWORK", "jupyter-positron")
activation_arch = os.environ.get("POSITRON_ACTIVATION_ARCH", "x86_64")
positron_server_dir = os.environ.get("POSITRON_SERVER_DIR", "/opt/positron-server")

signing_key_file = "/etc/positron/signing-key.pem"
license_manager = f"{positron_server_dir}/resources/activation/linux/{activation_arch}/license-manager"
minting_endpoint = f"http://hub:{verifier_port}/services/positron-license/mint"

# --- 1. positron-license minting service ------------------------------------
# Runs in the Hub container, holds the signing key, mints per-session tokens.
# Bind on 0.0.0.0 (not 127.0.0.1 as in TLJH) so single-user containers on the
# docker network can reach it by the hub's service name.
c.JupyterHub.services = [
    {
        "name": "positron-license",
        "url": f"http://0.0.0.0:{verifier_port}",
        "command": ["positron-verifier"],
        "environment": {
            "POSITRON_MINTING_KEY_FILE": signing_key_file,
            "POSITRON_LICENSE_MANAGER_PATH": license_manager,
            "PORT": verifier_port,
        },
    }
]

c.JupyterHub.load_roles = [
    {
        "name": "positron-license-service",
        "services": ["positron-license"],
        "scopes": ["read:users"],
    }
]

# --- 2. DockerSpawner: launch single-user containers as siblings ------------
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = singleuser_image
c.DockerSpawner.network_name = docker_network
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.remove = True  # remove stopped single-user containers

# The Hub API must be reachable by the spawned containers: bind on all
# interfaces, and have containers connect back by the compose service name.
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = "hub"

# Session environment: only the minting endpoint. PATH is intentionally NOT set
# here — positron-server is already on PATH via the single-user image's ENV, and
# overriding PATH would drop the image's own entries.
c.DockerSpawner.environment = {
    "POSITRON_LICENSE_MINTING_ENDPOINT": minting_endpoint,
}

# --- 3. Authenticator -------------------------------------------------------
# !!! TEMPLATE PLACEHOLDER: DummyAuthenticator accepts ANY username with ANY
# !!! password. You MUST replace this with a real authenticator (OAuth, native,
# !!! LDAP, ...) before any non-local or real deployment.
c.JupyterHub.authenticator_class = "jupyterhub.auth.DummyAuthenticator"
```

- [ ] **Step 2: Verify the config is valid Python (static parse; it references the JupyterHub `c` global so it cannot be exec'd standalone)**

Run: `python3 -c "import ast; ast.parse(open('docker/hub/jupyterhub_config.py').read()); print('OK')"`
Expected: prints `OK` (no SyntaxError).

- [ ] **Step 3: Verify the derived license-manager path matches the compose mount target**

Run:
```bash
python3 - <<'PY'
arch = "x86_64"  # POSITRON_ACTIVATION_ARCH default
sd = "/opt/positron-server"
print(f"{sd}/resources/activation/linux/{arch}/license-manager")
print(f"{sd}/resources/activation/linux/{arch}/license.lic")
PY
```
Expected: the two paths share the `.../linux/x86_64/` directory — the same dir Task 5 mounts `license.lic` into. Confirm they agree.

- [ ] **Step 4: Commit**

```bash
git add docker/hub/jupyterhub_config.py
git commit -m "feat(docker): add JupyterHub config for DockerSpawner + verifier"
```

---

### Task 5: Compose stack (`docker-compose.yml`)

Wires the two images together: builds both, publishes the hub, mounts the docker socket and the read-only secrets, and defines the shared named network.

**Files:**
- Create: `docker/docker-compose.yml`

**Interfaces:**
- Consumes: all Task 1 variables; the two Dockerfiles (Tasks 2, 3); passes the Task 4 runtime env into the `hub` service.
- Produces: a stack where `docker compose up -d` runs only `hub`; `singleuser` is behind a `build-only` profile so it is built but not run.

- [ ] **Step 1: Write `docker/docker-compose.yml`**

```yaml
# Positron Server on JupyterHub — docker-compose deployment template.
#
# Before `up`: copy .env.example to .env, then drop license.lic and
# signing-key.pem into secrets/ (see README.md). The single-user image is built
# but never run here — DockerSpawner launches it on demand.

services:
  hub:
    build:
      context: ./hub
      args:
        POSITRON_VERSION: ${POSITRON_VERSION}
        POSITRON_ARCH: ${POSITRON_ARCH}
        POSITRON_VERIFIER_PKG: ${POSITRON_VERIFIER_PKG}
    image: ${HUB_IMAGE}
    hostname: hub
    restart: unless-stopped
    ports:
      - "${HUB_PORT}:8000"
    environment:
      VERIFIER_PORT: ${VERIFIER_PORT}
      SINGLEUSER_IMAGE: ${SINGLEUSER_IMAGE}
      DOCKER_NETWORK: ${DOCKER_NETWORK}
      POSITRON_ACTIVATION_ARCH: ${POSITRON_ACTIVATION_ARCH}
    volumes:
      # DockerSpawner launches single-user containers via the host docker daemon.
      - /var/run/docker.sock:/var/run/docker.sock
      # Secrets — mounted read-only, never baked into image layers. These files
      # must exist in ./secrets before `up` (see README).
      - ./secrets/signing-key.pem:/etc/positron/signing-key.pem:ro
      - ./secrets/license.lic:/opt/positron-server/resources/activation/linux/${POSITRON_ACTIVATION_ARCH}/license.lic:ro

  # Built by `docker compose build singleuser` (or with --profile build-only);
  # never started by `up`. DockerSpawner runs it on demand.
  singleuser:
    build:
      context: ./singleuser
      args:
        POSITRON_VERSION: ${POSITRON_VERSION}
        POSITRON_ARCH: ${POSITRON_ARCH}
        POSITRON_SERVER_PKG: ${POSITRON_SERVER_PKG}
    image: ${SINGLEUSER_IMAGE}
    profiles:
      - build-only

# Explicit name (no compose project prefix) so DockerSpawner's network_name
# matches and spawned containers can resolve the hub by service name.
networks:
  default:
    name: ${DOCKER_NETWORK}
```

- [ ] **Step 2: Verify compose parses and interpolates against the example env**

Run: `docker compose -f docker/docker-compose.yml --env-file docker/.env.example config`
Expected: prints the fully-resolved config with no errors; confirm the `license.lic` mount target reads `.../linux/x86_64/license.lic` and the hub port maps `8000:8000`.

- [ ] **Step 3: Verify the single-user service is excluded from `up` but buildable**

Run: `docker compose -f docker/docker-compose.yml --env-file docker/.env.example config --services`
Expected: lists `hub` only (the `build-only`-profiled `singleuser` is excluded from the default profile).
Then run: `docker compose -f docker/docker-compose.yml --env-file docker/.env.example --profile build-only config --services`
Expected: lists both `hub` and `singleuser`.

- [ ] **Step 4: Commit**

```bash
git add docker/docker-compose.yml
git commit -m "feat(docker): add docker-compose stack wiring hub + single-user"
```

---

### Task 6: Usage docs (`docker/README.md`)

Admin-facing usage, mirroring the header comment of `install-positron.sh`: what the stack is, prerequisites, the copy-secrets-and-build-and-up flow, the auth warning, and documented trade-offs/TODOs.

**Files:**
- Create: `docker/README.md`

**Interfaces:**
- Consumes: the commands and variable names established in Tasks 1–5.

- [ ] **Step 1: Write `docker/README.md`**

````markdown
# Positron Server on JupyterHub — docker-compose deployment template

The Docker-native counterpart to [`scripts/install-positron.sh`](../scripts/install-positron.sh)
(which targets The Littlest JupyterHub). This is a **deployment template**: a
starting point you copy and adapt for a real deployment, not a throwaway demo.

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

## How it works (token flow — unchanged from the TLJH install)

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

## Trade-offs & TODOs (out of scope for this template)

- Both images bake the full Positron Server tarball; the hub strictly needs only
  `license-manager`. Image-size optimization (multi-stage / shared base) is a
  documented TODO.
- No TLS/HTTPS termination — add a reverse proxy for production.
- No persistent volume for user home directories — add one as needed.
- The single-user image's bundled `jupyterhub-singleuser` must be version-
  compatible with the hub's JupyterHub. If you hit a mismatch, pin `jupyterhub`
  in `singleuser/Dockerfile`.
````

- [ ] **Step 2: Verify internal command/variable consistency**

Run: `grep -nE 'docker compose|POSITRON_|HUB_PORT|VERIFIER_PORT|DOCKER_NETWORK' docker/README.md`
Expected: every command matches Task 5's service names (`hub`, `singleuser`) and every variable name matches Task 1's `.env.example`. Eyeball for drift.

- [ ] **Step 3: Commit**

```bash
git add docker/README.md
git commit -m "docs(docker): add usage README for the compose template"
```

---

## Final integration verification (after all tasks)

These confirm the files agree with each other. The full build/run is verified
manually by the user (not in this environment).

- [ ] `docker compose -f docker/docker-compose.yml --env-file docker/.env.example config` renders with no error.
- [ ] The `license.lic` mount target dir (`.../linux/${POSITRON_ACTIVATION_ARCH}/`) equals the dir in `jupyterhub_config.py`'s `POSITRON_LICENSE_MANAGER_PATH`.
- [ ] `DOCKER_NETWORK` is identical in `.env.example`, the compose `networks.default.name`, and (via env) `c.DockerSpawner.network_name`.
- [ ] `git status` shows only new files under `docker/` plus this plan; no existing file modified.
- [ ] **Hand to user:** build both images, `up` the hub, log in, launch Positron, and confirm a licensed session starts.
