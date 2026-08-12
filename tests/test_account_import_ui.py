"""账号导入管理：仅内存、不落盘、可手动点选。"""

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


def build_fake_jwt(email: str = "test@example.com", account_id: str = "acct-test-01") -> str:
    header = _b64url(json.dumps({"alg": "none"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url(
        json.dumps(
            {
                "email": email,
                "exp": 9999999999,
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

  if (!window.document.getElementById('accountFileInput')) throw new Error('missing accountFileInput');
  if (!window.document.getElementById('accountList')) throw new Error('missing accountList');
  if (!window.document.getElementById('accountClearAll')) throw new Error('missing accountClearAll');
  if (typeof window.importAccountTexts !== 'function') throw new Error('importAccountTexts not global');

  const jwt = process.env.FAKE_JWT;
  window.importAccountTexts([
    {text: jwt, source: 'demo.at'},
    {text: JSON.stringify({accessToken: jwt, user: {email: 'test@example.com'}}), source: 'session.json'}
  ]);
  await wait(20);

  const list = window.document.getElementById('accountList');
  if (list.hidden) throw new Error('account list still hidden after import');
  const chips = list.querySelectorAll('.account-chip');
  if (!chips.length) throw new Error('no account chips rendered');

  const token = window.document.getElementById('token');
  if (!String(token.value || '').includes('eyJ')) throw new Error('token textarea not filled');

  const before = chips.length;
  window.importAccountTexts([{text: jwt, source: 'demo2.at'}]);
  await wait(10);
  const after = list.querySelectorAll('.account-chip').length;
  if (after > before + 1) throw new Error(`unexpected account growth: ${before} -> ${after}`);

  // 本地私有化：账号库应写入 localStorage，并与账号绑定。
  const stored = window.localStorage.getItem('pay153.accounts.v1');
  if (!stored) throw new Error('expected pay153.accounts.v1 persistence');
  const parsedStore = JSON.parse(stored);
  if (!Array.isArray(parsedStore.accounts) || !parsedStore.accounts.length) {
    throw new Error('persisted accounts empty');
  }
  window.recordActiveAccountOutcome({
    status: 'done',
    result: {promo_requested: true, promo_applied: true, payment_method_types: ['card', 'paypal'], link_type: 'paypal', url: 'https://example.test/result'}
  }, 'paypal', 'job-status-1');
  const statusStore = JSON.parse(window.localStorage.getItem('pay153.accounts.v1'));
  const activeStatus = statusStore.accounts.find(item => item.id === statusStore.activeId) || statusStore.accounts[0];
  if (activeStatus.promoStatus !== 'supported') throw new Error('promo status not persisted');
  if (activeStatus.paymentMethods.paypal !== 'supported') throw new Error('payment method status not persisted');
  if (activeStatus.lastJobId !== 'job-status-1') throw new Error('last job status not persisted');
  if (activeStatus.lastResultUrl !== 'https://example.test/result') throw new Error('last result URL not persisted');
  window.recordActiveAccountOutcome({
    status: 'error', error_code: 'promo_not_applied',
    error: 'Plus 首月免费优惠未生效：Stripe 今日应付 amount=2000'
  }, 'paypal', 'job-promo-stop');
  const promoFailure = JSON.parse(window.localStorage.getItem('pay153.accounts.v1')).accounts.find(item => item.id === activeStatus.id);
  if (promoFailure.promoStatus !== 'unsupported') throw new Error('promo failure status not persisted');
  if (promoFailure.lastResultUrl !== 'https://example.test/result') throw new Error('promo failure overwrote last result');

  // 模拟点击清空：JSDOM 对 window.confirm 默认可能为 false，这里强制允许。
  window.confirm = () => true;
  window.document.getElementById('accountClearAll').click();
  await wait(10);
  if (!list.hidden) throw new Error('account list not hidden after clear');
  if (String(token.value || '').trim()) throw new Error('token not cleared');
  const afterClear = window.localStorage.getItem('pay153.accounts.v1');
  const cleared = afterClear ? JSON.parse(afterClear) : {accounts: []};
  if ((cleared.accounts || []).length) throw new Error('accounts not cleared from storage');

  console.log(JSON.stringify({ok: true, chips_before_clear: before}));
  process.exit(0);
})().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''


class AccountImportUiTests(unittest.TestCase):
    def test_account_import_persists_locally_and_is_selectable(self) -> None:
        env = os.environ.copy()
        env["FAKE_JWT"] = build_fake_jwt()
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
