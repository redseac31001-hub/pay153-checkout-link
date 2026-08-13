"""管理中心邮箱展开、账号选择同步到工作台及并发提链回归。"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def build_fake_jwt(email: str, account_id: str) -> str:
    header = _b64url(json.dumps({"alg": "none"}, separators=(",", ":")).encode())
    payload = _b64url(
        json.dumps(
            {
                "email": email,
                "exp": 4102444800,
                "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
            },
            separators=(",", ":"),
        ).encode()
    )
    return f"{header}.{payload}.sig"


NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const manageHtml = fs.readFileSync('static/manage.html', 'utf8');
const manageJs = fs.readFileSync('static/manage.js', 'utf8');
const workbenchHtml = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const accounts = JSON.parse(process.env.FAKE_ACCOUNTS);
const accountStorage = {version: 1, activeId: accounts[0].id, selectedIds: [], accounts};
let checkoutCalls = 0;

(async () => {
  const manageDom = new JSDOM(manageHtml, {url: 'http://localhost/manage#accounts', runScripts: 'outside-only'});
  const manageWindow = manageDom.window;
  manageWindow.matchMedia = () => ({matches: false});
  manageWindow.fetch = async url => {
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
  manageWindow.localStorage.setItem('pay153.accounts.v1', JSON.stringify(accountStorage));
  manageWindow.eval(manageJs);
  await wait(50);
  manageWindow.document.querySelector('[data-section="accounts"]').click();

  let firstRow = manageWindow.document.querySelector('#accountTable tr[data-id="acct-one"]');
  if (!firstRow) throw new Error('management account row missing');
  const revealButton = firstRow.querySelector('button[data-action="toggle-email"]');
  if (!revealButton || revealButton.textContent !== '查看邮箱') throw new Error('email reveal button missing');
  if (firstRow.textContent.includes('one@example.com')) throw new Error('email should start masked');
  revealButton.click();
  firstRow = manageWindow.document.querySelector('#accountTable tr[data-id="acct-one"]');
  if (!firstRow.textContent.includes('one@example.com')) throw new Error('full email was not revealed');
  if (firstRow.querySelector('button[data-action="toggle-email"]').textContent !== '隐藏邮箱') throw new Error('email reveal state did not toggle');

  manageWindow.document.querySelectorAll('.manage-account-check').forEach(check => {
    check.checked = true;
    check.dispatchEvent(new manageWindow.Event('change', {bubbles: true}));
  });
  const savedAfterSelection = JSON.parse(manageWindow.localStorage.getItem('pay153.accounts.v1') || '{}');
  if (!Array.isArray(savedAfterSelection.selectedIds) || savedAfterSelection.selectedIds.length !== 2) {
    throw new Error(`management selection was not persisted: ${JSON.stringify(savedAfterSelection)}`);
  }

  const workbenchDom = new JSDOM(workbenchHtml, {url: 'http://localhost/', runScripts: 'outside-only'});
  const window = workbenchDom.window;
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.matchMedia = () => ({matches: false});
  window.fetch = async (url, init = {}) => {
    const path = String(url);
    if (path.endsWith('/api/config')) {
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    }
    if (path.endsWith('/api/checkout')) {
      checkoutCalls += 1;
      const id = `manage-workbench-job-${checkoutCalls}`;
      return {ok: true, status: 202, json: async () => ({job_id: id, queue_position: 0})};
    }
    if (path.includes('/api/checkout-progress')) {
      const id = new URL(url, 'http://localhost/').searchParams.get('job_id');
      return {ok: true, status: 200, json: async () => ({
        status: 'done', percent: 100, text: '完成', logs: [],
        result: {link_type: 'hosted', checkout_url: `https://example.com/${id}`}
      })};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.localStorage.setItem('pay153.accounts.v1', JSON.stringify(savedAfterSelection));
  window.eval(appJs);
  await wait(40);
  const checks = [...window.document.querySelectorAll('.account-batch-check')];
  if (checks.length !== 2 || checks.some(check => !check.checked)) throw new Error('management selections did not appear in workbench');
  const batchButton = window.document.getElementById('accountBatchRun');
  if (batchButton.disabled || !batchButton.textContent.includes('2')) throw new Error('workbench batch button is not enabled for synced selection');
  window.document.getElementById('entryProxy').value = 'http://127.0.0.1:8080';
  window.document.getElementById('exitProxy').value = 'http://127.0.0.1:8081';
  await window.startBatchCheckout();
  await wait(30);
  if (checkoutCalls !== 2) throw new Error(`expected two concurrent checkout calls, got ${checkoutCalls}`);
  if (!window.document.getElementById('batchSummary').textContent.includes('2 个完成')) throw new Error('batch result did not converge');
  console.log(JSON.stringify({ok: true, emailReveal: true, synced: 2, checkoutCalls}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class ManageWorkbenchSelectionUiTests(unittest.TestCase):
    def test_manager_email_reveal_and_workbench_batch_sync(self) -> None:
        env = os.environ.copy()
        env["FAKE_ACCOUNTS"] = json.dumps(
            [
                {
                    "id": "acct-one",
                    "raw": build_fake_jwt("one@example.com", "acct-one"),
                    "token": build_fake_jwt("one@example.com", "acct-one"),
                    "email": "one@example.com",
                    "label": "one@example.com",
                    "accountId": "acct-one",
                    "exp": 4102444800,
                    "riskStatus": "clear",
                },
                {
                    "id": "acct-two",
                    "raw": build_fake_jwt("two@example.com", "acct-two"),
                    "token": build_fake_jwt("two@example.com", "acct-two"),
                    "email": "two@example.com",
                    "label": "two@example.com",
                    "accountId": "acct-two",
                    "exp": 4102444800,
                    "riskStatus": "clear",
                },
            ]
        )
        completed = subprocess.run(
            ["node", "-e", NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
