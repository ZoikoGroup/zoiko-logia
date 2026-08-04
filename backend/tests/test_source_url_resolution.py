from app.domains.source_library.service import resolve_source_url


def test_external_source_url_is_preserved_for_click_through():
    url = "https://www.irs.gov/newsroom/tax-inflation-adjustments"

    assert resolve_source_url("src-irs", url) == url


def test_external_source_url_is_case_insensitive():
    url = "HTTPS://example.gov/source"

    assert resolve_source_url("src-gov", url) == url


def test_malformed_or_credentialed_external_url_is_not_exposed():
    assert resolve_source_url("src-bad", "https://") is None
    assert resolve_source_url("src-bad", "https://user:secret@example.gov/source") is None


def test_local_governed_document_uses_authenticated_file_endpoint():
    assert (
        resolve_source_url("src-upload", "data/uploads/tenant/report.pdf")
        == "/sources/src-upload/file"
    )


def test_missing_file_path_has_no_fabricated_link():
    assert resolve_source_url("src-empty", None) is None
