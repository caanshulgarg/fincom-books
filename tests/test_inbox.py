import base64, json, threading, urllib.request, urllib.error
import pytest
from app_server import make_server

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


@pytest.fixture
def srv(tmp_path):
    s = make_server(0, str(tmp_path / 'b.sqlite3'))
    s.db.create_or_alter_company({'name': 'Co', 'starting_from': '20260401', 'ending_at': '20270331'})
    for n, g in [('Bank', 'Bank Accounts'), ('Supplier', 'Sundry Creditors')]:
        s.db.save_master('Co', 'ledger', {'name': n, 'parent': g, 'opening_balance': '0'})
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()


def call(s, path, body=None):
    url = f'http://127.0.0.1:{s.server_port}{path}'
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as r: return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e: return e.code, e.headers, e.read()


def payment(doc=None):
    return {'company': 'Co', 'inbox_doc': doc, 'voucher': {'VOUCHERTYPENAME': 'Payment', 'DATE': '20261001', 'PARTYLEDGERNAME': 'Supplier',
            'ALLLEDGERENTRIES.LIST': [{'LEDGERNAME': 'Supplier', 'AMOUNT': '-100', 'ISDEEMEDPOSITIVE': 'Yes'},
                                      {'LEDGERNAME': 'Bank', 'AMOUNT': '100', 'ISDEEMEDPOSITIVE': 'No'}]}}


def test_inbox_add_serve_link_and_duplicate(srv):
    st, _, body = call(srv, '/api/inbox_add', {'company': 'Co', 'name': 'bill 1.png', 'content': base64.b64encode(PNG).decode()})
    doc = json.loads(body)['doc']; assert st == 200 and doc['status'] == 'waiting'
    st, h, body = call(srv, f"/api/inbox_file?company=Co&id={doc['id']}")
    assert st == 200 and body == PNG and h['Content-Type'] == 'image/png' and "frame-ancestors 'self'" in h['Content-Security-Policy']
    assert json.loads(call(srv, '/api/inbox_add', {'company': 'Co', 'name': 'copy.png', 'content': base64.b64encode(PNG).decode()})[2])['duplicate']
    st, _, _ = call(srv, '/api/create_voucher', payment(doc['id'])); assert st == 200
    d = srv.db.get_company('Co')['inbox'][0]
    assert d['status'] == 'entered' and d['voucher'] == 'Payment 1'
    # a second voucher cannot claim the same bill, and the failed save posts nothing
    st, _, body = call(srv, '/api/create_voucher', payment(doc['id']))
    assert st >= 400 and b'already entered' in body
    assert len(srv.db.get_company('Co')['vouchers']) == 1
    st, _, _ = call(srv, '/api/inbox_set', {'company': 'Co', 'id': doc['id'], 'status': 'aside'}); assert st >= 400


def test_inbox_rejects_other_types_and_sets_aside(srv):
    st, _, body = call(srv, '/api/inbox_add', {'company': 'Co', 'name': 'x.exe', 'content': 'AAAA'}); assert st >= 400
    doc = json.loads(call(srv, '/api/inbox_add', {'company': 'Co', 'name': 'b.png', 'content': base64.b64encode(PNG).decode()})[2])['doc']
    call(srv, '/api/inbox_set', {'company': 'Co', 'id': doc['id'], 'status': 'aside'})
    assert srv.db.get_company('Co')['inbox'][0]['status'] == 'aside'
    assert call(srv, '/api/inbox_file?company=Co&id=nope')[0] >= 400
