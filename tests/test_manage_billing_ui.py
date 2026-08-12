import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');

const html = fs.readFileSync('static/manage.html', 'utf8');
const manageJs = fs.readFileSync('static/manage.js', 'utf8');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

const responses = {
  '/api/manage/session': {configured: true, authenticated: true},
  '/api/manage/summary': {proxy_pools: 0, billing_profiles: 0, asn_regions: 0, success_records: 0},
  '/api/manage/proxy-pools': {items: []},
  '/api/manage/billing-profiles': {items: []},
  '/api/manage/asn-recommendations': {items: []}
};

const addressResponse = {
  addresses: [{
      name: 'The Savoy',
      line1: 'Strand',
      city: 'London',
      state: '',
      postal_code: 'WC2R 0EZ',
      country: 'GB',
      type: 'office',
      source: 'builtin_public'
  }],
  countries: ['GB'],
  total: 1,
  library_total: 1,
  type_counts: {office: 1}
};

function responseFor(path) {
  if (path.startsWith('/api/manage/builtin-addresses')) return addressResponse;
  if (path.startsWith('/api/manage/success-records')) return {items: []};
  if (path.startsWith('/api/manage/logs')) return {items: []};
  return responses[path];
}

(async () => {
  const dom = new JSDOM(html, {url: 'http://localhost/manage', runScripts: 'outside-only'});
  const {window} = dom;
  window.matchMedia = () => ({matches: false, addEventListener() {}, removeEventListener() {}});
  window.fetch = async input => {
    const path = new URL(String(input), window.location.href).pathname + new URL(String(input), window.location.href).search;
    const payload = responseFor(path);
    if (!payload) throw new Error(`Unexpected request: ${path}`);
    return {ok: true, status: 200, json: async () => payload};
  };
  window.eval(manageJs);
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (window.document.querySelectorAll('#addressesTable tr').length) break;
    await wait(10);
  }
  const panels = [...window.document.querySelectorAll('[data-panel="addresses"]')];
  if (panels.length !== 1) throw new Error(`Expected one address-library panel, found ${panels.length}`);
  const overviewLink = window.document.querySelector('[data-jump="addresses"]#addressLibraryOverview');
  if (!overviewLink) throw new Error('Overview omitted the address-library entry');
  if (window.document.getElementById('statBuiltinAddresses').textContent.trim() !== '1') {
    throw new Error('Overview address count was not rendered');
  }
  overviewLink.click();
  if (panels[0].hidden) throw new Error('Overview entry did not open the address library');
  const rows = [...window.document.querySelectorAll('#addressesTable tr')];
  if (rows.length !== 1) throw new Error(`Expected one address row, rendered ${rows.length}`);
  const rowText = rows[0].textContent;
  for (const expected of ['GB', '办公室', 'The Savoy', 'Strand', 'London', 'WC2R 0EZ']) {
    if (!rowText.includes(expected)) throw new Error(`Address row omitted: ${expected}`);
  }
  if (window.document.querySelectorAll('#addressCountryFilter option').length !== 2) {
    throw new Error('Country filter was not populated from address metadata');
  }
  dom.window.close();
  console.log('manage address-library UI test passed');
})().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
'''


class ManageBillingUiTests(unittest.TestCase):
    def test_address_library_has_one_discoverable_filtered_table(self):
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
            (result.stderr or result.stdout or "内置账单地址页面测试失败").strip(),
        )


if __name__ == "__main__":
    unittest.main()
