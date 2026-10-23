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


VAT = WebSource(title="05_VAT_Return_Data_Northbridge_Q3.csv — Sheet1", url="",
                snippet="Date\tReference\tType\tCustomer/Supplier\tVAT treatment\tNet amount\tVAT amount\n"
                        "2026-07-03\tS-701\tSale\tHarbour Kitchens\tStandard 20%\t1000\t200", source_id="vat")


def test_a_follow_up_about_the_file_uses_it_and_an_unrelated_one_does_not():
    from app.orchestration.document_relevance import question_is_about_documents as about
    # About the file: by reference, by column or file name, or by a name in its rows.
    for question in ("Summarise the document", "Explain the above", "Analyse this", "Prepare the Q3 VAT return boxes 1 to 9",
                     "What is the total net amount for sales?", "What did Harbour Kitchens buy?", "Why?"):
        assert about(question, [VAT]), question
    # Not about the file: answered as a new question, the file kept for later.
    for question in ("What is IPR?", "Explain intellectual property rights", "Who won the cricket world cup?"):
        assert not about(question, [VAT]), question
