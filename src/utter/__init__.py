"""Utter: GNOME voice dictation with on-device speech recognition."""

try:
    import gi
except ImportError:  # plain test environments without PyGObject import the pure modules only
    gi = None

if gi is not None:
    # Pin the GI namespace versions once so every module in the package imports the same ones.
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("Gst", "1.0")
