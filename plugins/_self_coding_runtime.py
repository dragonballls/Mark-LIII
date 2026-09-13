"""Private implementation for the self-coding plugin.

The loader ignores underscore-prefixed plugin files, so this module keeps the
existing self-coding runtime out of the user-facing plugin list while preserving
all of its current behavior.
"""
