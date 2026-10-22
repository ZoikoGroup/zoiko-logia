"""Bounded revisions over typed user inputs; reuse the existing calculator.

Assistant examples are never task state. An intervening independent user task
stops history lookup. All arithmetic stays in the normal calculation engine.
"""
import re
from decimal import Decimal
from .schemas import CalculationResult, CalculationOutput

_CHANGE = re.compile(r'^\s*(?:correct|change|set|increase|decrease)\s+only\s+(outstanding cheques|variable cost)\s+to\s*([£$€₹])?\s*(\d[\d,]*(?:\.\d+)?)',re.I)
_REFUND = re.compile(r'\brefunds?\s+(?:totalling|totaling|of)\s*([£$€₹])?\s*(\d[\d,]*(?:\.\d+)?)',re.I)


def _family(query):
    change = _CHANGE.search(query)
    if change:
        return 'bank' if change[1].lower() == 'outstanding cheques' else 'cvp'
    return 'vat' if _REFUND.search(query) and re.search(r'\brecalculate\b',query,re.I) else None


def _compatible(result,family):
    return result is not None and result.status == 'success' and bool(set(result.formula_ids) & {
        'bank':{'bank_reconciliation'},'cvp':{'break_even_units'},'vat':{'vat_from_inclusive','vat_on_net'},
    }[family])


def _apply(query,base,family):
    from .engine import calculate_from_query, _CURRENCY_SYMBOLS, _money
    inputs = {i.name:i.value for i in base.inputs}
    currency = next((i.currency for i in base.inputs if i.currency),None)
    if not currency:
        return None
    symbol = {'GBP':'£','USD':'$','EUR':'€','INR':'₹','AED':'AED '}.get(currency,currency+' ')
    match = _REFUND.search(query) if family == 'vat' else _CHANGE.search(query)
    symbol_index, amount_index = (1,2) if family == 'vat' else (2,3)
    supplied_symbol = match[symbol_index]
    if supplied_symbol and _CURRENCY_SYMBOLS[supplied_symbol] != currency:
        return CalculationResult(matched=True,status='clarification_required',error_code='CURRENCY_MISMATCH',message='The revision must use the same currency as the original task.')
    value = Decimal(match[amount_index].replace(',',''))
    if family == 'bank':
        inputs['outstanding_cheques'] = value
        labels = {'bank_statement_balance':'bank statement balance','cash_book_balance':'cash book balance',
                  'deposits_in_transit':'deposits in transit','outstanding_cheques':'outstanding cheques',
                  'bank_charges':'bank charges','interest_received':'interest received'}
        canonical = 'Bank reconciliation. '+'. '.join(f'{label} {symbol}{inputs[name]}' for name,label in labels.items() if name in inputs)+'. There are no other reconciling items.'
        changed = 'outstanding_cheques'
    elif family == 'cvp':
        inputs['variable_cost'] = value
        canonical = f"Selling price {symbol}{inputs['selling_price']}. Variable cost {symbol}{value}. Fixed costs {symbol}{inputs['fixed_costs']}. Calculate break-even units and revenue."
        if 'target_profit' in inputs:
            canonical += f" Target profit {symbol}{inputs['target_profit']}."
        if 'capacity' in inputs:
            canonical += f" Annual capacity {inputs['capacity']}."
        changed = 'variable_cost'
    else:
        if not {'amount','vat_rate'} <= inputs.keys():
            return None
        rates = re.findall(r'(\d+(?:\.\d+)?)\s*%',query)
        if any(Decimal(r) != inputs['vat_rate'] for r in rates):
            return CalculationResult(matched=True,status='clarification_required',error_code='AMBIGUOUS_INPUTS',message='The refund rate differs from the original rate. Please confirm the intended treatment.')
        from .engine import _INCLUSIVE, _EXCLUSIVE
        if bool(_INCLUSIVE.search(query)) == bool(_EXCLUSIVE.search(query)):
            return CalculationResult(matched=True,status='clarification_required',error_code='MISSING_INPUT',message='Does the refund amount include VAT or exclude VAT?')
        factor = 1+inputs['vat_rate']/100
        gross = inputs['amount'] if 'vat_from_inclusive' in base.formula_ids else inputs['amount']*factor
        refund_gross = value if _INCLUSIVE.search(query) else value*factor
        if refund_gross > gross:
            return CalculationResult(matched=True,status='clarification_required',error_code='INVALID_RETURNS',message='The refund exceeds the remaining receipts. Please confirm the amounts.')
        canonical = f"Sales {symbol}{gross-refund_gross} including VAT at {inputs['vat_rate']}%. Calculate VAT and amount excluding VAT."
        changed = 'amount'
    result = calculate_from_query(canonical)
    if result.status != 'success':
        return result
    original = [CalculationOutput(name='original_'+o.name,value=o.value,display_value=o.display_value,kind=o.kind)
                for o in base.outputs if not o.name.startswith('original_')]
    result.outputs = original+result.outputs
    for item in result.inputs:
        item.source_location = 'query' if item.name == changed else 'conversation_history'
    result.notes += [f'Changed only the specified input using {_money(value,currency)}; all other task inputs and assumptions were retained. Original and revised results are shown.']
    return result


def calculate_task_followup(query,history,prior=None):
    family = _family(query)
    if family is None:
        return None
    from .engine import calculate_from_query
    pending=[]
    baseline=None
    user_turns=[m for m in history if m.role == 'user']
    for message in reversed(user_turns):
        if _family(message.content) == family:
            pending.insert(0,message.content)
            continue
        candidate=calculate_from_query(message.content)
        if _compatible(candidate,family):
            baseline=candidate
        break
    if baseline is None and not user_turns and _compatible(prior,family):
        baseline=prior
    if baseline is None:
        return CalculationResult(matched=True,status='clarification_required',error_code='MISSING_INPUT',message='The original task inputs are not available in this conversation. Please provide the original figures before applying this revision.')
    for text in [*pending,query]:
        baseline=_apply(text,baseline,family)
        if baseline is None or baseline.status != 'success':
            return baseline
    return baseline
