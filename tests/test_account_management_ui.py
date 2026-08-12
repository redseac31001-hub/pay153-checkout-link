"""账号状态管理列表：只读本机脱敏元数据，不展示或上传 Token。"""

from __future__ import annotations

import json
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
    if (path.includes('/api/manage/builtin-addresses')) {
      return {ok: true, status: 200, json: async () => ({addresses: [], countries: [], library_total: 0})};
    }
    if (path.includes('/api/manage/')) {
      return {ok: true, status: 200, json: async () => ({items: []})};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, accounts: [
    {
      id: 'acct-1', raw: 'eyJsecret-token-one', token: 'eyJsecret-token-one',
      label: 'alice@example.com', email: 'alice@example.com', accountId: 'acct-alice-123456',
      source: 'batch.at', promoStatus: 'supported',
      paymentMethods: {paypal: 'supported', gopay: 'rejected'}, riskStatus: 'clear',
      lastStatus: 'done', lastLinkType: 'paypal', lastResultUrl: 'https://example.test/result', lastCheckedAt: Date.now()
    },
    {
      id: 'acct-2', raw: 'eyJsecret-token-two', token: 'eyJsecret-token-two',
      label: 'blocked@example.com', email: 'blocked@example.com', accountId: 'acct-blocked-123456',
      source: 'manual', promoStatus: 'unsupported',
      paymentMethods: {paypal: 'rejected'}, riskStatus: 'blocked',
      riskReason: '账号 blocked', lastStatus: 'error', lastLinkType: 'paypal', lastCheckedAt: Date.now()
    },
    {
      id: 'acct-3', raw: 'eyJsecret-token-three', token: 'eyJsecret-token-three',
      label: 'frozen@example.com', email: 'frozen@example.com', accountId: 'acct-frozen-123456',
      source: 'batch', promoStatus: 'unknown',
      paymentMethods: {paypal: 'unknown'}, riskStatus: 'frozen', consecutiveBlocks: 3,
      riskReason: '连续 3 次明确 block，已进入本机冻结', lastStatus: 'error', lastLinkType: 'paypal', lastCheckedAt: Date.now()
    }
  ]}));
  window.eval(manageJs);
  await wait(40);

  const accountPanel = window.document.querySelector('[data-panel="accounts"]');
  if (!accountPanel) throw new Error('missing accounts panel');
  window.document.querySelector('[data-section="accounts"]').click();
  const table = window.document.getElementById('accountTable');
  if (table.querySelectorAll('tr').length !== 3) throw new Error('expected three account rows');
  const content = table.textContent;
  if (!content.includes('支持') || !content.includes('疑似封禁') || !content.includes('冻结（连续 block）') || !content.includes('PayPal')) {
    throw new Error(`account statuses not rendered: ${content}`);
  }
  if (table.querySelectorAll('a.account-result-link').length !== 1) throw new Error('last result link not rendered');
  if (content.includes('secret-token-one') || content.includes('secret-token-two')) {
    throw new Error('raw token leaked into account table');
  }
  const riskFilter = window.document.getElementById('accountRiskFilter');
  riskFilter.value = 'blocked';
  riskFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (table.querySelectorAll('tr').length !== 1) throw new Error('risk filter did not narrow accounts');
  console.log(JSON.stringify({ok: true, rows: 3, filtered: 1}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class AccountManagementUiTests(unittest.TestCase):
    def test_manage_account_status_list_is_masked_and_filterable(self) -> None:
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
