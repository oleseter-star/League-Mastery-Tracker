#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PROJECT_ROOT="$(cd -- "$SCRIPT_DIRECTORY/../.." && pwd -P)"
readonly BUILD_REQUIREMENTS="$PROJECT_ROOT/requirements-linux-tray-build.txt"
readonly BINDING_REQUIREMENTS="$PROJECT_ROOT/requirements-linux-tray.txt"
readonly BINDING_VERIFIER="$SCRIPT_DIRECTORY/probe/verify_bindings.py"
readonly PROVENANCE_COLLECTOR="$SCRIPT_DIRECTORY/capture_tray_provenance.py"
readonly PYCAIRO_PIN="1.26.1"
readonly PYGOBJECT_PIN="3.48.2"
readonly GCC_LINKER_SELECTOR="bfd"
readonly PYPI_INDEX_URL="https://pypi.org/simple"
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
readonly BUILD_DISTRIBUTIONS=(
  PyGObject
  altgraph
  meson
  meson-python
  packaging
  pip
  pycairo
  pyinstaller
  pyinstaller-hooks-contrib
  pyproject-metadata
  setuptools
  wheel
)

die() {
  printf '%s\n' "$1" >&2
  return "${2:-1}"
}

usage() {
  cat <<'EOF'
Usage:
  bash packaging/linux/run_tray_gates.sh G1 \
    --python /absolute/path/to/python3.12 \
    --work-root /absolute/new/directory

Only G1 is implemented in Slice 1A. The gate runner never installs operating
system packages. Provision a disposable builder explicitly and separately.
EOF
}

path_is_within() {
  [[ $1 == "$2" || $1 == "$2/"* ]]
}

validate_work_root() {
  local supplied=$1
  local resolved
  local root_bytes
  local project_venv
  local LC_ALL=C
  [[ $supplied == /* ]] || {
    die "The G1 work root must be absolute." 64
    return
  }
  # Preserve trailing newlines so unsupported names cannot be normalized away.
  resolved="$(realpath -m -- "$supplied" && printf '.')" || return
  resolved="${resolved%$'\n'.}"
  [[ $resolved != *[![:print:]]* ]] || {
    die "The canonical G1 work root must contain only printable ASCII characters." 64
    return
  }
  root_bytes="$(printf %s "$resolved" | LC_ALL=C wc -c)" || return
  [[ $root_bytes -le 128 ]] || {
    die "The G1 work root exceeds the 128-byte trace path limit." 64
    return
  }
  project_venv="$(realpath -m -- "$PROJECT_ROOT/.venv")" || return
  if path_is_within "$resolved" "$PROJECT_ROOT"; then
    die "The G1 work root must be outside the repository." 64
    return
  fi
  if path_is_within "$resolved" "$project_venv"; then
    die "The G1 work root must not use the project virtual environment." 64
    return
  fi
  [[ ! -e $resolved && ! -L $resolved ]] || {
    die "The G1 work root must be a new path." 64
    return
  }
  printf '%s\n' "$resolved"
}

verify_builder_platform() {
  local builder_id=""
  local builder_version=""
  local architecture
  local release
  [[ -r /etc/os-release ]] || {
    die "G1 requires readable Ubuntu release metadata."
    return
  }
  release="$(read_builder_release)" || return
  read -r builder_id builder_version <<<"$release" || return
  [[ $builder_id == ubuntu && $builder_version == 22.04 ]] || {
    die "G1 requires Ubuntu 22.04 exactly."
    return
  }
  architecture="$(builder_architecture)" || return
  [[ $architecture == x86_64 ]] || {
    die "G1 requires the x86-64 architecture."
    return
  }
}

read_builder_release() {
  (
    . /etc/os-release
    printf '%s %s\n' "${ID:-}" "${VERSION_ID:-}"
  )
}

builder_architecture() {
  uname -m
}

verify_interpreter() {
  local interpreter=$1
  [[ $interpreter == /* && -f $interpreter && -x $interpreter ]] || {
    die "G1 requires an explicit absolute executable interpreter path." 64
    return
  }
  "$interpreter" -I -S -B -c '
import pathlib
import platform
import sys
import sysconfig
if platform.python_implementation() != "CPython":
    raise SystemExit(1)
if sys.version_info[:2] != (3, 12):
    raise SystemExit(1)
header = pathlib.Path(sysconfig.get_path("include")) / "Python.h"
if not header.is_file():
    raise SystemExit(1)
' || {
    die "G1 requires CPython 3.12 with development headers."
    return
  }
  "$interpreter" -I -B -m pip --version >/dev/null 2>&1 || {
    die "The selected interpreter must provide pip for pinned downloads."
    return
  }
  "$interpreter" -I -B -m venv --help >/dev/null 2>&1 || {
    die "The selected interpreter must provide the venv module."
    return
  }
}

verify_build_prerequisites() {
  local command_name
  local package
  for command_name in cc dpkg-query ninja pkg-config realpath; do
    command -v "$command_name" >/dev/null || {
      die "A required G1 build command is unavailable: $command_name"
      return
    }
  done
  for package in "${BUILD_PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | \
      grep -qx 'install ok installed' || {
      die "A required G1 build package is unavailable: $package"
      return
    }
  done
  pkg-config --exists \
    'cairo >= 1.15.10' \
    'gdk-pixbuf-2.0' \
    'gobject-introspection-1.0 >= 1.64' \
    'glib-2.0 >= 2.64' \
    'gtk+-3.0 >= 3.24' || \
    {
      die "Required G1 native library versions are unavailable."
      return
    }
}

one_file_matching() {
  local directory=$1
  local pattern=$2
  local matches=()
  shopt -s nullglob
  matches=("$directory"/$pattern)
  shopt -u nullglob
  [[ ${#matches[@]} -eq 1 ]] || {
    die "G1 expected exactly one artifact matching $pattern."
    return
  }
  printf '%s\n' "${matches[0]}"
}

run_isolated_python() {
  local interpreter=$1
  shift
  "${ISOLATED_ENVIRONMENT[@]}" "$interpreter" "$@"
}

run_isolated_pip() {
  local interpreter=$1
  shift
  run_isolated_python "$interpreter" -I -B -m pip --isolated \
    --disable-pip-version-check --cache-dir "$G1_PIP_CACHE" "$@"
}

run_binding_pip() {
  local binding=$1
  local operation=$2
  local interpreter=$3
  shift 3
  "${ISOLATED_ENVIRONMENT[@]}" \
    "G1_BUILD_BINDING=$binding" "G1_BUILD_OPERATION=$operation" \
    "$interpreter" -I -B -m pip --isolated \
    --disable-pip-version-check --cache-dir "$G1_PIP_CACHE" "$@"
}

acquire_and_build_bindings() {
  local environment_python=$1
  local source_directory=$2
  local wheel_directory=$3
  local build_directory=$4

  run_binding_pip pycairo metadata "$environment_python" download \
    --no-build-isolation --no-deps --no-binary=:all: \
    --index-url "$PYPI_INDEX_URL" --dest "$source_directory" \
    "pycairo==$PYCAIRO_PIN" || return
  PYCAIRO_SOURCE_RESULT="$(
    one_file_matching "$source_directory" 'pycairo-*'
  )" || return
  record_build_phase pycairo start || return
  record_build_artifact pycairo source "$PYCAIRO_SOURCE_RESULT" || return
  run_binding_pip pycairo wheel "$environment_python" wheel \
    --no-build-isolation --no-deps --no-index \
    --wheel-dir "$wheel_directory" "$PYCAIRO_SOURCE_RESULT" || return
  PYCAIRO_WHEEL_RESULT="$(
    one_file_matching "$wheel_directory" 'pycairo-*.whl'
  )" || return
  record_build_artifact pycairo wheel "$PYCAIRO_WHEEL_RESULT" || return
  record_build_phase pycairo end || return
  run_binding_pip pycairo install "$environment_python" install \
    --no-index --no-deps "$PYCAIRO_WHEEL_RESULT" || return

  # pip may execute the PEP 517 backend while preparing source metadata.
  # PyGObject therefore cannot even be downloaded until pycairo is installed.
  run_binding_pip PyGObject metadata "$environment_python" download \
    --no-build-isolation --no-deps --no-binary=:all: \
    --index-url "$PYPI_INDEX_URL" --dest "$source_directory" \
    "PyGObject==$PYGOBJECT_PIN" || return
  PYGOBJECT_SOURCE_RESULT="$(
    one_file_matching "$source_directory" 'pygobject-*'
  )" || return
  record_build_phase PyGObject start || return
  record_build_artifact PyGObject source "$PYGOBJECT_SOURCE_RESULT" || return
  run_binding_pip PyGObject wheel "$environment_python" wheel \
    --no-build-isolation --no-deps --no-index \
    --config-settings="build-dir=$build_directory/pygobject" \
    --wheel-dir "$wheel_directory" "$PYGOBJECT_SOURCE_RESULT" || return
  PYGOBJECT_WHEEL_RESULT="$(
    one_file_matching "$wheel_directory" 'pygobject-*.whl'
  )" || return
  record_build_artifact PyGObject wheel "$PYGOBJECT_WHEEL_RESULT" || return
  record_build_phase PyGObject end || return
  run_binding_pip PyGObject install "$environment_python" install \
    --no-index --no-deps "$PYGOBJECT_WHEEL_RESULT" || return
}

canonical_tool() {
  local requested=$1
  local located
  if [[ $requested == /* ]]; then
    located=$requested
  elif [[ -x /usr/bin/$requested ]]; then
    located=/usr/bin/$requested
  elif [[ -x /bin/$requested ]]; then
    located=/bin/$requested
  else
    die "A selected G1 build tool is unavailable: $requested"
    return
  fi
  [[ -f $located && -x $located ]] || {
    die "A selected G1 build tool is unavailable: $requested"
    return
  }
  realpath -e -- "$located" || return
}

first_version_line() {
  local output
  output="$(
    "${ISOLATED_ENVIRONMENT[@]}" env LC_ALL=C "$@" 2>/dev/null
  )" || return
  [[ -n $output ]] || {
    die "A selected G1 build tool did not report a version."
    return
  }
  printf '%s\n' "${output%%$'\n'*}"
}

select_build_tools() {
  local environment_directory=$1
  local environment_bin="$environment_directory/bin"
  local ld_name

  G1_MESON_PATH="$(realpath -e -- "$environment_bin/meson")" || return
  G1_CC_PATH="$(canonical_tool /usr/bin/cc)" || return
  G1_NINJA_PATH="$(canonical_tool /usr/bin/ninja)" || return
  G1_PKG_CONFIG_PATH="$(canonical_tool /usr/bin/pkg-config)" || return
  ld_name="$(
    "${G1_BOOTSTRAP_ENVIRONMENT[@]}" \
      "$G1_CC_PATH" -print-prog-name="ld.$GCC_LINKER_SELECTOR"
  )" || return
  G1_LD_PATH="$(canonical_tool "$ld_name")" || return
  [[ $G1_MESON_PATH == "$environment_bin/"* ]] || {
    die "Pinned Meson did not resolve inside the dedicated environment."
    return
  }
  ISOLATED_ENVIRONMENT=(
    "${G1_BOOTSTRAP_ENVIRONMENT[@]}"
    "PATH=$environment_bin:/usr/bin:/bin"
    "MESON=$G1_MESON_PATH"
    "NINJA=$G1_NINJA_PATH"
    "CC=$G1_CC_PATH"
    "CC_LD=$GCC_LINKER_SELECTOR"
    "PKG_CONFIG=$G1_PKG_CONFIG_PATH"
  )
  G1_CC_VERSION="$(first_version_line "$G1_CC_PATH" --version)" || return
  G1_LD_VERSION="$(first_version_line "$G1_LD_PATH" --version)" || return
  G1_MESON_VERSION="$(
    first_version_line "$G1_MESON_PATH" --version
  )" || return
  G1_NINJA_VERSION="$(
    first_version_line "$G1_NINJA_PATH" --version
  )" || return
  G1_PKG_CONFIG_VERSION="$(
    first_version_line "$G1_PKG_CONFIG_PATH" --version
  )" || return
}

write_artifact_inventory() {
  local directory=$1
  local output=$2
  local partial="$output.partial"
  find "$directory" -maxdepth 1 -type f -print0 | sort -z >"$partial" || return
  mv -- "$partial" "$output" || return
}

write_tool_proxy() {
  local proxy=$1
  local label=$2
  local target_variable=$3
  write_python_proxy "$proxy" "$label" "$target_variable" || return
  chmod 700 "$proxy" || return
}

write_python_proxy() {
  local proxy=$1
  local label=$2
  local target_variable=$3
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'exec "${G1_PROXY_PYTHON:-%s}" -I -B %q --proxy %q %q "$0" "$@"\n' \
      /usr/bin/python3 "$PROVENANCE_COLLECTOR" "$label" "$target_variable"
  } >"$proxy" || return
}

write_compiler_proxy() {
  local proxy=$1
  write_python_proxy "$proxy" cc G1_REAL_CC || return
  chmod 700 "$proxy" || return
}

write_linker_proxy() {
  local proxy=$1
  write_python_proxy "$proxy" ld G1_REAL_CC_LD || return
  chmod 700 "$proxy" || return
}

record_build_phase() {
  printf 'phase|%s|%s\n' "$1" "$2" >>"$G1_TOOL_TRACE"
}

record_build_artifact() {
  local binding=$1
  local kind=$2
  local filename=${3##*/}
  [[ $binding == pycairo || $binding == PyGObject ]] || return 96
  [[ $kind == source || $kind == wheel ]] || return 96
  [[ -n $filename && $filename != *'|'* && $filename != *$'\n'* ]] || return 96
  printf 'artifact|%s|%s|%s\n' \
    "$binding" "$kind" "$filename" >>"$G1_TOOL_TRACE"
}

configure_traced_build_tools() {
  local proxy_directory=$1
  local trace_file=$2
  mkdir -m 700 -- "$proxy_directory" || return
  : >"$trace_file" || return
  mkdir -m 700 -- "$trace_file.pending" || return
  G1_TOOL_TRACE=$trace_file
  write_compiler_proxy "$proxy_directory/cc" || return
  write_linker_proxy \
    "$proxy_directory/ld.$GCC_LINKER_SELECTOR" || return
  write_tool_proxy "$proxy_directory/meson" meson G1_REAL_MESON || return
  write_tool_proxy "$proxy_directory/ninja" ninja G1_REAL_NINJA || return
  write_tool_proxy \
    "$proxy_directory/pkg-config" pkg-config G1_REAL_PKG_CONFIG || return
  [[ $(realpath -e -- "$G1_CC_PATH") != \
    $(realpath -e -- "$proxy_directory/cc") ]] || return 96
  [[ $(realpath -e -- "$G1_LD_PATH") != \
    $(realpath -e -- "$proxy_directory/ld.$GCC_LINKER_SELECTOR") ]] || return 96
  [[ $(realpath -e -- "$G1_MESON_PATH") != \
    $(realpath -e -- "$proxy_directory/meson") ]] || return 96
  [[ $(realpath -e -- "$G1_NINJA_PATH") != \
    $(realpath -e -- "$proxy_directory/ninja") ]] || return 96
  [[ $(realpath -e -- "$G1_PKG_CONFIG_PATH") != \
    $(realpath -e -- "$proxy_directory/pkg-config") ]] || return 96
  local discovered_linker
  discovered_linker="$(
    "${G1_BOOTSTRAP_ENVIRONMENT[@]}" "$G1_CC_PATH" \
      "-B$proxy_directory/" "-fuse-ld=$GCC_LINKER_SELECTOR" \
      -print-prog-name="ld.$GCC_LINKER_SELECTOR"
  )" || return
  G1_LINKER_DISCOVERY="$(realpath -e -- "$discovered_linker")" || return
  [[ $G1_LINKER_DISCOVERY == \
    "$(realpath -e -- "$proxy_directory/ld.$GCC_LINKER_SELECTOR")" ]] || {
    die "The compiler driver did not select the controlled linker proxy."
    return
  }
  ISOLATED_ENVIRONMENT=(
    "${G1_BOOTSTRAP_ENVIRONMENT[@]}"
    "PATH=$proxy_directory:/usr/bin:/bin"
    "MESON=$proxy_directory/meson"
    "NINJA=$proxy_directory/ninja"
    "CC=$proxy_directory/cc"
    "CC_LD=$GCC_LINKER_SELECTOR"
    "PKG_CONFIG=$proxy_directory/pkg-config"
    "G1_REAL_CC=$G1_CC_PATH"
    "G1_REAL_CC_LD=$G1_LD_PATH"
    "G1_REAL_MESON=$G1_MESON_PATH"
    "G1_REAL_NINJA=$G1_NINJA_PATH"
    "G1_REAL_PKG_CONFIG=$G1_PKG_CONFIG_PATH"
    "G1_LINKER_PROXY_DIRECTORY=$proxy_directory"
    "G1_LINKER_SELECTOR=$GCC_LINKER_SELECTOR"
    "G1_TOOL_TRACE=$trace_file"
    "G1_PROXY_PYTHON=${G1_PROXY_PYTHON:-/usr/bin/python3}"
  )
}

verify_compiler_driver_linker() {
  local fixture_directory=$1
  local proxy_directory=$2
  local source="$fixture_directory/driver-check.c"
  local object="$fixture_directory/driver-check.o"
  local shared="$fixture_directory/driver-check.so"
  mkdir -m 700 -- "$fixture_directory" || return
  printf '%s\n' 'int lmt_driver_check(void) { return 0; }' >"$source" || return
  record_build_phase driver-check start || return
  "${ISOLATED_ENVIRONMENT[@]}" \
    G1_BUILD_BINDING=driver-check G1_BUILD_OPERATION=driver-check \
    "$proxy_directory/cc" -fPIC -c "$source" -o "$object" || return
  "${ISOLATED_ENVIRONMENT[@]}" \
    G1_BUILD_BINDING=driver-check G1_BUILD_OPERATION=driver-check \
    "$proxy_directory/cc" -shared "$object" -o "$shared" || return
  [[ -f $object && -f $shared ]] || {
    die "The compiler-driver linker check did not create its outputs."
    return
  }
  record_build_phase driver-check end || return
}

run_g1() {
  local interpreter=$1
  local supplied_work_root=$2
  local work_root
  local environment_directory
  local environment_python
  local toolchain_directory
  local source_directory
  local wheel_directory
  local report_directory
  local build_directory
  local proxy_directory
  local tool_trace
  local artifact_inventory
  local interpreter_identity
  local pycairo_source
  local pygobject_source
  local pycairo_wheel
  local pygobject_wheel
  local package
  local package_version
  local toolchain_artifact
  local cc_path
  local ld_path
  local meson_path
  local ninja_path
  local pkg_config_path
  local cc_version
  local ld_version
  local meson_version
  local ninja_version
  local pkg_config_version
  local provenance_arguments=()

  work_root="$(validate_work_root "$supplied_work_root")" || return
  verify_builder_platform || return
  verify_interpreter "$interpreter" || return
  verify_build_prerequisites || return
  interpreter_identity="$(realpath -e -- "$interpreter")" || return

  mkdir -m 700 -- "$work_root" || return
  environment_directory="$work_root/build-environment"
  toolchain_directory="$work_root/toolchain"
  source_directory="$work_root/sources"
  wheel_directory="$work_root/wheels"
  report_directory="$work_root/reports"
  build_directory="$work_root/build"
  proxy_directory="$work_root/tool-proxies"
  tool_trace="$work_root/tmp/build-tool-trace.txt"
  artifact_inventory="$work_root/tmp/toolchain-artifacts.list"
  mkdir -m 700 -- "$toolchain_directory" "$source_directory" \
    "$wheel_directory" "$report_directory" "$build_directory" \
    "$work_root/home" \
    "$work_root/tmp" "$work_root/xdg-cache" "$work_root/xdg-config" \
    "$work_root/xdg-data" "$work_root/pip-cache" || return

  G1_PIP_CACHE="$work_root/pip-cache"
  G1_BOOTSTRAP_ENVIRONMENT=(
    env -u MESON -u NINJA -u CC -u CC_LD -u CC_LD_FOR_BUILD \
    -u CXX -u CXX_LD -u CXX_LD_FOR_BUILD -u AR \
    -u AS -u LD -u NM -u OBJCOPY -u OBJDUMP -u RANLIB -u READELF \
    -u STRINGS -u STRIP -u PKG_CONFIG -u PKG_CONFIG_FOR_BUILD \
    -u PKG_CONFIG_PATH -u PKG_CONFIG_PATH_FOR_BUILD \
    -u PKG_CONFIG_LIBDIR -u PKG_CONFIG_LIBDIR_FOR_BUILD \
    -u PKG_CONFIG_SYSROOT_DIR -u PKG_CONFIG_SYSROOT_DIR_FOR_BUILD \
    -u CFLAGS -u CPPFLAGS -u CXXFLAGS -u LDFLAGS -u PYTHONHOME \
    -u CPP -u LDSHARED -u LDCXXSHARED -u BLDSHARED \
    -u G1_BUILD_BINDING -u G1_BUILD_OPERATION -u G1_DRIVER_OPERATION_ID \
    -u G1_LINKER_PROXY_DIRECTORY -u G1_LINKER_SELECTOR \
    -u G1_REAL_CC -u G1_REAL_CC_LD -u G1_REAL_MESON \
    -u G1_REAL_NINJA -u G1_REAL_PKG_CONFIG -u G1_TOOL_TRACE \
    -u PYTHONPATH -u _PYTHON_HOST_PLATFORM -u ARCHFLAGS -u VIRTUAL_ENV \
    -u CONDA_PREFIX -u CPATH -u C_INCLUDE_PATH -u CPLUS_INCLUDE_PATH \
    -u LIBRARY_PATH -u LD_LIBRARY_PATH -u LD_RUN_PATH -u GCC_EXEC_PREFIX \
    -u GCC_SPECS -u COMPILER_PATH -u GI_TYPELIB_PATH -u GTK_PATH \
    -u GTK_EXE_PREFIX -u GTK_DATA_PREFIX -u GDK_BACKEND -u DISPLAY \
    -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY
    "HOME=$work_root/home"
    "TMPDIR=$work_root/tmp"
    "XDG_CACHE_HOME=$work_root/xdg-cache"
    "XDG_CONFIG_HOME=$work_root/xdg-config"
    "XDG_DATA_HOME=$work_root/xdg-data"
    PIP_CONFIG_FILE=/dev/null
    PYTHONDONTWRITEBYTECODE=1
    PIP_NO_BUILD_ISOLATION=1
  )
  ISOLATED_ENVIRONMENT=("${G1_BOOTSTRAP_ENVIRONMENT[@]}")

  run_isolated_pip "$interpreter" download \
    --no-deps \
    --only-binary=:all: \
    --index-url "$PYPI_INDEX_URL" \
    --dest "$toolchain_directory" \
    --requirement "$BUILD_REQUIREMENTS" || return

  run_isolated_python "$interpreter" -I -B -m venv \
    "$environment_directory" || return
  environment_python="$environment_directory/bin/python"
  run_isolated_pip "$environment_python" install \
    --no-index \
    --no-deps \
    --find-links "$toolchain_directory" \
    --requirement "$BUILD_REQUIREMENTS" || return

  select_build_tools "$environment_directory" || return
  G1_PROXY_PYTHON=$environment_python
  cc_path=$G1_CC_PATH
  ld_path=$G1_LD_PATH
  meson_path=$G1_MESON_PATH
  ninja_path=$G1_NINJA_PATH
  pkg_config_path=$G1_PKG_CONFIG_PATH
  cc_version=$G1_CC_VERSION
  ld_version=$G1_LD_VERSION
  meson_version=$G1_MESON_VERSION
  ninja_version=$G1_NINJA_VERSION
  pkg_config_version=$G1_PKG_CONFIG_VERSION

  configure_traced_build_tools "$proxy_directory" "$tool_trace" || return
  verify_compiler_driver_linker \
    "$work_root/tmp/driver-check" "$proxy_directory" || return

  acquire_and_build_bindings \
    "$environment_python" "$source_directory" "$wheel_directory" \
    "$build_directory" || return
  pycairo_source=$PYCAIRO_SOURCE_RESULT
  pygobject_source=$PYGOBJECT_SOURCE_RESULT
  pycairo_wheel=$PYCAIRO_WHEEL_RESULT
  pygobject_wheel=$PYGOBJECT_WHEEL_RESULT

  "${ISOLATED_ENVIRONMENT[@]}" "$G1_MESON_PATH" introspect --compilers \
    "$build_directory/pygobject" \
    >"$report_directory/pygobject-compilers.json" || return

  run_isolated_python "$environment_python" -I -B \
    "$BINDING_VERIFIER" \
    >"$report_directory/binding-versions.json" || return

  provenance_arguments=(
    --output "$report_directory/provenance.json"
    --interpreter "$interpreter_identity"
    --interpreter-invocation "$interpreter"
    --verification "$report_directory/binding-versions.json"
    --requirements "$BUILD_REQUIREMENTS"
    --requirements "$BINDING_REQUIREMENTS"
    --source "pycairo=$pycairo_source"
    --source "PyGObject=$pygobject_source"
    --source-url "pycairo=https://pypi.org/project/pycairo/1.26.1/"
    --source-url "PyGObject=https://pypi.org/project/PyGObject/3.48.2/"
    --wheel "pycairo=$pycairo_wheel"
    --wheel "PyGObject=$pygobject_wheel"
    --builder-os ubuntu-22.04
    --architecture x86_64
    --native-archive-provenance unavailable
    --tool-trace "$tool_trace"
    --compiler-evidence \
      "PyGObject=$report_directory/pygobject-compilers.json"
    --build-tool "cc=$cc_path"
    --build-tool "ld=$ld_path"
    --build-tool "meson=$meson_path"
    --build-tool "ninja=$ninja_path"
    --build-tool "pkg-config=$pkg_config_path"
    --build-tool-version "cc=$cc_version"
    --build-tool-version "ld=$ld_version"
    --build-tool-version "meson=$meson_version"
    --build-tool-version "ninja=$ninja_version"
    --build-tool-version "pkg-config=$pkg_config_version"
    --tool-proxy "cc=$proxy_directory/cc"
    --tool-proxy "ld=$proxy_directory/ld.$GCC_LINKER_SELECTOR"
    --tool-proxy "meson=$proxy_directory/meson"
    --tool-proxy "ninja=$proxy_directory/ninja"
    --tool-proxy "pkg-config=$proxy_directory/pkg-config"
    --linker-selector "$GCC_LINKER_SELECTOR"
    --linker-discovery "$G1_LINKER_DISCOVERY"
  )
  for package in "${BUILD_DISTRIBUTIONS[@]}"; do
    provenance_arguments+=(--distribution "$package")
  done
  write_artifact_inventory "$toolchain_directory" "$artifact_inventory" || return
  while IFS= read -r -d '' toolchain_artifact; do
    provenance_arguments+=(--toolchain-artifact "$toolchain_artifact")
  done <"$artifact_inventory"
  for package in "${BUILD_PACKAGES[@]}"; do
    package_version="$(dpkg-query -W -f='${Version}' "$package")" || return
    [[ -n $package_version ]] || {
      die "Required native package provenance is unavailable: $package"
      return
    }
    provenance_arguments+=(--native-package "$package=$package_version")
  done
  run_isolated_python "$environment_python" -I -B \
    "$PROVENANCE_COLLECTOR" \
    "${provenance_arguments[@]}" || return

  printf '%s\n' "G1 passed. Evidence: $report_directory/provenance.json"
}

main() {
  local gate="${1:-}"
  local interpreter=""
  local work_root=""
  [[ -n $gate ]] || {
    usage >&2
    return 64
  }
  shift
  case "$gate" in
    G1) ;;
    G2|G3|G4|G5|G6|G7)
      die "$gate is not implemented in Slice 1A." 78
      return
      ;;
    *)
      usage >&2
      return 64
      ;;
  esac
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --python)
        [[ $# -ge 2 ]] || {
          die "--python requires a value." 64
          return
        }
        interpreter=$2
        shift 2
        ;;
      --work-root)
        [[ $# -ge 2 ]] || {
          die "--work-root requires a value." 64
          return
        }
        work_root=$2
        shift 2
        ;;
      *)
        die "Unknown G1 argument: $1" 64
        return
        ;;
    esac
  done
  [[ -n $interpreter && -n $work_root ]] || {
    usage >&2
    return 64
  }
  run_g1 "$interpreter" "$work_root" || return
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi
