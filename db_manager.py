# app/db_manager.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

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
        import db_model  # models register karne ke liye
        db_model.Base.metadata.create_all(bind=self.engine)
        migrations = {
            "target_video": {"prompt_context": "TEXT"},
            "comments": {
                "parent_comment_id": "INTEGER REFERENCES comments(comment_id)",
                "youtube_reply_id": "VARCHAR(100)",
                "reply_status": "VARCHAR(20) NOT NULL DEFAULT 'draft'",
                "reply_posting_started_at": "DATETIME",
            },
        }
        inspector = inspect(self.engine)
        with self.engine.begin() as connection:
            for table_name, columns in migrations.items():
                existing = {
                    column["name"] for column in inspector.get_columns(table_name)
                }
                for column_name, column_type in columns.items():
                    if column_name not in existing:
                        connection.execute(
                            text(
                                f"ALTER TABLE {table_name} "
                                f"ADD COLUMN {column_name} {column_type}"
                            )
                        )
            connection.execute(
                text(
                    "UPDATE comments SET reply_status = 'posted' "
                    "WHERE is_replied = 1 AND reply_status != 'posted'"
                )
            )

    def drop_tables(self):
        import db_model
        db_model.Base.metadata.drop_all(bind=self.engine)

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


db_manager = DBManager()
