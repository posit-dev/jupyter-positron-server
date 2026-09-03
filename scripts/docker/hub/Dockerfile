# syntax=docker/dockerfile:1
# JupyterHub image. Runs JupyterHub + DockerSpawner, which launches single-user
# containers as siblings via the host docker socket (see docker-compose.yml).
#
# Holds no Positron-specific bits: positron-server and license.lic live only in
# the single-user image / its runtime mounts (see singleuser/Dockerfile and
# hub/jupyterhub_config.py).
#
# Based on the official JupyterHub image, which already bundles JupyterHub,
# node, and configurable-http-proxy.
ARG BASE_IMAGE=quay.io/jupyterhub/jupyterhub:5
FROM ${BASE_IMAGE}

# DockerSpawner launches single-user containers via the docker socket.
RUN pip install --no-cache-dir dockerspawner

COPY jupyterhub_config.py /srv/jupyterhub/jupyterhub_config.py
WORKDIR /srv/jupyterhub

EXPOSE 8000
CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
