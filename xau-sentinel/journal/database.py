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
from contextvars import ContextVar
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, future=True)

# Test-only override (see tests/conftest.py::temp_db): when set, every
# get_connection() call yields this same Connection instead of checking one
# out of the pool, so a whole test's writes live inside one transaction that
# the fixture rolls back at teardown. Never set outside tests.
_test_connection: ContextVar[Optional[Connection]] = ContextVar("_test_connection", default=None)


@contextmanager
def get_connection():
    override = _test_connection.get()
    if override is not None:
        # Wrap this call's unit of work in its own SAVEPOINT rather than
        # handing out the shared test connection bare: application code
        # calls conn.commit() itself on the success path (releasing this
        # SAVEPOINT), and on an exception that propagates out uncaught
        # (e.g. a test deliberately triggering an IntegrityError) we roll
        # back to the SAVEPOINT instead of poisoning the whole test's outer
        # transaction, so a later call in the same test can still read/write
        # normally. A read-only block that never calls commit() itself just
        # gets its SAVEPOINT released here on clean exit.
        nested = override.begin_nested()
        try:
            yield override
        except BaseException:
            if nested.is_active:
                nested.rollback()
            raise
        else:
            if nested.is_active:
                nested.commit()
        return
    with engine.connect() as conn:
        yield conn
