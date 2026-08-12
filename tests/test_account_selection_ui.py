"""主页账号排序、摘要和快速选择回归测试。"""

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
    header = _b64url(json.dumps({"alg": "none"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url(
        json.dumps(
            {
                "email": email,
                "exp": 4102444800,
                "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{header}.{payload}.sig"


NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.matchMedia = () => ({matches: false});
  window.fetch = async () => ({ok: true, status: 200, json: async () => ({})});
  window.eval(appJs);

  const healthy = process.env.HEALTHY_JWT;
  const flagged = process.env.FLAGGED_JWT;
  window.importAccountTexts([
    {text: healthy, source: 'healthy.at'},
    {text: flagged, source: 'flagged.at'}
  ]);
  await wait(10);

  const list = window.document.getElementById('accountList');
  const findRow = label => [...list.querySelectorAll('.account-chip')]
    .find(row => row.querySelector('.account-chip-title')?.textContent === label);
  const healthyRow = findRow('healthy@example.com');
  const flaggedRow = findRow('flagged@example.com');
  if (!healthyRow || !flaggedRow) throw new Error('accounts were not rendered');

  healthyRow.querySelector('.account-chip-main').click();
  window.recordActiveAccountOutcome({
    status: 'done',
    result: {
      promo_requested: true,
      promo_applied: true,
      payment_method_types: ['card', 'paypal'],
      link_type: 'paypal',
      checkout_country: 'DE',
      checkout_currency: 'EUR'
    }
  }, 'paypal', 'job-healthy');

  const markedRow = findRow('flagged@example.com');
  markedRow.querySelector('.account-chip-main').click();
  window.recordActiveAccountOutcome({
    status: 'error',
    error_code: 'account_blocked',
    error: 'account blocked by policy'
  }, 'paypal', 'job-flagged');
  await wait(10);

  const rows = [...list.querySelectorAll('.account-chip')];
  const first = rows[0];
  const last = rows[rows.length - 1];
  if (first.querySelector('.account-chip-title')?.textContent !== 'healthy@example.com') {
    throw new Error(`healthy account was not prioritized: ${list.textContent}`);
  }
  if (!last.textContent.includes('疑似封禁')) throw new Error('marked status summary missing');
  if (!first.textContent.includes('方式 Card / PayPal')) throw new Error('payment method summary missing');
  if (!first.textContent.includes('地区 DE/EUR')) throw new Error('region summary missing');
  if (!window.document.getElementById('accountListHint').textContent.includes('已标记账号已排到后方')) {
    throw new Error('marked account hint missing');
  }

  first.querySelector('.account-chip-main').click();
  if (window.document.getElementById('token').value !== healthy) throw new Error('quick selection did not update token');
  console.log(JSON.stringify({ok: true, first: 'healthy@example.com', last: 'flagged@example.com'}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class AccountSelectionUiTests(unittest.TestCase):
    def test_marked_accounts_are_sorted_later_and_quick_select_shows_summary(self) -> None:
        env = os.environ.copy()
        env["HEALTHY_JWT"] = build_fake_jwt("healthy@example.com", "acct-healthy")
        env["FLAGGED_JWT"] = build_fake_jwt("flagged@example.com", "acct-flagged")
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
