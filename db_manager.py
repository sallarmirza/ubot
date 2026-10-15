# app/db_manager.py
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")


class DBManager:
    def __init__(self):
        if not DB_URL:
            raise RuntimeError("DATABASE_URL is not set (check your .env file)")

        database_url = DB_URL
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url.removeprefix(
                "postgres://"
            )
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise RuntimeError("DATABASE_URL must point to a PostgreSQL database")
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        elif url.drivername != "postgresql+psycopg":
            raise RuntimeError(
                "DATABASE_URL must use the psycopg PostgreSQL driver"
            )

        self.engine = create_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)

    def create_tables(self):
        """Create missing tables from the models.

        This does not migrate existing schemas. Use Alembic for schema changes.
        """
        import db_model

        db_model.Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """Drop every table. Destructive: only for development/testing."""
        import db_model

        db_model.Base.metadata.drop_all(bind=self.engine)

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def close(self):
        """Close all connections in the engine's pool."""
        self.engine.dispose()


db_manager = DBManager()