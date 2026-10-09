"""Presentation repairs that preserve all answer content and provenance."""
import re
import json
from decimal import Decimal


def normalize_markdown_tables(text: str) -> str:
    lines = text.splitlines()
    in_fence = False
    width = None
    for i, line in enumerate(lines):
        if line.strip().startswith('```'):
            in_fence = not in_fence
            width = None
            continue
        if in_fence:
            continue
        if not line.strip().startswith('|'):
            width = None
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if i + 1 < len(lines) and re.fullmatch(r'[|:\-\s]+', lines[i + 1]) and '-' in lines[i + 1]:
            width = len(cells)
        if width is None:
            continue
        if len(cells) > width:
            cells = cells[:width - 1] + [' '.join(cells[width - 1:])]
        elif len(cells) < width:
            cells += [''] * (width - len(cells))
        lines[i] = '| ' + ' | '.join(cells) + ' |'
    return '\n'.join(lines)


def has_retained_agent_chart(text: str, artifacts: list[str]) -> bool:
    """Only an exact artifact from the validated chart tool counts as a visual."""
    return any(artifact.strip().startswith('```chart\n') and artifact.strip() in text
               for artifact in artifacts)


def verified_chart_presentation(claim: str, text: str, artifacts: list[str]) -> bool:
    """Check a narrow description of an attached tool chart as presentation.

    It makes no claim about a rate value or tax rule. Numeric or explanatory
    assertions continue through source verification.
    """
    claim = re.sub(r'[-‐‑‒–—]', ' ', claim)
    metric = r'(?:current )?(?:standard(?: rate)? )?(?:(?:VAT/GST|VAT|GST|tax) )?(?:rates|percentages)'
    direct = re.fullmatch(
        r'(?:The )?(?:bar )?chart (?:below )?(?:shows|visualises|visualizes|compares|displays|illustrates) '
        r'(?:the )?(?:three )?' + metric +
        r'(?: for (?:the )?three (?:jurisdictions|countries))?\.?', claim, re.I,
    )
    provided = re.fullmatch(
        r'(?:A |The )?(?:bar )?chart (?:of|comparing) (?:the |these )?(?:three )?'
        + metric + r' (?:is|has been) (?:shown|provided|displayed|generated)(?: below)?\.?', claim, re.I,
    )
    if not direct and not provided:
        return False
    for artifact in artifacts:
        if not has_retained_agent_chart(text, [artifact]):
            continue
        try:
            chart = json.loads(artifact.strip()[len('```chart\n'):-3])
        except (ValueError, TypeError):
            continue
        if chart.get('type') == 'bar' and (not re.search(r'\bthree\b', claim, re.I) or len(chart.get('categories', [])) == 3):
            return True
    return False


def restore_matching_tax_chart(text: str, artifacts: list[str]) -> str:
    """Reuse tool output after a rewrite only when every rate matches its table.

    Model rewrites changed titles/series names of validated tool charts,
    causing the visual-present check to fail. Never restore a chart whose
    data differs from the released comparison, or whose rows are missing.
    """
    from app.orchestration.source_taxonomy import detect_jurisdictions
    rates = {}
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip().startswith('|'):
            continue
        cells = [re.sub(r'\[REF-\d+\]', '', c).strip(' *_') for c in line.strip(' |').split('|')]
        if len(cells) < 2:
            continue
        countries = detect_jurisdictions(cells[0])
        rate = re.fullmatch(r'(\d+(?:\.\d+)?)\s*%', cells[1])
        if len(countries) == 1 and rate:
            if countries[0] in rates:
                return text
            rates[countries[0]] = Decimal(rate.group(1))
    for artifact in artifacts:
        if not artifact.startswith('```chart\n'):
            continue
        try:
            chart = json.loads(artifact[len('```chart\n'):-3])
            if chart.get('type') != 'bar' or len(chart.get('series', [])) != 1:
                continue
            categories, values = chart['categories'], chart['series'][0]['data']
            if len(categories) != len(values) or len(categories) != len(rates):
                continue
            keys = [detect_jurisdictions(category) for category in categories]
            if any(len(key) != 1 or key[0] not in rates for key in keys):
                continue
            if len({key[0] for key in keys}) != len(categories):
                continue
            if any(rates[key[0]] != Decimal(str(value)) for key, value in zip(keys, values)):
                continue
        except (ValueError, TypeError, KeyError):
            continue
        prose = re.sub(r'```chart\s*\n.*?```', '', text, flags=re.S).strip()
        return prose + '\n\n' + artifact
    return text


def missing_visual_message(query: str) -> str:
    if re.search(r'\b(?:flowchart|flow chart|process diagram|workflow)\b', query, re.I):
        return 'The requested process visual could not be built. Provide the stages and branches explicitly (for example, A → B; B → C).'
    return 'The requested chart could not be built from verified numeric data. See the table and source limitations for the available figures.'


_FRAC = re.compile(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}")
_LATEX_SYMBOLS = (
    ("\\left", ""), ("\\right", ""),
    ("{,}", ","), ("\\times", "×"), ("\\cdot", "×"), ("\\div", "÷"), ("\\%", "%"),
    ("\\approx", "≈"), ("\\leq", "≤"), ("\\geq", "≥"), ("\\le", "≤"), ("\\ge", "≥"),
    ("\\,", ""), ("\\;", " "), ("\\!", ""),
    # Layout-only commands: "\displaystyle (£100,000) ÷ (£25,000) = 4" was
    # shown with the command visible.
    ("\\displaystyle", ""), ("\\textstyle", ""), ("\\qquad", " "), ("\\quad", " "),
)


def latex_to_plain(text: str) -> str:
    """Maths notation in plain text. The answer view does not render LaTeX,
    so "\\( FV = 10{,}000 \\times 1.1025 = 10{,}025 \\)" was shown raw, and the
    arithmetic check could not read it: $10,000 at 5% for two years was
    released as $10,025 instead of $11,025."""
    if "\\" not in text and "{,}" not in text:
        return text
    out, in_fence = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence:
            line = re.sub(r"\\(?:text|mathrm|textbf)\{([^{}]*)\}", r"\1", line)
            for _ in range(3):  # nested fractions
                line = _FRAC.sub(r"(\1) ÷ (\2)", line)
            for latex, plain in _LATEX_SYMBOLS:
                line = line.replace(latex, plain)
            line = re.sub(r"\^\{([^{}]*)\}", r"^\1", line)
            line = re.sub(r"\\[()\[\]]", "", line)
            line = line.replace("$$", "")
        out.append(line)
    return "\n".join(out)
