from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.app.config import DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# `check_same_thread` is required because stream workers write from their own
# threads; `timeout` makes those threads wait for the write lock instead of
# failing immediately with "database is locked".
connect_args = {"check_same_thread": False, "timeout": 15.0} if IS_SQLITE else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False
)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """
        Several stream workers plus the API write concurrently. In SQLite's
        default rollback-journal mode every writer blocks every reader, which
        under load surfaces as "database is locked" mid-pursuit. WAL lets reads
        proceed during writes.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import backend.app.models  # Ensure all models are registered
    Base.metadata.create_all(bind=engine)
