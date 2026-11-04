"""Background loop: sends due posts, retries failures, and mirrors the schedule into Open WebUI."""

import logging
import threading
import time

from . import config, db, mirror, service, timeutil
from .wordpress import WpError

log = logging.getLogger("lich.worker")

status = {"last_tick_at": None, "last_sent_at": None, "last_error": None, "mirror_error": None, "mirror_at": None}


def _claim(post_id: str, now: int) -> bool:
    """Moves a due post to 'sending' so nobody can edit it mid-send. False if someone changed it first."""
    with db.tx() as conn:
        changed = conn.execute(
            "UPDATE posts SET state='sending', next_try_at=NULL, updated_at=? WHERE id=? AND archived_at IS NULL AND "
            "((state='scheduled' AND publish_at<=?) OR (state='sending' AND next_try_at IS NOT NULL AND next_try_at<=?))",
            (now, post_id, now, now),
        ).rowcount
    return changed == 1


def _fail(post_id: str, error: WpError, now: int) -> None:
    row = db.one("SELECT attempts, publish_at FROM posts WHERE id=?", (post_id,))
    attempts = row["attempts"] + 1
    too_late = now - (row["publish_at"] or now) > config.GIVE_UP_AFTER_SECONDS
    with db.tx() as conn:
        if error.permanent or too_late:
            conn.execute(
                "UPDATE posts SET state='failed', attempts=?, next_try_at=NULL, error=?, updated_at=? WHERE id=?",
                (attempts, error.message, now, post_id),
            )
            service._history(conn, post_id, "Máy chủ", "Lỗi, dừng gửi: " + error.message)
        else:
            delay = config.RETRY_DELAYS_SECONDS[min(attempts - 1, len(config.RETRY_DELAYS_SECONDS) - 1)]
            conn.execute(
                "UPDATE posts SET state='sending', attempts=?, next_try_at=?, error=?, updated_at=? WHERE id=?",
                (attempts, now + delay, error.message, now, post_id),
            )
            service._history(conn, post_id, "Máy chủ", f"Gửi lần {attempts} không được, thử lại sau {delay // 60} phút: {error.message}")


def dispatch_due() -> int:
    now = timeutil.now()
    due = db.query(
        "SELECT id FROM posts WHERE archived_at IS NULL AND ((state='scheduled' AND publish_at<=?) "
        "OR (state='sending' AND next_try_at IS NOT NULL AND next_try_at<=?)) ORDER BY publish_at",
        (now, now),
    )
    sent = 0
    for row in due:
        if not _claim(row["id"], now):
            continue
        try:
            service.send(row["id"])
            sent += 1
            status["last_sent_at"] = timeutil.now()
        except WpError as error:
            _fail(row["id"], error, timeutil.now())
        except Exception as error:  # noqa: BLE001 - one broken post must not stop the others
            log.exception("send failed for %s", row["id"])
            _fail(row["id"], WpError(f"Lỗi máy chủ Lịch đăng: {error}"), timeutil.now())
    return sent


def recover() -> None:
    """A post left in 'sending' with no retry time was interrupted by a restart: try it again now."""
    with db.tx() as conn:
        conn.execute("UPDATE posts SET next_try_at=? WHERE state='sending' AND next_try_at IS NULL", (timeutil.now(),))


def _loop(stop: threading.Event) -> None:
    recover()
    last_mirror = 0.0
    while not stop.is_set():
        try:
            dispatch_due()
            status["last_error"] = None
        except Exception as error:  # noqa: BLE001
            log.exception("dispatch loop")
            status["last_error"] = str(error)
        if time.monotonic() - last_mirror >= config.MIRROR_EVERY_SECONDS:
            last_mirror = time.monotonic()
            try:
                mirror.sync_all()
                status["mirror_error"] = None
                status["mirror_at"] = timeutil.now()
            except Exception as error:  # noqa: BLE001
                log.exception("calendar mirror")
                status["mirror_error"] = str(error)
        status["last_tick_at"] = timeutil.now()
        stop.wait(config.WORKER_TICK_SECONDS)


_started: list[threading.Event] = []


def start() -> threading.Event:
    """Once per process (Open WebUI runs one uvicorn worker, checked by __main__)."""
    if _started:
        return _started[0]
    stop = threading.Event()
    _started.append(stop)
    threading.Thread(target=_loop, args=(stop,), name="lich-worker", daemon=True).start()
    return stop
