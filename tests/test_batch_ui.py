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


DETECT_NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const accounts = JSON.parse(process.env.FAKE_ACCOUNTS);
let detectCalls = 0;

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
    if (path.endsWith('/api/checkout-detect')) {
      detectCalls += 1;
      const body = JSON.parse(init.body || '{}');
      if (!body.detection_only || body.country !== 'DE' || body.currency !== 'EUR' || body.use_promo) {
        throw new Error(`invalid detection request: ${JSON.stringify(body)}`);
      }
      return {ok: true, status: 202, json: async () => ({job_id: `detect-${detectCalls}`, queue_position: 0})};
    }
    if (path.includes('/api/checkout-progress')) {
      const id = new URL(url, 'http://localhost/').searchParams.get('job_id');
      const index = Number(String(id).split('-')[1] || 1);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: 'done', percent: 100, text: '协议检测完成', logs: [],
          result: {
            detection_only: true, link_type: 'paypal',
            checkout_protocol: index % 2 ? 'oaics' : 'cs',
            checkout_country: 'DE', checkout_currency: 'EUR',
            checkout_protocol_country: 'DE', checkout_protocol_currency: 'EUR',
            checkout_protocol_baseline: true, checkout_protocol_source: 'fixed_de',
            checkout_protocol_checked_at: Date.now()
          }
        })
      };
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.eval(appJs);
  window.importAccountTexts(accounts.map((token, index) => ({text: token, source: `detect-${index + 1}.at`})));
  const firstRow = [...window.document.querySelectorAll('.account-chip')]
    .find(row => row.querySelector('.account-chip-title')?.textContent === 'one@example.com');
  firstRow?.querySelector('.account-chip-main')?.click();
  window.recordActiveAccountOutcome({
    status: 'done',
    result: {
      detection_only: true,
      link_type: 'paypal',
      checkout_protocol: 'cs',
      checkout_country: 'DE',
      checkout_currency: 'EUR',
      checkout_protocol_country: 'DE',
      checkout_protocol_currency: 'EUR',
      checkout_protocol_checked_at: Date.now(),
      checkout_protocol_baseline: true,
      checkout_protocol_source: 'fixed_de'
    }
  }, 'paypal', 'preexisting-detection');
  window.document.querySelector('input[name="link_type"][value="paypal"]').click();
  window.document.getElementById('entryProxy').value = 'http://127.0.0.1:8080';
  window.document.getElementById('exitProxy').value = 'http://127.0.0.1:8081';
  [...window.document.querySelectorAll('.account-batch-check')].forEach(check => {
    check.checked = true;
    check.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  const detectButton = window.document.getElementById('accountBatchDetect');
  if (!detectButton || detectButton.disabled) throw new Error('batch detection button should be enabled');
  await window.startBatchProtocolDetection();
  await wait(30);
  if (detectCalls !== 1) throw new Error(`expected one detection call after skipping one marked account, got ${detectCalls}`);
  if (!window.document.getElementById('batchSummary').textContent.includes('协议检测结束：1 个完成 · 1 个跳过')) {
    throw new Error('batch detection summary missing');
  }
  const stored = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
  const saved = stored.accounts || [];
  if (saved.length !== 2 || saved.some(account => !account.checkoutProtocols?.['paypal:DE:EUR'])) {
    throw new Error(`protocol markers were not persisted: ${JSON.stringify(saved)}`);
  }
  console.log(JSON.stringify({ok: true, detection_calls: detectCalls, saved: saved.length}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


QUEUE_NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const accounts = JSON.parse(process.env.FAKE_ACCOUNTS);
const jobs = new Map();
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
      return {ok: true, status: 200, json: async () => ({task_limits: {per_ip_rpm: 2, global_rpm: 20, workers: 20}})};
    }
    if (path.endsWith('/api/checkout')) {
      checkoutCalls += 1;
      const id = `job-${checkoutCalls}`;
      jobs.set(id, JSON.parse(init.body || '{}'));
      return {ok: true, status: 202, json: async () => ({job_id: id, queue_position: 0})};
    }
    if (path.includes('/api/checkout-progress')) {
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
  window.importAccountTexts(accounts.map((token, index) => ({text: token, source: `queue-${index + 1}.at`})));
  window.document.getElementById('entryProxy').value = 'http://127.0.0.1:8080';
  [...window.document.querySelectorAll('.account-batch-check')].forEach(check => {
    check.checked = true;
    check.dispatchEvent(new window.Event('change', {bubbles: true}));
  });
  await window.startBatchCheckout();
  await wait(120);
  if (checkoutCalls !== 4) throw new Error(`expected all four jobs to enter through local queue, got ${checkoutCalls}`);
  if (window.document.querySelectorAll('.batch-job-row').length !== 4) throw new Error('queued rows were not retained');
  if (!window.document.getElementById('batchSummary').textContent.includes('4 个完成')) {
    throw new Error(`queue did not converge: ${window.document.getElementById('batchSummary').textContent}`);
  }
  console.log(JSON.stringify({ok: true, checkout_calls: checkoutCalls, rows: 4}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


SINGLE_ACCOUNT_BINDING_NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const accounts = JSON.parse(process.env.FAKE_ACCOUNTS);
let submittedToken = '';

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
      submittedToken = JSON.parse(init.body || '{}').token || '';
      const second = [...window.document.querySelectorAll('.account-chip')]
        .find(row => row.querySelector('.account-chip-title')?.textContent === 'second@example.com');
      if (!second) throw new Error('second account row missing');
      // Simulate selecting another account immediately after the backend accepted
      // the first account's token but before the terminal poll returns.
      second.querySelector('.account-chip-main').click();
      return {ok: true, status: 202, json: async () => ({job_id: 'job-single-binding', queue_position: 0})};
    }
    if (path.includes('/api/checkout-progress')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: 'error', percent: 100, text: 'PayPal 风控熔断',
          error_code: 'paypal_generic_decline_fuse',
          error: '连续 3 次 PayPal 风控拒绝，任务已停止', logs: [], result: null
        })
      };
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  window.eval(appJs);
  window.importAccountTexts(accounts.map((token, index) => ({
    text: token,
    source: `single-binding-${index + 1}.at`
  })));

  const first = [...window.document.querySelectorAll('.account-chip')]
    .find(row => row.querySelector('.account-chip-title')?.textContent === 'first@example.com');
  if (!first) throw new Error('first account row missing');
  first.querySelector('.account-chip-main').click();
  window.document.querySelector('input[name="link_type"][value="paypal"]').click();
  window.document.getElementById('entryProxy').value = 'http://127.0.0.1:8080';
  window.document.getElementById('exitProxy').value = 'http://127.0.0.1:8081';
  await window.startSingleCheckout();
  await wait(20);

  const stored = JSON.parse(window.localStorage.getItem('pay153.accounts.v1') || '{}');
  const saved = stored.accounts || [];
  const firstSaved = saved.find(account => account.email === 'first@example.com');
  const secondSaved = saved.find(account => account.email === 'second@example.com');
  if (submittedToken !== accounts[0]) throw new Error('submitted token was not the first account');
  if (!firstSaved || firstSaved.riskStatus !== 'cooldown') {
    throw new Error(`first account did not receive the fuse: ${JSON.stringify(saved)}`);
  }
  if (secondSaved && secondSaved.riskStatus === 'cooldown') {
    throw new Error(`second account was incorrectly fused: ${JSON.stringify(saved)}`);
  }
  dom.window.close();
  console.log(JSON.stringify({ok: true, bound: 'first@example.com', switched_to: 'second@example.com'}));
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

    def test_selected_accounts_can_run_concurrent_protocol_detection(self) -> None:
        env = os.environ.copy()
        env["FAKE_ACCOUNTS"] = json.dumps(
            [
                build_fake_jwt("one@example.com", "acct-one-detect"),
                build_fake_jwt("two@example.com", "acct-two-detect"),
            ]
        )
        completed = subprocess.run(
            ["node", "-e", DETECT_NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node detection test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))

    def test_batch_tasks_over_limit_wait_for_candidate_slots(self) -> None:
        env = os.environ.copy()
        env["FAKE_ACCOUNTS"] = json.dumps(
            [
                build_fake_jwt("one@example.com", "acct-one-queue"),
                build_fake_jwt("two@example.com", "acct-two-queue"),
                build_fake_jwt("three@example.com", "acct-three-queue"),
                build_fake_jwt("four@example.com", "acct-four-queue"),
            ]
        )
        completed = subprocess.run(
            ["node", "-e", QUEUE_NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node batch queue test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))

    def test_single_task_terminal_result_stays_bound_to_submitted_account(self) -> None:
        env = os.environ.copy()
        env["FAKE_ACCOUNTS"] = json.dumps(
            [
                build_fake_jwt("first@example.com", "acct-first-single"),
                build_fake_jwt("second@example.com", "acct-second-single"),
            ]
        )
        completed = subprocess.run(
            ["node", "-e", SINGLE_ACCOUNT_BINDING_NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "single account binding test failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
