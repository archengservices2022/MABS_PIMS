"""Exercise actual PDF rendering without application startup or Firebase access."""
import ast
import copy
import io
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock

from flask import Flask, request
from pypdf import PdfReader


class InvoicePdfPerformanceTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name('app.py')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        names = {'_invoice_pdf_data_reader', '_generate_invoice_pdf_bytes',
                 '_generate_invoice_summary_pdf_bytes', 'invoicing_export_pdf_selected'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        for node in nodes:
            node.decorator_list = []
        self.calls = Counter()
        self.records = {'/projects': {'p': {'project_number': 'P-1', 'plant': 'TEST PLANT',
                         'po_wo_number': 'PO-123', 'project_name': 'Test project'}}}
        for i in range(3):
            self.records[f'/invoices/{i}'] = {
                'meta': {'invoice_number': f'INV-{i}', 'company_name': 'Test Client',
                         'project_number': 'P-1', 'subtotal': 100, 'total': 100},
                'line_items': [{'description': 'Engineering', 'quantity': 1,
                                'unit_price': 50, 'amount': 50, 'project_number': 'P-1'}] * 2}
        self.records['/clients/Test Client'] = {'email': 'test@example.com'}
        def read(path):
            self.calls[path] += 1
            if path in ('/invoices', '/clients'):
                raise AssertionError('Must not load entire invoice/client tables')
            return copy.deepcopy(self.records.get(path))
        self.env = dict(__file__=str(path), fb_get=read, datetime=datetime,
                        COMPANY_TZ=timezone.utc, log=logging.getLogger(__name__),
                        company_info=lambda: {'name': 'Test Company'},
                        _get_company_logo_path=lambda: None,
                        _safe_float=lambda v: float(v or 0),
                        _normalise_list=lambda v: list(v.values()) if isinstance(v, dict) else (v or []),
                        _pdf_job_style_footer=Mock(), _calculate_invoice_status=lambda inv: "Unpaid", request=request,
                        flash=Mock(), redirect=lambda v: v, url_for=lambda *a, **k: 'invoicing')
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), self.env)

    def test_combined_pdf_reads_each_record_once_and_preserves_content(self):
        app = Flask(__name__)
        with app.test_request_context('/?invoice_ids=2&invoice_ids=0&invoice_ids=1'):
            response = self.env['invoicing_export_pdf_selected']()
        self.assertEqual(response.mimetype, 'application/pdf')
        pdf = PdfReader(io.BytesIO(response.get_data()))
        texts = [page.extract_text() for page in pdf.pages]
        self.assertIn('INVOICE SUMMARY', texts[0])
        self.assertIn('INV-2', texts[1])
        self.assertIn('INV-0', texts[2])
        self.assertIn('INV-1', texts[3])
        self.assertIn('PO-123', texts[1])
        self.assertIn('TEST PLANT', texts[0])
        self.assertEqual(self.calls, Counter({path: 1 for path in self.records}))

    def test_reader_isolates_mutations_and_refreshes_next_export(self):
        reader = self.env['_invoice_pdf_data_reader']()
        reader('/invoices/0')['meta']['total'] = 999
        self.assertEqual(reader('/invoices/0')['meta']['total'], 100)
        self.assertIs(reader('/projects'), reader('/projects'))
        self.records['/invoices/0']['meta']['total'] = 200
        fresh = self.env['_invoice_pdf_data_reader']()
        self.assertEqual(fresh('/invoices/0')['meta']['total'], 200)
        self.assertIsNone(reader('/invoices/missing'))
        self.assertIsNone(reader('/invoices/missing'))
        self.assertEqual(self.calls['/invoices/missing'], 1)

    def test_single_invoice_reuses_projects_for_multiple_rows(self):
        pdf = self.env['_generate_invoice_pdf_bytes']('0')
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(self.calls['/projects'], 1)


if __name__ == '__main__':
    unittest.main()

