"""Bank statement to entries: read a CSV or Excel statement, suggest a ledger for
each line, spot lines already in the books, and post the rest as vouchers."""
import base64, csv, datetime as dt, io, re
from decimal import Decimal, InvalidOperation

from books import GROUP_PARENTS, date_key, entries, entry_debit, effective

BANK_GROUPS = {'Bank Accounts', 'Bank OCC A/c', 'Bank OD A/c'}
CASH_GROUPS = {'Cash-in-hand'}
HEAD = {
    'date': ('txn date', 'transaction date', 'tran date', 'trans date', 'date', 'value date', 'post date'),
    'narr': ('narration', 'description', 'particulars', 'transaction remarks', 'remarks', 'details'),
    'ref': ('chq', 'cheque', 'ref'),
    'out': ('withdrawal', 'debit', 'dr amount', 'paid out'),
    'in': ('deposit', 'credit', 'cr amount', 'paid in'),
    'amt': ('amount',),
    'drcr': ('dr/cr', 'cr/dr', 'dr / cr', 'type'),
    'bal': ('balance',),
}
SUFFIX = re.compile(r'\b(private|pvt|limited|ltd|llp|co|company|and|the)\b')


def _norm(text):
    return re.sub(r'[^a-z0-9]', '', SUFFIX.sub(' ', str(text or '').lower()))


def _in_groups(c, name, groups):
    group, seen = c.get('ledgers', {}).get(name, {}).get('parent'), set()
    while group and group not in seen and group != 'Primary':
        if group in groups or c.get('group_records', {}).get(group, {}).get('system_group') in groups: return True
        seen.add(group)
        group = c.get('group_records', {}).get(group, {}).get('parent', GROUP_PARENTS.get(group))
    return False


def is_bank(c, name): return _in_groups(c, name, BANK_GROUPS)
def is_cash_bank(c, name): return _in_groups(c, name, BANK_GROUPS | CASH_GROUPS)


def money(v):
    if v is None or v == '': return Decimal('0')
    if isinstance(v, (int, float, Decimal)): return abs(Decimal(str(v))).quantize(Decimal('0.01'))
    s = re.sub(r'(?i)[₹,\s]|inr|rs\.?|\(?(cr|dr)\)?\.?$', '', str(v))
    try: return abs(Decimal(s)).quantize(Decimal('0.01')) if s not in ('', '-') else Decimal('0')
    except InvalidOperation: return None


def bank_date(v):
    if isinstance(v, dt.datetime): v = v.date()
    if isinstance(v, dt.date): return v.strftime('%Y%m%d')
    s = str(v or '').strip().split(' ')[0] if re.match(r'^\d{4}-\d\d-\d\d \d', str(v or '')) else str(v or '').strip()
    for fmt in ('%d/%m/%Y', '%d/%m/%y', '%d-%m-%Y', '%d-%m-%y', '%d.%m.%Y', '%d-%b-%Y', '%d-%b-%y', '%d %b %Y', '%d %b %y', '%Y-%m-%d', '%d/%b/%Y'):
        try: return dt.datetime.strptime(s, fmt).strftime('%Y%m%d')
        except ValueError: pass
    return None


def _grid(filename, data):
    name = str(filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True).active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if name.endswith(('.csv', '.txt')):
        text = data.decode('utf-8-sig', errors='replace')
        return list(csv.reader(io.StringIO(text), dialect=csv.Sniffer().sniff(text[:4096], ',;\t|') if text.strip() else 'excel'))
    raise ValueError('Upload the statement as Excel (.xlsx) or CSV. For .xls or PDF, open it in Excel and save as .xlsx.')


def _columns(row):
    cells = [str(c or '').strip().lower() for c in row]
    cols = {}
    for key, words in HEAD.items():
        for w in words:  # earlier words win, so "txn date" beats "value date"
            i = next((i for i, c in enumerate(cells) if c and w in c and i not in cols.values()), None)
            if i is not None: cols[key] = i; break
    if 'drcr' in cols and cols.get('drcr') in (cols.get('out'), cols.get('in')): cols.pop('drcr')
    ok = 'date' in cols and 'narr' in cols and (('out' in cols and 'in' in cols) or 'amt' in cols)
    return cols if ok else None


def parse_statement(filename, data):
    grid = _grid(filename, data)
    for h, row in enumerate(grid[:60]):
        cols = _columns(row)
        if cols: break
    else:
        raise ValueError('Could not find the column headings (Date, Narration, Withdrawal, Deposit) in this file')
    rows, cell = [], lambda r, k: r[cols[k]] if k in cols and cols[k] < len(r) else None
    for n, r in enumerate(grid[h + 1:], start=h + 2):
        d = bank_date(cell(r, 'date'))
        if not d: continue  # totals, blank and page-break lines
        if 'out' in cols and 'in' in cols:
            out, inn = money(cell(r, 'out')), money(cell(r, 'in'))
        else:
            a, kind = money(cell(r, 'amt')), str(cell(r, 'drcr') or cell(r, 'amt') or '').lower()
            out, inn = (a, Decimal('0')) if 'dr' in kind or 'debit' in kind or kind.strip().startswith('-') else (Decimal('0'), a)
        if out is None or inn is None: raise ValueError(f'Line {n}: amount is not a number')
        if not out and not inn: continue
        if out and inn: raise ValueError(f'Line {n}: has both a withdrawal and a deposit')
        rows.append({'line': n, 'date': d, 'narration': ' '.join(str(cell(r, 'narr') or '').split()),
                     'ref': str(cell(r, 'ref') or '').strip(), 'dir': 'out' if out else 'in', 'amount': f'{out or inn:.2f}'})
    if not rows: raise ValueError('No transactions found under the headings')
    return rows


def suggest(c, bank, row, rules):
    text = row['narration'].lower()
    for rule in rules:
        if rule.get('text') and all(w in text for w in rule['text'].lower().split()) and rule.get('ledger') in c['ledgers'] and rule['ledger'] != bank:
            return rule['ledger'], 'rule: "' + rule['text'] + '"'
    flat = _norm(text)
    hits = [n for n in c['ledgers'] if n != bank and len(_norm(n)) >= 4 and _norm(n) in flat]
    if hits: return max(hits, key=lambda n: len(_norm(n))), 'name in narration'
    # banks cut names short ("GUPTA INFRA"): the first two words are enough when only one ledger fits
    short = [n for n in c['ledgers'] if n != bank and not is_cash_bank(c, n)
             and len(k := _norm(' '.join(SUFFIX.sub(' ', n.lower()).split()[:2]))) >= 6 and k in flat]
    if len(short) == 1: return short[0], 'name in narration'
    if re.search(r'\b(atm|cash wdl|cash withdrawal|self)\b', text) and row['dir'] == 'out' or re.search(r'\bcash dep', text):
        cash = next((n for n in c['ledgers'] if _in_groups(c, n, CASH_GROUPS)), None)
        if cash: return cash, 'cash'
    for words, names in ((r'\b(chg|chgs|charges|commission|sms)\b', ('bank charges',)), (r'\b(int|interest)\b', ('interest received', 'bank interest', 'interest income'))):
        if re.search(words, text):
            led = next((n for n in c['ledgers'] if n.lower() in names), None)
            if led: return led, 'bank charges' if 'chg' in words else 'interest'
    return '', ''


def _bank_amount(v, bank):
    """Debit (+) / credit (-) of the bank ledger in this voucher."""
    return sum((entry_debit(e) for e in entries(v) if e.get('LEDGERNAME') == bank), Decimal('0'))


def preview(db, company, bank, filename, content_b64):
    c = db.get_company(company)
    if bank not in c['ledgers'] or not is_cash_bank(c, bank): raise ValueError('Choose a bank ledger')
    rows = parse_statement(filename, base64.b64decode(content_b64))
    rules = c.get('bank_rules', [])
    used = set()
    pool = [v for v in c['vouchers'] if effective(v) and any(e.get('LEDGERNAME') == bank for e in entries(v))]
    for r in rows:
        want = Decimal(r['amount']) * (1 if r['dir'] == 'in' else -1)
        day = dt.datetime.strptime(r['date'], '%Y%m%d')
        match = next((v for v in pool if id(v) not in used and _bank_amount(v, bank) == want
                      and abs((dt.datetime.strptime(date_key(v['DATE']), '%Y%m%d') - day).days) <= 5), None)
        if match:
            used.add(id(match))
            r.update(state='matched', voucher=f"{match['VOUCHERTYPENAME']} {match.get('VOUCHERNUMBER', '')}".strip(),
                     voucher_id=str(match.get('MASTERID') or match.get('GUID') or match.get('VOUCHERNUMBER')))
        else:
            r['ledger'], r['why'] = suggest(c, bank, r, rules)
            r['state'] = 'suggested' if r['ledger'] else 'open'
    return {'rows': rows, 'rules': rules, 'revision': db.data['revision']}


def post(db, company, bank, rows, expected_revision=None, remember=()):
    """Post every row in one transaction: all go in, or none do."""
    with db.transaction():
        if expected_revision is not None and int(expected_revision) != int(db.data.get('revision', 0)):
            raise ValueError('The books changed since the preview; preview the statement again')
        c = db.get_company(company)
        if not is_cash_bank(c, bank): raise ValueError('Choose a bank ledger')
        made, marked = [], 0
        for r in rows:
            if r.get('voucher_id'):  # already in the books: just tick it as cleared
                try: db.set_bank_date(company, r['voucher_id'], bank, r['date']); marked += 1
                except ValueError: pass
                continue
            led, amt = r.get('ledger'), money(r.get('amount'))
            if not led or led not in c['ledgers']: raise ValueError(f"Line {r.get('line')}: choose a ledger")
            if led == bank: raise ValueError(f"Line {r.get('line')}: ledger cannot be the bank itself")
            if not amt: raise ValueError(f"Line {r.get('line')}: amount is zero")
            vtype = 'Contra' if is_cash_bank(c, led) else 'Payment' if r['dir'] == 'out' else 'Receipt'
            dr, cr = (led, bank) if r['dir'] == 'out' else (bank, led)
            v = {'VOUCHERTYPENAME': vtype, 'DATE': r['date'], 'NARRATION': r.get('narration', ''),
                 'ALLLEDGERENTRIES.LIST': [{'LEDGERNAME': dr, 'AMOUNT': f'-{amt}', 'ISDEEMEDPOSITIVE': 'Yes'},
                                           {'LEDGERNAME': cr, 'AMOUNT': f'{amt}', 'ISDEEMEDPOSITIVE': 'No'}]}
            if vtype != 'Contra': v['PARTYLEDGERNAME'] = led
            if r.get('ref'): v['CHEQUENUMBER'] = r['ref']
            for e in v['ALLLEDGERENTRIES.LIST']:
                if e['LEDGERNAME'] == bank: e['BANKDATE'] = r['date']
            try: made.append(db.post_voucher(company, v))
            except ValueError as e: raise ValueError(f"Line {r.get('line')}: {e}")
        rules = c.setdefault('bank_rules', [])
        for rule in remember or ():
            text, led = str(rule.get('text') or '').strip(), rule.get('ledger')
            if len(text) >= 3 and led in c['ledgers'] and not any(x['text'].lower() == text.lower() for x in rules):
                rules.append({'text': text, 'ledger': led})
        return {'posted': len(made), 'cleared': marked, 'revision': db.data['revision']}


def save_rules(db, company, rules):
    with db.transaction():
        c = db.get_company(company)
        c['bank_rules'] = [{'text': str(r['text']).strip(), 'ledger': r['ledger']} for r in rules
                           if str(r.get('text') or '').strip() and r.get('ledger') in c['ledgers']]
        return {'rules': c['bank_rules']}
