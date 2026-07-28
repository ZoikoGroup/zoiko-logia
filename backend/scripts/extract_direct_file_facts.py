"""
Trial extractor for IRS Direct File's Fact Dictionary (a declarative XML
rules schema encoding real US tax law — see
https://github.com/IRS-Public/direct-file, direct-file/backend/src/main/
resources/tax/*.xml). Each <Fact> has a human-readable <Name> and often a
<Description>; everything else (Derived/Dependency/etc.) is business-rule
logic, not reference prose, and is intentionally not extracted.

This is a standalone trial — it does not write to the database or register
anything in source_library. It just proves out extraction quality on one
topic file before deciding whether to expand to the other 14+.

Usage:
    python3 scripts/extract_direct_file_facts.py <path-to-topic.xml>
"""
import re
import sys
import xml.etree.ElementTree as ET


def _title_from_path(path: str) -> str:
    """Fallback heading when <Name> is absent — turns a camelCase fact path
    like "/maxIncomeLimitForMFJ" into "Max Income Limit For MFJ". A real gap
    found while extracting the full Fact Dictionary: many topic files (e.g.
    ptc.xml — 391 of 392 facts, saversCredits.xml — 86 of 86) have a
    <Description> but no <Name> at all; skipping unnamed facts (the original
    version of this script) silently threw away almost all of their content,
    including real dollar figures cited to specific IRS notices."""
    leaf = path.strip("/").split("/")[-1]
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", leaf)
    return spaced[:1].upper() + spaced[1:]


def extract_facts(xml_path: str) -> list[dict]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    facts = []
    for fact_el in root.iter("Fact"):
        path = fact_el.get("path", "")
        name_el = fact_el.find("Name")
        desc_el = fact_el.find("Description")

        name = (name_el.text or "").strip() if name_el is not None else ""
        description = (desc_el.text or "").strip() if desc_el is not None else ""
        # Collapse the XML's indentation-preserved whitespace into normal
        # paragraph text.
        description = " ".join(description.split())

        if not name and not description:
            continue  # nothing readable to extract from this fact at all
        if not name:
            name = _title_from_path(path)
        facts.append({"path": path, "name": name, "description": description})
    return facts


def format_as_text(topic: str, facts: list[dict]) -> str:
    lines = [f"# IRS Direct File Fact Dictionary — {topic}", ""]
    for f in facts:
        lines.append(f"## {f['name']}")
        lines.append(f"(fact path: {f['path']})")
        if f["description"]:
            lines.append(f["description"])
        else:
            lines.append("(no description provided)")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 extract_direct_file_facts.py <path-to-topic.xml>")
        sys.exit(1)

    xml_path = sys.argv[1]
    topic = xml_path.split("/")[-1].replace(".xml", "")
    facts = extract_facts(xml_path)
    text = format_as_text(topic, facts)

    print(f"Extracted {len(facts)} facts ({sum(1 for f in facts if f['description'])} with descriptions) from {xml_path}", file=sys.stderr)
    print(f"Output length: {len(text)} chars", file=sys.stderr)
    print(text)
