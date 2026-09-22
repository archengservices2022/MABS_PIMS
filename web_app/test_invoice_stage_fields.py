"""Verify rendered invoice rows keep parallel form fields aligned."""
import ast
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import unittest
from unittest.mock import Mock

from jinja2 import Environment
from werkzeug.datastructures import MultiDict


class Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name'):
            self.fields.append((attrs['name'], attrs.get('value', '')))


class InvoiceStageFieldsTests(unittest.TestCase):
    def test_all_initial_row_variants_submit_aligned_metadata(self):
        source = Path(__file__).with_name('templates').joinpath('invoice_form.html').read_text(encoding='utf-8')
        fragment = source.split('<tbody id="lineItemsBody">', 1)[1].split('</tbody>', 1)[0]
        template = Environment().from_string(fragment)
        for overrides in ({}, {'prefill_proj': 'A'}, {'stage_idx': 0},
                          {'prefill_items': [{'project': 'A', 'stage_index': 0}]},
                          {'invoice': {'line_items': [{'project_number': 'A', 'payment_stage_index': 0}]}}):
            with self.subTest(overrides=overrides):
                context = dict(invoice=None, stage_idx='', prefill_items=[], prefill_proj='',
                               prefill_name='Road', stage_name='Installment 1 of 4', stage_amount=250,
                               project_select=lambda value: '', lock_unit_price=False)
                context.update(overrides)
                inputs = Inputs()
                inputs.feed(template.render(**context))
                fields = MultiDict(inputs.fields)
                for name in ('item_stage_index[]', 'item_co_number[]', 'item_co_firebase_id[]', 'item_powo_number[]'):
                    self.assertEqual(len(fields.getlist(name)), len(fields.getlist('item_description[]')))

    def test_saved_stage_names_and_co_details_stay_on_their_rows(self):
        tree = ast.parse(Path(__file__).with_name('app.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_parse_invoice_form')
        projects = {'a': {'project_number': 'A', 'po_wo_number': 'MAIN',
                         'payment_stages': [{'name': 'Installment 1 of 4'}] +
                             [{'name': f'co{i}', 'co_firebase_id': f'c{i}'} for i in range(1, 5)],
                         'change_orders': [{'firebase_id': f'c{i}', 'co_number': f'co{i}',
                                            'po_wo_number': f'PO{i}'} for i in range(1, 5)]}}
        env = dict(fb_get=lambda path: projects, _project_plant_display=lambda p: '',
                   _safe_float=lambda v: float(v or 0), log=Mock(), datetime=datetime, COMPANY_TZ=timezone.utc)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<parser>', 'exec'), env)
        form = MultiDict()
        for i in range(5):
            for name, value in {'item_description[]': 'Road' if i == 0 else f'co{i}',
                                'item_project[]': 'A', 'item_stage_index[]': str(i),
                                'item_quantity[]': '1', 'item_unit_price[]': '250' if i == 0 else '100',
                                'item_co_number[]': f'co{i}' if i else '',
                                'item_co_firebase_id[]': f'c{i}' if i else '',
                                'item_powo_number[]': f'PO{i}' if i else ''}.items():
                form.add(name, value)
        items = env['_parse_invoice_form'](form)['line_items']
        self.assertEqual([i['stage_name'] for i in items], ['Installment 1 of 4', 'co1', 'co2', 'co3', 'co4'])
        self.assertEqual([i['co_firebase_id'] for i in items], ['', 'c1', 'c2', 'c3', 'c4'])
        self.assertEqual([i['powo_number'] for i in items], ['MAIN', 'PO1', 'PO2', 'PO3', 'PO4'])


if __name__ == '__main__':
    unittest.main()
