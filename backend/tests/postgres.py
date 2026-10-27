from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import make_url

CONNECT_TIMEOUT_S = 10


def fresh_database(server_uri: str) -> str:
    """Create an empty database on the test server and return its URI."""
    name = f"test_{uuid4().hex}"
    with psycopg.connect(
        server_uri, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S
    ) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return make_url(server_uri).set(database=name).render_as_string(hide_password=False)
