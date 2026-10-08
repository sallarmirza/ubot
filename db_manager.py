# app/db_manager.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event,inspect,text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

Base = declarative_base()

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")


class DBManager:
    def __init__(self):
        is_sqlite = bool(DB_URL and DB_URL.startswith("sqlite"))

        connect_args = (
            # check_same_thread: SQLAlchemy shares connections across threads
            # timeout:           wait up to 30s before raising "database is locked"
            {"check_same_thread": False, "timeout": 30}
            if is_sqlite
            else {}
        )

        self.engine = create_engine(DB_URL, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)

        if is_sqlite:
            self._enable_sqlite_wal()

    def _enable_sqlite_wal(self):
        """Turn on WAL mode so readers don't block writers and vice-versa.

        Without this, SQLite allows either one writer OR many readers. If a
        slow endpoint (e.g. one calling YouTube for 20 seconds) holds a write
        transaction, any concurrent read fails instantly with "database is
        locked". WAL mode lets readers and the writer coexist.
        """
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds
            cursor.close()

    def create_tables(self):
        import db_model  # models register karne ke liye
        db_model.Base.metadata.create_all(bind=self.engine)
        migrations = {
            "target_video": {"prompt_context": "TEXT"},
            "comments": {
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