"""Run in the benchmark worker to collect RQ queue/service times and failures."""
import json
import redis
from rq.job import Job
from rq.exceptions import NoSuchJobError

connection = redis.from_url("redis://redis:6379/0")
records = []
for key in connection.scan_iter("rq:job:*"):
    job_id = key.decode().removeprefix("rq:job:")
    if ":" in job_id:
        continue
    try:
        job = Job.fetch(job_id, connection=connection)
    except NoSuchJobError:
        continue
    records.append({"id": job_id, "status": job.get_status(),
                    "queue_seconds": (job.started_at-job.enqueued_at).total_seconds() if job.started_at and job.enqueued_at else None,
                    "service_seconds": (job.ended_at-job.started_at).total_seconds() if job.ended_at and job.started_at else None,
                    "error": job.exc_info})
print(json.dumps(records, indent=2))
