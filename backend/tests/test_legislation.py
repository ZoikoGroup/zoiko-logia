import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from app.orchestration.legislation import _query_target, fetch_legislation


def test_self_gate_requires_named_legislation():
    assert _query_target("How should depreciation be calculated?") is None
    assert _query_target("Explain the Companies Act 2006") == (
        "Companies Act", "2006", "/ukpga/2006/46"
    )


async def test_fetches_a_known_act_section_as_structured_source():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ukpga/2006/46/section/386/data.xml"
        return httpx.Response(200, text="""<?xml version="1.0"?>
          <Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
            <Metadata><Title>Companies Act 2006, section 386</Title></Metadata>
            <Body><P1><Pnumber>386</Pnumber><P1para>Every company must keep adequate accounting records.</P1para></P1></Body>
          </Legislation>""")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sources = await fetch_legislation("What does section 386 of the Companies Act 2006 require?", client=client)

    assert len(sources) == 1
    assert sources[0].provider == "legislation.gov.uk"
    assert sources[0].url.endswith("/ukpga/2006/46/section/386")
    assert "adequate accounting records" in sources[0].snippet


async def test_unknown_named_act_uses_official_atom_search():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Some Business Act 2024</title>
      <link href="https://www.legislation.gov.uk/ukpga/2024/99" />
    </entry></feed>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/all/data.feed"):
            assert request.url.params["title"] == "Some Business Act"
            assert request.url.params["year"] == "2024"
            return httpx.Response(200, text=feed)
        return httpx.Response(200, text="<Legislation><Title>Some Business Act 2024</Title><Body>Official text.</Body></Legislation>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sources = await fetch_legislation("What does the Some Business Act 2024 say?", client=client)

    assert sources and sources[0].url.endswith("/ukpga/2024/99")
