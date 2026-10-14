# app/db_manager.py
# PostgreSQL engine, session factory, table creation and the get_db dependency.
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")


class DBManager:
    def __init__(self):
        if not DB_URL:
            raise RuntimeError("DATABASE_URL is not set (check your .env file)")

        self.engine = create_engine(
            DB_URL,
            pool_size=10,        # connections kept open in the pool
            max_overflow=20,     # extra connections allowed under load
            pool_pre_ping=True,  # test a connection before use, drops stale ones
            pool_recycle=1800,   # recycle connections after 30 minutes
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)

    def create_tables(self):
        """Create all tables from the models (skips tables that already exist).

        The old SQLite ALTER TABLE migrations are gone: on a fresh Postgres
        database create_all builds the final schema, including every column
        that used to be added by hand. Use Alembic for future schema changes.
        """
        import db_model  # imported here so the models register on Base

        db_model.Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """Drop every table. Destructive: only for development/testing."""
        import db_model

        db_model.Base.metadata.drop_all(bind=self.engine)

    # FastAPI dependency: one session per request, always closed afterwards
    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # close all connections on shutdown
    def close(self):
        self.engine.dispose()


db_manager = DBManager()