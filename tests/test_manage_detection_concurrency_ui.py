"""管理中心协议检测并发池与动态并发设置回归。"""

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
const accounts = Array.from({length: 5}, (_, index) => ({
  id: `acct-concurrent-${index}`,
  raw: `eyJconcurrent-token-${index}`,
  token: `eyJconcurrent-token-${index}`,
  label: `concurrent-${index}@example.com`,
  email: `concurrent-${index}@example.com`,
  exp: 4102444800,
  source: 'concurrency-test',
  riskStatus: 'unknown',
  addedAt: Date.now() - index * 1000
}));
let activeCreates = 0;
let maxActiveCreates = 0;
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
    if (path.endsWith('/api/config')) {
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 4}})};
    }
    if (path.endsWith('/api/manage/summary')) {
      return {ok: true, status: 200, json: async () => ({proxy_pools: 0, billing_profiles: 0, asn_regions: 0, success_records: 0, last_success: null})};
    }
    if (path.includes('/api/manage/builtin-addresses')) {
      return {ok: true, status: 200, json: async () => ({addresses: [], countries: [], library_total: 0})};
    }
    if (path.endsWith('/api/checkout-detect')) {
      detectionCalls += 1;
      activeCreates += 1;
      maxActiveCreates = Math.max(maxActiveCreates, activeCreates);
      await wait(12);
      activeCreates -= 1;
      return {ok: true, status: 202, json: async () => ({job_id: `manage-detect-${detectionCalls}`, queue_position: 0})};
    }
    if (path.includes('/api/checkout-progress')) {
      return {ok: true, status: 200, json: async () => ({
        status: 'done', percent: 100, text: '完成',
        result: {checkout_protocol: detectionCalls % 2 ? 'oaics' : 'cs', checkout_protocol_country: 'DE', checkout_protocol_currency: 'EUR'}
      })};
    }
    if (path.includes('/api/manage/')) {
      return {ok: true, status: 200, json: async () => ({items: []})};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({
    version: 1, activeId: accounts[0].id, selectedIds: accounts.map(item => item.id), accounts
  }));
  window.eval(manageJs);
  await wait(60);

  const concurrency = window.document.getElementById('manageDetectConcurrency');
  if (concurrency.max !== '4') throw new Error(`worker max was not synchronized: ${concurrency.max}`);
  concurrency.value = '2';
  concurrency.dispatchEvent(new window.Event('change', {bubbles: true}));
  if (window.localStorage.getItem('pay153.manage.detection.concurrency.v1') !== '2') {
    throw new Error('concurrency preference was not persisted');
  }
  const note = window.document.getElementById('manageDetectionConcurrencyNote').textContent;
  if (!note.includes('当前并发 2') || !note.includes('worker 上限 4')) throw new Error(`concurrency note missing: ${note}`);

  const mode = window.document.getElementById('manageDetectProxyMode');
  mode.value = 'local';
  mode.dispatchEvent(new window.Event('change', {bubbles: true}));
  window.document.getElementById('manageDetectLocalProxy').value = 'http://127.0.0.1:9697';
  window.document.getElementById('manageDetectSelected').click();
  await wait(180);

  if (detectionCalls !== 5) throw new Error(`expected all detection jobs, got ${detectionCalls}`);
  if (maxActiveCreates !== 2) throw new Error(`expected 2 concurrent creates, got ${maxActiveCreates}`);
  if (!window.document.getElementById('manageDetectionStatus').textContent.includes('5 个完成')) {
    throw new Error('concurrent detection did not converge');
  }
  console.log(JSON.stringify({ok: true, detection_calls: detectionCalls, max_concurrency: maxActiveCreates}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
''';


class ManageDetectionConcurrencyUiTests(unittest.TestCase):
    def test_manage_detection_uses_configured_concurrency(self) -> None:
        completed = subprocess.run(
            ["node", "-e", NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node concurrency test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
