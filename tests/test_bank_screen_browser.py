import sys
from pathlib import Path

from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).parent))
from test_browser_vouchers import app  # noqa: F401  (fixture)
from books import entries, entry_debit

CSV = b"""Date,Narration,Chq./Ref.No.,Withdrawal Amt.,Deposit Amt.,Closing Balance
05/10/26,NEFT-CUSTOMER-INV 12,N1,,"1,500.00",
06/10/26,UPI-SUPPLIER-PAY,U1,700.00,,
07/10/26,MISC DEBIT 8812,,40.00,,
"""


def test_statement_upload_choose_ledger_and_post(app):
    page, db, _ = app
    page.locator('nav button[data-action=bankImport]').click()
    expect(page.locator('.bk-head h2')).to_have_text('Bank statement → entries')
    page.set_input_files('[name=bk-file]', files=[{'name': 'st.csv', 'mimeType': 'text/csv', 'buffer': CSV}])
    expect(page.locator('.bk-table tbody tr')).to_have_count(3)
    expect(page.locator('#bk-what-0')).to_contain_text('Receipt')
    expect(page.locator('#bk-what-1')).to_contain_text('Payment')
    expect(page.locator('#bk-what-2')).to_contain_text('Choose a ledger')
    expect(page.locator('.bk-table tbody tr').first).to_contain_text('1,500.00')
    page.select_option('[name=bk-ledger][data-i="2"]', 'Discount')
    page.check('[name=bk-keep][data-i="2"]')
    expect(page.locator('[name=bk-text][data-i="2"]')).to_have_value('misc debit')
    page.locator('[data-action=bankPost]').click()
    page.locator('#dialog button.yes').click()
    expect(page.locator('#status')).to_contain_text('3 entries posted')
    c = db.get_company('Voucher Test')
    posted = [v for v in c['vouchers'] if v.get('NARRATION', '').startswith(('NEFT', 'UPI', 'MISC'))]
    assert sorted(v['VOUCHERTYPENAME'] for v in posted) == ['Payment', 'Payment', 'Receipt']
    assert sum(entry_debit(e) for v in posted for e in entries(v) if e['LEDGERNAME'] == 'Bank') == 760
    assert c['bank_rules'] == [{'text': 'misc debit', 'ledger': 'Discount'}]


PNG = __import__('base64').b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


def test_inbox_add_open_beside_voucher_and_set_aside(app):
    page, db, _ = app
    page.locator('nav button[data-action=inbox]').click()
    page.set_input_files('[name=ib-file]', files=[{'name': 'bill.png', 'mimeType': 'image/png', 'buffer': PNG}])
    expect(page.locator('.ib-list button')).to_have_count(1)
    expect(page.locator('.ib-frame img')).to_be_visible()
    page.locator('.ib-acts [data-action=inboxEnter][data-args=Payment]').click()
    expect(page.locator('#inbox-peek img')).to_be_visible()
    expect(page.locator('#edit-form')).to_be_visible()
    page.keyboard.press('Escape')  # first Esc closes the ledger list
    page.keyboard.press('Escape')
    expect(page.locator('#inbox-peek')).to_have_count(0)
    page.locator('.ib-acts [data-action=inboxStatus][data-args=aside]').click()
    expect(page.locator('.ib-tabs [aria-selected=true]')).to_contain_text('Waiting 0')
    assert db.get_company('Voucher Test')['inbox'][0]['status'] == 'aside'


def test_saving_the_voucher_marks_the_bill_entered(app):
    page, db, _ = app
    page.locator('nav button[data-action=inbox]').click()
    page.set_input_files('[name=ib-file]', files=[{'name': 'bill.png', 'mimeType': 'image/png', 'buffer': PNG}])
    page.locator('.ib-list button').first.click()
    page.keyboard.press('F5')  # contextual key enters the selected bill as a Payment
    expect(page.locator('#inbox-peek img')).to_be_visible()
    page.keyboard.press('Escape')  # close the ledger list
    page.select_option('#edit-form [name=payment_bank]', 'Bank')
    page.select_option('#edit-form [name=party]', 'Supplier')
    page.fill('#edit-form [name=payment_amount]', '250')
    page.keyboard.press('Control+a')
    expect(page.locator('#title')).to_have_text('Document inbox')
    expect(page.locator('#inbox-peek')).to_have_count(0)
    doc = db.get_company('Voucher Test')['inbox'][0]
    assert doc['status'] == 'entered' and doc['voucher'].startswith('Payment')
