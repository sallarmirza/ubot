# app/db_manager.py
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")


class DBManager:
    def __init__(self):
        connect_args = (
            {"check_same_thread": False}
            if DB_URL and DB_URL.startswith("sqlite")
            else {}
        )
        self.engine = create_engine(DB_URL, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)

    def create_tables(self):
        import db_model

        db_model.Base.metadata.create_all(bind=self.engine)
        # create_all does not add columns to existing databases; keep this
        # additive migration so deployed comment tables gain author tracking.
        columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("comments")
        }
        if "author_channel_id" not in columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE comments ADD COLUMN author_channel_id VARCHAR(100)")
                )

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


db_manager = DBManager()