"""回归检查：多账号选择会同时创建并收敛为批量结果。"""

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
                "exp": 9999999999,
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
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const accounts = JSON.parse(process.env.FAKE_ACCOUNTS);
const progressById = {};
let checkoutCalls = 0;

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.matchMedia = () => ({matches: false});
  window.fetch = async (url, init = {}) => {
    if (String(url).endsWith('/api/config')) {
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 3, global_rpm: 20, workers: 20}})};
    }
    if (String(url).endsWith('/api/checkout')) {
      checkoutCalls += 1;
      const body = JSON.parse(init.body);
      const jobId = `job-${checkoutCalls}`;
      progressById[jobId] = body.token;
      return {ok: true, status: 202, json: async () => ({job_id: jobId, queue_position: 0})};
    }
    if (String(url).includes('/api/checkout-progress')) {
      const id = new URL(url, 'http://localhost/').searchParams.get('job_id');
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: 'done', percent: 100, text: '完成', logs: [],
          result: {link_type: 'hosted', checkout_url: `https://example.com/${id}`}
        })
      };
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.eval(appJs);

  window.importAccountTexts(accounts.map((token, index) => ({
    text: token,
    source: `batch-${index + 1}.at`
  })));
  const checks = [...window.document.querySelectorAll('.account-batch-check')];
  if (checks.length !== 2) throw new Error(`expected two account checks, got ${checks.length}`);
  checks.forEach(check => { check.checked = true; check.dispatchEvent(new window.Event('change', {bubbles: true})); });

  const batchButton = window.document.getElementById('accountBatchRun');
  if (batchButton.disabled) throw new Error('batch button should be enabled for two accounts');
  window.document.getElementById('entryProxy').value = 'http://127.0.0.1:8080';
  await window.startBatchCheckout();
  await wait(20);

  const rows = window.document.querySelectorAll('.batch-job-row');
  if (rows.length !== 2) throw new Error(`expected two batch rows, got ${rows.length}`);
  if (!window.document.getElementById('batchSummary').textContent.includes('2 个完成')) {
    throw new Error('batch summary did not report two completed jobs');
  }
  if (checkoutCalls !== 2) throw new Error(`expected two concurrent checkout calls, got ${checkoutCalls}`);
  if (!window.document.getElementById('planSection').open || !window.document.getElementById('railSection').open) {
    throw new Error('collapsible sections should be open by default');
  }
  console.log(JSON.stringify({ok: true, checkout_calls: checkoutCalls, batch_rows: rows.length}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


CANCEL_NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const accounts = JSON.parse(process.env.FAKE_ACCOUNTS);
const cancelled = new Set();
let checkoutCalls = 0;

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
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
      const jobId = `job-${checkoutCalls}`;
      return {ok: true, status: 202, json: async () => ({job_id: jobId, queue_position: 0})};
    }
    if (path.endsWith('/api/checkout-cancel')) {
      const body = JSON.parse(init.body || '{}');
      cancelled.add(String(body.job_id || ''));
      return {ok: true, status: 200, json: async () => ({ok: true})};
    }
    if (path.includes('/api/checkout-progress')) {
      const id = new URL(url, 'http://localhost/').searchParams.get('job_id');
      const stopped = cancelled.has(id);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: stopped ? 'cancelled' : 'running',
          percent: stopped ? 100 : 42,
          text: stopped ? '任务已停止' : '处理中',
          logs: [],
          result: null
        })
      };
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.eval(appJs);
  window.importAccountTexts(accounts.map((token, index) => ({text: token, source: `cancel-${index + 1}.at`})));
  [...window.document.querySelectorAll('.account-batch-check')].forEach(check => {
    check.checked = true;
    check.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  window.document.getElementById('entryProxy').value = 'http://127.0.0.1:8080';
  await window.startBatchCheckout();
  await wait(20);

  let rows = [...window.document.querySelectorAll('.batch-job-row')];
  if (rows.length !== 2) throw new Error(`expected two rows, got ${rows.length}`);
  const buttons = [...window.document.querySelectorAll('.batch-job-cancel')];
  if (buttons.length !== 2) throw new Error(`expected two individual cancel buttons, got ${buttons.length}`);
  buttons[0].click();
  await wait(30);
  rows = [...window.document.querySelectorAll('.batch-job-row')];
  if (!rows[0].classList.contains('is-cancelled')) throw new Error('first job was not cancelled');
  if (!rows[1].classList.contains('is-running')) throw new Error('second job did not continue running');
  if (cancelled.size !== 1) throw new Error(`expected one cancel request, got ${cancelled.size}`);

  window.document.querySelector('.batch-job-cancel').click();
  await wait(30);
  if (cancelled.size !== 2) throw new Error('second cancel request was not sent');
  console.log(JSON.stringify({ok: true, checkout_calls: checkoutCalls, cancelled: cancelled.size}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class BatchUiTests(unittest.TestCase):
    def test_multiple_accounts_run_as_batch(self) -> None:
        env = os.environ.copy()
        env["FAKE_ACCOUNTS"] = json.dumps(
            [
                build_fake_jwt("one@example.com", "acct-one"),
                build_fake_jwt("two@example.com", "acct-two"),
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

    def test_single_batch_row_can_be_cancelled_without_stopping_siblings(self) -> None:
        env = os.environ.copy()
        env["FAKE_ACCOUNTS"] = json.dumps(
            [
                build_fake_jwt("one@example.com", "acct-one-cancel"),
                build_fake_jwt("two@example.com", "acct-two-cancel"),
            ]
        )
        completed = subprocess.run(
            ["node", "-e", CANCEL_NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node cancel test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
