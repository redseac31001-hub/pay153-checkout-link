import os, sys, time, random, io
from pathlib import Path
from collections import Counter
from urllib.parse import urlsplit, unquote

ROOT = Path(r'E:\mygit\pay153-checkout-link')
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for line in (ROOT / '.env').read_text(encoding='utf-8', errors='replace').splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    os.environ.setdefault(key.strip(), value.strip())

report = io.StringIO()

def p(x):
    print(x, flush=True)
    report.write(str(x) + '\n')

import stripe_checkout as sc
from manage_store import ManageStore

def mask(line):
    line = str(line or '').strip()
    if not line:
        return ''
    try:
        parsed = urlsplit(line if '://' in line else 'socks5h://' + line)
        host = unquote(parsed.hostname or '?')
        port = parsed.port or ''
        user = unquote(parsed.username or '')
        scheme = parsed.scheme or ''
        if user:
            return f'{scheme}://{user[:1]}***@{host}:{port}'
        return f'{scheme}://{host}:{port}'
    except Exception:
        return line[:26] + '...'

def classify(message):
    message = str(message or '').lower()
    for key in ('proxy', 'ssl', 'timeout', 'connect', 'curl'):
        if key in message:
            return key.upper()
    return 'OTHER'

def geo_one(proxy, pre):
    from curl_cffi.requests import Session
    from curl_cffi.const import CurlOpt
    started = time.time()
    try:
        if pre is False:
            http = Session(impersonate='chrome136', curl_options={})
            if proxy:
                http.proxies = {'http': proxy, 'https': proxy}
        else:
            http = Session(impersonate='chrome136', curl_options={CurlOpt.PRE_PROXY: pre})
            if proxy:
                http.proxies = {'http': proxy, 'https': proxy}
        probes = (
            'http://ip-api.com/json/?fields=status,countryCode,regionName,city,query',
            'https://ipapi.co/json/',
            'https://api.ipify.org?format=json',
        )
        errors = []
        for url in probes:
            try:
                response = http.get(url, timeout=10)
                if getattr(response, 'status_code', 0) != 200:
                    errors.append(f'{url} HTTP {getattr(response, "status_code", 0)}')
                    continue
                try:
                    data = response.json() or {}
                except Exception:
                    errors.append(f'{url} bad-json')
                    continue
                ip = str((data or {}).get('ip') or (data or {}).get('query') or '')
                cc = str((data or {}).get('countryCode') or (data or {}).get('country_code') or (data or {}).get('country') or '')[:2].upper()
                if len(cc) != 2:
                    continue
                return {
                    'ok': 1,
                    'ms': int((time.time() - started) * 1000),
                    'ip': ip,
                    'cc': cc,
                    'region': str((data or {}).get('regionName') or (data or {}).get('region') or ''),
                    'city': str((data or {}).get('city') or ''),
                }
            except Exception as exc:
                errors.append(f'{url} {type(exc).__name__}:{str(exc)[:80]}')
        pending = errors[-3:]
        return {
            'ok': 0,
            'ms': int((time.time() - started) * 1000),
            'err': ' | '.join(pending) or 'no response',
            'cls': classify(pending[-1] if pending else 'fail'),
        }
    except Exception as exc:
        return {
            'ok': 0,
            'ms': int((time.time() - started) * 1000),
            'err': f'{type(exc).__name__}: {exc}',
            'cls': classify(exc),
        }

p('=' * 70)
p('Pay153 代理随机检测诊断  start=' + time.strftime('%H:%M:%S'))
p('PRE_PROXY env=' + repr(os.getenv('PAY153_PROXY_PRE_PROXY')))
p('proxy_pre_proxy()=' + repr(sc.proxy_pre_proxy()))
p('=' * 70)

p('\n[A] 基线')
for label, kw in [
    ('A1 本机直连', {'proxy': None, 'pre': False}),
    ('A2 本地9697作主代理', {'proxy': 'socks5h://127.0.0.1:9697', 'pre': False}),
    ('A3 仅PRE 无池', {'proxy': None, 'pre': 'socks5h://127.0.0.1:9697'}),
]:
    r = geo_one(kw['proxy'], kw['pre'])
    if r['ok']:
        p('  OK  ' + f"{label}: {r['cc']}/{r.get('region')}/{r.get('city')} ip={r['ip']} {r['ms']}ms")
    else:
        p('  FAIL[' + str(r.get('cls')) + '] ' + f"{label}: {r.get('err')} {r['ms']}ms")

p('\n[B] Manage 代理池')
key = ROOT / 'data/.manage.key'
if not key.exists():
    p('  missing data/.manage.key')
    raise SystemExit(2)
store = ManageStore(db_path=ROOT / 'data/pay153_manage.sqlite3', encryption_key=key.read_bytes().strip())
listed = store.list_proxy_pools()
p(f'  池数 {len(listed)}')
pools = []
for meta in listed:
    full = store.get_proxy_pool(int(meta['id']), reveal=True)
    proxies = full.get('proxies') or []
    pools.append({
        'id': meta['id'], 'name': meta.get('name'), 'rail': meta.get('rail'),
        'country': meta.get('country'), 'kind': meta.get('pool_kind'),
        'enabled': meta.get('enabled'), 'n': len(proxies), 'ps': proxies,
        'preview': full.get('proxy_preview') or meta.get('proxy_preview'),
    })
    p(f"  #{meta['id']} {meta.get('name')} rail={meta.get('rail')} country={meta.get('country')} "
      f"kind={meta.get('pool_kind')} enabled={meta.get('enabled')} n={len(proxies)} {full.get('proxy_preview') or meta.get('proxy_preview')}")

import random
rng = random.SystemRandom()
summary = []
PRE = 'socks5h://127.0.0.1:9697'
p('\n[C] 随机抽检')
for po in pools:
    ps = [x for x in po['ps'] if x]
    if not ps:
        p(f"\n-- 池#{po['id']} {po['name']} 空")
        continue
    sample = ps if len(ps) <= 3 else rng.sample(ps, 3)
    p(f"\n-- 池#{po['id']} {po['name']} rail={po['rail']} country={po['country']} kind={po['kind']} 抽样{len(sample)}/{len(ps)}")
    for i, x in enumerate(sample, 1):
        prefix = f'   样本{i}: {mask(x)}'
        p(prefix)
        dual = geo_one(x, PRE)
        direct = geo_one(x, False)
        for label, r in [('双层PRE+池', dual), ('直连池无PRE', direct)]:
            if r['ok']:
                p(f"    OK  {label}: {r['cc']}/{r.get('region')}/{r.get('city')} ip={r['ip']} {r['ms']}ms")
            else:
                p(f"    FAIL {label}: [{r.get('cls')}] {r.get('err')} {r['ms']}ms")
            summary.append({'label': label, 'ok': r['ok'], 'cls': r.get('cls'), 'po': po['id']})

p('\n[D] app.proxy_geo 抽 3')
try:
    import app as am
    ps = []
    for po in pools:
        for x in po['ps']:
            if x:
                ps.append((po, x))
    few = ps if len(ps) <= 3 else rng.sample(ps, 3)
    for po, x in few:
        started = time.time()
        try:
            g = am.proxy_geo(x)
            p(f"   pool#{po['id']} {mask(x)} -> {g.get('country')}/{g.get('region')}/{g.get('city')} ip={g.get('ip')} {int((time.time() - started) * 1000)}ms")
        except Exception as exc:
            p(f"   pool#{po['id']} {mask(x)} -> FAIL {type(exc).__name__}: {exc} {int((time.time() - started) * 1000)}ms")
except Exception as exc:
    p('  app import fail ' + repr(exc))

p('\n[E] 汇总')
okp = sum(1 for s in summary if s['label'] == '双层PRE+池' and s['ok'])
fp = sum(1 for s in summary if s['label'] == '双层PRE+池' and not s['ok'])
okd = sum(1 for s in summary if s['label'] == '直连池无PRE' and s['ok'])
fd = sum(1 for s in summary if s['label'] == '直连池无PRE' and not s['ok'])
p(f'双层PRE: OK {okp} / FAIL {fp}')
p(f'直连:   OK {okd} / FAIL {fd}')
p('失败分类: ' + str(dict(Counter(s['cls'] for s in summary if not s['ok']))))
if fp and okd:
    p('判定: 池可达，问题在双层PRE(9697->池)链路')
elif fp and fd:
    p('判定: 池条目大面积不可达(凭据/节点/协议)，非本地代理问题')
elif okp:
    p('判定: 抽样双层可用；任务失败多为抽到坏节点/间歇')
else:
    p('判定: 结合明细')
p('=' * 70)

Path('proxy_diag_report.txt').write_text(report.getvalue(), encoding='utf-8')
print('report saved to proxy_diag_report.txt')