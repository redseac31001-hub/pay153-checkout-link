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
const response = (status, payload) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => payload
});

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  window.requestAnimationFrame = () => 0;
  window.cancelAnimationFrame = () => {};
  window.matchMedia = () => ({matches: false});
  let checkoutBody = null;
  window.fetch = async (url, options = {}) => {
    const href = String(url);
    if (href.startsWith('/api/manage/paypal-billing-options')) {
      const parsed = new URL(href, window.location.origin);
      const country = parsed.searchParams.get('country') || '';
      return response(200, {
        country,
        countries: [{country: 'GB', builtin_count: 1, manual_count: 1}],
        manual_profiles: country ? [{
          id: 12,
          profile_key: 'paypal:GB:primary',
          rail: 'paypal',
          country: 'GB',
          name_masked: 'Pr***',
          address_masked: '77*** · Lo*** · SW***'
        }] : [],
        builtin_addresses: country ? [{
          id: '0123456789abcdefabcd',
          name: 'The Savoy',
          line1: 'Strand',
          city: 'London',
          state: '',
          postal_code: 'WC2R 0EZ',
          country: 'GB',
          type: 'office'
        }] : []
      });
    }
    if (href === '/api/checkout') {
      checkoutBody = JSON.parse(options.body);
      return response(400, {error: 'test stop'});
    }
    throw new Error(`unexpected fetch: ${href}`);
  };
  window.eval(appJs);

  const paypalRail = window.document.querySelector('label.rail input[value="paypal"]').closest('label');
  paypalRail.click();
  await wait(40);

  const source = window.document.getElementById('paypalBillingSource');
  const country = window.document.getElementById('paypalBillingCountry');
  const address = window.document.getElementById('paypalBillingAddress');
  if (!source || !country || !address) throw new Error('PayPal billing selectors are missing');
  if (window.document.getElementById('paypalOptions').hidden) throw new Error('PayPal options are hidden');

  source.value = 'builtin_address';
  source.dispatchEvent(new window.Event('change', {bubbles: true}));
  await wait(40);
  if (country.value !== 'GB') throw new Error(`expected GB country, got ${country.value}`);
  if (address.options.length !== 1) throw new Error(`expected one address, got ${address.options.length}`);
  address.value = '0123456789abcdefabcd';
  address.dispatchEvent(new window.Event('change', {bubbles: true}));

  window.document.getElementById('token').value = 'test-token';
  window.document.getElementById('entryProxy').value = 'http://user:pass@127.0.0.1:18080';
  window.document.getElementById('exitProxy').value = 'http://user:pass@127.0.0.1:18081';
  window.document.getElementById('checkoutForm').dispatchEvent(
    new window.Event('submit', {bubbles: true, cancelable: true})
  );
  await wait(40);

  if (!checkoutBody) throw new Error('Checkout body was not submitted');
  const selection = checkoutBody.billing_selection;
  if (!selection || selection.kind !== 'builtin_address') throw new Error('Built-in selection was not submitted');
  if (selection.id !== '0123456789abcdefabcd' || selection.country !== 'GB') {
    throw new Error(`wrong selection: ${JSON.stringify(selection)}`);
  }
  if (checkoutBody.billing_profile !== null) throw new Error('Hidden Gopay billing profile leaked into PayPal');

  source.value = 'manage_profile';
  source.dispatchEvent(new window.Event('change', {bubbles: true}));
  await wait(40);
  if (address.options.length !== 1 || address.value !== '12') {
    throw new Error('Manage manual profile was not rendered');
  }
  window.document.getElementById('checkoutForm').dispatchEvent(
    new window.Event('submit', {bubbles: true, cancelable: true})
  );
  await wait(40);
  if (checkoutBody.billing_selection.kind !== 'manage_profile' || checkoutBody.billing_selection.id !== 12) {
    throw new Error(`wrong manual selection: ${JSON.stringify(checkoutBody.billing_selection)}`);
  }
  console.log('paypal billing selection UI tests passed');
})().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
'''


class PaypalBillingSelectionUiTests(unittest.TestCase):
    def test_paypal_can_submit_selected_manage_address(self):
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
            (result.stderr or result.stdout or "PayPal 账单选择 UI 测试失败").strip(),
        )


if __name__ == "__main__":
    unittest.main()
