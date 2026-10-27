from alembic import context
from sqlalchemy import Connection, text

# Two deploys that migrate at once queue here instead of racing on the same DDL; the lock is
# released when the migration transaction ends.
MIGRATION_LOCK = 8_008

connection: Connection = context.config.attributes["connection"]
connection.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": MIGRATION_LOCK})
context.configure(connection=connection)
with context.begin_transaction():
    context.run_migrations()
