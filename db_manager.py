# app/db_manager.py
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
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

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


db_manager = DBManager()