from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(settings.dsn, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency.

    0.48.0 — Durci : rollback explicite si la requête échoue, pour
    qu'aucune session ne reste en ``idle in transaction`` côté PG même
    quand le client se déconnecte à chaud ou qu'une exception non
    attrapée remonte. ``close()`` seul rollbacke implicitement, mais
    ne couvre pas le cas où le pool recycle la connexion plus tard —
    le rollback explicite coupe toute ambiguïté.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            if db.in_transaction():
                db.rollback()
        except Exception:
            pass
        db.close()
