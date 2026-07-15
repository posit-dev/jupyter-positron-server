#!/usr/bin/env bash
#
# One-time install of Positron Server into an existing TLJH (The Littlest
# JupyterHub) deployment. Run this ONCE as the JupyterHub admin (root) on the
# TLJH host after TLJH itself has been bootstrapped.
#
# It:
#   1. Downloads and unpacks Positron Server (or uses a tarball you provide).
#   2. Installs the license next to the license-manager.
#   3. Installs the signing key that the Hub-side verifier uses to mint
#      short-lived, per-session license tokens.
#   4. Installs the user-facing extension (jupyter-positron-server) into the
#      TLJH *user* env and the minting service (jupyter-positron-verifier) into
#      the TLJH *hub* env.
#   5. Generates the JupyterHub config that registers the verifier service and
#      reloads TLJH.
#
# This script is self-contained: it needs no files other than your license and
# signing key, so it can be distributed on its own (e.g. from the
# jupyter-positron-server repo).
#
# Everything is configurable via the environment variables below; the defaults
# match a standard TLJH layout. Override any of them inline, e.g.:
#
#   sudo POSITRON_VERSION=2026.05.0-179 POSITRON_ARCH=arm64 \
#        LICENSE_SRC=./positron.lic SIGNING_KEY_SRC=./signing-key.pem \
#        ./install-positron-tljh.sh
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via environment; sensible defaults below)
# ---------------------------------------------------------------------------

# Which Positron Server release to install and for which CPU architecture.
POSITRON_VERSION="${POSITRON_VERSION:-2026.05.0-179}"
POSITRON_ARCH="${POSITRON_ARCH:-arm64}"          # arm64 | x64

# Where Positron Server is unpacked.
POSITRON_SERVER_DIR="${POSITRON_SERVER_DIR:-/opt/positron-server}"

# Provide a pre-downloaded tarball to skip the CDN download. If empty, the
# script downloads POSITRON_VERSION for POSITRON_ARCH from the Posit CDN.
POSITRON_TARBALL="${POSITRON_TARBALL:-}"

# Source files the admin supplies (defaults look in the current directory).
LICENSE_SRC="${LICENSE_SRC:-./positron.lic}"
SIGNING_KEY_SRC="${SIGNING_KEY_SRC:-./signing-key.pem}"

# Signing key destination (read only by the Hub-context verifier service).
SIGNING_KEY_DEST="${SIGNING_KEY_DEST:-/etc/positron/signing-key.pem}"

# TLJH layout: hub env, user env, and where jupyterhub_config.d lives.
TLJH_HUB_PIP="${TLJH_HUB_PIP:-/opt/tljh/hub/bin/pip}"
TLJH_USER_PIP="${TLJH_USER_PIP:-/opt/tljh/user/bin/pip}"
TLJH_USER_JUPYTER="${TLJH_USER_JUPYTER:-/opt/tljh/user/bin/jupyter}"
TLJH_CONFIG_D="${TLJH_CONFIG_D:-/opt/tljh/config/jupyterhub_config.d}"

# The verifier/minting service. VERIFIER_PORT is used for the service URL and
# the minting endpoint handed to user sessions.
VERIFIER_PORT="${VERIFIER_PORT:-10101}"

# JupyterHub config that registers the verifier service. Leave empty to have
# this script generate it inline (self-contained, no external files needed).
# Set POSITRON_CONFIG_SRC to a path to use your own config file instead.
POSITRON_CONFIG_SRC="${POSITRON_CONFIG_SRC:-}"
POSITRON_CONFIG_NAME="${POSITRON_CONFIG_NAME:-positron-license.py}"

# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------

# Positron spells the CPU arch three different ways, so a single POSITRON_ARCH
# is not enough:
#   * download filename infix -> POSITRON_ARCH   (x64    | arm64)
#   * CDN path segment        -> CDN_ARCH        (x86_64 | arm64)
#   * activation dir name      -> ACTIVATION_ARCH (x86_64 | aarch64)
# Derive the other two from POSITRON_ARCH (matching the docker/ template).
# Override CDN_ARCH/ACTIVATION_ARCH if your layout differs.
case "$POSITRON_ARCH" in
    arm64) CDN_ARCH="${CDN_ARCH:-arm64}";  ACTIVATION_ARCH="${ACTIVATION_ARCH:-aarch64}" ;;
    x64)   CDN_ARCH="${CDN_ARCH:-x86_64}"; ACTIVATION_ARCH="${ACTIVATION_ARCH:-x86_64}" ;;
    *)     CDN_ARCH="${CDN_ARCH:-$POSITRON_ARCH}"; ACTIVATION_ARCH="${ACTIVATION_ARCH:-$POSITRON_ARCH}" ;;
esac

ACTIVATION_DIR="$POSITRON_SERVER_DIR/resources/activation/linux/$ACTIVATION_ARCH"
LICENSE_DEST="$ACTIVATION_DIR/license.lic"
LICENSE_MANAGER="$ACTIVATION_DIR/license-manager"
CDN_URL="https://cdn.posit.co/positron/releases/server/${CDN_ARCH}/positron-server-linux-${POSITRON_ARCH}-${POSITRON_VERSION}.tar.gz"

# Bin dirs derived from the pip paths, used to locate positron-verifier and to
# build the spawner PATH.
TLJH_HUB_BIN="${TLJH_HUB_BIN:-$(dirname "$TLJH_HUB_PIP")}"
TLJH_USER_BIN="${TLJH_USER_BIN:-$(dirname "$TLJH_USER_PIP")}"
VERIFIER_CMD="${VERIFIER_CMD:-$TLJH_HUB_BIN/positron-verifier}"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Install Positron Server into an existing TLJH (The Littlest JupyterHub).

Usage:
  sudo [VAR=value ...] $(basename "$0")

Run once as the JupyterHub admin (root) on the TLJH host. All options are set
via environment variables; current values (defaults unless overridden) shown
in brackets.

Release:
  POSITRON_VERSION        Positron Server release to install [$POSITRON_VERSION]
  POSITRON_ARCH           CPU arch: arm64 | x64 [$POSITRON_ARCH]
  POSITRON_TARBALL        Local tarball to use instead of downloading [${POSITRON_TARBALL:-<download from CDN>}]

Admin-supplied files:
  LICENSE_SRC             Path to the license file [$LICENSE_SRC]
  SIGNING_KEY_SRC         Path to the RSA signing key [$SIGNING_KEY_SRC]

Install locations:
  POSITRON_SERVER_DIR     Where Positron Server is unpacked [$POSITRON_SERVER_DIR]
  SIGNING_KEY_DEST        Where the signing key is installed [$SIGNING_KEY_DEST]

TLJH layout:
  TLJH_HUB_PIP            pip in the TLJH hub env [$TLJH_HUB_PIP]
  TLJH_USER_PIP           pip in the TLJH user env [$TLJH_USER_PIP]
  TLJH_USER_JUPYTER       jupyter in the TLJH user env [$TLJH_USER_JUPYTER]
  TLJH_CONFIG_D           jupyterhub_config.d directory [$TLJH_CONFIG_D]

Verifier / minting service:
  VERIFIER_PORT           Port for the license minting service [$VERIFIER_PORT]
  VERIFIER_CMD            positron-verifier executable [$VERIFIER_CMD]

Packages (git URL @branch or PyPI spec):
  POSITRON_SERVER_PKG     User-facing extension [$POSITRON_SERVER_PKG]
  POSITRON_VERIFIER_PKG   Hub-side minting service [$POSITRON_VERIFIER_PKG]

JupyterHub config:
  POSITRON_CONFIG_SRC     Use this config file instead of generating one inline [${POSITRON_CONFIG_SRC:-<generate inline>}]
  POSITRON_CONFIG_NAME    Filename for the generated config [$POSITRON_CONFIG_NAME]

Options:
  -h, --help              Show this help and exit

Examples:
  sudo POSITRON_VERSION=$POSITRON_VERSION POSITRON_ARCH=arm64 \\
       LICENSE_SRC=./positron.lic SIGNING_KEY_SRC=./signing-key.pem \\
       $(basename "$0")

  # Use a pre-downloaded tarball and a dev build of the packages:
  sudo POSITRON_TARBALL=./positron-server.tar.gz \\
       POSITRON_SERVER_PKG='git+https://github.com/posit-dev/jupyter-positron-server@main' \\
       $(basename "$0")
EOF
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "")        ;;
    *)         die "Unknown argument: $1 (see --help)" ;;
esac

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

[ "$(id -u)" -eq 0 ] || die "Run as root (JupyterHub admin), e.g. via sudo."
[ -s "$LICENSE_SRC" ]      || die "License not found or empty: $LICENSE_SRC (set LICENSE_SRC; request one from academic-licenses@posit.co)"
[ -s "$SIGNING_KEY_SRC" ]  || die "Signing key not found or empty: $SIGNING_KEY_SRC (set SIGNING_KEY_SRC; request one from academic-licenses@posit.co)"
[ -z "$POSITRON_CONFIG_SRC" ] || [ -f "$POSITRON_CONFIG_SRC" ] || die "Config not found: $POSITRON_CONFIG_SRC (set POSITRON_CONFIG_SRC or leave empty to generate inline)"
[ -x "$TLJH_HUB_PIP" ]     || die "TLJH hub pip not found: $TLJH_HUB_PIP ‚Äî is TLJH installed?"
[ -x "$TLJH_USER_PIP" ]    || die "TLJH user pip not found: $TLJH_USER_PIP ‚Äî is TLJH installed?"

log "Installing Positron Server $POSITRON_VERSION ($POSITRON_ARCH) into TLJH"
echo "    server dir:    $POSITRON_SERVER_DIR"
echo "    license:       $LICENSE_SRC -> $LICENSE_DEST"
echo "    signing key:   $SIGNING_KEY_SRC -> $SIGNING_KEY_DEST"
echo "    hub env:       $TLJH_HUB_PIP"
echo "    user env:      $TLJH_USER_PIP"

# ---------------------------------------------------------------------------
# 1. Positron Server binary
# ---------------------------------------------------------------------------

log "Unpacking Positron Server into $POSITRON_SERVER_DIR"
mkdir -p "$POSITRON_SERVER_DIR"
if [ -n "$POSITRON_TARBALL" ]; then
    [ -f "$POSITRON_TARBALL" ] || die "POSITRON_TARBALL not found: $POSITRON_TARBALL"
    tarball="$POSITRON_TARBALL"
else
    tarball="$(mktemp /tmp/positron-server.XXXXXX.tar.gz)"
    trap 'rm -f "$tarball"' EXIT
    echo "    downloading $CDN_URL"
    curl -fL "$CDN_URL" -o "$tarball"
fi
tar -xzf "$tarball" -C "$POSITRON_SERVER_DIR" --strip-components=1

# ---------------------------------------------------------------------------
# 2. License (next to license-manager, root-only)
# ---------------------------------------------------------------------------

log "Installing license -> $LICENSE_DEST"
[ -d "$ACTIVATION_DIR" ] || die "Activation dir missing: $ACTIVATION_DIR (check POSITRON_ARCH/ACTIVATION_ARCH)"
install -m 600 "$LICENSE_SRC" "$LICENSE_DEST"

# ---------------------------------------------------------------------------
# 3. Signing key (Hub-only, used by the verifier to mint tokens)
# ---------------------------------------------------------------------------

log "Installing signing key -> $SIGNING_KEY_DEST"
mkdir -p "$(dirname "$SIGNING_KEY_DEST")"
install -m 600 "$SIGNING_KEY_SRC" "$SIGNING_KEY_DEST"

# ---------------------------------------------------------------------------
# 4. Python packages: user extension + hub minting service
# ---------------------------------------------------------------------------

log "Installing user extension ($POSITRON_SERVER_PKG) into the TLJH user env"
"$TLJH_USER_PIP" install "$POSITRON_SERVER_PKG"
"$TLJH_USER_JUPYTER" server extension enable --sys-prefix jupyter_server_proxy

log "Installing minting service ($POSITRON_VERIFIER_PKG) into the TLJH hub env"
"$TLJH_HUB_PIP" install "$POSITRON_VERIFIER_PKG"

# ---------------------------------------------------------------------------
# 5. JupyterHub config + reload
# ---------------------------------------------------------------------------

mkdir -p "$TLJH_CONFIG_D"
if [ -n "$POSITRON_CONFIG_SRC" ]; then
    log "Installing JupyterHub config from $POSITRON_CONFIG_SRC -> $TLJH_CONFIG_D/"
    install -m 644 "$POSITRON_CONFIG_SRC" "$TLJH_CONFIG_D/$(basename "$POSITRON_CONFIG_SRC")"
else
    config_dest="$TLJH_CONFIG_D/$POSITRON_CONFIG_NAME"
    log "Generating JupyterHub config -> $config_dest"
    # Registers the verifier as a Hub-managed service (runs as root, holds the
    # signing key, mints per-session tokens) and injects the minting endpoint
    # into user sessions. Generated inline so this script needs no other files.
    umask 022
    cat > "$config_dest" <<EOF
# Generated by install-positron-tljh.sh, do not edit by hand; re-run the
# installer (or edit the variables at the top of it) to change these values.
import os

c.JupyterHub.services = [
    {
        "name": "positron-license",
        "url": "http://127.0.0.1:${VERIFIER_PORT}",
        "command": ["${VERIFIER_CMD}"],
        "environment": {
            "POSITRON_MINTING_KEY_FILE": "${SIGNING_KEY_DEST}",
            "POSITRON_LICENSE_MANAGER_PATH": "${LICENSE_MANAGER}",
            "PORT": "${VERIFIER_PORT}",
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

# Spawner environment for user sessions, including the minting endpoint served
# by the positron-license service above.
path = os.environ.get("PATH", "/bin:/usr/bin")
c.SystemdSpawner.environment = {
    "PATH": f"${POSITRON_SERVER_DIR}/bin:/usr/local/bin:${TLJH_USER_BIN}:{path}",
    "POSITRON_LICENSE_MINTING_ENDPOINT": "http://127.0.0.1:${VERIFIER_PORT}/services/positron-license/mint",
}
EOF
fi

log "Reloading TLJH"
tljh-config reload

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

log "Positron Server installed."
echo "    License status:"
echo "      $LICENSE_MANAGER status"
echo "    Verify the verifier service is running:"
echo "      journalctl -u jupyterhub --no-pager | grep -i positron-license"
echo "    Users can now launch Positron from the JupyterLab launcher."
