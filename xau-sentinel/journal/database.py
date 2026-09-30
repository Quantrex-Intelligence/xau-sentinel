"""PostgreSQL connection management for the trading journal (DEP-002).

Schema lives in journal/schema.py and is applied via Alembic migrations
(`alembic upgrade head`), never by this module -- there is no init_db()
here anymore. A pooled SQLAlchemy Engine is created once at import time;
get_connection() keeps its pre-DEP-002 name and context-manager shape so
every store module's `with get_connection() as conn: ... conn.commit()`
call site keeps working unchanged, now yielding a SQLAlchemy Connection
instead of a sqlite3.Connection.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine

import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)


@contextmanager
def get_connection():
    with engine.connect() as conn:
        yield conn
