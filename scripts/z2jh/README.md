# Positron Server on Zero to JupyterHub (Kubernetes)

A deployment template for [Zero to JupyterHub](https://z2jh.jupyter.org/) — the
official JupyterHub Helm chart, and what most universities running JupyterHub on
Kubernetes use. Copy and adapt it; it is a starting point, not a finished product.

The Kubernetes counterpart to [`../install-positron.sh`](../install-positron.sh)
(The Littlest JupyterHub) and [`../docker/`](../docker/) (single-host
docker-compose).

## What this deployment looks like

Everything Positron-related lives in the **single-user** image:

- **No custom hub image.** Nothing Positron-related runs on the Hub, so the
  chart's stock hub image is used unchanged. There is no `hub.image` override and
  no `hub.extraVolumes` anywhere in `values.yaml`.
- **The single-user image** carries the Positron Server binary and
  `jupyter-positron-server`, and holds no secrets.
- **The license** is a Kubernetes Secret mounted into the user pod at the path
  Positron expects.

## Prerequisites

- A Kubernetes cluster and Helm.
- A **license file** (`license.lic`) from Posit — email
  [academic-licenses@posit.co](mailto:academic-licenses@posit.co). See the project
  README for eligibility. That is the only file you need.
- A registry your cluster can pull from, or a local cluster you can load images
  into directly.

## Setup

**1. Build the single-user image.**

```bash
docker build -t positron-singleuser:v1 \
  --build-arg POSITRON_ARCH=x64 \
  -f Dockerfile.singleuser .
```

Use `POSITRON_ARCH=arm64` for arm64 nodes. Push it to your registry, or for a
local cluster:

```bash
kind load docker-image positron-singleuser:v1
```

**2. Set the architecture in `values.yaml`.** The `mountPath` under
`singleuser.extraFiles` contains the activation directory name, which must match
your nodes: `x86_64` for amd64, `aarch64` for arm64. See the warning below.

**3. Install the chart**, passing the license at install time so it never lands in
a values file or in git:

```bash
helm repo add jupyterhub https://hub.jupyter.org/helm-chart/ && helm repo update

helm upgrade --install positron jupyterhub/jupyterhub \
  --version 4.4.1 --namespace jupyterhub --create-namespace \
  --values values.yaml \
  --set-file 'singleuser.extraFiles.license\.lic.stringData'=./license.lic \
  --wait
```

**4. Reach the hub**, then log in and launch Positron from the JupyterLab launcher.

```bash
kubectl -n jupyterhub port-forward svc/proxy-public 8080:http
```

> [!WARNING]
> The chart's default authenticator is `DummyAuthenticator`, which accepts **any
> username and password**. Replace it before exposing the hub to anyone; see the
> commented block at the bottom of `values.yaml`.

## Verifying the install

Note that `license-manager status` **cannot** be used here. It requires root, and
user pods run as uid 1000 with no privilege escalation. Check the mount instead:

```bash
POD=$(kubectl -n jupyterhub get pod -l component=singleuser-server -o name | head -1)

# License present, and license-manager + the .so files still alongside it
kubectl -n jupyterhub exec $POD -c notebook -- \
  ls -l /opt/positron-server/resources/activation/linux/x86_64/

# The architecture the code actually resolves
kubectl -n jupyterhub exec $POD -c notebook -- \
  python3 -c "import platform; print(platform.machine())"

# Positron's own verdict
kubectl -n jupyterhub logs $POD -c notebook | grep -i "license verified"
```

A healthy directory listing keeps `license-manager`, `librclient.so`,
`librserver.so` and `license-manager.conf` next to `license.lic`. Ultimately the
real test is that Positron opens in the browser.

## Two things that are easy to get wrong

- **`subPath` is required.** The license must mount at the full *file* path.
  Mounting at the directory replaces it, so `license-manager` and the activation
  libraries disappear. `values.yaml` uses `singleuser.extraFiles`, which derives
  `subPath` for you; `values-secret-alternative.yaml` does not.
- **The activation directory must match your nodes** — `x86_64` on amd64,
  `aarch64` on arm64. Every tarball ships *both*, fully populated, so the wrong
  one looks completely normal on inspection. Mixed-architecture node pools cannot
  be served by a single `mountPath`; you would need per-architecture
  `singleuser.profileList` entries with node selectors.

Both fail with symptoms that point somewhere else. See
[Troubleshooting](https://posit-dev.github.io/jupyter-positron-server/troubleshooting.html#zero-to-jupyterhub-kubernetes-specifics) for what you actually see and how to diagnose it.

## Configuration reference

| Setting | Purpose |
|---|---|
| `singleuser.image.name` / `.tag` | Your built single-user image |
| `singleuser.extraFiles."license.lic".mountPath` | Where the license lands — **arch-specific** |
| `singleuser.extraFiles."license.lic".mode` | `0440`, unquoted so YAML reads it as octal |
| `singleuser.storage.type` | `dynamic` persists `$HOME`, so extensions bootstrap once |
| `singleuser.startTimeout` | Raised to 600; Positron images are large |
| `POSITRON_VERSION` (build arg) | Positron Server release |
| `POSITRON_ARCH` (build arg) | `x64` or `arm64` |
| `POSITRON_SERVER_PKG` (build arg) | Pinned to `jupyter-positron-server==0.0.6` |

## Versions

Targets Positron Server **2026.09.0-XX** and `jupyter-positron-server`
**0.0.6**, which read the license file directly from the activation directory.

The Kubernetes side of this template was developed and verified against z2jh
chart **4.4.1** (JupyterHub 5.5.1) on Kubernetes **v1.36.1**.
