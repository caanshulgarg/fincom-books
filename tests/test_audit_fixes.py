import datetime as dt
from decimal import Decimal
import json
import pytest
import sqlite3
import urllib.request
import urllib.error

from books import Books, decimal, gst_components, calculate_item_gst
from app_server import make_server


def test_database_history_pruning_and_no_quadratic_growth(tmp_path):
    db_file = tmp_path / "growth_test.sqlite3"
    b = Books(db_file)
    b.create_or_alter_company({
        'name': 'Test Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    b.save_master('Test Co', 'ledger', {'name': 'Cash', 'parent': 'Cash-in-hand', 'opening_balance': '10000.00'})
    b.save_master('Test Co', 'ledger', {'name': 'Sales', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})

    # Post 40 transactions and check history row count
    for i in range(1, 41):
        b.post_voucher('Test Co', {
            'VOUCHERTYPENAME': 'Receipt',
            'VOUCHERNUMBER': str(i),
            'DATE': '20260402',
            'ALLLEDGERENTRIES.LIST': [
                {'LEDGERNAME': 'Cash', 'AMOUNT': '100.00', 'ISDEEMEDPOSITIVE': 'Yes'},
                {'LEDGERNAME': 'Sales', 'AMOUNT': '-100.00', 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })

    conn = sqlite3.connect(db_file)
    count = conn.execute("SELECT count(*) FROM history").fetchone()[0]
    conn.close()
    # History must be pruned to rolling window (<= 35 rows), never growing unbounded (40+ rows)
    assert count <= 35, f"Expected rolling history <= 35 revisions, got {count}"


def test_block_negative_stock_does_not_brick_view_or_reports(tmp_path):
    b = Books(tmp_path / "stock_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Stock Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
        'negative_stock_policy': 'warn',
    })
    b.save_master('Stock Co', 'unit', {'name': 'pcs', 'factor': '1'})
    b.save_master('Stock Co', 'stock_item', {
        'name': 'Item A', 'base_units': 'pcs', 'opening_qty': '0', 'opening_balance': '0.00'
    })
    b.save_master('Stock Co', 'ledger', {'name': 'Customer', 'parent': 'Sundry Debtors', 'opening_balance': '0.00'})
    b.save_master('Stock Co', 'ledger', {'name': 'Sales', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})

    sale = {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-1',
        'DATE': '20260401',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Customer', 'AMOUNT': '-100.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'Sales', 'AMOUNT': '100.00', 'ISDEEMEDPOSITIVE': 'Yes'}
        ],
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Item A', 'ACTUALQTY': '5 pcs', 'RATE': '20/pcs', 'AMOUNT': '100.00'}
        ]
    }
    # Acknowledge warning as user would in Tally
    token = b.inventory_warning_token('Stock Co', sale, b.data.get('revision', 0))
    b.post_voucher('Stock Co', sale, allow_inventory_warning=True, warning_token=token)

    # Now switch policy to 'block'
    b.get_company('Stock Co')['negative_stock_policy'] = 'block'
    b.save()

    # Reading view() or financial reports must NOT raise ValueError
    view_data = b.view('Stock Co')
    assert 'Item A' in view_data['stock_items']
    assert view_data['stock_items']['Item A']['closing_qty'] == '-5'


def test_allocate_bills_commits_to_pending_bills(tmp_path):
    b = Books(tmp_path / "alloc_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Bill Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    b.save_master('Bill Co', 'ledger', {'name': 'Customer', 'parent': 'Sundry Debtors', 'opening_balance': '0.00'})
    b.save_master('Bill Co', 'ledger', {'name': 'Sales', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})

    b.post_voucher('Bill Co', {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-100',
        'DATE': '20260401',
        'ALLLEDGERENTRIES.LIST': [
            {
                'LEDGERNAME': 'Customer', 'AMOUNT': '-1000.00', 'ISDEEMEDPOSITIVE': 'No',
                'BILLALLOCATIONS.LIST': [{'BILLTYPE': 'New Ref', 'NAME': 'INV-100', 'AMOUNT': '1000.00'}]
            },
            {'LEDGERNAME': 'Sales', 'AMOUNT': '1000.00', 'ISDEEMEDPOSITIVE': 'Yes'}
        ]
    })
    pending_before = b.pending_bills('Bill Co', 'Customer')
    assert len(pending_before) == 1
    assert pending_before[0]['pending'] == '1000.00'
    bill_id = pending_before[0]['bill_id']

    # Commit allocation of 400
    rev = b.data['revision']
    commit_res = b.allocate_bill_lines('Bill Co', 'Customer', '400.00', 'Agst Ref', [
        {'bill_id': bill_id, 'amount': '400.00'}
    ], rev, commit=True)

    assert commit_res['residual'] == '0.00'
    # Check that pending bill is now reduced to 600.00!
    pending_after = b.pending_bills('Bill Co', 'Customer')
    assert len(pending_after) == 1
    assert pending_after[0]['pending'] == '600.00'


def test_blank_state_defaults_to_igst_not_local():
    co = {'gstin': '29AAAAA0000A1Z5', 'state': 'Karnataka', 'ledgers': {}}
    # Party has no state set
    co['ledgers']['Debtor No State'] = {'name': 'Debtor No State', 'state': '', 'tax_rate': 18}
    res = gst_components(co, 1000, party_name='Debtor No State')
    # Must be IGST, never local CGST/SGST!
    assert len(res) == 1
    assert res[0]['ledger'] == 'IGST'
    assert res[0]['amount'] == '180.00'


def test_decimal_rejects_junk_and_handles_spaces_without_truncating():
    # Spaced Indian grouping
    assert decimal('1 234.50') == Decimal('1234.50')
    assert decimal(' 5 000 ') == Decimal('5000')
    assert decimal('1,23,456.78') == Decimal('123456.78')

    # Rejection of junk
    with pytest.raises(ValueError, match='Invalid numeric amount'):
        decimal('12.50 abc')
    with pytest.raises(ValueError, match='Invalid numeric amount'):
        decimal('invalid_text')


def test_voucher_date_after_fy_end_is_rejected(tmp_path):
    b = Books(tmp_path / "date_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Date Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    b.save_master('Date Co', 'ledger', {'name': 'Cash', 'parent': 'Cash-in-hand', 'opening_balance': '1000.00'})
    b.save_master('Date Co', 'ledger', {'name': 'Sales', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})

    # Date after FY end (01-04-2027) must be rejected
    with pytest.raises(ValueError, match='exceeds financial year'):
        b.post_voucher('Date Co', {
            'VOUCHERTYPENAME': 'Receipt',
            'VOUCHERNUMBER': '1',
            'DATE': '20270401',
            'ALLLEDGERENTRIES.LIST': [
                {'LEDGERNAME': 'Cash', 'AMOUNT': '100.00', 'ISDEEMEDPOSITIVE': 'Yes'},
                {'LEDGERNAME': 'Sales', 'AMOUNT': '-100.00', 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })


def test_settle_invoice_without_bill_details_works(tmp_path):
    b = Books(tmp_path / "unalloc_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Unalloc Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    b.save_master('Unalloc Co', 'ledger', {'name': 'Customer', 'parent': 'Sundry Debtors', 'opening_balance': '0.00'})
    b.save_master('Unalloc Co', 'ledger', {'name': 'Sales', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})

    # Post invoice without explicit BILLALLOCATIONS.LIST
    b.post_voucher('Unalloc Co', {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-RAW',
        'DATE': '20260401',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Customer', 'AMOUNT': '-500.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'Sales', 'AMOUNT': '500.00', 'ISDEEMEDPOSITIVE': 'Yes'}
        ]
    })
    pending = b.pending_bills('Unalloc Co', 'Customer')
    assert len(pending) == 1
    assert pending[0]['pending'] == '500.00'
    bill_id = pending[0]['bill_id']

    # Allocating against this invoice must NOT raise "Allocation belongs to another party"
    res = b.allocate_bill_lines('Unalloc Co', 'Customer', '200.00', 'Agst Ref', [
        {'bill_id': bill_id, 'amount': '200.00'}
    ], b.data['revision'], commit=True)
    assert res['residual'] == '0.00'


def test_missing_ledger_does_not_crash_rebuild(tmp_path):
    b = Books(tmp_path / "missing_ledger.sqlite3")
    b.create_or_alter_company({
        'name': 'Missing Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    b.save_master('Missing Co', 'ledger', {'name': 'Cash', 'parent': 'Cash-in-hand', 'opening_balance': '1000.00'})
    b.save_master('Missing Co', 'ledger', {'name': 'OldLedger', 'parent': 'Direct Incomes', 'opening_balance': '0.00'})

    b.post_voucher('Missing Co', {
        'VOUCHERTYPENAME': 'Receipt',
        'VOUCHERNUMBER': '1',
        'DATE': '20260401',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Cash', 'AMOUNT': '100.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'OldLedger', 'AMOUNT': '-100.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    # Simulate deletion of OldLedger from ledgers dictionary
    b.get_company('Missing Co')['ledgers'].pop('OldLedger')
    b.save()

    # view() must NOT crash with KeyError
    view = b.view('Missing Co')
    assert 'OldLedger' in view['ledgers']


def test_calculate_item_gst_does_not_use_unit_rate_as_tax_percentage():
    company = {
        'gstin': '29AAAAA0000A1Z5',
        'state': 'Karnataka',
        'ledgers': {
            'Party': {'name': 'Party', 'state': 'Karnataka', 'tax_rate': 0}
        },
        'stock_items': {
            'Steel': {'name': 'Steel', 'gst_rate': 18}
        }
    }
    # Item price rate is 1500, amount is 1000. GST rate must be 18%, not 1500%!
    res = calculate_item_gst(company, 'Party', [
        {'item': 'Steel', 'amount': '1000.00', 'rate': '1500.00'}
    ])
    cgst = next(e for e in res if e['ledger'] == 'CGST')
    sgst = next(e for e in res if e['ledger'] == 'SGST')
    assert cgst['amount'] == '90.00'
    assert sgst['amount'] == '90.00'


def test_check_update_status_and_url(tmp_path, monkeypatch):
    # Hermetic: the update check must never need the real internet in tests.
    import app_server
    monkeypatch.setattr(app_server, '_fetch_remote_version', lambda: {'version': '99.0.0', 'download_url': 'https://github.com/caanshulgarg/fincom-books/releases/latest'})
    server = make_server(0, str(tmp_path / "server.sqlite3"))
    import threading
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/check_update"
        resp = json.loads(urllib.request.urlopen(url, timeout=3).read())
        assert resp['status'] == 'success'
        assert resp['update_available'] is True
        assert resp['current_version'] == app_server.APP_VERSION
        assert 'caanshulgarg/fincom-books' in resp['download_url']
        monkeypatch.setattr(app_server, '_fetch_remote_version', lambda: None)
        resp = json.loads(urllib.request.urlopen(url, timeout=3).read())
        assert resp['status'] == 'offline' and resp['update_available'] is False
    finally:
        server.shutdown()
