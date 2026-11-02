"""Comprehensive test suite for the 7 TallyPrime parity modules:
1. GST Filing & Statutory Reports (GSTR-1 B2B, B2CL, B2CS, HSN and GSTR-3B Tables 3.1, 4, 6.1)
2. Bank Work & Reconciliation (BRS: set/clear bank dates, reconciliation statement calculations)
3. Credit Control & Period Lock (books_locked_until rejection and debtor credit limits with override)
4. Cost Centres in Vouchers (allocations validation, breakup and category summary reports)
5. Manufacturing & BOM (BOM definitions, component consumption, additional costs, finished good costing)
6. Local Company Security / PIN Lock (hash/salt storage, verification, API gate blocking/allowance)
7. Paging & Performance (voucher_register pagination, searching, and sorting)
"""
import copy
import datetime as dt
from decimal import Decimal
import json
import pytest
import sqlite3
import threading
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from books import Books, decimal
from interchange import export_xml, apply_import
from app_server import make_server


def test_gst_filing_reports(tmp_path):
    """Module 1: Test GSTR-1 calculation & export and GSTR-3B computation."""
    b = Books(tmp_path / "gst_test.sqlite3")
    b.create_or_alter_company({
        'name': 'GST Enterprise',
        'starting_from': '20260401',
        'ending_at': '20270331',
        'state': 'West Bengal',
        'gstin': '19AAAAA0000A1Z5'
    })
    comp = 'GST Enterprise'

    # Master setup
    b.save_master(comp, 'unit', {'name': 'pcs', 'factor': '1'})
    b.save_master(comp, 'stock_item', {
        'name': 'Steel Rod', 'base_units': 'pcs', 'gst_rate': '18',
        'hsn_code': '7214', 'description': 'Steel TMT Rods',
        'opening_qty': '1000', 'opening_rate': '100.00'
    })
    b.save_master(comp, 'stock_item', {
        'name': 'Computer Mouse', 'base_units': 'pcs', 'gst_rate': '18',
        'hsn_code': '8471', 'description': 'Optical Mouse',
        'opening_qty': '500', 'opening_rate': '200.00'
    })
    b.save_master(comp, 'ledger', {'name': 'Sales Account', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})
    b.save_master(comp, 'ledger', {'name': 'Purchase Account', 'parent': 'Purchase Accounts', 'opening_balance': '0.00'})

    # B2B Party (Registered with GSTIN)
    b.save_master(comp, 'ledger', {
        'name': 'Apex Corp', 'parent': 'Sundry Debtors',
        'gstin': '19ABCDE1234F1Z5', 'state': 'West Bengal', 'opening_balance': '0.00'
    })
    # B2CL Party (Unregistered interstate, large invoice > 2.5L)
    b.save_master(comp, 'ledger', {
        'name': 'Grand Hotel', 'parent': 'Sundry Debtors',
        'gstin': '', 'state': 'Bihar', 'opening_balance': '0.00'
    })
    # B2CS Party 1 (Unregistered local)
    b.save_master(comp, 'ledger', {
        'name': 'Local Walkin', 'parent': 'Sundry Debtors',
        'gstin': '', 'state': 'West Bengal', 'opening_balance': '0.00'
    })
    # B2CS Party 2 (Unregistered interstate, small invoice <= 2.5L)
    b.save_master(comp, 'ledger', {
        'name': 'Small Inter Retail', 'parent': 'Sundry Debtors',
        'gstin': '', 'state': 'Odisha', 'opening_balance': '0.00'
    })
    # Supplier for Purchases (ITC)
    b.save_master(comp, 'ledger', {
        'name': 'Global Supplier', 'parent': 'Sundry Creditors',
        'gstin': '19XYZAB9876C1Z1', 'state': 'West Bengal', 'opening_balance': '0.00'
    })

    # 1. Post B2B Sale (Local: CGST 9% + SGST 9%)
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-B2B-01',
        'DATE': '20260405',
        'PARTYLEDGERNAME': 'Apex Corp',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Steel Rod', 'ACTUALQTY': '10 pcs', 'BILLEDQTY': '10 pcs', 'RATE': '1000.00', 'AMOUNT': '10000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Apex Corp', 'AMOUNT': '11800.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales Account', 'AMOUNT': '-10000.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'CGST', 'AMOUNT': '-900.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'SGST', 'AMOUNT': '-900.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # 2. Post B2CL Sale (Interstate Unregistered > 2,50,000: IGST 18%)
    # Amount = 3,00,000 + 18% IGST (54,000) = 3,54,000
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-B2CL-01',
        'DATE': '20260408',
        'PARTYLEDGERNAME': 'Grand Hotel',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Steel Rod', 'ACTUALQTY': '300 pcs', 'BILLEDQTY': '300 pcs', 'RATE': '1000.00', 'AMOUNT': '300000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Grand Hotel', 'AMOUNT': '354000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales Account', 'AMOUNT': '-300000.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'IGST', 'AMOUNT': '-54000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # 3. Post B2CS Sale Local (Unregistered <= 2.5L: CGST 9% + SGST 9%)
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-B2CS-01',
        'DATE': '20260412',
        'PARTYLEDGERNAME': 'Local Walkin',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Computer Mouse', 'ACTUALQTY': '5 pcs', 'BILLEDQTY': '5 pcs', 'RATE': '1000.00', 'AMOUNT': '5000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Local Walkin', 'AMOUNT': '5900.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales Account', 'AMOUNT': '-5000.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'CGST', 'AMOUNT': '-450.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'SGST', 'AMOUNT': '-450.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # 4. Post B2CS Sale Interstate (Unregistered <= 2.5L: IGST 18%)
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-B2CS-02',
        'DATE': '20260415',
        'PARTYLEDGERNAME': 'Small Inter Retail',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Computer Mouse', 'ACTUALQTY': '10 pcs', 'BILLEDQTY': '10 pcs', 'RATE': '1000.00', 'AMOUNT': '10000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Small Inter Retail', 'AMOUNT': '11800.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales Account', 'AMOUNT': '-10000.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'IGST', 'AMOUNT': '-1800.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # 5. Post Purchase for ITC (Input CGST 1800, SGST 1800)
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Purchase',
        'VOUCHERNUMBER': 'PUR-01',
        'DATE': '20260402',
        'PARTYLEDGERNAME': 'Global Supplier',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Steel Rod', 'ACTUALQTY': '20 pcs', 'BILLEDQTY': '20 pcs', 'RATE': '1000.00', 'AMOUNT': '20000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Global Supplier', 'AMOUNT': '-23600.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'Purchase Account', 'AMOUNT': '20000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'CGST', 'AMOUNT': '1800.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'SGST', 'AMOUNT': '1800.00', 'ISDEEMEDPOSITIVE': 'Yes'}
        ]
    })

    # Run GSTR-1 Report
    gstr1 = b.gstr1_report(comp, '20260401', '20260430')
    assert gstr1['summary']['invoice_count'] == 4

    # Check B2B: Apex Corp
    assert len(gstr1['b2b']) == 1
    assert gstr1['b2b'][0]['ctin'] == '19ABCDE1234F1Z5'
    assert len(gstr1['b2b'][0]['inv']) == 1
    assert gstr1['b2b'][0]['inv'][0]['inum'] == 'INV-B2B-01'

    # Check B2CL: Grand Hotel
    assert len(gstr1['b2cl']) == 1
    assert gstr1['b2cl'][0]['inv'][0]['inum'] == 'INV-B2CL-01'
    assert gstr1['b2cl'][0]['inv'][0]['val'] == 354000.0

    # Check B2CS: Both Local and Small Interstate
    assert len(gstr1['b2cs']) >= 2
    types = [x['sply_ty'] for x in gstr1['b2cs']]
    assert 'INTRA' in types
    assert 'INTER' in types

    # Check HSN Summary
    hsn_codes = [x['hsn_sc'] for x in gstr1['hsn']['data']]
    assert '7214' in hsn_codes
    assert '8471' in hsn_codes

    # Check GSTR-1 Export JSON schema
    export_json = b.gstr1_export(comp, '20260401', '20260430')
    assert 'gstin' in export_json
    assert 'fp' in export_json
    assert 'b2b' in export_json
    assert 'b2cl' in export_json
    assert 'b2cs' in export_json
    assert 'hsn' in export_json
    assert export_json['gt'] > 0

    # Run GSTR-3B Report
    gstr3b = b.gstr3b_report(comp, '20260401', '20260430')
    t31 = gstr3b['table_3_1']['outward_taxable_supplies']
    assert decimal(t31['txval']) == Decimal('325000.00')
    assert decimal(t31['iamt']) == Decimal('55800.00')
    assert decimal(t31['camt']) == Decimal('1350.00')
    assert decimal(t31['samt']) == Decimal('1350.00')

    # Check Table 4 ITC (From purchase of 20,000 @ 18%)
    t4 = gstr3b['table_4_itc']['net_itc_available']
    assert decimal(t4['camt']) == Decimal('1800.00')
    assert decimal(t4['samt']) == Decimal('1800.00')

    # Check Table 6.1 Payment in Cash
    t61 = gstr3b['table_6_1_payment']
    # IGST: 55,800 payable, 0 ITC -> 55,800 cash
    assert decimal(t61['tax_paid_in_cash']['iamt']) == Decimal('55800.00')
    # CGST & SGST: 1,350 payable each, 1,800 ITC available -> 0 cash
    assert decimal(t61['tax_paid_in_cash']['camt']) == Decimal('0.00')
    assert decimal(t61['tax_paid_in_cash']['samt']) == Decimal('0.00')
    assert decimal(t61['total_cash_payable']) == Decimal('55800.00')


def test_bank_reconciliation_statement(tmp_path):
    """Module 2: Test Bank Reconciliation Statement (BRS) and BANKDATE workflow."""
    b = Books(tmp_path / "brs_test.sqlite3")
    b.create_or_alter_company({
        'name': 'BRS Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'BRS Co'

    b.save_master(comp, 'ledger', {'name': 'HDFC Bank', 'parent': 'Bank Accounts', 'opening_balance': '50000.00', 'drcr': 'Dr'})
    b.save_master(comp, 'ledger', {'name': 'Client A', 'parent': 'Sundry Debtors', 'opening_balance': '0.00'})
    b.save_master(comp, 'ledger', {'name': 'Vendor B', 'parent': 'Sundry Creditors', 'opening_balance': '0.00'})

    # 1. Receipt voucher: Client pays 10,000 (deposited into bank, books balance +10,000)
    v1_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Receipt',
        'VOUCHERNUMBER': 'RCP-01',
        'DATE': '20260405',
        'PARTYLEDGERNAME': 'Client A',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'HDFC Bank', 'AMOUNT': '10000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Client A', 'AMOUNT': '-10000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # 2. Payment voucher: Issue cheque to Vendor B for 15,000 (books balance -15,000)
    v2_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Payment',
        'VOUCHERNUMBER': 'PMT-01',
        'DATE': '20260408',
        'PARTYLEDGERNAME': 'Vendor B',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Vendor B', 'AMOUNT': '15000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'HDFC Bank', 'AMOUNT': '-15000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # Initial BRS: Neither transaction cleared in bank yet
    brs = b.bank_reconciliation_statement(comp, 'HDFC Bank', '20260430')
    assert brs['uncleared_count'] == 2
    # Books balance: 50,000 (opening) + 10,000 (receipt) - 15,000 (payment) = 45,000
    assert decimal(brs['balance_as_per_books']) == Decimal('45000.00')
    # Cheques issued not cleared: 15,000
    assert decimal(brs['cheques_issued_not_cleared']) == Decimal('15000.00')
    # Deposits not cleared: 10,000
    assert decimal(brs['deposits_not_cleared']) == Decimal('10000.00')
    # Balance as per Bank: 45,000 + 15,000 - 10,000 = 50,000
    assert decimal(brs['balance_as_per_bank']) == Decimal('50000.00')

    # Now clear the deposit voucher in bank on 20260410
    b.set_bank_date(comp, v1_id, 'HDFC Bank', '20260410')

    brs2 = b.bank_reconciliation_statement(comp, 'HDFC Bank', '20260430')
    assert brs2['uncleared_count'] == 1
    assert decimal(brs2['deposits_not_cleared']) == Decimal('0.00')
    assert decimal(brs2['cheques_issued_not_cleared']) == Decimal('15000.00')
    # Balance as per Bank: 45,000 + 15,000 - 0 = 60,000
    assert decimal(brs2['balance_as_per_bank']) == Decimal('60000.00')

    # Clear the payment voucher on 20260412
    b.set_bank_date(comp, v2_id, 'HDFC Bank', '20260412')
    brs3 = b.bank_reconciliation_statement(comp, 'HDFC Bank', '20260430')
    assert brs3['uncleared_count'] == 0
    assert decimal(brs3['balance_as_per_bank']) == Decimal('45000.00')

    # Test clearing with as_of_date: as of 20260409, neither was cleared
    brs_as_of_9 = b.bank_reconciliation_statement(comp, 'HDFC Bank', '20260409')
    assert brs_as_of_9['uncleared_count'] == 2

    # Unclear a bank date by setting to None
    b.set_bank_date(comp, v1_id, 'HDFC Bank', None)
    brs4 = b.bank_reconciliation_statement(comp, 'HDFC Bank', '20260430')
    assert brs4['uncleared_count'] == 1


def test_credit_control_and_period_lock(tmp_path):
    """Module 3: Test Period Lock and Debtor Credit Limit controls."""
    b = Books(tmp_path / "lock_credit_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Lock Credit Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Lock Credit Co'

    b.save_master(comp, 'ledger', {'name': 'Sales A/c', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})
    # Debtor with 50,000 credit limit
    b.save_master(comp, 'ledger', {
        'name': 'Trusted Buyer', 'parent': 'Sundry Debtors',
        'opening_balance': '0.00', 'credit_limit': '50000.00'
    })

    # Part A: Credit Limit Check
    check = b.check_credit_limit(comp, 'Trusted Buyer', Decimal('20000.00'))
    assert check['exceeded'] is False
    assert decimal(check['available_credit']) == Decimal('50000.00')

    # Post invoice of 30,000 (Within limit)
    v1_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'SALES-01',
        'DATE': '20260405',
        'PARTYLEDGERNAME': 'Trusted Buyer',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Trusted Buyer', 'AMOUNT': '30000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-30000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # Available credit is now 20,000
    check2 = b.check_credit_limit(comp, 'Trusted Buyer', Decimal('25000.00'))
    assert check2['exceeded'] is True

    # Attempting to post invoice of 25,000 must raise ValueError
    with pytest.raises(ValueError, match="Credit limit .* exceeded"):
        b.post_voucher(comp, {
            'VOUCHERTYPENAME': 'Sales',
            'VOUCHERNUMBER': 'SALES-02',
            'DATE': '20260408',
            'PARTYLEDGERNAME': 'Trusted Buyer',
            'ALLLEDGERENTRIES.LIST': [
                {'LEDGERNAME': 'Trusted Buyer', 'AMOUNT': '25000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
                {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-25000.00', 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })

    # Posting with override_credit_limit succeeds
    v2_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'SALES-02',
        'DATE': '20260408',
        'PARTYLEDGERNAME': 'Trusted Buyer',
        'override_credit_limit': True,
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Trusted Buyer', 'AMOUNT': '25000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-25000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    assert v2_id is not None

    # Part B: Period Lock
    # Lock company records up to 20260410
    b.set_period_lock(comp, '20260410')

    # Attempt to post new voucher on or before 20260410 -> rejected
    with pytest.raises(ValueError, match="Period is locked until"):
        b.post_voucher(comp, {
            'VOUCHERTYPENAME': 'Sales',
            'VOUCHERNUMBER': 'SALES-03',
            'DATE': '20260409',
            'PARTYLEDGERNAME': 'Trusted Buyer',
            'override_credit_limit': True,
            'ALLLEDGERENTRIES.LIST': [
                {'LEDGERNAME': 'Trusted Buyer', 'AMOUNT': '1000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
                {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-1000.00', 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })

    # Attempt to alter existing voucher (SALES-01 from 20260405) -> rejected
    with pytest.raises(ValueError, match="Period is locked until"):
        b.post_voucher(comp, {
            '@ACTION': 'Alter',
            'MASTERID': v1_id,
            'VOUCHERTYPENAME': 'Sales',
            'VOUCHERNUMBER': 'SALES-01',
            'DATE': '20260405',
            'PARTYLEDGERNAME': 'Trusted Buyer',
            'override_credit_limit': True,
            'ALLLEDGERENTRIES.LIST': [
                {'LEDGERNAME': 'Trusted Buyer', 'AMOUNT': '32000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
                {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-32000.00', 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })

    # Attempt to cancel/delete voucher on or before lock date -> rejected
    with pytest.raises(ValueError, match="Period is locked until"):
        b.cancel_or_delete_voucher(comp, v1_id, delete=True)

    # Post voucher dated AFTER lock date -> succeeds
    v3_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'SALES-04',
        'DATE': '20260415',
        'PARTYLEDGERNAME': 'Trusted Buyer',
        'override_credit_limit': True,
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Trusted Buyer', 'AMOUNT': '1000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-1000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    assert v3_id is not None

    # Unlock period
    b.set_period_lock(comp, None)
    # Cancellation now works
    assert b.cancel_or_delete_voucher(comp, v3_id, delete=True) is True


def test_cost_centres_in_vouchers(tmp_path):
    """Module 4: Test Cost Centre allocations on vouchers and reporting."""
    b = Books(tmp_path / "cost_centre_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Cost Centre Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Cost Centre Co'

    b.save_master(comp, 'cost_category', {'name': 'Departments'})
    b.save_master(comp, 'cost_centre', {'name': 'Marketing', 'category': 'Departments'})
    b.save_master(comp, 'cost_centre', {'name': 'Engineering', 'category': 'Departments'})
    b.save_master(comp, 'ledger', {'name': 'Bank', 'parent': 'Bank Accounts', 'opening_balance': '50000.00', 'drcr': 'Dr'})
    b.save_master(comp, 'ledger', {'name': 'Staff Welfare', 'parent': 'Indirect Expenses', 'opening_balance': '0.00'})

    # 1. Post voucher with valid COSTCENTREALLOCATIONS
    # Total Welfare expense = 1,000: Marketing 400, Engineering 600
    v_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Payment',
        'VOUCHERNUMBER': 'CC-01',
        'DATE': '20260405',
        'ALLLEDGERENTRIES.LIST': [
            {
                'LEDGERNAME': 'Staff Welfare',
                'AMOUNT': '1000.00',
                'ISDEEMEDPOSITIVE': 'Yes',
                'COSTCENTREALLOCATIONS.LIST': [
                    {'NAME': 'Marketing', 'AMOUNT': '400.00', 'CATEGORY': 'Departments'},
                    {'NAME': 'Engineering', 'AMOUNT': '600.00', 'CATEGORY': 'Departments'}
                ]
            },
            {'LEDGERNAME': 'Bank', 'AMOUNT': '-1000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    assert v_id is not None

    # 2. Attempt voucher where allocations do not sum to entry amount -> ValueError
    with pytest.raises(ValueError, match="Cost centre allocations sum"):
        b.post_voucher(comp, {
            'VOUCHERTYPENAME': 'Payment',
            'VOUCHERNUMBER': 'CC-02',
            'DATE': '20260406',
            'ALLLEDGERENTRIES.LIST': [
                {
                    'LEDGERNAME': 'Staff Welfare',
                    'AMOUNT': '1000.00',
                    'ISDEEMEDPOSITIVE': 'Yes',
                    'COSTCENTREALLOCATIONS.LIST': [
                        {'NAME': 'Marketing', 'AMOUNT': '400.00', 'CATEGORY': 'Departments'},
                        {'NAME': 'Engineering', 'AMOUNT': '500.00', 'CATEGORY': 'Departments'} # Only 900
                    ]
                },
                {'LEDGERNAME': 'Bank', 'AMOUNT': '-1000.00', 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })

    # Check Cost Centre Breakup Report for Marketing
    breakup = b.cost_centre_breakup(comp, 'Marketing')
    assert breakup['cost_centre'] == 'Marketing'
    assert decimal(breakup['total_debit']) == Decimal('400.00')
    assert len(breakup['transactions']) == 1
    assert breakup['transactions'][0]['ledger'] == 'Staff Welfare'

    # Check Cost Category Summary
    summary = b.cost_category_summary(comp)
    assert len(summary['categories']) == 1
    cat = summary['categories'][0]
    assert cat['category'] == 'Departments'
    assert decimal(cat['total_debit']) == Decimal('1000.00')
    cc_names = [cc['name'] for cc in cat['cost_centres']]
    assert 'Marketing' in cc_names
    assert 'Engineering' in cc_names


def test_manufacturing_and_bom(tmp_path):
    """Module 5: Test Bill of Materials (BOM) and Manufacturing Journal."""
    b = Books(tmp_path / "mfg_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Mfg Industrial Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Mfg Industrial Co'

    b.save_master(comp, 'unit', {'name': 'nos', 'factor': '1'})
    b.save_master(comp, 'unit', {'name': 'kg', 'factor': '1'})
    b.save_master(comp, 'ledger', {'name': 'Wages', 'parent': 'Direct Expenses', 'opening_balance': '0.00'})
    b.save_master(comp, 'ledger', {'name': 'Bank', 'parent': 'Bank Accounts', 'opening_balance': '50000.00', 'drcr': 'Dr'})

    # Raw material components
    b.save_master(comp, 'stock_item', {
        'name': 'Raw Steel', 'base_units': 'kg',
        'opening_qty': '500', 'opening_rate': '50.00'  # 500 kg @ 50 = 25,000
    })
    b.save_master(comp, 'stock_item', {
        'name': 'Rubber Handle', 'base_units': 'nos',
        'opening_qty': '200', 'opening_rate': '10.00'  # 200 nos @ 10 = 2,000
    })

    # Finished Good with BOM
    # To produce 1 unit of "Steel Hammer": requires 2 kg Raw Steel and 1 Rubber Handle
    b.save_master(comp, 'stock_item', {
        'name': 'Steel Hammer', 'base_units': 'nos',
        'opening_qty': '0', 'opening_balance': '0.00',
        'bom': {
            'name': 'Standard Hammer BOM',
            'unit_qty': 1,
            'components': [
                {'item': 'Raw Steel', 'qty': 2},
                {'item': 'Rubber Handle', 'qty': 1}
            ]
        }
    })

    # Post Manufacturing Journal to produce 10 Steel Hammers
    # Raw materials consumed:
    # - Raw Steel: 10 * 2 = 20 kg @ 50 = 1000.00
    # - Rubber Handle: 10 * 1 = 10 nos @ 10 = 100.00
    # Total raw material cost = 1100.00
    # Additional cost: Wages = 200.00
    # Total finished goods cost = 1300.00 (rate per hammer = 130.00)
    v_id = b.post_manufacturing_journal(
        comp, 'Steel Hammer', 10,
        date='20260410', voucher_number='MFG-001',
        additional_costs=[{'ledger': 'Wages', 'amount': '200.00', 'balancing_ledger': 'Bank'}]
    )
    assert v_id is not None

    # Check stock summary
    view = b.view(comp)
    items = view['stock_items']

    # Raw Steel: 500 - 20 = 480 kg
    assert decimal(items['Raw Steel']['closing_qty']) == Decimal('480')
    # Rubber Handle: 200 - 10 = 190 nos
    assert decimal(items['Rubber Handle']['closing_qty']) == Decimal('190')
    # Steel Hammer: 0 + 10 = 10 nos, closing value = 1300.00, rate = 130.00
    assert decimal(items['Steel Hammer']['closing_qty']) == Decimal('10')
    assert decimal(items['Steel Hammer']['closing_balance']) == Decimal('1300.00')
    assert decimal(items['Steel Hammer']['closing_rate']) == Decimal('130.00')

    # Check accounting entry for additional costs
    wages_ledger = view['ledgers']['Wages']
    assert decimal(wages_ledger['signed_closing']) == Decimal('200.00')


def test_company_pin_security_and_api(tmp_path):
    """Module 6: Test Local Company PIN Lock, authentication, and API gates."""
    b = Books(tmp_path / "pin_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Secure Vault Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Secure Vault Co'

    # Initial state: company is not locked
    assert b.is_company_locked(comp) is False
    assert b.verify_company_pin(comp, None) is True

    # Set PIN to '9876'
    b.set_company_pin(comp, '9876')
    assert b.is_company_locked(comp) is True
    assert b.verify_company_pin(comp, '9876') is True
    assert b.verify_company_pin(comp, '1111') is False
    assert b.verify_company_pin(comp, '') is False

    # Changing PIN without current PIN fails
    with pytest.raises(ValueError, match="Current PIN is incorrect"):
        b.set_company_pin(comp, '5555', old_pin='wrong')

    # Changing PIN with correct old PIN succeeds
    b.set_company_pin(comp, '5555', old_pin='9876')
    assert b.verify_company_pin(comp, '5555') is True

    # Start HTTP server to test PIN gating
    server = make_server(port=0, data_path=tmp_path / "pin_test.sqlite3")
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        # GET /api/data without PIN -> 401 Unauthorized
        req = urllib.request.Request(f"{base_url}/api/data?company={urllib.parse.quote(comp)}")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 401
        err_body = json.loads(exc_info.value.read().decode('utf-8'))
        assert err_body['is_locked'] is True

        # GET /api/data with wrong PIN header -> 401 Unauthorized
        req_wrong = urllib.request.Request(f"{base_url}/api/data?company={urllib.parse.quote(comp)}", headers={'X-Company-PIN': '0000'})
        with pytest.raises(urllib.error.HTTPError) as exc_info2:
            urllib.request.urlopen(req_wrong)
        assert exc_info2.value.code == 401

        # GET /api/data with correct PIN header -> 200 OK
        req_correct = urllib.request.Request(f"{base_url}/api/data?company={urllib.parse.quote(comp)}", headers={'X-Company-PIN': '5555'})
        with urllib.request.urlopen(req_correct) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode('utf-8'))
            assert data['active_company'] == comp

        # POST /api/verify_company_pin -> valid: True
        post_data = json.dumps({'company': comp, 'pin': '5555'}).encode('utf-8')
        v_req = urllib.request.Request(f"{base_url}/api/verify_company_pin", data=post_data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(v_req) as resp:
            v_res = json.loads(resp.read().decode('utf-8'))
            assert v_res['valid'] is True

    finally:
        server.shutdown()
        server.server_close()


def test_voucher_register_paging_and_performance(tmp_path):
    """Module 7: Test voucher_register pagination, query filtering, and sorting."""
    b = Books(tmp_path / "paging_test.sqlite3")
    b.create_or_alter_company({
        'name': 'Paging Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Paging Co'

    b.save_master(comp, 'ledger', {'name': 'Cash', 'parent': 'Cash-in-hand', 'opening_balance': '50000.00', 'drcr': 'Dr'})
    b.save_master(comp, 'ledger', {'name': 'Sales A/c', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})

    # Generate 25 sales vouchers
    for i in range(1, 26):
        b.post_voucher(comp, {
            'VOUCHERTYPENAME': 'Sales',
            'VOUCHERNUMBER': f"INV-{i:03d}",
            'DATE': f"202604{i:02d}",
            'NARRATION': f"Sale order transaction {i}",
            'ALLLEDGERENTRIES.LIST': [
                {'LEDGERNAME': 'Cash', 'AMOUNT': str(i * 100), 'ISDEEMEDPOSITIVE': 'Yes'},
                {'LEDGERNAME': 'Sales A/c', 'AMOUNT': str(-i * 100), 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })

    # Page 1 with page_size=10
    reg_p1 = b.voucher_register(comp, page=1, page_size=10, sort_by='date', sort_order='asc')
    assert reg_p1['total_count'] == 25
    assert reg_p1['total_pages'] == 3
    assert reg_p1['page'] == 1
    assert len(reg_p1['items']) == 10
    assert reg_p1['items'][0]['voucher_number'] == 'INV-001'

    # Page 3 with page_size=10 (remaining 5)
    reg_p3 = b.voucher_register(comp, page=3, page_size=10, sort_by='date', sort_order='asc')
    assert reg_p3['page'] == 3
    assert len(reg_p3['items']) == 5
    assert reg_p3['items'][-1]['voucher_number'] == 'INV-025'

    # Search filter
    reg_search = b.voucher_register(comp, search='INV-015')
    assert reg_search['total_count'] == 1
    assert reg_search['items'][0]['voucher_number'] == 'INV-015'

    # Sort by amount descending
    reg_sorted = b.voucher_register(comp, sort_by='amount', sort_order='desc', page_size=5)
    assert reg_sorted['items'][0]['voucher_number'] == 'INV-025'  # 2500 is highest amount


def test_tally_xml_interchange_parity(tmp_path):
    """Test XML Export and Import preserves credit limits, HSN codes, and voucher allocations."""
    b = Books(tmp_path / "xml_test.sqlite3")
    b.create_or_alter_company({
        'name': 'XML Parity Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'XML Parity Co'

    b.save_master(comp, 'unit', {'name': 'pcs', 'factor': '1'})
    b.save_master(comp, 'stock_item', {
        'name': 'Electronic Gadget', 'base_units': 'pcs',
        'hsn_code': '8517', 'description': 'Smartphone handset',
        'opening_qty': '10', 'opening_rate': '15000.00'
    })
    b.save_master(comp, 'ledger', {
        'name': 'Premier Electronics', 'parent': 'Sundry Debtors',
        'opening_balance': '0.00', 'credit_limit': '150000.00'
    })
    b.save_master(comp, 'ledger', {'name': 'Sales Account', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})

    # Export XML
    company_data = b.get_company(comp)
    xml_str = export_xml(company_data)

    # Check exported XML contains CREDITLIMIT and HSNCODE
    assert '<CREDITLIMIT>150000.00</CREDITLIMIT>' in xml_str
    assert '<HSNCODE>8517</HSNCODE>' in xml_str

    # Import XML into a fresh Books instance
    b2 = Books(tmp_path / "xml_import_test.sqlite3")
    apply_import(b2, {'xml': xml_str, 'company': comp})

    # Verify imported data
    c2 = b2.get_company(comp)
    assert c2['ledgers']['Premier Electronics']['credit_limit'] == '150000.00'
    assert c2['stock_items']['Electronic Gadget']['hsn_code'] == '8517'
    assert c2['stock_items']['Electronic Gadget']['description'] == 'Smartphone handset'


def test_edge_cases_empty_and_boundaries(tmp_path):
    """Test boundary and error edge cases across all modules."""
    b = Books(tmp_path / "edge_cases.sqlite3")
    b.create_or_alter_company({
        'name': 'Edge Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Edge Co'

    # 1. Empty GSTR-1 and GSTR-3B reports
    g1_empty = b.gstr1_report(comp)
    assert g1_empty['summary']['invoice_count'] == 0
    assert g1_empty['b2b'] == []
    assert g1_empty['b2cl'] == []
    assert g1_empty['b2cs'] == []

    g3_empty = b.gstr3b_report(comp)
    assert decimal(g3_empty['table_6_1_payment']['total_cash_payable']) == Decimal('0.00')

    # 2. BRS errors on unknown bank ledger or voucher without bank entry
    with pytest.raises(ValueError, match="Unknown bank ledger"):
        b.bank_reconciliation_statement(comp, "NonExistentBank")

    b.save_master(comp, 'ledger', {'name': 'Bank A', 'parent': 'Bank Accounts', 'opening_balance': '0.00'})
    b.save_master(comp, 'ledger', {'name': 'Cash', 'parent': 'Cash-in-hand', 'opening_balance': '1000.00'})
    b.save_master(comp, 'ledger', {'name': 'Rent', 'parent': 'Indirect Expenses', 'opening_balance': '0.00'})
    v_cash_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Payment',
        'VOUCHERNUMBER': 'PMT-CASH',
        'DATE': '20260402',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Rent', 'AMOUNT': '100.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Cash', 'AMOUNT': '-100.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    with pytest.raises(ValueError, match="Ledger Bank A not found on voucher"):
        b.set_bank_date(comp, v_cash_id, 'Bank A', '20260405')

    # 3. Manufacturing error on missing BOM or negative qty
    b.save_master(comp, 'unit', {'name': 'pcs', 'factor': '1'})
    b.save_master(comp, 'stock_item', {'name': 'NoBOMItem', 'base_units': 'pcs', 'opening_qty': '0', 'opening_balance': '0.00'})
    with pytest.raises(ValueError, match="No BOM"):
        b.post_manufacturing_journal(comp, 'NoBOMItem', 10)

    # 4. PIN Lock clear by passing empty string
    assert b.is_company_locked(comp) is False
    b.set_company_pin(comp, '1234')
    assert b.is_company_locked(comp) is True
    # Clear PIN
    b.set_company_pin(comp, '', old_pin='1234')
    assert b.is_company_locked(comp) is False

    # 5. Voucher register out-of-bounds page and filtering by type
    b.save_master(comp, 'ledger', {'name': 'Sales', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'S-01',
        'DATE': '20260403',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Cash', 'AMOUNT': '500.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales', 'AMOUNT': '-500.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    # Filter by voucher_type Payment vs Sales
    reg_pmt = b.voucher_register(comp, voucher_type='Payment')
    assert reg_pmt['total_count'] == 1
    assert reg_pmt['items'][0]['voucher_type'] == 'Payment'

    reg_sales = b.voucher_register(comp, voucher_type='Sales')
    assert reg_sales['total_count'] == 1
    assert reg_sales['items'][0]['voucher_type'] == 'Sales'

    # Out of bounds page
    reg_oob = b.voucher_register(comp, page=50, page_size=10)
    assert reg_oob['total_count'] == 2
    assert reg_oob['items'] == []


def test_gstr1_credit_notes_and_reconciliation(tmp_path):
    """Test GSTR-1 correctly segregates B2B Credit Notes into CDNR and nets B2CS returns."""
    b = Books(tmp_path / "gst_cn_test.sqlite3")
    b.create_or_alter_company({
        'name': 'GST CN Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
        'state': 'West Bengal',
        'gstin': '19AAAAA0000A1Z5'
    })
    comp = 'GST CN Co'

    b.save_master(comp, 'unit', {'name': 'pcs', 'factor': '1'})
    b.save_master(comp, 'stock_item', {
        'name': 'Widget A', 'base_units': 'pcs', 'gst_rate': '18',
        'hsn_code': '8400', 'opening_qty': '100', 'opening_rate': '100.00'
    })
    b.save_master(comp, 'ledger', {'name': 'Sales A/c', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})
    b.save_master(comp, 'ledger', {
        'name': 'Registered Client', 'parent': 'Sundry Debtors',
        'gstin': '19XYZAB1234C1Z9', 'state': 'West Bengal', 'opening_balance': '0.00'
    })
    b.save_master(comp, 'ledger', {
        'name': 'Retail Consumer', 'parent': 'Sundry Debtors',
        'gstin': '', 'state': 'West Bengal', 'opening_balance': '0.00'
    })

    # 1. B2B Sale of 10,000 + 18% GST (900 CGST + 900 SGST) = 11,800
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-001',
        'DATE': '20260405',
        'PARTYLEDGERNAME': 'Registered Client',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Widget A', 'ACTUALQTY': '10 pcs', 'BILLEDQTY': '10 pcs', 'RATE': '1000.00', 'AMOUNT': '10000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Registered Client', 'AMOUNT': '11800.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-10000.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'CGST', 'AMOUNT': '-900.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'SGST', 'AMOUNT': '-900.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # 2. B2B Credit Note (Return of 2 pcs): 2,000 + 18% GST (180 CGST + 180 SGST) = 2,360
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Credit Note',
        'VOUCHERNUMBER': 'CN-001',
        'DATE': '20260410',
        'PARTYLEDGERNAME': 'Registered Client',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Widget A', 'ACTUALQTY': '2 pcs', 'BILLEDQTY': '2 pcs', 'RATE': '1000.00', 'AMOUNT': '2000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Registered Client', 'AMOUNT': '-2360.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '2000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'CGST', 'AMOUNT': '180.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'SGST', 'AMOUNT': '180.00', 'ISDEEMEDPOSITIVE': 'Yes'}
        ]
    })

    # 3. B2CS Retail Sale: 5,000 + 18% GST (450 CGST + 450 SGST) = 5,900
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales',
        'VOUCHERNUMBER': 'INV-RET-01',
        'DATE': '20260412',
        'PARTYLEDGERNAME': 'Retail Consumer',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Widget A', 'ACTUALQTY': '5 pcs', 'BILLEDQTY': '5 pcs', 'RATE': '1000.00', 'AMOUNT': '5000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Retail Consumer', 'AMOUNT': '5900.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '-5000.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'CGST', 'AMOUNT': '-450.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'SGST', 'AMOUNT': '-450.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # 4. B2CS Retail Return (Credit Note): 1,000 + 18% GST (90 CGST + 90 SGST) = 1,180
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Credit Note',
        'VOUCHERNUMBER': 'CN-RET-01',
        'DATE': '20260414',
        'PARTYLEDGERNAME': 'Retail Consumer',
        'ALLINVENTORYENTRIES.LIST': [
            {'STOCKITEMNAME': 'Widget A', 'ACTUALQTY': '1 pcs', 'BILLEDQTY': '1 pcs', 'RATE': '1000.00', 'AMOUNT': '1000.00'}
        ],
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Retail Consumer', 'AMOUNT': '-1180.00', 'ISDEEMEDPOSITIVE': 'No'},
            {'LEDGERNAME': 'Sales A/c', 'AMOUNT': '1000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'CGST', 'AMOUNT': '90.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'SGST', 'AMOUNT': '90.00', 'ISDEEMEDPOSITIVE': 'Yes'}
        ]
    })

    # Run GSTR-1
    g1 = b.gstr1_report(comp, '20260401', '20260430')

    # B2B must have only the invoice (INV-001)
    assert len(g1['b2b']) == 1
    assert len(g1['b2b'][0]['inv']) == 1
    assert g1['b2b'][0]['inv'][0]['inum'] == 'INV-001'

    # CDNR must have the credit note (CN-001) with ntty: 'C'
    assert len(g1['cdnr']) == 1
    assert g1['cdnr'][0]['ctin'] == '19XYZAB1234C1Z9'
    assert len(g1['cdnr'][0]['nt']) == 1
    assert g1['cdnr'][0]['nt'][0]['nt_num'] == 'CN-001'
    assert g1['cdnr'][0]['nt'][0]['ntty'] == 'C'
    assert g1['cdnr'][0]['nt'][0]['val'] == 2360.0

    # B2CS must be NET of return: 5,000 - 1,000 = 4,000 taxable; CGST 360, SGST 360
    assert len(g1['b2cs']) == 1
    assert g1['b2cs'][0]['txval'] == 4000.0
    assert g1['b2cs'][0]['camt'] == 360.0
    assert g1['b2cs'][0]['samt'] == 360.0

    # Table 12 HSN: must have 'num': 1 and net qty = 10 - 2 + 5 - 1 = 12 pcs, net txval = 12,000
    assert len(g1['hsn']['data']) == 1
    hsn_row = g1['hsn']['data'][0]
    assert hsn_row['num'] == 1
    assert hsn_row['hsn_sc'] == '8400'
    assert hsn_row['qty'] == 12.0
    assert hsn_row['txval'] == 12000.0

    # Summary net outward supplies:
    # Net taxable = (10,000 - 2,000) + (5,000 - 1,000) = 12,000
    # Net CGST = 900 - 180 + 450 - 90 = 1080
    assert decimal(g1['summary']['total_taxable_value']) == Decimal('12000.00')
    assert decimal(g1['summary']['total_cgst']) == Decimal('1080.00')
    assert decimal(g1['summary']['total_sgst']) == Decimal('1080.00')

    # GSTR-3B Table 3.1 outward taxable supplies must reconcile exactly:
    g3 = b.gstr3b_report(comp, '20260401', '20260430')
    t31 = g3['table_3_1']['outward_taxable_supplies']
    assert decimal(t31['txval']) == Decimal('12000.00')
    assert decimal(t31['camt']) == Decimal('1080.00')
    assert decimal(t31['samt']) == Decimal('1080.00')


def test_credit_limit_journal_and_guid_alteration(tmp_path):
    """Test credit limit blocks journal debits and altering by GUID works without double counting."""
    b = Books(tmp_path / "cl_journal.sqlite3")
    b.create_or_alter_company({
        'name': 'CL Journal Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'CL Journal Co'

    # Master with 20,000 credit limit
    b.save_master(comp, 'ledger', {
        'name': 'Client A', 'parent': 'Sundry Debtors',
        'opening_balance': '0.00', 'credit_limit': '20000.00'
    })
    b.save_master(comp, 'ledger', {'name': 'Service Revenue', 'parent': 'Direct Incomes', 'opening_balance': '0.00'})

    # 1. Negative credit limit rejected in save_master
    with pytest.raises(ValueError, match="Credit limit cannot be negative"):
        b.save_master(comp, 'ledger', {'name': 'Bad Limit', 'parent': 'Sundry Debtors', 'credit_limit': '-500'})

    # 2. Journal voucher without PARTYLEDGERNAME header that debits Client A by 25,000 -> Blocked!
    with pytest.raises(ValueError, match="Credit limit .* exceeded for Client A"):
        b.post_voucher(comp, {
            'VOUCHERTYPENAME': 'Journal',
            'VOUCHERNUMBER': 'J-01',
            'DATE': '20260405',
            'ALLLEDGERENTRIES.LIST': [
                {'LEDGERNAME': 'Client A', 'AMOUNT': '25000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
                {'LEDGERNAME': 'Service Revenue', 'AMOUNT': '-25000.00', 'ISDEEMEDPOSITIVE': 'No'}
            ]
        })

    # 3. Journal voucher within limit: 15,000 -> Succeeds
    v_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Journal',
        'VOUCHERNUMBER': 'J-01',
        'DATE': '20260405',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Client A', 'AMOUNT': '15000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Service Revenue', 'AMOUNT': '-15000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    c = b.get_company(comp)
    voucher = next(v for v in c['vouchers'] if str(v.get('MASTERID')) == str(v_id))
    guid = voucher.get('GUID')

    # 4. Alter existing voucher by GUID: changing amount from 15,000 to 18,000 (still <= 20,000 limit)
    # If old was not excluded, it would think 15,000 + 18,000 = 33,000 > 20,000 and fail!
    altered_id = b.post_voucher(comp, {
        '@ACTION': 'Alter',
        'GUID': guid,
        'VOUCHERTYPENAME': 'Journal',
        'VOUCHERNUMBER': 'J-01',
        'DATE': '20260405',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Client A', 'AMOUNT': '18000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Service Revenue', 'AMOUNT': '-18000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    assert altered_id is not None
    assert b.party_balance(comp, 'Client A') == Decimal('18000.00')


def test_manufacturing_multigodown_and_split_balancing(tmp_path):
    """Test Manufacturing Journal with components from multiple godowns and distinct balancing ledgers."""
    b = Books(tmp_path / "mfg_multi.sqlite3")
    b.create_or_alter_company({
        'name': 'Mfg Multi Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Mfg Multi Co'

    b.save_master(comp, 'unit', {'name': 'kg', 'factor': '1'})
    b.save_master(comp, 'unit', {'name': 'nos', 'factor': '1'})
    b.save_master(comp, 'godown', {'name': 'Warehouse North'})
    b.save_master(comp, 'godown', {'name': 'Warehouse South'})
    b.save_master(comp, 'godown', {'name': 'Assembly Plant'})
    b.save_master(comp, 'ledger', {'name': 'Wages', 'parent': 'Direct Expenses', 'opening_balance': '0.00'})
    b.save_master(comp, 'ledger', {'name': 'Electricity', 'parent': 'Direct Expenses', 'opening_balance': '0.00'})
    b.save_master(comp, 'ledger', {'name': 'Cash', 'parent': 'Cash-in-hand', 'opening_balance': '10000.00', 'drcr': 'Dr'})
    b.save_master(comp, 'ledger', {'name': 'Bank', 'parent': 'Bank Accounts', 'opening_balance': '50000.00', 'drcr': 'Dr'})

    # Raw materials with godowns
    b.save_master(comp, 'stock_item', {
        'name': 'Steel Sheet', 'base_units': 'kg',
        'opening_qty': '100', 'opening_rate': '100.00', 'godown': 'Warehouse North'
    })
    b.save_master(comp, 'stock_item', {
        'name': 'Plastic Case', 'base_units': 'nos',
        'opening_qty': '50', 'opening_rate': '20.00', 'godown': 'Warehouse South'
    })

    # Finished Good with BOM specifying component godowns
    b.save_master(comp, 'stock_item', {
        'name': 'Finished Machine', 'base_units': 'nos', 'godown': 'Assembly Plant',
        'bom': {
            'name': 'Machine Assembly BOM',
            'unit_qty': 1,
            'components': [
                {'item': 'Steel Sheet', 'qty': 5, 'godown': 'Warehouse North'},
                {'item': 'Plastic Case', 'qty': 2, 'godown': 'Warehouse South'}
            ]
        }
    })

    # Post manufacturing journal with multiple additional costs using different balancing ledgers:
    # - Wages 300 from Cash
    # - Electricity 500 from Bank
    v_id = b.post_manufacturing_journal(
        comp, 'Finished Machine', 2,
        date='20260410', voucher_number='MFG-MULTI-01',
        additional_costs=[
            {'ledger': 'Wages', 'amount': '300.00', 'balancing_ledger': 'Cash'},
            {'ledger': 'Electricity', 'amount': '500.00', 'balancing_ledger': 'Bank'}
        ]
    )
    assert v_id is not None

    c = b.get_company(comp)
    vch = next(v for v in c['vouchers'] if str(v.get('MASTERID')) == str(v_id))

    # Check consumption godowns
    consump = vch['CONSUMPTIONENTRIES.LIST']
    steel_entry = next(e for e in consump if e['STOCKITEMNAME'] == 'Steel Sheet')
    plastic_entry = next(e for e in consump if e['STOCKITEMNAME'] == 'Plastic Case')
    assert steel_entry['GODOWN'] == 'Warehouse North'
    assert plastic_entry['GODOWN'] == 'Warehouse South'

    # Check production godown
    assert vch['PRODUCTIONENTRIES.LIST'][0]['GODOWN'] == 'Assembly Plant'

    # Check additional ledger entries balance:
    # Wages (+300), Cash (-300), Electricity (+500), Bank (-500) -> Net 0
    ledger_entries = vch['ALLLEDGERENTRIES.LIST']
    assert len(ledger_entries) == 4
    net_ledger = sum((decimal(e['AMOUNT']) for e in ledger_entries), Decimal('0.00'))
    assert net_ledger == Decimal('0.00')

    # Total cost of 2 machines:
    # Steel: 2 * 5 = 10 kg @ 100 = 1000.00
    # Plastic: 2 * 2 = 4 nos @ 20 = 80.00
    # Additional: 300 + 500 = 800.00
    # Total = 1880.00 (940.00 per machine)
    assert decimal(vch['PRODUCTIONENTRIES.LIST'][0]['AMOUNT']) == Decimal('1880.00')
    assert decimal(vch['PRODUCTIONENTRIES.LIST'][0]['RATE']) == Decimal('940.00')


def test_tally_category_allocations_and_bom_xml(tmp_path):
    """Test Tally XML CATEGORYALLOCATIONS.LIST support and BOM XML serialization roundtrip."""
    b = Books(tmp_path / "xml_roundtrip.sqlite3")
    b.create_or_alter_company({
        'name': 'XML Full Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'XML Full Co'

    b.save_master(comp, 'unit', {'name': 'nos', 'factor': '1'})
    b.save_master(comp, 'stock_item', {
        'name': 'Bolt', 'base_units': 'nos', 'opening_qty': '100', 'opening_rate': '5.00'
    })
    b.save_master(comp, 'stock_item', {
        'name': 'Wheel', 'base_units': 'nos', 'opening_qty': '0', 'opening_balance': '0.00',
        'bom': {
            'name': 'Wheel Assembly',
            'unit_qty': 1,
            'components': [{'item': 'Bolt', 'qty': 4}]
        }
    })
    b.save_master(comp, 'ledger', {'name': 'Bank', 'parent': 'Bank Accounts', 'opening_balance': '10000.00', 'drcr': 'Dr'})
    b.save_master(comp, 'ledger', {'name': 'Printing', 'parent': 'Indirect Expenses', 'opening_balance': '0.00'})

    # Post voucher using nested CATEGORYALLOCATIONS.LIST (Tally XML standard format)
    v_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Payment',
        'VOUCHERNUMBER': 'CAT-01',
        'DATE': '20260408',
        'ALLLEDGERENTRIES.LIST': [
            {
                'LEDGERNAME': 'Printing',
                'AMOUNT': '500.00',
                'ISDEEMEDPOSITIVE': 'Yes',
                'CATEGORYALLOCATIONS.LIST': [
                    {
                        'CATEGORY': 'Branch Overhead',
                        'COSTCENTREALLOCATIONS.LIST': [
                            {'NAME': 'Kolkata Office', 'AMOUNT': '500.00'}
                        ]
                    }
                ]
            },
            {'LEDGERNAME': 'Bank', 'AMOUNT': '-500.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    assert v_id is not None

    # Check that cost_centre_breakup and cost_category_summary recognize the nested allocation
    breakup = b.cost_centre_breakup(comp, 'Kolkata Office')
    assert breakup['total_debit'] == '500.00'

    summary = b.cost_category_summary(comp)
    assert len(summary['categories']) == 1
    assert summary['categories'][0]['category'] == 'Branch Overhead'
    assert summary['categories'][0]['cost_centres'][0]['name'] == 'Kolkata Office'

    # Export XML and check BOM MULTICOMPONENTLIST is present
    xml_data = export_xml(b.get_company(comp))
    assert '<MULTICOMPONENTLIST.LIST>' in xml_data
    assert '<STOCKITEMNAME>Bolt</STOCKITEMNAME>' in xml_data

    # Import into fresh database and verify BOM was preserved
    b2 = Books(tmp_path / "xml_import_roundtrip.sqlite3")
    apply_import(b2, {'xml': xml_data, 'company': comp})
    c2 = b2.get_company(comp)
    assert 'Wheel' in c2['stock_items']
    assert c2['stock_items']['Wheel']['bom']['components'][0]['item'] == 'Bolt'
    assert c2['stock_items']['Wheel']['bom']['components'][0]['qty'] == 4.0


def test_cancelled_voucher_bank_date_and_custom_vtype_paging(tmp_path):
    """Test set_bank_date rejects cancelled vouchers and voucher_register matches custom types."""
    b = Books(tmp_path / "vreg_custom.sqlite3")
    b.create_or_alter_company({
        'name': 'Custom VType Co',
        'starting_from': '20260401',
        'ending_at': '20270331',
    })
    comp = 'Custom VType Co'

    b.save_master(comp, 'ledger', {'name': 'Bank A', 'parent': 'Bank Accounts', 'opening_balance': '10000.00', 'drcr': 'Dr'})
    b.save_master(comp, 'ledger', {'name': 'Sales A', 'parent': 'Sales Accounts', 'opening_balance': '0.00'})
    # Custom voucher type 'GST Invoice' whose parent is 'Sales'
    b.save_master(comp, 'voucher_type', {'name': 'GST Invoice', 'parent': 'Sales', 'base_type': 'Sales'})

    # Post 1 regular Sales voucher and 1 GST Invoice voucher
    b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'Sales', 'VOUCHERNUMBER': 'S-1', 'DATE': '20260402',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Bank A', 'AMOUNT': '1000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales A', 'AMOUNT': '-1000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })
    v2_id = b.post_voucher(comp, {
        'VOUCHERTYPENAME': 'GST Invoice', 'VOUCHERNUMBER': 'GST-1', 'DATE': '20260404',
        'ALLLEDGERENTRIES.LIST': [
            {'LEDGERNAME': 'Bank A', 'AMOUNT': '2000.00', 'ISDEEMEDPOSITIVE': 'Yes'},
            {'LEDGERNAME': 'Sales A', 'AMOUNT': '-2000.00', 'ISDEEMEDPOSITIVE': 'No'}
        ]
    })

    # Filter voucher_register by 'Sales': should find BOTH S-1 and GST-1
    reg = b.voucher_register(comp, voucher_type='Sales')
    assert reg['total_count'] == 2

    # Filter voucher_register by specific 'GST Invoice': should find only GST-1
    reg_gst = b.voucher_register(comp, voucher_type='GST Invoice')
    assert reg_gst['total_count'] == 1
    assert reg_gst['items'][0]['voucher_number'] == 'GST-1'

    # Cancel GST Invoice voucher
    b.cancel_or_delete_voucher(comp, v2_id, delete=False)

    # Attempt to set bank date on cancelled voucher -> must raise ValueError
    with pytest.raises(ValueError, match="Cannot set bank date on cancelled"):
        b.set_bank_date(comp, v2_id, 'Bank A', '20260405')

