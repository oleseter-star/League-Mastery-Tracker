#!/usr/bin/env bash
set -euo pipefail

readonly BUILD_PACKAGES=(
  build-essential
  fontconfig
  fonts-dejavu-core
  gobject-introspection
  libcairo2-dev
  libffi-dev
  libgdk-pixbuf2.0-bin
  libgirepository1.0-dev
  libglib2.0-bin
  libgtk-3-dev
  ninja-build
  pkg-config
)

readonly NATIVE_LAB_PACKAGES=(
  at-spi2-core
  binutils
  dbus-x11
  iproute2
  libcap2-bin
  openbox
  python3-pyatspi
  python3-xlib
  strace
  util-linux
  x11-utils
  xauth
  xfce4-panel
  xfconf
  xvfb
)

usage() {
  cat <<'EOF'
Usage:
  sudo bash packaging/linux/provision_tray_lab.sh \
    --disposable-builder --build
  sudo bash packaging/linux/provision_tray_lab.sh \
    --disposable-builder --native-lab

--build installs only G1 compiler and native development prerequisites.
--native-lab installs later X11/XFCE acceptance tools as well as --build.
This script does not provide CPython 3.12; pass that trusted interpreter to
run_tray_gates.sh. Run this script only in an explicitly disposable system.
EOF
}

main() {
  if [[ $# -ne 2 || $1 != "--disposable-builder" ]]; then
    usage >&2
    return 64
  fi
  if [[ $(id -u) -ne 0 ]]; then
    printf '%s\n' "Provisioning requires root in a disposable builder." >&2
    return 77
  fi
  case "$2" in
    --build)
      apt-get update
      apt-get install --no-install-recommends -y "${BUILD_PACKAGES[@]}"
      ;;
    --native-lab)
      apt-get update
      apt-get install --no-install-recommends -y \
        "${BUILD_PACKAGES[@]}" "${NATIVE_LAB_PACKAGES[@]}"
      ;;
    *)
      usage >&2
      return 64
      ;;
  esac
}

main "$@"
