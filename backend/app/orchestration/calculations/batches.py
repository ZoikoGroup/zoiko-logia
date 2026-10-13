"""Execute bounded numbered arithmetic requests with each question's own inputs."""
import re
from decimal import Decimal, localcontext
from app.orchestration.calculations.schemas import CalculationOutput

_MONEY = r'(?:[₹£$€]\s*)?(\d[\d,]*(?:\.\d+)?)'

def _numbered_markers(question):
    # Plain numbering uses an initial capital; explicit 1./1) numbering also
    # accepts lowercase text. Ordinary "3 years" is not a question marker.
    return list(re.finditer(r'(?:^|\s)(\d{1,2})(?:[.)]\s+(?=[A-Za-z₹£$€])|\s+(?=[A-Z₹£$€]))', question))


def has_numbered_questions(question):
    """Explicitly marked problems only. Unmarked sentence groups are a best
    effort: a follow-up scenario ("… Then show what happens if expenses
    increase to ₹400,000.") reads like a second problem but is not one."""
    return len(numbered_parts(question, unmarked=False)) >= 2


def _sequential(parts):
    return len(parts) >= 2 and [n for n, _ in parts] == list(range(parts[0][0], parts[0][0] + len(parts)))


def _split_at(question, matches, numbering):
    """(number, text) for each marker match, the text running to the next."""
    parts = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(question)
        parts.append((numbering(i, match), question[match.end():end].strip()))
    return parts


_INSTRUCTION = re.compile(
    r"\b(?:calculate|compute|work\s+out|determine|find|what\s+is|what's|what\s+are)\b|\?", re.I)


def _request_groups(question):
    """Unnumbered problems written one after another: sentences up to and
    including each instruction ("… Calculate debt-to-equity.") form one
    problem. A group with no figures of its own ("Calculate the margin
    too.") belongs to the problem before it, so one problem asked in two
    instruction sentences is never split."""
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+|\n+", question) if s.strip()]
    groups, current = [], []
    for sentence in sentences:
        current.append(sentence)
        if _INSTRUCTION.search(sentence):
            groups.append(" ".join(current))
            current = []
    if current:
        groups.append(" ".join(current))
    merged = []
    for group in groups:
        if merged and not re.search(r"\d", group):
            merged[-1] = merged[-1] + " " + group
        else:
            merged.append(group)
    if len(merged) < 2:
        return []
    # Keep the user's own numbering ("9 …", "15 …"; "1) …", "3) …").
    numbered = []
    for i, group in enumerate(merged):
        marker = re.match(r"\(?(\d{1,2})[.):]?\s+(.*)", group, re.S)
        numbered.append((int(marker.group(1)), marker.group(2).strip()) if marker else (i + 1, group))
    return numbered


def numbered_parts(question, unmarked=True):
    """The separate problems in a message, in order, however they are marked:
    "1 …", "1. …", "(1) …", "Q1: …", "a) …", bullets, or one problem after
    another with no marker. Only "1 …" and "1. …" were recognised; any other
    marking made the problems one calculation, and a debt-to-equity ratio
    took its liabilities from the previous problem (0.50 instead of 1.50)
    and was labelled verified."""
    starts = _numbered_markers(question)
    if 2 <= len(starts) <= 20:
        parts = _split_at(question, starts, lambda i, m: int(m.group(1)))
        if _sequential(parts):
            return parts
    styles = (
        (r"(?:^|\s)\((\d{1,2})\)\s+", 0, lambda i, m: int(m.group(1))),
        (r"(?:^|\s)Q(\d{1,2})\s*[:.)\-]?\s+", 0, lambda i, m: int(m.group(1))),
        (r"(?:^|\s)\(?([a-j])\)\s+|(?:^|\n)([a-j])\.\s+", 0,
         lambda i, m: ord((m.group(1) or m.group(2)).lower()) - ord("a") + 1),
        (r"(?:^|\n)\s*[-*•]\s+", 0, lambda i, m: i + 1),
    )
    for pattern, flags, numbering in styles:
        matches = list(re.finditer(pattern, question, flags))
        if not 2 <= len(matches) <= 20:
            continue
        parts = _split_at(question, matches, numbering)
        if _sequential(parts) and all(text for _, text in parts):
            return parts
    if not unmarked:
        return []
    groups = _request_groups(question)
    return groups if 2 <= len(groups) <= 20 else []


def calculate_numbered_batch(question):
    parts = numbered_parts(question)
    if not parts:
        return None
    from app.orchestration.calculations.engine import _success, _money, _percent, _ratio, calculate_from_query
    outputs, steps, formulas = [], [], []
    for number,q in parts:
        words={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10}
        q=re.sub(r'\b('+ '|'.join(words)+r')\s+(years?)\b',lambda m:f'{words[m.group(1).lower()]} {m.group(2)}',q,flags=re.I)
        symbols = set(re.findall(r'[₹£$€]', q))
        if len(symbols) > 1:
            return None
        currency = {'₹':'INR','£':'GBP','$':'USD','€':'EUR'}.get(next(iter(symbols),''))
        prefix = f'Question {number}'
        def value(label):
            found = re.search(rf'\b(?:{label})\s*(?:(?:is|of|at)\s+)?[:=]?\s*{_MONEY}', q, re.I)
            return Decimal(found.group(1).replace(',','')) if found else None
        def add(name, number, kind='money'):
            display = _money(number,currency) if kind=='money' else _percent(number) if kind=='percentage' else _ratio(number)
            outputs.append(CalculationOutput(name=f'{prefix} {name}',value=number,display_value=display,kind=kind))
        if re.search(r'current.*quick ratios?',q,re.I):
            a,l,stock = value('current assets'),value('current liabilities'),value('inventory')
            if any(v is None for v in (a,l,stock)) or l<=0:
                return None
            add('current ratio',a/l,'ratio'); add('quick ratio',(a-stock)/l,'ratio')
            steps += [f'{prefix}: Current ratio = {a} ÷ {l} = {a/l}', f'{prefix}: Quick ratio = ({a} − {stock}) ÷ {l} = {(a-stock)/l}']
            formulas.append('current_and_quick_ratio')
        elif re.search(r'markup.*margin',q,re.I):
            cost,price=value('cost'),value('selling price')
            if cost is None or price is None or cost<=0 or price<=0:
                return None
            add('markup',(price-cost)/cost*100,'percentage'); add('margin',(price-cost)/price*100,'percentage')
            steps += [f'{prefix}: Markup = ({price} − {cost}) ÷ {cost} × 100 = {(price-cost)/cost*100}',f'{prefix}: Margin = ({price} − {cost}) ÷ {price} × 100 = {(price-cost)/price*100}']
            formulas.append('markup_and_margin')
        elif re.search(r'\b(?:cagr|simple interest|compounded annually|emi)\b',q,re.I):
            term=re.search(r'(\d+(?:\.\d+)?)\s*years?\b',q,re.I)
            if not term or not 0<Decimal(term.group(1))<=100:
                return None
            years=Decimal(term.group(1))
            if re.search(r'\bcagr\b',q,re.I):
                growth=re.search(rf'\bfrom\s+{_MONEY}\s+to\s+{_MONEY}',q,re.I)
                if not growth:
                    return None
                old,new=[Decimal(v.replace(',','')) for v in growth.groups()]
                if old<=0 or new<=0:
                    return None
                with localcontext() as ctx:
                    ctx.prec=40
                    number=((new/old)**(Decimal(1)/years)-1)*100
                add('CAGR',number,'percentage')
                steps.append(f'{prefix}: CAGR = (({new} ÷ {old})^(1 ÷ {years}) − 1) × 100 = {number:.6f}')
                formulas.append('cagr')
            else:
                rate=re.search(r'(\d+(?:\.\d+)?)\s*%',q)
                principal=re.search(r'[₹£$€]\s*(\d[\d,]*(?:\.\d+)?)',q)
                if not rate or not principal:
                    return None
                p,r=Decimal(principal.group(1).replace(',','')),Decimal(rate.group(1))/100
                if not 0<=r<=1:
                    return None
                if re.search(r'\bsimple interest\b',q,re.I):
                    result=p*r*years
                    add('simple interest',result)
                    steps.append(f'{prefix}: Simple interest = {p} × {r} × {years} = {result}')
                    formulas.append('simple_interest')
                elif re.search(r'compounded annually',q,re.I):
                    result=p*(1+r)**years
                    add('future value',result)
                    steps.append(f'{prefix}: Future value = {p} × (1 + {r})^{years} = {result:.6f}')
                    formulas.append('compound_interest')
                else:
                    months=years*12; monthly=r/12
                    if months!=months.to_integral_value():
                        return None
                    result=p/months if r==0 else p*monthly*(1+monthly)**months/((1+monthly)**months-1)
                    add('monthly EMI',result)
                    steps.append(f'{prefix}: Monthly EMI calculated with principal {p}, monthly rate {monthly}, and {months} payments.')
                    formulas.append('emi')
        elif re.search(r'straight[- ]line depreciation', q, re.I):
            cost,residual,life=value('machine cost|asset cost|cost'),value('residual(?: value)?|salvage(?: value)?'),value('life|useful life')
            if any(v is None for v in (cost,residual,life)) or cost<residual or life<=0:
                return None
            number=(cost-residual)/life
            add('annual depreciation',number)
            steps.append(f'{prefix}: Annual depreciation = ({cost} − {residual}) ÷ {life} = {number}')
            formulas.append('straight_line_depreciation')
        else:
            isolated=q
            if re.search(r'break[- ]even',q,re.I):
                isolated=re.sub(r'\bprice\b','selling price',q,flags=re.I)
            # Other families retain the existing labelled-input parser.
            result=calculate_from_query('Calculate '+isolated)
            if result.status!='success':
                return None
            outputs += [o.model_copy(update={'name':f'{prefix} {o.name}', **({'display_value':f'{o.value:,.2f} units'} if o.kind=='units' and o.value is not None else {})}) for o in result.outputs]
            steps += [f'{prefix}: {s}' for s in result.steps]
            formulas += result.formula_ids
    return _success(formulas,[],outputs,steps)
