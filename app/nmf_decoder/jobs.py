"""Uses the existing single import worker and its advisory lock, never another worker."""
import time
from sqlalchemy import text
from .store import decode_capture
from .projection import refresh_projections

def process_next(db,stop_event=None):
    job=db.execute(text("SELECT * FROM nmf_decode_job WHERE status IN ('queued','running') ORDER BY created_at LIMIT 1")).mappings().first()
    if not job:return False
    jid=job['id'];start=time.perf_counter()
    db.execute(text("UPDATE nmf_decode_job SET status='running',updated_at=now() WHERE id=:id"),{'id':jid});db.commit()
    try:
        for i,cap in enumerate(job['capture_ids']):
            if stop_event is not None and stop_event.is_set():return True
            if i<job['done']:continue
            decode_capture(db,job['project_id'],cap,job['level'])
            db.execute(text('UPDATE nmf_decode_job SET done=:n,updated_at=now() WHERE id=:id'),{'id':jid,'n':i+1});db.commit()
        refresh_projections(db,job['project_id'])
        from app.services.task_run import populate_tasks
        populate_tasks(db,job['project_id'],captures=job['capture_ids'])
        db.execute(text("UPDATE nmf_decode_job SET status='done',updated_at=now(),elapsed_s=:s,error=NULL WHERE id=:id"),{'id':jid,'s':time.perf_counter()-start});db.commit()
    except Exception as exc:
        db.rollback()
        # Error type only: exceptions must never serialize source fields or identities.
        db.execute(text("UPDATE nmf_decode_job SET status='error',updated_at=now(),elapsed_s=:s,error=:error WHERE id=:id"),{'id':jid,'s':time.perf_counter()-start,'error':type(exc).__name__});db.commit()
        import logging;logging.getLogger(__name__).error('Decode job failed id=%s type=%s',jid,type(exc).__name__)
    return True
