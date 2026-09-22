const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/templates/invoice_form.html', 'utf8');
const functions = source.slice(source.indexOf('function stageIdentityKeys'), source.indexOf('// Turn a plain <select>'));
let rows = [];
const catalog = {
  A: {project_number: 'A', has_payment_stages: true,
    all_pending_stages: [{stage_idx: 0}, {stage_idx: 1}],
    approved_pending_cos: [{stage_idx: 2, co_firebase_id: 'c1', co_number: 'co1'}]},
  B: {project_number: 'B', has_payment_stages: true, all_pending_stages: [{stage_idx: 0}], approved_pending_cos: []},
  Manual: {project_number: 'Manual', has_payment_stages: false, all_pending_stages: [], approved_pending_cos: []}
};
function row(project, stage, co = '', number = '') {
  const values = {'item_project[]': project, 'item_stage_index[]': stage,
    'item_co_firebase_id[]': co, 'item_co_number[]': number};
  return {querySelector: selector => ({value: values[selector.match(/name="(.*?)"/)[1]] ?? ''})};
}
const newSelect = {value: '', options: ['', 'A', 'B', 'Manual'].map(value => ({value})), closest: () => null};
const context = {invoiceStageOptions: catalog, document: {
  querySelector: () => ({value: 'A'}),
  querySelectorAll: selector => selector.includes('tr.line-item-row') ? rows : [newSelect]
}};
vm.createContext(context);
vm.runInContext(functions, context);
rows = [row('A', '0')];
assert.equal(context.availableStageChoices(catalog.A).all_pending_stages.length, 1);
assert.equal(context.canSelectInvoiceProject('A'), true);
assert.equal(context.canSelectInvoiceProject('B'), true);
rows.push(row('A', '1'), row('A', '2', 'c1', 'co1'));
context.refreshInvoiceProjectChoices();
assert.equal(context.canSelectInvoiceProject('A'), false);
assert.equal(newSelect.options[1].hidden, true);
assert.equal(newSelect.options[1].disabled, true);
assert.equal(context.canSelectInvoiceProject('A', rows[0]), true, 'own stage can be replaced');
rows.splice(0, 1); // delete stage zero without saving
context.refreshInvoiceProjectChoices();
assert.equal(context.canSelectInvoiceProject('A'), true);
assert.equal(newSelect.options[1].hidden, false);
assert.equal(context.availableStageChoices(catalog.A).all_pending_stages[0].stage_idx, 0);
rows = [row('', '0'), row('A', '', 'c1', 'co1')];
assert.equal(context.availableStageChoices(catalog.A).approved_pending_cos.length, 0, 'CO identity works without stage index');
assert.equal(context.availableStageChoices(catalog.A).all_pending_stages[0].stage_idx, 1, 'default project rows count');
rows = [];
assert.equal(context.availableStageChoices(catalog.A).approved_pending_cos.length, 1, 'deleted CO restored');
assert.equal(context.canSelectInvoiceProject('Manual'), true);
console.log('Invoice stage selection regressions passed.');
