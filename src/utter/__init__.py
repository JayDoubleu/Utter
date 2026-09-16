"""Utter: GNOME voice dictation with on-device speech recognition."""

import gi

# Pin the GI namespace versions once so every module in the package imports the same ones.
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
