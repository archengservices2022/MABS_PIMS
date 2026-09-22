"""Isolated invoice-edit regression tests; no Firebase or application startup."""
import ast
import copy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class InvoiceEditUnlinkTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        names = {'invoice_edit', '_invoice_stage_pairs', '_unlink_removed_invoice_stages', '_duplicate_invoice_stage_rows'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        for node in nodes:
            node.decorator_list = []
        self.env = {'datetime': datetime, 'timezone': timezone}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(Path(__file__).with_name('app.py')), 'exec'), self.env)

    def run_edit(self, old_items, new_items, primary=None, fail_save=False):
        def item(project, stage):
            return {'project_number': project, 'payment_stage_index': stage, 'description': str(stage)}
        original = {'meta': {'invoice_number': 'INV-1', 'total': '100', 'linked_projects': []},
                    'line_items': [item(*pair) for pair in old_items]}
        if primary:
            original['meta'].update(project_number=primary[0], payment_stage_index=primary[1], payment_stage='First')
        edited = {'meta': {'invoice_number': 'INV-1', 'total': '100', 'project_number': primary[0] if primary else ''},
                  'line_items': [item(*pair) for pair in new_items]}
        projects = {p: {'payment_stages': [
            {'invoice_id': 'inv', 'invoice_number': 'INV-1', 'invoice_date': '2026-09-22',
             'amount_paid': '0', 'amount': 50, 'status': 'Invoiced'} for _ in range(3)]}
                    for p in ('A', 'B')}
        projects['B']['payment_stages'][2]['invoice_id'] = 'other'
        before = copy.deepcopy(projects)
        updates = []
        def update(path, data):
            if fail_save and path == '/invoices/inv':
                raise RuntimeError('save failed')
            updates.append((path, copy.deepcopy(data)))
        self.env.update(
            fb_get=lambda path: copy.deepcopy(original), fb_update=update,
            _load_clients=lambda: [], _load_projects_list=lambda: [],
            _parse_invoice_form=lambda form: copy.deepcopy(edited),
            _find_project_by_number=lambda number: (number, projects[number]),
            request=SimpleNamespace(method='POST', form={}), session={},
            _safe_float=lambda value: float(value or 0),
            _update_project_stage_payment_status=Mock(), _mark_project_stage=Mock(),
            _sync_project_payment=Mock(), _auto_complete_project_if_paid=Mock(),
            flash=Mock(), redirect=lambda value: value, url_for=lambda *a, **k: 'detail')
        if fail_save:
            with self.assertRaises(RuntimeError):
                self.env['invoice_edit']('inv')
            self.assertEqual(projects, before)
        else:
            self.env['invoice_edit']('inv')
        return projects, before, updates

    def test_only_removed_stages_unlinked_across_projects(self):
        projects, before, updates = self.run_edit(
            [('A', 0), ('A', 1), ('B', 0), ('B', 1), ('B', 2)], [('A', 1), ('B', 0)])
        for project, index in [('A', 0), ('B', 1)]:
            stage = projects[project]['payment_stages'][index]
            self.assertEqual(stage, {'amount': 50, 'status': 'Pending Invoice'})
        for project, index in [('A', 1), ('B', 0), ('B', 2)]:
            self.assertEqual(projects[project]['payment_stages'][index], before[project]['payment_stages'][index])
        self.assertEqual(updates[0][0], '/invoices/inv')

    def test_string_indices_and_duplicate_remaining_row_keep_link(self):
        projects, before, _ = self.run_edit([('A', '0'), ('A', 0)], [('A', 0)])
        self.assertEqual(projects, before)

    def test_removed_primary_stage_is_not_restored(self):
        _, _, updates = self.run_edit([('A', 0), ('A', 1)], [('A', 1)], primary=('A', 0))
        self.assertNotIn('payment_stage_index', updates[0][1]['meta'])
        calls = self.env['_mark_project_stage'].call_args_list
        self.assertEqual([(c.args[0], c.args[1]) for c in calls], [('A', 1)])

    def test_save_failure_does_not_unlink(self):
        self.run_edit([('A', 0), ('A', 1)], [('A', 1)], fail_save=True)

    def test_removing_entire_project_keeps_other_project(self):
        projects, before, _ = self.run_edit([('A', 0), ('A', 1), ('B', 0)], [('B', 0)])
        self.assertEqual(projects['B'], before['B'])
        self.assertEqual(projects['A']['payment_stages'][0]['status'], 'Pending Invoice')
        self.assertEqual(projects['A']['payment_stages'][1]['status'], 'Pending Invoice')


if __name__ == '__main__':
    unittest.main()
