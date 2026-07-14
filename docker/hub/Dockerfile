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
