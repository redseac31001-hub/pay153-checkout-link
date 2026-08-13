"""管理中心协议状态变化后的账号选择一致性与一键选择回归。"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('static/manage.html', 'utf8');
const manageJs = fs.readFileSync('static/manage.js', 'utf8');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const accounts = Array.from({length: 16}, (_, index) => ({
  id: `acct-${index + 1}`,
  raw: `raw-token-${index + 1}`,
  token: `raw-token-${index + 1}`,
  label: `account-${index + 1}@example.com`,
  email: `account-${index + 1}@example.com`,
  exp: 4102444800,
  source: 'test',
  checkoutProtocols: {},
  riskStatus: 'unknown',
  promoStatus: 'unknown'
}));
const selectedIds = accounts.map(account => account.id);
let detectionCalls = 0;

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/manage#accounts', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false});
  window.fetch = async (url, options = {}) => {
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
    if (path.endsWith('/api/manage/proxy-pools')) {
      return {ok: true, status: 200, json: async () => ({items: []})};
    }
    if (path.endsWith('/api/config')) {
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    }
    if (path.endsWith('/api/checkout-detect')) {
      detectionCalls += 1;
      return {ok: true, status: 202, json: async () => ({job_id: `detect-${detectionCalls}`, queue_position: 0})};
    }
    if (path.includes('/api/checkout-progress')) {
      const jobId = new URL(url, 'http://localhost/').searchParams.get('job_id');
      const index = Number(String(jobId).split('-')[1] || 1);
      return {ok: true, status: 200, json: async () => ({
        status: 'done', percent: 100, text: '协议检测完成',
        result: {
          detection_only: true,
          link_type: 'paypal',
          checkout_protocol: index % 2 ? 'oaics' : 'cs',
          checkout_protocol_country: 'DE',
          checkout_protocol_currency: 'EUR',
          checkout_protocol_checked_at: Date.now(),
          checkout_protocol_source: 'fixed_de'
        }
      })};
    }
    return {ok: true, status: 200, json: async () => ({items: []})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, activeId: accounts[0].id, selectedIds, accounts}));
  window.eval(manageJs);
  await wait(60);
  window.document.querySelector('[data-section="accounts"]').click();

  const protocolFilter = window.document.getElementById('accountProtocolFilter');
  protocolFilter.value = 'unknown';
  protocolFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (window.document.querySelectorAll('.manage-account-check:checked').length !== 16) throw new Error('fixture did not start with 16 checked accounts');

  const mode = window.document.getElementById('manageDetectProxyMode');
  mode.value = 'local';
  mode.dispatchEvent(new window.Event('change', {bubbles: true}));
  window.document.getElementById('manageDetectLocalProxy').value = 'http://127.0.0.1:9697';
  await window.startManageProtocolDetection(selectedIds);
  await wait(30);

  if (detectionCalls !== 16) throw new Error(`expected 16 detection jobs, got ${detectionCalls}`);
  if (window.document.querySelectorAll('.manage-account-check:checked').length !== 0) throw new Error('protocol filter should no longer show checked rows after status changes');
  const detectButton = window.document.getElementById('manageDetectSelected');
  if (detectButton.textContent !== '批量检测选中（0）' || !detectButton.disabled) {
    throw new Error(`stale selection remains after protocol status update: ${detectButton.textContent}`);
  }

  protocolFilter.value = '';
  protocolFilter.dispatchEvent(new window.Event('change', {bubbles: true}));
  window.document.getElementById('manageSelectAll').click();
  if (window.document.querySelectorAll('.manage-account-check:checked').length !== 16) throw new Error('select all did not check every available account');
  window.document.getElementById('manageClearSelection').click();
  if (window.document.querySelectorAll('.manage-account-check:checked').length !== 0) throw new Error('clear selection did not uncheck every account');
  if (window.document.getElementById('manageDetectSelected').textContent !== '批量检测选中（0）') throw new Error('clear selection did not update detection count');
  console.log(JSON.stringify({ok: true, detectionCalls, cleared: true}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class ManageAccountSelectionUiTests(unittest.TestCase):
    def test_protocol_status_updates_clear_stale_selection_and_actions(self) -> None:
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
            self.fail(completed.stderr or completed.stdout or "node selection test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
