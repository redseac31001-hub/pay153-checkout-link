"""工作台从管理中心导入代理池及支付方式展示回归。"""

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
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const pools = [
  {id: 1, name: '德国入口池', rail: 'shared', country: 'DE', pool_kind: 'entry', enabled: true, proxy_count: 2, proxy_preview: ['http://***:8080']},
  {id: 2, name: '印尼出口池', rail: 'gopay', country: 'ID', pool_kind: 'exit', enabled: true, proxy_count: 1, proxy_preview: ['http://***:8081']},
  {id: 3, name: '已停用池', rail: 'shared', country: 'US', pool_kind: 'entry', enabled: false, proxy_count: 1, proxy_preview: ['http://***:8082']}
];

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false});
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.confirm = () => true;
  window.fetch = async (url) => {
    const path = String(url);
    if (path.endsWith('/api/config')) {
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    }
    if (path.endsWith('/api/manage/session')) {
      return {ok: true, status: 200, json: async () => ({configured: true, authenticated: true})};
    }
    if (path.endsWith('/api/manage/proxy-pools')) {
      return {ok: true, status: 200, json: async () => ({items: pools})};
    }
    if (path.includes('/api/manage/proxy-pools/1?reveal=1')) {
      return {ok: true, status: 200, json: async () => ({...pools[0], proxies: ['http://entry.example:8080', 'http://entry.example:8081']})};
    }
    if (path.includes('/api/manage/proxy-pools/2?reveal=1')) {
      return {ok: true, status: 200, json: async () => ({...pools[1], proxies: ['http://exit.example:9090']})};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.eval(appJs);
  await wait(30);

  if (window.document.getElementById('railDetailsMethod').textContent !== 'Checkout 长链') throw new Error('hosted payment summary missing');
  window.document.querySelector('label.rail input[value="gopay"]').parentElement.click();
  await wait(20);
  if (window.document.getElementById('railDetailsMethod').textContent !== 'Gopay 钱包') throw new Error('selected payment summary did not update');
  if (window.document.getElementById('exitProxyField').hidden) throw new Error('gopay exit pool should be visible');

  window.document.getElementById('importEntryProxy').click();
  await wait(40);
  const importPanel = window.document.getElementById('proxyImportPanel');
  if (importPanel.hidden) throw new Error('proxy import panel did not open');
  const importButtons = [...window.document.querySelectorAll('#proxyImportPoolList .proxy-import-item-button')];
  if (importButtons.length !== 2 || importPanel.textContent.includes('已停用池')) throw new Error('enabled management pools were not filtered correctly');
  importButtons.find(button => button.textContent.includes('代理池 1')).click();
  await wait(40);
  if (window.document.getElementById('entryProxy').value !== 'http://entry.example:8080\nhttp://entry.example:8081') throw new Error('entry pool was not imported');

  window.document.getElementById('importExitProxy').click();
  await wait(40);
  const exitImportButton = window.document.querySelector('#proxyImportPoolList .proxy-import-item-button');
  if (!exitImportButton || !exitImportButton.textContent.includes('代理池 2')) throw new Error('exit import target was not switched');
  exitImportButton.click();
  await wait(40);
  if (window.document.getElementById('exitProxy').value !== 'http://exit.example:9090') throw new Error('exit pool was not imported');

  window.showResult({link_type: 'gopay', payment_method_types: ['card', 'gopay'], account_email: 'pay@example.com'});
  const resultMethods = window.document.getElementById('resultPaymentMethods').textContent;
  if (!resultMethods.includes('Card') || !resultMethods.includes('Gopay')) throw new Error(`result payment methods were not rendered: ${resultMethods}`);
  console.log(JSON.stringify({ok: true, importedEntry: 2, importedExit: 1, paymentMethods: resultMethods}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class WorkbenchProxyImportPaymentUiTests(unittest.TestCase):
    def test_proxy_import_and_payment_method_display(self) -> None:
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
