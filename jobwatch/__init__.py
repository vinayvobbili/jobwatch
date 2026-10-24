"""jobwatch: watch company job boards and get a ranked digest of new matches."""

__version__ = "0.6.0"

# The local page's own name, so it doesn't read as just "localhost" beside other local apps. Every *.localhost
# name reaches this machine without setup (macOS resolves them, as do browsers), and never the web.
APP_HOST = "jobwatch.localhost"

# The guide (docs/guide in the repo): where messages send people for the details.
GUIDE = "https://github.com/vinayvobbili/jobwatch/blob/main/docs/guide"
