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


_BOLD_HEADING = re.compile(r"^\s*(?:\*\*|__)[^*_\n]{1,80}(?:\*\*|__)\s*:?\s*$")


def separate_headings(text: str) -> str:
    """A blank line after a line that is only a bold heading. Markdown joins
    "**Conversion Ratio**" and the next line into one paragraph, shown as
    "Conversion Ratio Conversion Ratio = 1000 ÷ 40 = 25" (22 Oct 2026)."""
    lines = text.splitlines()
    out: list[str] = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        out.append(line)
        following = lines[i + 1] if i + 1 < len(lines) else ""
        if not in_fence and _BOLD_HEADING.match(line) and following.strip() and not following.lstrip().startswith("|"):
            out.append("")
    return "\n".join(out)


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
    # Sizing only: "\\big/ \\big((1000+950)/2\\big)" in a WACC answer (22 Oct 2026).
    ("\\Bigl", ""), ("\\Bigr", ""), ("\\bigl", ""), ("\\bigr", ""), ("\\Big", ""), ("\\big", ""),
    ("\\cdots", "…"), ("\\ldots", "…"), ("\\dots", "…"), ("\\sum", "Σ"), ("\\log", "log"), ("\\ln", "ln"),
    ("\\neq", "≠"), ("\\pm", "±"), ("\\to", "→"), ("\\rightarrow", "→"),
)
# Greek letters as symbols: "(1-\\tau)" in an NPV answer.
# "\\DeltaDays": a capital letter after the name starts the next word.
_GREEK = re.compile(r"\\(alpha|beta|gamma|delta|Delta|epsilon|theta|lambda|mu|pi|rho|sigma|Sigma|tau|phi|omega)(?![a-z])")
_GREEK_LETTERS = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ", "epsilon": "ε", "theta": "θ",
                  "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "Sigma": "Σ", "tau": "τ",
                  "phi": "φ", "omega": "ω"}
_SQRT = re.compile(r"\\sqrt\{([^{}]*)\}")
# Formatting wrappers whose content is the meaning.
_WRAPPER = re.compile(r"\\(?:text|mathrm|textbf|textit|mathbf|mathit|boxed|operatorname|bm)\{([^{}]*)\}")
# "\underbrace{(Net Income) ÷ (Sales)}_{Net Profit Margin}" was shown raw in a
# DuPont answer (22 Oct 2026). The label follows in brackets: in parentheses
# it would read as a multiplication.
_BRACE_LABEL = re.compile(r"\\(?:under|over)brace\{([^{}]*)\}(?:[_^](?:\{([^{}]*)\}|(\w)))?(\()?")
_ENVIRONMENT = re.compile(r"\\(?:begin|end)\{(?:aligned|align\*?|equation\*?|array|gathered|split|cases)\}(?:\{[^{}]*\})?")


def _labelled(match: re.Match) -> str:
    body, label = match.group(1).strip(), (match.group(2) or match.group(3) or "").strip()
    # "[Label](" would be a Markdown link.
    return (f"{body} [{label}]" if label else body) + (" (" if match.group(4) else "")


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
            # Before fractions: "\frac{468{,}000}{5{,}200{,}000}" has braces inside.
            line = line.replace("{,}", ",")
            for _ in range(3):  # nested: \underbrace{\frac{\text{A}}{B}}_{\text{C}}
                line = _WRAPPER.sub(r"\1", line)
                line = _FRAC.sub(r"(\1) ÷ (\2)", line)
                line = _BRACE_LABEL.sub(_labelled, line)
            # An unclosed one (a formula split over lines, or cut off): the
            # command goes, its content stays.
            line = re.sub(r"\\(?:under|over)brace\{", "", line)
            line = _ENVIRONMENT.sub("", line)
            # An aligned row: "&=" is "=", "\\" a line break (in a table row, a
            # semicolon). Other "&" stay ("R&D", "Profit & Loss").
            line = re.sub(r"\s*&\s*=", " =", line)
            line = re.sub(r"\s*\\\\\s*$", "", line)
            if "\\\\" in line:
                line = re.sub(r"\s*\\\\\s*", "; " if line.lstrip().startswith("|") else "\n", line)
            line = _SQRT.sub(r"√(\1)", line)
            # Longest first: "\\rightarrow" before "\\right", "\\Bigl" before "\\Big".
            for latex, plain in sorted(_LATEX_SYMBOLS, key=lambda pair: -len(pair[0])):
                line = line.replace(latex, plain)
            # "Depreciation\\tau" is a product: keep the letter apart from the word.
            line = _GREEK.sub(lambda m: (" " if m.start() and line[m.start() - 1].isalnum() else "")
                              + _GREEK_LETTERS[m.group(1)], line)
            line = re.sub(r"_\{([^{}]*)\}", r"_\1", line)
            line = re.sub(r"\^\{([^{}]*)\}", r"^\1", line)
            line = _SQRT.sub(r"√(\1)", line)
            line = re.sub(r"\\[()\[\]]", "", line)
            line = line.replace("$$", "")
        out.append(line)
    return "\n".join(out)


_PLACEHOLDER = re.compile(
    r"^\s*\[(?:the\s+)?(?:chart|graph|table|diagram|visual(?:isation|ization)?|image)(?:\s+\w+){0,3}\]\s*$",
    re.I | re.M)


def remove_visual_placeholders(text: str) -> str:
    """A line such as "[The chart below]" is the model marking where a chart
    goes; the chart is rendered on its own, so the marker was shown as text."""
    return re.sub(r"\n{3,}", "\n\n", _PLACEHOLDER.sub("", text or ""))


# Calculated percentages are shown to two decimals (QA bank: 38.00%, 25.00%).
# The prompt asks for it, yet a pie-chart answer still gave "2100 / 10000 *
# 100 = 21 %" and a Share column of "21 %". Only a calculated result is
# changed: a value after "x 100 =", or a table cell under / beside a share,
# margin, growth or percentage heading. A stated rate ("VAT at 20%") is not.
_TIMES_100 = re.compile(r"((?:[×*]|\bx)\s*100\s*=\s*)(-?\d[\d,]*(?:\.\d)?)\s*%", re.I)
_PERCENT_CELL = re.compile(r"^(-?\d[\d,]*(?:\.\d)?)\s*%$")
_PERCENT_HEADING = re.compile(r"\bshare\b|\bmargin\b|\bgrowth\b|percent|\bmix\b|%", re.I)


def _two_decimals(number: str) -> str:
    return f"{float(number.replace(',', '')):,.2f}%"


def _table_cells(line: str) -> list[str]:
    return line.strip().strip("|").split("|")


def calculated_percentages(text: str) -> str:
    lines = (text or "").split("\n")
    out: list[str] = []
    header: list[str] | None = None
    for line in lines:
        line = _TIMES_100.sub(lambda m: m.group(1) + _two_decimals(m.group(2)), line)
        if line.lstrip().startswith("|"):
            cells = _table_cells(line)
            if header is None:
                header = cells
            elif not all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in cells):
                row_label = cells[0] if cells else ""
                fixed = []
                for i, cell in enumerate(cells):
                    match = _PERCENT_CELL.match(cell.strip())
                    heading = header[i] if i < len(header) else ""
                    if match and i and (_PERCENT_HEADING.search(heading) or _PERCENT_HEADING.search(row_label)):
                        cell = f" {_two_decimals(match.group(1))} "
                    fixed.append(cell)
                line = "|" + "|".join(fixed) + "|"
        else:
            header = None
        out.append(line)
    return "\n".join(out)


_NUMBERED_ITEM = re.compile(r"^(\s*)(\d+)([.)])(\s+)")


def renumber_ordered_lists(text: str) -> str:
    """Renumber each run of numbered list items 1, 2, 3 … after unsupported
    steps were removed ("2. … 3. … 5. … 7." in a GSTR-3B answer). A blank
    line or any other line ends a run; nested (indented) lists keep their
    own count."""
    out: list[str] = []
    counters: dict[str, int] = {}
    for line in (text or "").split("\n"):
        match = _NUMBERED_ITEM.match(line)
        if match:
            indent = match.group(1)
            counters[indent] = counters.get(indent, 0) + 1
            line = f"{indent}{counters[indent]}{match.group(3)}{match.group(4)}" + line[match.end():]
        elif line.strip() and not line.startswith((" ", "\t")):
            counters = {}
        out.append(line)
    return "\n".join(out)
