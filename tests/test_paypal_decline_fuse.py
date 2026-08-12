"""PayPal 风控熔断与账号本地冷却：静态/轻量验证（避免 import 完整 app 卡住）。"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _is_paypal_risk_decline_error(error: str, error_code: str = "") -> bool:
    """与 app.is_paypal_risk_decline_error 保持同逻辑的镜像，供无 Flask 环境单测。"""
    code = str(error_code or "").strip().lower()
    if code in {"paypal_generic_decline_fuse", "paypal_generic_decline"}:
        return True
    text = str(error or "")
    lowered = text.lower()
    if "generic_decline" in lowered:
        return True
    if "setup_attempt_failed" in lowered:
        return True
    if "checkout_approval_payment_failure" in lowered:
        return True
    if ("approve" in lowered or "轮询" in text) and "未返回跳转" in text:
        return True
    if "支付被拒绝" in text or "支付通道拒绝" in text:
        return True
    return False


class PaypalDeclineFuseStaticTests(unittest.TestCase):
    def test_app_source_contains_fuse(self) -> None:
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("PAYPAL_GENERIC_DECLINE_FUSE_ERROR_CODE", text)
        self.assertIn("paypal_decline_streak", text)
        self.assertIn("is_paypal_risk_decline_error", text)
        self.assertIn("PAYPAL_GENERIC_DECLINE_STREAK", text)

    def test_poll_early_stop_in_stripe_checkout(self) -> None:
        text = (ROOT / "stripe_checkout.py").read_text(encoding="utf-8")
        self.assertIn("停止继续轮询以避免空转", text)
        self.assertIn("risk_decline", text)

    def test_decline_classifier(self) -> None:
        self.assertTrue(_is_paypal_risk_decline_error("decline_code=generic_decline"))
        self.assertTrue(
            _is_paypal_risk_decline_error(
                "PayPal approve 已成功，但轮询 20 次未返回跳转地址，正在更换代理重新尝试"
            )
        )
        self.assertFalse(_is_paypal_risk_decline_error("代理地区检测失败：SSLError"))
        self.assertFalse(_is_paypal_risk_decline_error("Plus 首月免费优惠未生效：amount=2000"))


class AccountCooldownStaticTests(unittest.TestCase):
    def test_frontend_hooks_exist(self) -> None:
        app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("pay153.accounts.v1", app_js)
        self.assertIn("ACCOUNT_COOLDOWN_MS", app_js)
        self.assertIn("markActiveAccountCooldown", app_js)
        self.assertIn("getActiveAccountCooldownBlocker", app_js)
        self.assertIn("ACCOUNT_BLOCK_STREAK_LIMIT", app_js)
        self.assertIn("ACCOUNT_BLOCK_FUSE_ERROR_CODE", app_js)
        self.assertIn("clearAccountFreeze", app_js)
        self.assertIn("paypal_generic_decline_fuse", app_js)
        self.assertIn("本机保存", html)
        self.assertTrue(re.search(r"60\s*\*\s*60\s*\*\s*1000", app_js))

    def test_account_cooldown_roundtrip_jsdom(self) -> None:
        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

        header = b64url(json.dumps({"alg": "none"}, separators=(",", ":")).encode())
        payload = b64url(
            json.dumps(
                {
                    "email": "cool@example.com",
                    "exp": 9999999999,
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-cool-01"},
                },
                separators=(",", ":"),
            ).encode()
        )
        jwt = f"{header}.{payload}.sig"
        script = r"""
const fs = require('fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.matchMedia = () => ({matches: false});
  window.fetch = async () => ({ok: true, status: 200, json: async () => ({})});
  window.eval(appJs);
  const jwt = process.env.FAKE_JWT;
  window.document.getElementById('token').value = jwt;
  window.importAccountTexts([{text: jwt, source: 'cool.at'}]);
  const marked = window.markActiveAccountCooldown(60 * 60 * 1000, 'test');
  if (!marked || !marked.cooldownUntil) throw new Error('mark failed');
  const raw = JSON.parse(window.localStorage.getItem('pay153.accounts.v1'));
  if (!raw.accounts[0].cooldownUntil || raw.accounts[0].cooldownUntil <= Date.now()) {
    throw new Error('cooldown not stored');
  }
  if (!window.getActiveAccountCooldownBlocker()) throw new Error('blocker missing');
  process.stdout.write(JSON.stringify({ok: true}) + '\n');
  process.exit(0);
})().catch((error) => {
  process.stderr.write(String(error && error.stack || error) + '\n');
  process.exit(1);
});
"""
        env = os.environ.copy()
        env["FAKE_JWT"] = jwt
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            env=env,
            timeout=30,
            check=False,
        )
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if completed.returncode != 0:
            self.fail(stderr or stdout or "node failed")
        self.assertIn('"ok":true', stdout.replace(" ", ""))

    def test_account_freezes_after_three_explicit_block_outcomes(self) -> None:
        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

        header = b64url(json.dumps({"alg": "none"}, separators=(",", ":")).encode())
        payload = b64url(
            json.dumps(
                {
                    "email": "blocked@example.com",
                    "exp": 9999999999,
                    "https://api.openai.com/auth": {"chatgpt_account_id": "acct-block-01"},
                },
                separators=(",", ":"),
            ).encode()
        )
        jwt = f"{header}.{payload}.sig"
        script = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');
(async () => {
  const dom = new JSDOM(fs.readFileSync('static/index.html', 'utf8'), {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.matchMedia = () => ({matches: false});
  window.fetch = async () => ({ok: true, status: 200, json: async () => ({})});
  window.eval(fs.readFileSync('static/app.js', 'utf8'));
  const jwt = process.env.FAKE_JWT;
  window.document.getElementById('token').value = jwt;
  window.importAccountTexts([{text: jwt, source: 'blocked.at'}]);
  for (let index = 1; index <= 3; index += 1) {
    window.recordActiveAccountOutcome({
      status: 'error',
      error_code: 'account_blocked',
      error: 'account blocked by policy'
    }, 'paypal', `job-block-${index}`);
  }
  const stored = JSON.parse(window.localStorage.getItem('pay153.accounts.v1'));
  const account = stored.accounts[0];
  if (account.riskStatus !== 'frozen') throw new Error(`expected frozen, got ${account.riskStatus}`);
  if (account.consecutiveBlocks !== 3) throw new Error(`expected 3 blocks, got ${account.consecutiveBlocks}`);
  if (!window.getActiveAccountCooldownBlocker()) throw new Error('frozen account was not blocked');
  const checkbox = window.document.querySelector('.account-batch-check');
  if (!checkbox || !checkbox.disabled) throw new Error('frozen account remained selectable');
  window.clearAccountFreeze(account.id);
  const unfrozen = JSON.parse(window.localStorage.getItem('pay153.accounts.v1')).accounts[0];
  if (unfrozen.riskStatus !== 'rejected' || unfrozen.consecutiveBlocks !== 0) throw new Error('manual unfreeze did not reset state');
  console.log(JSON.stringify({ok: true, risk: account.riskStatus}));
})().catch(error => {
  console.error(error && error.stack || error);
  process.exit(1);
});
'''
        env = os.environ.copy()
        env["FAKE_JWT"] = jwt
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node failed")
        self.assertIn('"ok":true', completed.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
