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


STATEMENT = WebSource(title="NB-STATEMENTS_RELEASED.pdf — Page 1", url="",
                      snippet="FY2025 Revenue\n10,000\nFY2025 NET INCOME\n900\nNote 2. Q4 revenue\n3,100", source_id="nb")


def test_a_question_with_its_own_new_amount_is_not_answered_from_the_file():
    from app.orchestration.document_relevance import question_is_about_documents as about
    # Asked after attaching a statement PDF: an invented quarterly allocation,
    # and "insufficient evidence" for a textbook journal entry.
    assert not about("When should my company recognize this $2 million contract revenue?", [STATEMENT])
    assert not about("Show the initial journal entry for a $12,000 invoice issued on credit for earned consulting "
                     "services, assuming no tax.", [STATEMENT])
    # The file's own figures, a reference to it, or no amount at all keep it.
    assert about("Why was revenue 10,000 in FY2025?", [STATEMENT])
    assert about("Explain the Q4 revenue of $3,100k", [STATEMENT])
    assert about("From this file, what if revenue were $12,000?", [STATEMENT])
    assert about("What were the top 5 revenue lines?", [STATEMENT])
