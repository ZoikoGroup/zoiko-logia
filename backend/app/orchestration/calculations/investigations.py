"""Supplied-data investigations: arithmetic plus explicitly conditional work.

These are not opinions on compliance or fraud. External rules remain on the
governed evidence path; management explanations remain unverified claims.
"""
import re
from decimal import Decimal
from .schemas import CalculationOutput


def supplied_investigation(query):
    from .engine import _find_value, _supplied, _success_with_notes, _money
    if (re.search(r'\binventory ledger\b',query,re.I)
            and re.search(r'\bphysical count\b',query,re.I)):
        ledger=_find_value(query,('inventory ledger records',))
        counted=_find_value(query,('physical count finds',))
        cost=_find_value(query,('each','per unit'))
        if not all((ledger,counted,cost)) or not cost[1] or min(ledger[0],counted[0],cost[0]) < 0:
            return None
        if len(re.findall(r'\binventory ledger records\b|\bphysical count finds\b',query,re.I)) != 2:
            return None
        quantity=ledger[0]-counted[0]
        currency=cost[1]
        notes=['Confirmed supplied observations: the ledger quantity and physical-count quantity differ. This arithmetic does not establish theft, timing, a recording error or the accuracy of either record.',
               'Evidence to inspect: signed count sheets and recounts; item identity and unit cost; dispatch and goods-received records around year-end; sales and inventory ledger entries; and any authorised adjustments.',
               'Conditional outcomes: if dispatch occurred in the relevant period but was not recorded, correct the supported movement. If a count or ledger error is established, correct that error. Do not post a loss or adjustment solely from an unsupported explanation.']
        claimed=_find_value(query,('management says',))
        if claimed:
            notes.append(f'Management claims {claimed[0]:f} units were dispatched; this is not verified. If relevant dispatch and missing ledger recording are proved, {claimed[0]:f} units ({_money(claimed[0]*cost[0],currency)}) may explain part of the observed difference.')
            if 0 <= claimed[0] <= quantity:
                notes.append(f'Under that conditional explanation, {quantity-claimed[0]:f} units ({_money((quantity-claimed[0])*cost[0],currency)}) would remain to investigate; it is not an established loss.')
        outputs=[CalculationOutput(name=name,value=value,display_value=(f'{value:f} units' if kind=='units' else _money(value,currency)),kind=kind)
                 for name,value,kind in [('quantity_difference',quantity,'units'),('value_difference',quantity*cost[0],'money'),
                                         ('ledger_inventory_value',ledger[0]*cost[0],'money'),('counted_inventory_value',counted[0]*cost[0],'money')]]
        result=_success_with_notes(['inventory_count_investigation'],outputs,[
            f'Observed quantity difference = {ledger[0]} − {counted[0]} = {quantity} units.',
            f'Observed value difference = {quantity} × {_money(cost[0],currency)} = {_money(quantity*cost[0],currency)}.'],notes)
        result.inputs=[_supplied('ledger_units',ledger[0],kind='units'),_supplied('counted_units',counted[0],kind='units'),_supplied('unit_cost',cost[0],currency)]
        return result
    listed=re.search(r'\bsupplier invoices?\s+(?:are|is)\s+for\s+(.+?)\.(?:\s|$)',query,re.I)
    if listed and re.search(r'\bsecond approval\b',query,re.I):
        cells=re.findall(r'([£$€₹])\s*(\d[\d,]*(?:\.\d+)?)',listed[1])
        remaining=re.sub(r'[£$€₹]\s*\d[\d,]*(?:\.\d+)?','',listed[1])
        if not 2 <= len(cells) <= 50 or re.sub(r'\band\b|[,\s]','',remaining):
            return None
        threshold=_find_value(query,('individual invoices of','approval threshold of'))
        from .engine import _CURRENCY_SYMBOLS
        currencies={_CURRENCY_SYMBOLS[symbol] for symbol,_ in cells}
        if not threshold or len(currencies)!=1 or threshold[1] not in currencies:
            return None
        currency=threshold[1]
        amounts=[Decimal(value.replace(',','')) for _,value in cells]
        total=sum(amounts)
        result=_success_with_notes(['approval_threshold_investigation'],[
            CalculationOutput(name='combined_invoice_amount',value=total,display_value=_money(total,currency),kind='money')],
            ['Combined invoice amount = '+' + '.join(_money(v,currency) for v in amounts)+' = '+_money(total,currency)+'.'],
            ['The approval threshold is the policy supplied in the question, not a verified statutory requirement.',
             f'{sum(v>=threshold[0] for v in amounts)} listed invoices individually meet or exceed the stated {_money(threshold[0],currency)} threshold. A combined total does not automatically breach an individual-invoice policy.',
             'Possible concern: related invoices might have been split to avoid additional approval. Similar values or the same approver alone do not establish splitting, intent or fraud.',
             'Investigation procedures: link invoices to purchase orders/contracts and deliveries; compare supplier identity, dates and descriptions; check aggregate commitments, approval records and authority; inspect duplicates and credit notes; obtain explanations and corroborate them against records.'])
        result.inputs=[_supplied(f'invoice_{i}',value,currency) for i,value in enumerate(amounts,1)]+[_supplied('approval_threshold',threshold[0],currency)]
        return result
    return None
