import json
from pathlib import Path


def test_consent_required_before_storage(web, tmp_path):
    main, client = web
    for data in ({}, {"terms_version": "old"}):
        response = client.post("/", data=data, files={"file": ("form.pdf", b"pdf")})
        assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []
    main.queue.enqueue.assert_not_called()


def test_random_links_consent_and_no_queued_secrets(web, monkeypatch):
    main, client = web
    monkeypatch.setenv("OPEN_AI__key", "secret-test-key")
    locations = []
    for _ in range(2):
        response = client.post("/", data={"terms_version": main.TERMS_VERSION}, files={"file": ("form.pdf", b"same pdf")}, follow_redirects=False)
        assert response.status_code == 303
        locations.append(response.headers["location"])
        args, kwargs = main.queue.enqueue.call_args
        assert "openai_creds" not in kwargs
        assert "secret-test-key" not in repr((args, kwargs))
        consent = json.loads((Path(args[1]) / "consent.json").read_text())
        assert consent["terms_version"] == main.TERMS_VERSION
        assert consent["accepted_at"]
    assert locations[0] != locations[1]


def test_policy_and_upload_render(web):
    _, client = web
    for path in ("/", "/terms", "/loading_animation", "/example_forms.html"):
        response = client.get(path)
        assert response.status_code == 200
    assert 'name="terms_version"' in client.get("/").text
    assert "no automatic file-deletion schedule" in client.get("/terms").text


def test_private_routes_suppress_caching_and_referrers(web):
    _, client = web
    response = client.get("/download/" + "f" * 64)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_worker_resolves_key_without_organization(web, monkeypatch, tmp_path):
    from unittest.mock import Mock
    main, _ = web
    monkeypatch.setenv("OPEN_AI__key", "worker-key")
    monkeypatch.delenv("OPEN_AI__org", raising=False)
    monkeypatch.setattr(main, "get_current_job", Mock(return_value=Mock(meta={})))
    monkeypatch.setattr(main, "has_fields", Mock(return_value=True))
    parse = Mock(return_value={"text": "example"})
    monkeypatch.setattr(main.formfyxer, "parse_form", parse)
    main.parse_form_job(str(tmp_path), "form.pdf")
    assert parse.call_args.kwargs["openai_creds"] == {"key": "worker-key", "org": None}
    assert json.loads((tmp_path / "stats.json").read_text()) == {"text": "example"}


def test_legacy_result_and_download_still_work(web, monkeypatch, tmp_path):
    from unittest.mock import Mock
    import pikepdf
    main, client = web
    old_id = "a" * 64
    folder = tmp_path / old_id
    folder.mkdir()
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(folder / "old.pdf")
    (folder / "stats.json").write_text("{}")
    monkeypatch.setattr(main.rq.job.Job, "fetch", Mock(side_effect=main.NoSuchJobError))
    assert client.get("/view/" + old_id).status_code == 200
    response = client.get("/download/" + old_id)
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
