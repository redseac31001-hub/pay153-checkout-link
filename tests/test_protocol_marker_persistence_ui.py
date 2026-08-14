"""协议检测标记在后续结果与页面恢复后保持一致的回归。"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const accounts = [
  {token: 'eyJprotocol.oaics.fixture', protocol: 'oaics', jobId: 'detect-oaics'},
  {token: 'eyJprotocol.cs.fixture', protocol: 'cs', jobId: 'detect-cs'}
];

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false});
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.fetch = async url => {
    if (String(url).endsWith('/api/config')) {
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.eval(appJs);
  for (const account of accounts) {
    window.importAccountTexts([{text: account.token, source: 'marker-fixture'}]);
    const afterImport = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
    const imported = afterImport.accounts.find(item => item.raw === account.token);
    window.selectAccount(imported.id);
    window.recordActiveAccountOutcome({
      status: 'done',
      result: {
        detection_only: true,
        link_type: 'paypal',
        checkout_protocol: account.protocol,
        checkout_protocol_country: 'DE',
        checkout_protocol_currency: 'EUR',
        checkout_protocol_checked_at: Date.now()
      }
    }, 'paypal', account.jobId);

    // A later PayPal result can be incomplete and report protocol=unknown.
    // It must not erase a valid marker established by protocol detection.
    window.recordActiveAccountOutcome({
      status: 'done',
      result: {
        link_type: 'paypal',
        checkout_protocol: 'unknown',
        checkout_protocol_country: 'DE',
        checkout_protocol_currency: 'EUR',
        checkout_protocol_checked_at: Date.now()
      }
    }, 'paypal', 'later-incomplete-result');
  }

  const stored = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
  for (const account of accounts) {
    const marker = stored.accounts.find(item => item.raw === account.token)?.checkoutProtocols?.['paypal:DE:EUR'];
    if (marker?.protocol !== account.protocol) {
      throw new Error(`known ${account.protocol.toUpperCase()} marker was overwritten: ${JSON.stringify(marker)}`);
    }
  }
  console.log(JSON.stringify({ok: true, protocols: accounts.map(account => account.protocol)}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
''';


class ProtocolMarkerPersistenceUiTests(unittest.TestCase):
    def test_unknown_later_result_does_not_erase_known_protocol_marker(self) -> None:
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
            self.fail(completed.stderr or completed.stdout or "node protocol marker test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))

    def test_manage_detection_unknown_result_does_not_erase_known_marker(self) -> None:
        node_script = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('static/manage.html', 'utf8');
const manageJs = fs.readFileSync('static/manage.js', 'utf8');
const accounts = [
  {id: 'manage-oaics', raw: 'oaics-token', token: 'oaics-token', label: 'oaics@example.com', email: 'oaics@example.com', checkoutProtocols: {
    'paypal:DE:EUR': {protocol: 'oaics', country: 'DE', currency: 'EUR', checkedAt: Date.now()}
  }},
  {id: 'manage-cs', raw: 'cs-token', token: 'cs-token', label: 'cs@example.com', email: 'cs@example.com', checkoutProtocols: {
    'paypal:DE:EUR': {protocol: 'cs', country: 'DE', currency: 'EUR', checkedAt: Date.now()}
  }}
];

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/manage#accounts', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false});
  window.fetch = async url => {
    const path = String(url);
    if (path.endsWith('/api/manage/session')) return {ok: true, status: 200, json: async () => ({configured: true, authenticated: true})};
    if (path.endsWith('/api/manage/summary')) return {ok: true, status: 200, json: async () => ({proxy_pools: 0, billing_profiles: 0, asn_regions: 0, success_records: 0, last_success: null})};
    if (path.includes('/api/manage/builtin-addresses')) return {ok: true, status: 200, json: async () => ({addresses: [], countries: [], library_total: 0})};
    if (path.endsWith('/api/manage/proxy-pools')) return {ok: true, status: 200, json: async () => ({items: []})};
    if (path.endsWith('/api/config')) return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, accounts}));
  window.eval(manageJs);
  await new Promise(resolve => setTimeout(resolve, 40));
  for (const account of accounts) {
    window.manageRecordDetectionOutcome(
      {accountId: account.id, jobId: `unknown-${account.id}`, status: 'done'},
      {status: 'done', result: {
        checkout_protocol: 'unknown',
        checkout_protocol_country: 'DE',
        checkout_protocol_currency: 'EUR',
        checkout_protocol_checked_at: Date.now()
      }}
    );
  }
  const stored = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
  for (const account of accounts) {
    const marker = stored.accounts.find(item => item.id === account.id)?.checkoutProtocols?.['paypal:DE:EUR'];
    const expected = account.checkoutProtocols['paypal:DE:EUR'].protocol;
    if (marker?.protocol !== expected) throw new Error(`manage marker was overwritten: ${JSON.stringify(marker)}`);
  }
  console.log(JSON.stringify({ok: true, manage: true}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''
        completed = subprocess.run(
            ["node", "-e", node_script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=os.environ.copy(),
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node manage protocol marker test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
