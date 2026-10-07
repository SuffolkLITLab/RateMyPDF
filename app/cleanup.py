"""Remove expired upload directories; run at startup and Sundays at 03:00 UTC."""
import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import re
import shutil
import time

from redis import Redis
from rq.exceptions import NoSuchJobError
from rq.job import Job

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"finished", "failed", "stopped", "canceled"}


def cleanup(root: Path, connection, retention_days=7, dry_run=False, now=None):
    """Fail closed on Redis errors and retain active jobs, symlinks and unknown data."""
    if retention_days < 1:
        raise ValueError("Retention must be at least one day")
    connection.ping()
    cutoff = (time.time() if now is None else now) - retention_days * 86400
    deleted = 0
    for directory in root.iterdir():
        if not re.fullmatch(r"[a-fA-F0-9]{64}", directory.name):
            continue
        if directory.is_symlink() or not directory.is_dir():
            continue
        children = list(directory.iterdir())
        # Upload directories are flat. Never traverse linked or unfamiliar trees.
        if not children or any(child.is_symlink() or not child.is_file() for child in children):
            continue
        if max([directory.stat().st_mtime] + [child.stat().st_mtime for child in children]) >= cutoff:
            continue
        try:
            job = Job.fetch(directory.name, connection=connection)
        except NoSuchJobError:
            job = None
        if job is not None and job.get_status(refresh=True) not in TERMINAL_STATUSES:
            continue
        # Recognize modern uploads or legacy completed results. A known terminal
        # RQ job also identifies failed legacy uploads before its record expires.
        if job is None and not any(child.name in {"consent.json", "stats.json"} for child in children):
            continue
        logger.info("%s expired upload %s", "Would remove" if dry_run else "Removing", directory.name)
        if not dry_run:
            shutil.rmtree(directory)
        deleted += 1
    return deleted


def next_run(now):
    """Next Sunday at 03:00 UTC, strictly after now."""
    target = (now + timedelta(days=(6 - now.weekday()) % 7)).replace(hour=3, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=7)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/pdf-files"))
    parser.add_argument("--retention-days", type=int, default=int(os.getenv("UPLOAD_RETENTION_DAYS", "7")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    args = parser.parse_args()
    if args.retention_days < 1:
        parser.error("--retention-days must be positive")
    logging.basicConfig(level=logging.INFO)
    connection = Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), socket_connect_timeout=5, socket_timeout=5)
    while True:
        try:
            count = cleanup(args.root, connection, args.retention_days, args.dry_run)
            logger.info("Cleanup complete: %s eligible directories", count)
        except Exception:
            logger.exception("Cleanup failed; retained remaining files")
            if not args.schedule:
                raise
            # Retry a failed run in one hour instead of waiting another week.
            time.sleep(3600)
            continue
        if not args.schedule:
            return
        now = datetime.now(timezone.utc)
        scheduled = next_run(now)
        logger.info("Next cleanup: %s", scheduled.isoformat())
        time.sleep((scheduled - now).total_seconds())


if __name__ == "__main__":
    main()
