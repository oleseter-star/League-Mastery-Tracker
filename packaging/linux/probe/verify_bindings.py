#!/usr/bin/env python3
"""Report raw GI binding versions without importing GTK overrides."""

import importlib
import importlib.metadata
import json
import platform


REQUIRED_NAMESPACES = (
    ("Gtk", "3.0"),
    ("GdkPixbuf", "2.0"),
    ("Gio", "2.0"),
    ("GLib", "2.0"),
)


def collect_binding_versions(
    import_module=importlib.import_module,
    distribution_version=importlib.metadata.version,
    python_version=platform.python_version,
    python_implementation=platform.python_implementation,
):
    """Load raw introspection modules without GTK override initialization."""

    gi = import_module("gi")
    for namespace, version in REQUIRED_NAMESPACES:
        gi.require_version(namespace, version)

    cairo = import_module("cairo")
    gi_module = import_module("gi.module")
    raw_modules = {
        namespace: gi_module.get_introspection_module(namespace)
        for namespace, _version in REQUIRED_NAMESPACES
    }
    gtk = raw_modules["Gtk"]
    gdk_pixbuf = raw_modules["GdkPixbuf"]
    glib = raw_modules["GLib"]

    return {
        "python": {
            "implementation": python_implementation(),
            "version": python_version(),
        },
        "bindings": {
            "PyGObject": distribution_version("PyGObject"),
            "pycairo": distribution_version("pycairo"),
        },
        "native": {
            "cairo": str(cairo.cairo_version_string()),
            "gdk_pixbuf": _version_from_constants(
                gdk_pixbuf,
                "PIXBUF_MAJOR",
                "PIXBUF_MINOR",
                "PIXBUF_MICRO",
            ),
            "glib": _version_from_constants(
                glib,
                "MAJOR_VERSION",
                "MINOR_VERSION",
                "MICRO_VERSION",
            ),
            "gtk": ".".join(
                str(value)
                for value in (
                    gtk.get_major_version(),
                    gtk.get_minor_version(),
                    gtk.get_micro_version(),
                )
            ),
        },
        "required_namespaces": {
            namespace: version
            for namespace, version in REQUIRED_NAMESPACES
        },
    }


def _version_from_constants(module, major, minor, micro):
    return ".".join(
        str(getattr(module, name))
        for name in (major, minor, micro)
    )


def main():
    report = collect_binding_versions()
    print(
        json.dumps(
            report,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
