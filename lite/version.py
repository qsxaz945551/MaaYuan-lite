"""Single source of truth for the program version.

`app.py` exposes it through /api/meta, `apply_scope.py` stamps it into the
generated interface, and the release builder reads it for the folder name.
"""

VERSION = "0.3.8"
API_VERSION = 2
