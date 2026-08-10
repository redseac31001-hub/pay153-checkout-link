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

function setup(seed = {}) {
  const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only'});
  const {window} = dom;
  Object.entries(seed).forEach(([key, value]) => window.localStorage.setItem(key, value));
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

async function testSwitching() {
  const window = setup();
  input(window, 'entryProxy', 'http://default-entry:1000');
  input(window, 'exitProxy', 'http://default-exit:2000');
  await wait(260);
  rail(window, 'gopay').click();
  await wait(30);
  if (window.document.getElementById('entryProxy').value !== 'http://default-entry:1000') throw new Error('default entry was not inherited');
  input(window, 'entryProxy', 'http://gopay-entry:3000');
  input(window, 'exitProxy', 'http://gopay-exit:4000');
  await wait(260);
  rail(window, 'paypal').click();
  await wait(30);
  if (window.document.getElementById('entryProxy').value !== 'http://default-entry:1000') throw new Error('PayPal inherited Gopay entry');
  rail(window, 'gopay').click();
  await wait(30);
  if (window.document.getElementById('entryProxy').value !== 'http://gopay-entry:3000') throw new Error('Gopay profile was not restored');
}

function testLegacyMigration() {
  const window = setup({
    'pay153.proxy_pool_1': 'http://legacy-entry:1000',
    'pay153.proxy_pool_2': 'http://legacy-exit:2000'
  });
  if (window.document.getElementById('entryProxy').value !== 'http://legacy-entry:1000') throw new Error('legacy entry was not restored');
  const migrated = JSON.parse(window.localStorage.getItem('pay153.proxy_profiles.v1'));
  if (migrated.default.entry !== 'http://legacy-entry:1000') throw new Error('legacy profile was not migrated');
}

(async () => {
  await testSwitching();
  testLegacyMigration();
  console.log('proxy profile tests passed');
})().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
'''


class ProxyProfileTests(unittest.TestCase):
    def test_switching_and_legacy_migration(self):
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
            (result.stderr or result.stdout or "代理配置测试失败").strip(),
        )


if __name__ == "__main__":
    unittest.main()
