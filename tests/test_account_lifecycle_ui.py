"""账号生命周期在工作台与管理中心之间同步的回归。"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const accounts = [
  {id: 'active-account', raw: 'eyJactive.fixture.token', token: 'eyJactive.fixture.token', label: 'active@example.com', email: 'active@example.com', lifecycle: 'active', exp: 4102444800},
  {id: 'completed-account', raw: 'eyJcompleted.fixture.token', token: 'eyJcompleted.fixture.token', label: 'completed@example.com', email: 'completed@example.com', lifecycle: 'completed', exp: 4102444800},
  {id: 'deleted-account', raw: 'eyJdeleted.fixture.token', token: 'eyJdeleted.fixture.token', label: 'deleted@example.com', email: 'deleted@example.com', lifecycle: 'deleted', exp: 4102444800}
];

function installCommonWindow(window) {
  window.matchMedia = () => ({matches: false});
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
}

async function testWorkbenchVisibility() {
  const html = fs.readFileSync('static/index.html', 'utf8');
  const appJs = fs.readFileSync('static/app.js', 'utf8');
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  installCommonWindow(window);
  window.fetch = async url => {
    if (String(url).endsWith('/api/config')) {
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, activeId: accounts[0].id, accounts}));
  window.eval(appJs);
  await wait(20);

  const list = window.document.getElementById('accountList');
  const chips = [...list.querySelectorAll('.account-chip')];
  if (chips.length !== 1) throw new Error(`workbench should show 1 active account, got ${chips.length}`);
  if (!list.textContent.includes('active@example.com')) throw new Error('active account is missing from workbench');
  if (list.textContent.includes('completed@example.com') || list.textContent.includes('deleted@example.com')) {
    throw new Error('archived accounts leaked into workbench');
  }
  if (!window.document.getElementById('accountListHint').textContent.includes('已隐藏 2 个')) {
    throw new Error('workbench hidden-account hint is missing');
  }
  const stored = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
  if (stored.accounts.find(item => item.id === 'completed-account')?.lifecycle !== 'completed') {
    throw new Error('completed lifecycle was not persisted');
  }
  return {window, stored};
}

async function testManagementEditing() {
  const html = fs.readFileSync('static/manage.html', 'utf8');
  const manageJs = fs.readFileSync('static/manage.js', 'utf8');
  const dom = new JSDOM(html, {url: 'http://localhost/manage#accounts', runScripts: 'outside-only'});
  const {window} = dom;
  installCommonWindow(window);
  window.fetch = async url => {
    const path = String(url);
    if (path.endsWith('/api/manage/session')) return {ok: true, status: 200, json: async () => ({configured: true, authenticated: true})};
    if (path.endsWith('/api/manage/summary')) return {ok: true, status: 200, json: async () => ({proxy_pools: 0, billing_profiles: 0, asn_regions: 0, success_records: 0, last_success: null})};
    if (path.includes('/api/manage/builtin-addresses')) return {ok: true, status: 200, json: async () => ({addresses: [], countries: [], library_total: 0})};
    if (path.endsWith('/api/manage/proxy-pools')) return {ok: true, status: 200, json: async () => ({items: []})};
    if (path.endsWith('/api/config')) return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    return {ok: true, status: 200, json: async () => ({items: []})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, activeId: accounts[0].id, selectedIds: accounts.map(item => item.id), accounts}));
  window.eval(manageJs);
  await wait(60);

  const table = window.document.getElementById('accountTable');
  if (table.querySelectorAll('tr').length !== 3) throw new Error('management center should keep all lifecycle records');
  const checks = [...table.querySelectorAll('.manage-account-check')];
  if (checks.filter(input => input.disabled).length !== 2) throw new Error('archived accounts should be excluded from batch operations');

  const lifecycleFilter = window.document.getElementById('accountLifecycleFilter');
  lifecycleFilter.value = 'completed';
  lifecycleFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (table.querySelectorAll('tr').length !== 1 || !table.querySelector('tr[data-id="completed-account"]')) {
    throw new Error('completed lifecycle filter did not work');
  }

  const completedSelect = table.querySelector('tr[data-id="completed-account"] .account-lifecycle-select');
  completedSelect.value = 'active';
  completedSelect.dispatchEvent(new window.Event('change', {bubbles: true}));
  const afterRestore = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
  if (afterRestore.accounts.find(item => item.id === 'completed-account')?.lifecycle !== 'active') {
    throw new Error('lifecycle edit was not persisted');
  }

  lifecycleFilter.value = 'active';
  lifecycleFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (table.querySelectorAll('tr').length !== 2) throw new Error('restored account did not enter active filter');
  const activeSelect = table.querySelector('tr[data-id="active-account"] .account-lifecycle-select');
  activeSelect.value = 'deleted';
  activeSelect.dispatchEvent(new window.Event('change', {bubbles: true}));
  const afterDelete = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
  if (afterDelete.accounts.find(item => item.id === 'active-account')?.lifecycle !== 'deleted') {
    throw new Error('deleted lifecycle edit was not persisted');
  }
  return {window, stored: afterDelete};
}

(async () => {
  await testWorkbenchVisibility();
  const management = await testManagementEditing();
  if (management.stored.accounts.filter(item => item.lifecycle === 'active').length !== 1) {
    throw new Error('management lifecycle counts are inconsistent');
  }
  console.log(JSON.stringify({ok: true, visible_on_workbench: 1, managed_records: 3, active_after_edit: 1}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class AccountLifecycleUiTests(unittest.TestCase):
    def test_lifecycle_hides_on_workbench_and_is_editable_in_management(self) -> None:
        completed = subprocess.run(
            ["node", "-e", NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=os.environ.copy(),
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node lifecycle test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
