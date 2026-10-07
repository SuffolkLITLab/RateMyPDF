# Local end-to-end load test

Run from the repository root. This stack uses isolated Redis and document storage,
no production credentials, no host Docker socket, and localhost ports 18080 (app)
and 18081 (API simulator). It
runs the real web app, RQ worker, FormFyxer and Gotenberg with the production
Compose worker/converter resource limits. It replaces only OpenAI HTTP responses with a local deterministic simulator
(default 50 ms per request). It does not simulate Lightsail CPU credits, real AI
output quality, or real third-party API latency/cost.

```sh
docker build -t ratemypdf-loadtest:stack .
docker compose -p ratemypdf-bench -f tests/load/compose.yml up -d
python -m venv /tmp/ratemypdf-bench-venv
/tmp/ratemypdf-bench-venv/bin/pip install httpx reportlab python-docx
/tmp/ratemypdf-bench-venv/bin/python tests/load/run.py --output /tmp/ratemypdf-baseline.json
/tmp/ratemypdf-bench-venv/bin/python tests/load/run.py --cases small,small,medium,word --concurrency 4 --output /tmp/ratemypdf-concurrent.json
docker compose -p ratemypdf-bench -f tests/load/compose.yml down
```

Wait for `/healthz` to return HTTP 200 before starting. Results include upload
latency, observed processing stages, total upload-to-render time, PDF download
validation, health latency samples and failures. The default sequential suite
covers fielded/unfielded PDFs, Word conversion, 10/50-page PDFs, exactly 20 MiB,
and an incident-sized 62 MiB rejection. Documents contain generated placeholder
text only. For concurrency sweeps pass a comma-separated `--cases` list and
`--concurrency`; the semaphore bounds in-flight upload-to-result sessions.

A successful result requires HTML rendering and a PDF download. No mocked parser
is used. Record failures as failures; API-dependent failures without credentials
are not successful performance measurements. Persist the JSON output with the
commit, dependency versions and host/resource configuration when comparing runs.
The queue-wait and service-time breakdown can be obtained from RQ job timestamps;
HTTP stage changes alone cannot separate those durations exactly.

The simulator is test-only, with dummy credentials and an internal base URL. To
change latency and reset its request counter:

```sh
curl -X POST http://127.0.0.1:18081/config -H 'Content-Type: application/json' -d '{"delay_seconds":1}'
```

The report records simulator latency and request count. A 1-second profile can
expose the cost of per-sentence API calls and exercise the hard worker timeout.
Do not run this harness against production. The default cases include intentionally
oversized uploads and expensive PDFs.

For one-logical-CPU contention, start Compose with both files:

```sh
docker compose -p ratemypdf-bench -f tests/load/compose.yml -f tests/load/single-cpu.yml up -d
```

This pins web, worker, Redis and Gotenberg to CPU 0, while the simulated remote
API remains outside that cpuset. It is not a full 2 GiB host/OS simulation.
`oversize_stream` sends an oversized multipart body without Content-Length to
exercise streamed-body enforcement, rather than just the header check.

Collect precise job service and queue times before the one-hour RQ TTL expires:

```sh
docker exec -i ratemypdf-bench-worker-1 python < tests/load/collect_jobs.py > /tmp/ratemypdf-jobs.json
```

## Recorded run: October 7, 2026

[Machine-readable results](results/2026-10-07.json) and
[installed packages](results/2026-10-07-packages.txt) capture the combined PR stack
plus the OpenCV compatibility fix. The original unconstrained image failed on
OpenCV 5 (`cv2.groupRectangles` removed); `<5` constraints restored field detection.
The first no-credentials run also confirmed FormFyxer requires an API key for
passive-voice analysis. Successful runs below used the local API simulator.

| Scenario | Outcome | Upload-to-result time | Health p95 |
| --- | --- | --- | --- |
| One-page fielded PDF, 50 ms API | Success | 15.2 s | Part of baseline |
| One-page unfielded PDF | Success | 22.1 s | Part of baseline |
| Word document | Success | 20.1 s | Part of baseline |
| 10-page PDF | Success | 62.2 s | Part of baseline |
| 50-page PDF | Failed at configured timeout; following upload succeeded | 180.7 s | Baseline: 6 ms |
| Exact 20 MiB PDF | Success | 34.8 s | Part of baseline |
| Four simultaneous 62 MiB uploads | All HTTP 413 | 134–217 ms | One probe only |
| Two chunked oversized uploads under worker load | Both HTTP 413 | 114–131 ms | One probe only |
| Four concurrent small PDFs, one CPU | 4/4 success | 15.9–48.2 s | 7 ms |
| Eight mixed uploads, one CPU | 7/8 success | 12.2–196.9 s for successes | 9 ms |
| Two follow-up Word uploads, one CPU | 2/2 success | 16.1 s each | See JSON |
| Small PDF, 1-second API, one CPU | Success, 40 API calls | 50.2 s | 4 ms |

The mixed-load failure was Gotenberg 7.10.2 returning HTTP 500 after LibreOffice
segfaulted, with no cgroup OOM event. Subsequent Word conversions recovered. This
remains an unresolved converter reliability finding, not a clean load-test pass.
No health probes failed, and no container restarts or OOM kills were observed.
Health latency did have a 1.75-second maximum in the four-client run despite low
p95. Observed peak memory was approximately 320 MiB web, 449 MiB worker and
159 MiB converter. A single worker serializes work: queue time can push total
latency past 180 seconds even though each job's execution is bounded separately.

Cleanup passed a real Redis/filesystem test: dry-run identified an expired
synthetic upload, execution deleted it while retaining an equally old queued
upload, and the scheduled service removed that second upload after its status
became terminal. It logged its next run as October 11 at 03:00 UTC. The complete
regression suite passed 31 tests. Cleanup's idle memory was 27 MiB.

The baseline used the production per-container caps on an 8-CPU, 15.4-GiB host;
concurrency and slow-API profiles pinned application services to one CPU. These
small synthetic samples are not a production capacity guarantee. They exclude
real API quotas/context errors, scanned PDFs, TLS, and Lightsail CPU credits.
Core upload/processing code was unchanged when cleanup was added; cleanup was
validated separately and was running during the slow-API test. All benchmark
containers were stopped afterward. No production settings or files were changed.
