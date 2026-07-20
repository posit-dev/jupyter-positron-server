# syntax=docker/dockerfile:1
# Single-user Positron session image. Holds NO secrets — it fetches a minted
# license token from the Hub at session start. Launched on demand by
# DockerSpawner, so it is built (see README) but never run as a compose service.
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
