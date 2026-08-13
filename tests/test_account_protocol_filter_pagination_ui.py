"""账号协议筛选、加入时间倒序与分页回归。"""

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
const html = fs.readFileSync('static/manage.html', 'utf8');
const manageJs = fs.readFileSync('static/manage.js', 'utf8');
const now = Date.now();
const accounts = Array.from({length: 25}, (_, index) => {
  const protocol = index % 3 === 0 ? 'oaics' : index % 3 === 1 ? 'cs' : '';
  return {
    id: `acct-${String(index).padStart(2, '0')}`,
    raw: `eyJtoken-${index}`,
    token: `eyJtoken-${index}`,
    label: `account-${index}@example.com`,
    email: `account-${index}@example.com`,
    source: 'test',
    addedAt: now - (24 - index) * 1000,
    checkoutProtocols: protocol ? {
      'paypal:DE:EUR': {protocol, country: 'DE', currency: 'EUR', checkedAt: now}
    } : {}
  };
});

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/manage', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false});
  window.fetch = async url => {
    const path = String(url);
    if (path.endsWith('/api/manage/session')) {
      return {ok: true, status: 200, json: async () => ({configured: true, authenticated: true})};
    }
    if (path.endsWith('/api/manage/summary')) {
      return {ok: true, status: 200, json: async () => ({proxy_pools: 0, billing_profiles: 0, asn_regions: 0, success_records: 0, last_success: null})};
    }
    if (path.includes('/api/manage/')) {
      return {ok: true, status: 200, json: async () => ({items: []})};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, accounts}));
  window.eval(manageJs);
  await wait(40);

  window.document.querySelector('[data-section="accounts"]').click();
  const table = window.document.getElementById('accountTable');
  const pagination = window.document.getElementById('accountPagination');
  if (table.querySelectorAll('tr').length !== 20) throw new Error('expected first page to contain 20 rows');
  if (table.querySelector('tr')?.dataset.id !== 'acct-24') throw new Error('newest account is not first');
  if (pagination.hidden) throw new Error('pagination should be visible for 25 accounts');
  if (window.document.getElementById('accountPageStatus').textContent !== '第 1 / 2 页') throw new Error('wrong first page status');

  window.document.getElementById('accountNextPage').click();
  if (table.querySelectorAll('tr').length !== 5) throw new Error('expected second page to contain 5 rows');
  if (table.querySelector('tr')?.dataset.id !== 'acct-04') throw new Error('second page order is wrong');

  const protocolFilter = window.document.getElementById('accountProtocolFilter');
  protocolFilter.value = 'oaics';
  protocolFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (table.querySelectorAll('tr').length !== 9) throw new Error('OAICS filter did not narrow accounts');
  if (!pagination.hidden) throw new Error('single-page protocol filter should hide pagination');
  if (!table.textContent.includes('OAICS')) throw new Error('OAICS status is not rendered');

  protocolFilter.value = 'cs';
  protocolFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (table.querySelectorAll('tr').length !== 8) throw new Error('CS filter did not narrow accounts');
  protocolFilter.value = 'unknown';
  protocolFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (table.querySelectorAll('tr').length !== 8) throw new Error('unknown protocol filter did not narrow accounts');

  console.log(JSON.stringify({ok: true, first_page: 20, second_page: 5, oaics: 9, cs: 8, unknown: 8}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class AccountProtocolFilterPaginationUiTests(unittest.TestCase):
    def test_protocol_filter_sort_and_pagination(self) -> None:
        completed = subprocess.run(
            ["node", "-e", NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
