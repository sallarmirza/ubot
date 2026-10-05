# app/db_manager.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

Base = declarative_base()


class DBManager:
    def __init__(self):
        self.engine = create_engine(
            DB_URL,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)

    def create_tables(self):
  # noqa: F401
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        Base.metadata.drop_all(bind=self.engine)

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


db_manager = DBManager()