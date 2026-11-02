"""Document inbox: bills and invoices waiting to be entered. Files sit next to the
books in an "inbox" folder; the company keeps the list. Nothing is ever deleted:
a file is entered (linked to its voucher) or set aside."""
import base64, datetime as dt, hashlib
from pathlib import Path

TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
MAX_BYTES = 20 * 1024 * 1024


def folder(db):
    return Path(db.data_file).resolve().parent / 'inbox'


def add(db, company, name, content_b64):
    name = Path(str(name or 'document')).name
    ext = Path(name).suffix.lower()
    if ext not in TYPES: raise ValueError('Inbox takes PDF, JPG, PNG or WEBP files')
    data = base64.b64decode(content_b64 or '')
    if not data: raise ValueError('The file is empty')
    if len(data) > MAX_BYTES: raise ValueError('Files over 20 MB are not taken')
    doc_id = hashlib.sha256(data).hexdigest()[:20]
    with db.transaction():
        docs = db.get_company(company).setdefault('inbox', [])
        same = next((d for d in docs if d['id'] == doc_id), None)
        if same: return {'duplicate': True, 'doc': same}
        path = folder(db) / (doc_id + ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists(): path.write_bytes(data)
        doc = {'id': doc_id, 'name': name, 'ext': ext, 'size': len(data), 'status': 'waiting',
               'received': dt.datetime.now().isoformat(timespec='seconds')}
        docs.append(doc)
        return {'duplicate': False, 'doc': doc}


def _doc(db, company, doc_id):
    doc = next((d for d in db.get_company(company).get('inbox', []) if d['id'] == doc_id), None)
    if not doc: raise ValueError('Document not found in the inbox')
    return doc


def read(db, company, doc_id):
    doc = _doc(db, company, doc_id)
    return (folder(db) / (doc['id'] + doc['ext'])).read_bytes(), TYPES[doc['ext']]


def set_status(db, company, doc_id, status):
    if status not in ('waiting', 'aside'): raise ValueError('Status must be waiting or aside')
    with db.transaction():
        doc = _doc(db, company, doc_id)
        if doc['status'] == 'entered': raise ValueError('This document is already entered as ' + doc.get('voucher', 'a voucher'))
        doc['status'] = status
        return {'doc': doc}


def link(db, company, doc_id, voucher_id):
    """Mark the document entered; called in the same transaction that posts the voucher."""
    doc = _doc(db, company, doc_id)
    if doc['status'] == 'entered': raise ValueError('This document is already entered as ' + doc.get('voucher', 'a voucher'))
    v = next(x for x in db.get_company(company)['vouchers'] if str(voucher_id) in (str(x.get('MASTERID')), str(x.get('GUID'))))
    doc.update(status='entered', voucher_id=str(voucher_id), voucher=f"{v['VOUCHERTYPENAME']} {v.get('VOUCHERNUMBER', '')}".strip(),
               entered=dt.datetime.now().isoformat(timespec='seconds'))
