from app.domains.documents.extract import Segment
from app.domains.documents.ingestion_agent import execute_plan, register_ocr_adapter


def test_native_text_skips_ocr():
    called = False
    def ocr(*_args):
        nonlocal called
        called = True
        return []
    register_ocr_adapter(ocr)
    try:
        outcome = execute_plan(b"A sufficiently detailed accounting document for native extraction.", ".txt")
        assert outcome.status == "ready"
        assert outcome.method == "native"
        assert not called
    finally:
        register_ocr_adapter(None)


def test_ocr_output_requires_review(monkeypatch):
    from app.domains.documents import ingestion_agent
    monkeypatch.setattr(ingestion_agent, "extract", lambda *_: (_ for _ in ()).throw(
        ingestion_agent.ExtractionError("scan needs OCR")
    ))
    register_ocr_adapter(lambda *_: [Segment(locator="page 1", text="Revenue 100")])
    try:
        outcome = execute_plan(b"pdf", ".pdf")
        assert outcome.status == "needs_review"
        assert outcome.method == "ocr"
        assert outcome.segments
        assert outcome.confidence < 0.8
    finally:
        register_ocr_adapter(None)


def test_celery_task_is_registered_without_file_bytes():
    from app.jobs.celery_app import celery_app
    import app.jobs.document_ingestion  # noqa: F401

    task = celery_app.tasks["documents.process"]
    assert task.name == "documents.process"
    # The durable task contract contains identifiers only. Original bytes are
    # loaded from private object storage by the worker.
    assert list(task.run.__annotations__)[:3] == ["document_id", "tenant_id", "user_id"]
