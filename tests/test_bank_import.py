import base64
import openpyxl, io
import pytest
from books import Books, entries, entry_debit
import bank_import as bi


def company(tmp_path):
    b = Books(tmp_path / 'b.sqlite3')
    b.create_or_alter_company({'name': 'Co', 'starting_from': '20260401', 'ending_at': '20270331'})
    for name, parent in [('HDFC Bank', 'Bank Accounts'), ('Cash', 'Cash-in-hand'), ('Gupta Infra Projects', 'Sundry Debtors'),
                         ('Kumar & Associates', 'Sundry Creditors'), ('Bank Charges', 'Indirect Expenses')]:
        b.save_master('Co', 'ledger', {'name': name, 'parent': parent, 'opening_balance': '0.00'})
    return b


CSV = b"""HDFC BANK LTD,,,,,
Statement of account,,,,,
Date,Narration,Chq./Ref.No.,Withdrawal Amt.,Deposit Amt.,Closing Balance
31/10/26,NEFT-HDFCN526-GUPTA INFRA,N526,,"2,00,000.00","2,00,000.00"
30/10/26,UPI-KUMAR ASSOCIATES-FEES,U1,"45,000.00",,"1,55,000.00"
30/10/26,CHGS FOR NEFT INCL GST,,590.00,,"1,54,410.00"
29/10/26,ATM-CASH WDL NOIDA,,"20,000.00",,"1,34,410.00"
29/10/26,SOMETHING UNKNOWN,,100.00,,"1,34,310.00"
,Total,,,,
"""


def test_preview_suggests_and_post_balances(tmp_path):
    b = company(tmp_path)
    p = bi.preview(b, 'Co', 'HDFC Bank', 'st.csv', base64.b64encode(CSV).decode())
    got = [(r['date'], r['dir'], r['amount'], r.get('ledger')) for r in p['rows']]
    assert got == [('20261031', 'in', '200000.00', 'Gupta Infra Projects'), ('20261030', 'out', '45000.00', 'Kumar & Associates'),
                   ('20261030', 'out', '590.00', 'Bank Charges'), ('20261029', 'out', '20000.00', 'Cash'),
                   ('20261029', 'out', '100.00', '')]
    rows = [r for r in p['rows'] if r['ledger']]
    res = bi.post(b, 'Co', 'HDFC Bank', rows, p['revision'], remember=[{'text': 'unknown something', 'ledger': 'Bank Charges'}])
    assert res['posted'] == 4
    vs = b.get_company('Co')['vouchers']
    assert sorted(v['VOUCHERTYPENAME'] for v in vs) == ['Contra', 'Payment', 'Payment', 'Receipt']
    for v in vs: assert sum(entry_debit(e) for e in entries(v)) == 0
    bank = sum(entry_debit(e) for v in vs for e in entries(v) if e['LEDGERNAME'] == 'HDFC Bank')
    assert str(bank) == '134410.00'
    # second upload of the same statement: posted lines are matched, the rule now catches the unknown line
    p2 = bi.preview(b, 'Co', 'HDFC Bank', 'st.csv', base64.b64encode(CSV).decode())
    assert [r['state'] for r in p2['rows']] == ['matched'] * 4 + ['suggested']
    assert p2['rows'][4]['ledger'] == 'Bank Charges'


def test_failed_line_posts_nothing(tmp_path):
    b = company(tmp_path)
    rows = [{'line': 4, 'date': '20261031', 'dir': 'in', 'amount': '10.00', 'ledger': 'Gupta Infra Projects', 'narration': 'x'},
            {'line': 5, 'date': '20261031', 'dir': 'out', 'amount': '5.00', 'ledger': 'No Such Ledger', 'narration': 'y'}]
    with pytest.raises(ValueError, match='Line 5'):
        bi.post(b, 'Co', 'HDFC Bank', rows)
    assert b.get_company('Co')['vouchers'] == []


def test_excel_amount_with_drcr_column(tmp_path):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(['Txn Date', 'Value Date', 'Description', 'Amount', 'Dr/Cr', 'Balance'])
    ws.append(['05-Oct-2026', '05-Oct-2026', 'IMPS GUPTA INFRA', '1,500.00', 'CR', '1,500.00'])
    ws.append(['06-Oct-2026', '06-Oct-2026', 'SMS CHARGES', '15', 'DR', '1,485.00'])
    buf = io.BytesIO(); wb.save(buf)
    rows = bi.parse_statement('s.xlsx', buf.getvalue())
    assert [(r['date'], r['dir'], r['amount']) for r in rows] == [('20261005', 'in', '1500.00'), ('20261006', 'out', '15.00')]


def test_rejects_unsupported_and_headless_files():
    with pytest.raises(ValueError, match='xlsx'): bi.parse_statement('s.pdf', b'%PDF')
    with pytest.raises(ValueError, match='headings'): bi.parse_statement('s.csv', b'a,b\n1,2\n')
