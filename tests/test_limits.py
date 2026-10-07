import asyncio
from unittest.mock import Mock

import limits
from starlette.exceptions import HTTPException


def test_oversize_file_does_not_enqueue(web, monkeypatch):
    main, client = web
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 4)
    response = client.post("/", data={"terms_version": main.TERMS_VERSION}, files={"file": ("big.pdf", b"12345")})
    assert response.status_code == 413
    main.queue.enqueue.assert_not_called()


def test_filename_and_timeout(web):
    main, client = web
    response = client.post("/", data={"terms_version": main.TERMS_VERSION}, files={"file": ("../../escape.pdf", b"pdf")}, follow_redirects=False)
    assert response.status_code == 303
    args, kwargs = main.queue.enqueue.call_args
    assert args[2] == "escape.pdf"
    assert kwargs["job_timeout"] == 180
    from pathlib import Path
    assert (Path(args[1]) / "escape.pdf").read_bytes() == b"pdf"


def test_request_length_rejected_before_parser(web, monkeypatch):
    main, client = web
    monkeypatch.setattr(limits, "MAX_REQUEST_BYTES", 4)
    assert client.post("/", content=b"12345").status_code == 413
    main.queue.enqueue.assert_not_called()


def test_chunked_body_limit(monkeypatch):
    monkeypatch.setattr(limits, "MAX_REQUEST_BYTES", 4)
    async def app(scope, receive, send):
        await receive()
        try:
            await receive()
        except HTTPException as exc:
            assert exc.status_code == 413
        else:
            raise AssertionError("unbounded stream")
    async def receive():
        return {"type": "http.request", "body": b"123", "more_body": True}
    asyncio.run(limits.UploadLimitMiddleware(app)({"type": "http", "method": "POST", "headers": []}, receive, None))


def test_missing_job_stops_polling(web, monkeypatch):
    main, client = web
    monkeypatch.setattr(main.rq.job.Job, "fetch", Mock(side_effect=main.NoSuchJobError))
    assert client.get("/job-status/" + "a" * 64).json()["status"] == "failed"
    assert client.get("/job-status/invalid").status_code == 400


def test_conversion_limit(web, monkeypatch, tmp_path):
    main, _ = web
    source = tmp_path / "input.docx"
    source.write_bytes(b"word")
    response = Mock(status_code=200)
    response.iter_content.return_value = [b"123", b"456"]
    monkeypatch.setattr(main.requests, "post", Mock(return_value=response))
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 4)
    import pytest
    with pytest.raises(ValueError, match="exceeds"):
        main.convert_word_to_pdf(str(source), str(tmp_path / "output.pdf"), "http://converter")
    response.close.assert_called_once()
    assert main.requests.post.call_args.kwargs["timeout"] == (5, 60)
