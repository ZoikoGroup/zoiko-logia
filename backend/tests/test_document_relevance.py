"""A follow-up uses only the chat files it is about (document_relevance.py)."""
from app.orchestration.document_relevance import documents_for_question
from app.orchestration.websearch import WebSource


def _file(name: str, sid: str, header: str) -> WebSource:
    return WebSource(title=f"{name} — Sheet1", url="", snippet=header + "\nrow\t1\t2", source_id=sid)


SALES = _file("kriton-test-sales-invoices.csv", "sales", "invoice_no\tinvoice_date\tcustomer\tnet_amount\tvat_amount\tstatus")
PAYROLL = _file("kriton-test-payroll-register.csv", "payroll", "employee_id\tdepartment\tgross_pay\tpaye\tnet_pay")
ASSETS = _file("kriton-test-fixed-assets.xlsx", "assets",
               "asset_id\tcategory\tcost\tuseful_life_years\taccumulated_depreciation\tnet_book_value")
CHAT = [SALES, PAYROLL, ASSETS]


def test_a_question_about_one_file_keeps_only_that_file():
    # Three files sent for this question went over the request-size limit.
    assert documents_for_question("Show the net book value of each asset category.", CHAT) == {"assets"}
    assert documents_for_question("Prepare the payroll journal entry for this month.", CHAT) == {"payroll"}
    assert documents_for_question("Which invoices are overdue?", CHAT) == {"sales"}


def test_every_file_is_kept_when_the_question_names_none_or_several_equally():
    assert documents_for_question("Summarise these documents.", CHAT) is None
    assert documents_for_question("Compare payroll cost with sales.", CHAT) is None
    assert documents_for_question("Show the net book value of each asset category.", [ASSETS]) is None


def test_a_misspelt_question_still_finds_its_file():
    assert documents_for_question("give me the different types of assests", CHAT) == {"assets"}
