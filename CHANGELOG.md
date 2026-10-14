# Releases

## 2.0.0

- Update database schema so that all datasets are associated with a visit ID.
- Handle day-end messages sent from Prompt Processing Butler Writer (by ignoring them.)
- Switch Postgres driver from `asyncpg` to `psycopg` 3 to align with `daf_butler`.
- Update all libraries to the latest versions.

## 1.0.0

Initial release.
