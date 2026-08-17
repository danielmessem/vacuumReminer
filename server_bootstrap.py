#!/usr/bin/env python3
"""Stable entry point for the DEEBOT diagnostics add-on."""
import server_lab_v117 as app

# Keep one authoritative runtime entry point.  The add-on manifest owns the
# release version; this prevents an old laboratory module from being launched
# accidentally by the Docker image.
app.VERSION = "1.2.0"

if __name__ == "__main__":
    app.ThreadingHTTPServer(("0.0.0.0", app.PORT), app.H).serve_forever()
