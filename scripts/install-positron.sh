#!/usr/bin/env bash
#
# One-time install of Positron Server into an existing TLJH (The Littlest
# JupyterHub) deployment. Run this ONCE as the JupyterHub admin (root) on the
# TLJH host after TLJH itself has been bootstrapped.
#
# It:
#   1. Downloads and unpacks Positron Server (or uses a tarball you provide).
#   2. Installs the license next to the license-manager, mode 644 so each
#      session can read and validate it as the student.
#   3. Installs the user-facing extension (jupyter-positron-server) into the
#      TLJH *user* env.
#   4. Generates the JupyterHub config that puts positron-server on the
#      session PATH, and reloads TLJH.
#
# This script is self-contained: it needs no file other than your license, so
# it can be distributed on its own (e.g. from the jupyter-positron-server
# repo).
#
# Everything is configurable via the environment variables below; the defaults
# match a standard TLJH layout. Override any of them inline, e.g.:
#
#   sudo POSITRON_VERSION=2026.09.0-256 POSITRON_ARCH=arm64 \
#        LICENSE_SRC=./license.lic \
#        ./install-positron.sh
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via environment; sensible defaults below)
# ---------------------------------------------------------------------------

# Which Positron Server release to install and for which CPU architecture.
POSITRON_VERSION="${POSITRON_VERSION:-2026.09.0-256}"
POSITRON_ARCH="${POSITRON_ARCH:-arm64}"          # arm64 | x64

# Where Positron Server is unpacked.
POSITRON_SERVER_DIR="${POSITRON_SERVER_DIR:-/opt/positron-server}"

# Provide a pre-downloaded tarball to skip the CDN download. If empty, the
# script downloads POSITRON_VERSION for POSITRON_ARCH from the Posit CDN.
POSITRON_TARBALL="${POSITRON_TARBALL:-}"

# Source file the admin supplies (default looks in the current directory).
LICENSE_SRC="${LICENSE_SRC:-./license.lic}"

# jupyter-positron-server spec: a PyPI spec, or git+https://...@branch.
POSITRON_SERVER_PKG="${POSITRON_SERVER_PKG:-jupyter-positron-server>=0.0.5}"

# TLJH layout: user env, and where jupyterhub_config.d lives.
TLJH_USER_PIP="${TLJH_USER_PIP:-/opt/tljh/user/bin/pip}"
TLJH_USER_JUPYTER="${TLJH_USER_JUPYTER:-/opt/tljh/user/bin/jupyter}"
TLJH_CONFIG_D="${TLJH_CONFIG_D:-/opt/tljh/config/jupyterhub_config.d}"

# JupyterHub config that puts positron-server on the session PATH. Leave empty
# to have this script generate it inline (self-contained, no external files
# needed). Set POSITRON_CONFIG_SRC to a path to use your own config file
# instead.
POSITRON_CONFIG_SRC="${POSITRON_CONFIG_SRC:-}"
POSITRON_CONFIG_NAME="${POSITRON_CONFIG_NAME:-positron.py}"

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

# Bin dir derived from the pip path, used to build the spawner PATH.
TLJH_USER_BIN="${TLJH_USER_BIN:-$(dirname "$TLJH_USER_PIP")}"

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

Admin-supplied file:
  LICENSE_SRC             Path to the license file [$LICENSE_SRC]

Install locations:
  POSITRON_SERVER_DIR     Where Positron Server is unpacked [$POSITRON_SERVER_DIR]

TLJH layout:
  TLJH_USER_PIP           pip in the TLJH user env [$TLJH_USER_PIP]
  TLJH_USER_JUPYTER       jupyter in the TLJH user env [$TLJH_USER_JUPYTER]
  TLJH_CONFIG_D           jupyterhub_config.d directory [$TLJH_CONFIG_D]

Packages (git URL @branch or PyPI spec):
  POSITRON_SERVER_PKG     User-facing extension [$POSITRON_SERVER_PKG]

JupyterHub config:
  POSITRON_CONFIG_SRC     Use this config file instead of generating one inline [${POSITRON_CONFIG_SRC:-<generate inline>}]
  POSITRON_CONFIG_NAME    Filename for the generated config [$POSITRON_CONFIG_NAME]

Options:
  -h, --help              Show this help and exit

Examples:
  sudo POSITRON_VERSION=$POSITRON_VERSION POSITRON_ARCH=arm64 \\
       LICENSE_SRC=./license.lic \\
       $(basename "$0")

  # Use a pre-downloaded tarball and a dev build of the package:
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
[ -z "$POSITRON_CONFIG_SRC" ] || [ -f "$POSITRON_CONFIG_SRC" ] || die "Config not found: $POSITRON_CONFIG_SRC (set POSITRON_CONFIG_SRC or leave empty to generate inline)"
[ -x "$TLJH_USER_PIP" ]    || die "TLJH user pip not found: $TLJH_USER_PIP -- is TLJH installed?"

log "Installing Positron Server $POSITRON_VERSION ($POSITRON_ARCH) into TLJH"
echo "    server dir:    $POSITRON_SERVER_DIR"
echo "    license:       $LICENSE_SRC -> $LICENSE_DEST"
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
# 2. License (next to license-manager, mode 644 -- each session reads it as
#    the student, not as root)
# ---------------------------------------------------------------------------

log "Installing license -> $LICENSE_DEST"
[ -d "$ACTIVATION_DIR" ] || die "Activation dir missing: $ACTIVATION_DIR (check POSITRON_ARCH/ACTIVATION_ARCH)"
install -m 644 "$LICENSE_SRC" "$LICENSE_DEST"

# ---------------------------------------------------------------------------
# 3. Python package: user extension
# ---------------------------------------------------------------------------

log "Installing user extension ($POSITRON_SERVER_PKG) into the TLJH user env"
"$TLJH_USER_PIP" install "$POSITRON_SERVER_PKG"
"$TLJH_USER_JUPYTER" server extension enable --sys-prefix jupyter_server_proxy

# ---------------------------------------------------------------------------
# 4. JupyterHub config + reload
# ---------------------------------------------------------------------------

mkdir -p "$TLJH_CONFIG_D"
if [ -n "$POSITRON_CONFIG_SRC" ]; then
    log "Installing JupyterHub config from $POSITRON_CONFIG_SRC -> $TLJH_CONFIG_D/"
    install -m 644 "$POSITRON_CONFIG_SRC" "$TLJH_CONFIG_D/$(basename "$POSITRON_CONFIG_SRC")"
else
    config_dest="$TLJH_CONFIG_D/$POSITRON_CONFIG_NAME"
    log "Generating JupyterHub config -> $config_dest"
    # Puts positron-server on the session PATH. No license environment
    # variable is needed: positron-server finds and validates license.lic in
    # its own activation directory. Generated inline so this script needs no
    # other files.
    umask 022
    cat > "$config_dest" <<EOF
# Generated by install-positron.sh, do not edit by hand; re-run the installer
# (or edit the variables at the top of it) to change these values.
import os

path = os.environ.get("PATH", "/bin:/usr/bin")
c.SystemdSpawner.environment = {
    "PATH": f"${POSITRON_SERVER_DIR}/bin:/usr/local/bin:${TLJH_USER_BIN}:{path}",
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
echo "    Users can now launch Positron from the JupyterLab launcher."
