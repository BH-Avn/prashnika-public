"""Where the database is. Set QH_DB to a Postgres address, e.g. a standard Postgres address."""

import os

DSN = os.environ.get("QH_DB", "postgresql://postgres@localhost:5432/prashnika")
