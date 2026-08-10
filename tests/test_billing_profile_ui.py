import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');

const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function setup() {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.matchMedia = () => ({matches: false});
  window.fetch = async () => { throw new Error('network not expected'); };
  window.eval(appJs);
  return window;
}

function rail(window, value) {
  return window.document.querySelector(`label.rail input[value="${value}"]`).closest('label');
}

function input(window, id, value) {
  const node = window.document.getElementById(id);
  node.value = value;
  node.dispatchEvent(new window.Event('input', {bubbles: true}));
}

(async () => {
  const window = setup();
  rail(window, 'gopay').click();
  await wait(30);
  const block = window.document.getElementById('billingBlock');
  if (block.hidden) throw new Error('Gopay billing block is hidden');
  if (!window.document.getElementById('billingName').required) throw new Error('Gopay billing name is not required');
  input(window, 'billingName', 'Verified Customer');
  input(window, 'billingLine1', 'Jl. Example No. 10');
  input(window, 'billingCity', 'Jakarta');
  input(window, 'billingState', 'Jakarta');
  input(window, 'billingPostalCode', '10110');
  await wait(300);
  const stored = JSON.parse(window.localStorage.getItem('pay153.billing_profiles.v1'));
  if (!stored.profiles['gopay:ID']) throw new Error('Gopay billing profile was not saved');
  rail(window, 'paypal').click();
  await wait(30);
  if (!block.hidden) throw new Error('Billing block should be hidden for PayPal');
  rail(window, 'gopay').click();
  await wait(30);
  if (window.document.getElementById('billingCity').value !== 'Jakarta') throw new Error('Gopay billing profile was not restored');
  console.log('billing profile UI tests passed');
})().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
'''


class BillingProfileUiTests(unittest.TestCase):
    def test_gopay_profile_save_and_switching(self):
        result = subprocess.run(
            ["node", "-e", NODE_SCRIPT],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(
            result.returncode,
            0,
            (result.stderr or result.stdout or "账单档案 UI 测试失败").strip(),
        )


if __name__ == "__main__":
    unittest.main()
