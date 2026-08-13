"""管理中心协议检测的本地代理、手工代理与代理池编辑回归。"""

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

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/manage#accounts', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false});
  const proxyItems = [
    {id: 1, name: '入口池', rail: 'shared', country: 'DE', pool_kind: 'entry', enabled: true, proxy_count: 1, proxy_preview: ['http://127.0.0.1:9697']},
    {id: 2, name: '出口池', rail: 'paypal', country: 'DE', pool_kind: 'exit', enabled: true, proxy_count: 1, proxy_preview: ['http://127.0.0.1:9698']}
  ];
  const detectionBodies = [];
  const proxyCreates = [];
  window.fetch = async (url, options = {}) => {
    const path = String(url);
    if (path.endsWith('/api/manage/session')) {
      return {ok: true, status: 200, json: async () => ({configured: true, authenticated: true})};
    }
    if (path.endsWith('/api/manage/summary')) {
      return {ok: true, status: 200, json: async () => ({proxy_pools: 2, billing_profiles: 0, asn_regions: 0, success_records: 0, last_success: null})};
    }
    if (path.includes('/api/manage/builtin-addresses')) {
      return {ok: true, status: 200, json: async () => ({addresses: [], countries: [], library_total: 0})};
    }
    if (path.includes('/api/manage/proxy-pools/1?reveal=1')) {
      return {ok: true, status: 200, json: async () => ({...proxyItems[0], proxies: ['http://127.0.0.1:9697']})};
    }
    if (path.includes('/api/manage/proxy-pools/2?reveal=1')) {
      return {ok: true, status: 200, json: async () => ({...proxyItems[1], proxies: ['http://127.0.0.1:9698']})};
    }
    if (path.endsWith('/api/manage/proxy-pools')) {
      if (options.method === 'POST') {
        proxyCreates.push(JSON.parse(options.body));
        return {ok: true, status: 200, json: async () => ({item: {name: proxyCreates[0].name}})};
      }
      return {ok: true, status: 200, json: async () => ({items: proxyItems})};
    }
    if (path.endsWith('/api/checkout-detect')) {
      detectionBodies.push(JSON.parse(options.body));
      return {ok: true, status: 200, json: async () => ({job_id: `proxy-ui-job-${detectionBodies.length}`})};
    }
    if (path.includes('/api/checkout-progress')) {
      const protocol = detectionBodies.length === 1 ? 'oaics' : 'cs';
      return {ok: true, status: 200, json: async () => ({
        status: 'done', percent: 100, text: '完成',
        result: {checkout_protocol: protocol, checkout_protocol_country: 'DE', checkout_protocol_currency: 'EUR'}
      })};
    }
    if (path.includes('/api/manage/')) {
      return {ok: true, status: 200, json: async () => ({items: []})};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, activeId: 'acct-1', accounts: [
    {id: 'acct-1', raw: 'eyJlocal-proxy-token', token: 'eyJlocal-proxy-token', label: 'proxy@example.com', exp: 4102444800, riskStatus: 'clear'}
  ]}));
  window.eval(manageJs);
  await wait(50);

  const proxyTable = window.document.getElementById('proxyTable');
  if (proxyTable.querySelectorAll('button[data-action="edit-proxy"]').length !== 2) throw new Error('proxy edit actions missing');
  proxyTable.querySelector('button[data-action="edit-proxy"]').click();
  await wait(20);
  if (window.document.getElementById('proxyId').value !== '1') throw new Error('proxy edit did not load the selected pool');
  if (!window.document.getElementById('proxyFormTitle').textContent.includes('入口池')) throw new Error('proxy edit title missing');
  window.document.getElementById('resetProxyForm').click();
  window.document.getElementById('proxyName').value = '新增本地池';
  window.document.getElementById('proxyRail').value = 'paypal';
  window.document.getElementById('proxyCountry').value = 'DE';
  window.document.getElementById('proxyData').value = 'http://127.0.0.1:9697';
  window.document.getElementById('proxyForm').dispatchEvent(new window.Event('submit', {bubbles: true, cancelable: true}));
  await wait(30);
  if (proxyCreates.length !== 1 || proxyCreates[0].proxies[0] !== 'http://127.0.0.1:9697') throw new Error('proxy add did not submit editable pool data');

  const mode = window.document.getElementById('manageDetectProxyMode');
  const localFields = window.document.getElementById('manageDetectionLocalFields');
  const manualFields = window.document.getElementById('manageDetectionManualFields');
  mode.value = 'local';
  mode.dispatchEvent(new window.Event('change', {bubbles: true}));
  window.document.getElementById('manageDetectLocalProxy').value = 'http://127.0.0.1:9697';
  if (localFields.hidden || !manualFields.hidden) throw new Error('local proxy mode fields did not toggle');
  window.document.getElementById('manageDetectCurrent').click();
  await wait(80);
  if (detectionBodies.length !== 1 || detectionBodies[0].entry_proxies[0] !== 'http://127.0.0.1:9697' || detectionBodies[0].exit_proxies[0] !== 'http://127.0.0.1:9697') {
    throw new Error('local proxy was not sent to both detection routes');
  }

  mode.value = 'manual';
  mode.dispatchEvent(new window.Event('change', {bubbles: true}));
  window.document.getElementById('manageDetectManualEntryProxy').value = 'http://entry.example:8000\nentry.example:8001:user:pass';
  window.document.getElementById('manageDetectManualExitProxy').value = 'socks5://exit.example:9000';
  if (!localFields.hidden || manualFields.hidden) throw new Error('manual proxy mode fields did not toggle');
  window.document.getElementById('manageDetectCurrent').click();
  await wait(80);
  if (detectionBodies.length !== 2 || detectionBodies[1].entry_proxies.length !== 2 || detectionBodies[1].exit_proxies[0] !== 'socks5://exit.example:9000') {
    throw new Error('manual proxy lists were not sent to detection');
  }
  console.log(JSON.stringify({ok: true, proxyEdit: true, proxyAdd: true, local: true, manual: true}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class ManageDetectionProxyUiTests(unittest.TestCase):
    def test_detection_proxy_sources_and_pool_editor(self) -> None:
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
