import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NODE_SCRIPT = r'''
const fs = require('fs');
const {JSDOM} = require('jsdom');

const html = fs.readFileSync('static/index.html', 'utf8');
const appJs = fs.readFileSync('static/app.js', 'utf8');

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

function setCountry(window, country) {
  const node = window.document.getElementById('country');
  node.value = country;
  node.dispatchEvent(new window.Event('change', {bubbles: true}));
}

function rows(window) {
  return [...window.document.querySelectorAll('#proxyAsnList .proxy-asn-item code')].map(node => node.textContent);
}

function testDefaultAndCountrySwitching() {
  const window = setup();
  const stored = JSON.parse(window.localStorage.getItem('pay153.proxy_asn_recommendations.v1'));
  if (stored.version !== 1) throw new Error('ASN recommendation storage version is incorrect');
  if (stored.regions.GB.items[0].asn !== 'AS2856') throw new Error('GB default order was not saved');
  setCountry(window, 'GB');
  const list = rows(window);
  if (list[0] !== 'AS2856' || list[1] !== 'AS5607' || list[2] !== 'AS5089') {
    throw new Error(`unexpected GB order: ${list.slice(0, 3).join(', ')}`);
  }
  if (list.length !== 35) throw new Error(`expected 35 GB ASN recommendations, got ${list.length}`);
  setCountry(window, 'US');
  if (!window.document.getElementById('proxyAsnRecommendationHint').textContent.includes('暂无本地 ASN')) {
    throw new Error('unknown country should show an empty recommendation state');
  }
}

function testStoredOrderWins() {
  const custom = JSON.stringify({
    version: 1,
    regions: {
      GB: {
        label: '英国自定义',
        items: [
          {asn: 'AS99999', provider: 'Local test', tier: 'A', note: 'custom first'},
          {asn: 'AS2856', provider: 'BT', tier: 'B', note: 'custom second'}
        ]
      }
    }
  });
  const window = setup({'pay153.proxy_asn_recommendations.v1': custom});
  setCountry(window, 'GB');
  const list = rows(window);
  if (list[0] !== 'AS99999' || list[1] !== 'AS2856' || list.length !== 2) {
    throw new Error(`stored GB order was overwritten: ${list.join(', ')}`);
  }
}

try {
  testDefaultAndCountrySwitching();
  testStoredOrderWins();
  console.log('proxy ASN recommendation tests passed');
} catch (error) {
  console.error(error.stack || error);
  process.exitCode = 1;
}
'''


class ProxyAsnRecommendationUiTests(unittest.TestCase):
    def test_country_scoped_local_order(self):
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
            (result.stderr or result.stdout or "ASN 推荐顺序测试失败").strip(),
        )


if __name__ == "__main__":
    unittest.main()
