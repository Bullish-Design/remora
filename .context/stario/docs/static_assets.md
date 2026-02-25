
stario.dev
Staticassets
~2 minutes
Static Assets ¶

Stario serves static files with automatic fingerprinting, pre-compression, and immutable caching.
Quick Start ¶

from pathlib import Path
from stario import Stario, asset

app = Stario(tracer)
app.assets("/static", Path(__file__).parent / "static")

# In your HTML:
Link({"rel": "stylesheet", "href": f"/static/{asset('css/style.css')}"})
# Result: /static/css/style.abc123.css

How It Works ¶

    Fingerprinting: At startup, Stario hashes your files. The asset() helper returns filenames with these hashes (e.g., style.abc123.css).
    Cache Busting: When you change a file, its hash changes. The URL changes, forcing browsers and CDNs to fetch the new version.
    Immutable Caching: Fingerprinted files are served with Cache-Control: immutable, max-age=31536000, making them extremely fast for returning users.
    Pre-Compression: Stario pre-compresses files into .zst, .br, and .gz at startup to save CPU during requests.

Setup ¶

app.assets(url_prefix, directory_path)

Argument 	Description
url_prefix 	The base URL for assets (e.g., "/static").
directory_path 	Path object to the local directory.
The asset() Helper ¶

The asset() function is used to look up the fingerprinted name of a file relative to your assets directory.

from stario import asset

# Returns "js/app.d41d8c.js"
url = f"/static/{asset('js/app.js')}"

Security ¶

Stario protects against path traversal. Only files explicitly found in the asset directory at startup can be served.

Changing the world, one byte at a time
