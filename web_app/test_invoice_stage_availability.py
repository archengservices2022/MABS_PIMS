"""Offline regressions for invoice stage availability and duplicate submissions."""
import ast
import copy
from datetime import datetime
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

from jinja2 import Environment


class InvoiceStageAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path(__file__).with_name('app.py').read_text(encoding='utf-8'))
        names = {'_invoice_form_stage_options', '_duplicate_invoice_stage_rows',
                 '_invoice_stage_pairs', '_compute_project_invoice_pending', '_get_next_payment_stage'}
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        cls.env = {'_safe_float': lambda v: float(v or 0), 'log': Mock()}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<availability>', 'exec'), cls.env)

    def test_edit_catalog_releases_only_current_invoice_without_mutating_projects(self):
        project = {'project_number': 'A', 'payment_stages': [
            {'name': 'First', 'amount': 250, 'status': 'Invoiced', 'invoice_id': 'current'},
            {'name': 'Second', 'amount': 250, 'status': 'Pending Invoice'},
            {'name': 'Third', 'amount': 250, 'status': 'Paid', 'invoice_id': 'other'},
            {'name': 'co1', 'amount': 100, 'status': 'Invoiced', 'invoice_id': 'current',
             'co_number': 'co1', 'co_firebase_id': 'co-id'}],
            'change_orders': [{'co_number': 'co1', 'firebase_id': 'co-id', 'amount': 100, 'status': 'Approved'}]}
        invoices = {'current': {'meta': {'project_number': 'A'}, 'line_items': [
            {'project_number': 'A', 'payment_stage_index': 0},
            {'project_number': 'A', 'payment_stage_index': 3, 'co_firebase_id': 'co-id'}]}}
        before = copy.deepcopy(project)
        choices = self.env['_invoice_form_stage_options']([project], invoices, 'current')['A']
        self.assertEqual([s['stage_idx'] for s in choices['all_pending_stages']], [0, 1])
        self.assertEqual([s['stage_idx'] for s in choices['approved_pending_cos']], [3])
        self.assertEqual(project, before)
        new_choices = self.env['_invoice_form_stage_options']([project], invoices)['A']
        self.assertEqual([s['stage_idx'] for s in new_choices['all_pending_stages']], [1])
        self.assertEqual(new_choices['approved_pending_cos'], [])

    def test_duplicate_stage_zero_and_co_rejected_but_other_projects_allowed(self):
        duplicate = self.env['_duplicate_invoice_stage_rows']
        self.assertTrue(duplicate({'line_items': [
            {'project_number': 'A', 'payment_stage_index': 0},
            {'project_number': 'A', 'payment_stage_index': '0'}]}))
        self.assertTrue(duplicate({'meta': {'project_number': 'A'}, 'line_items': [
            {'co_firebase_id': 'co-id'}, {'project_number': 'A', 'co_firebase_id': 'co-id'}]}))
        self.assertFalse(duplicate({'line_items': [
            {'project_number': 'A', 'payment_stage_index': 0},
            {'project_number': 'B', 'payment_stage_index': 0}]}))

    def test_complete_rendered_javascript_syntax(self):
        source = Path(__file__).with_name('templates').joinpath('invoice_form.html').read_text(encoding='utf-8')
        script = source.split('{% block scripts %}', 1)[1].split('<script>', 1)[1].split('</script>', 1)[0]
        rendered = Environment().from_string(script).render(now=datetime.now(), projects=[], invoice=None)
        result = subprocess.run(['node', '--check'], input=rendered, encoding='utf-8', capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
