"""管理中心仅导出邮箱名称回归。"""

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
const accounts = [
  {id: 'acct-1', raw: 'token-1', token: 'token-1', label: 'alice@example.com', email: 'alice@example.com', exp: 4102444800},
  {id: 'acct-2', raw: 'token-2', token: 'token-2', label: 'bob@example.com', email: 'bob@example.com', exp: 4102444800},
  {id: 'acct-3', raw: 'token-3', token: 'token-3', label: '无邮箱账号', email: '', exp: 4102444800},
  {id: 'acct-4', raw: 'token-4', token: 'token-4', label: 'ALICE@EXAMPLE.COM', email: '', exp: 4102444800}
];

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/manage#accounts', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false});
  const blobs = [];
  let download = null;
  window.Blob = class {
    constructor(parts, options) { this.parts = parts; this.type = options?.type || ''; }
  };
  window.URL.createObjectURL = blob => { blobs.push(blob); return 'blob:email-export'; };
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function() {
    download = {href: this.href, name: this.download};
  };
  window.fetch = async url => {
    const path = String(url);
    if (path.endsWith('/api/manage/session')) return {ok: true, status: 200, json: async () => ({configured: true, authenticated: true})};
    if (path.endsWith('/api/manage/summary')) return {ok: true, status: 200, json: async () => ({proxy_pools: 0, billing_profiles: 0, asn_regions: 0, success_records: 0, last_success: null})};
    if (path.includes('/api/manage/builtin-addresses')) return {ok: true, status: 200, json: async () => ({addresses: [], countries: [], library_total: 0})};
    if (path.endsWith('/api/manage/proxy-pools')) return {ok: true, status: 200, json: async () => ({items: []})};
    if (path.endsWith('/api/config')) return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    if (path.includes('/api/manage/')) return {ok: true, status: 200, json: async () => ({items: []})};
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify({version: 1, activeId: 'acct-1', selectedIds: [], accounts}));
  window.eval(manageJs);
  await wait(60);
  window.document.querySelector('[data-section="accounts"]').click();
  window.document.getElementById('manageExportEmails').click();
  await wait(10);

  if (!download || !download.name.endsWith('.txt')) throw new Error('email export did not trigger a txt download');
  if (blobs.length !== 1) throw new Error(`expected one exported blob, got ${blobs.length}`);
  if (blobs[0].type !== 'text/plain;charset=utf-8') throw new Error('export content type is wrong');
  if (blobs[0].parts[0] !== 'alice@example.com\nbob@example.com\n') throw new Error(`export included non-email or duplicate data: ${blobs[0].parts[0]}`);
  if (!window.document.getElementById('manageAccountStatus').textContent.includes('已导出 2 个邮箱名称')) throw new Error('export status count is wrong');
  console.log(JSON.stringify({ok: true, emails: 2, content: blobs[0].parts[0]}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
''';


class ManageEmailExportUiTests(unittest.TestCase):
    def test_export_contains_only_unique_email_names(self) -> None:
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
            self.fail(completed.stderr or completed.stdout or "node email export test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
