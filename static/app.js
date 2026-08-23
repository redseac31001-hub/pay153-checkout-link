const $ = (id) => document.getElementById(id);
const form = $('checkoutForm');
let jobId = '';
let singleJobBinding = null;
let pollTimer = 0;
let countdownTimer = 0;
let displayedProgress = 0;
let targetProgress = 0;
let progressStatus = 'idle';
let progressFrame = 0;
let progressLastTick = 0;
let proxySaveTimer = 0;
let logAutoFollow = true;
let renderedLogKey = '';
let activeRunMode = '';
let batchPollTimer = 0;
let batchJobs = [];
let activeBatchTaskType = 'checkout';
let batchPumpTimer = 0;
let batchPumpRunning = false;
let batchCreateReadyAt = 0;
const batchSelectedAccountIds = new Set();
let taskLimits = {perIp: 3, global: 20, workers: 20};

const PROXY_STORAGE_KEYS = {
  profiles: 'pay153.proxy_profiles.v1',
  legacyEntry: 'pay153.proxy_pool_1',
  legacyExit: 'pay153.proxy_pool_2'
};
const BILLING_STORAGE_KEY = 'pay153.billing_profiles.v1';
const PROXY_ASN_RECOMMENDATION_STORAGE_KEY = 'pay153.proxy_asn_recommendations.v1';
const BILLING_PROFILE_FIELDS = ['name', 'email', 'line1', 'line2', 'city', 'state', 'postal_code'];

// 账号库本地持久化（私有化本机）；含冷却标记。明文 token 仅存本机浏览器。
const ACCOUNT_STORAGE_KEY = 'pay153.accounts.v1';
// 工程降频默认 60 分钟（非 Stripe/PayPal 官方规定时长）。
const ACCOUNT_COOLDOWN_MS = 60 * 60 * 1000;
const ACCOUNT_BLOCK_STREAK_LIMIT = 3;
const ACCOUNT_BLOCK_FUSE_ERROR_CODE = 'account_blocked_fuse';
const ACCOUNT_PAYMENT_METHOD_ALIASES = {
  card: 'card',
  gopay: 'gopay',
  ideal: 'ideal',
  paypal: 'paypal',
  pix: 'pix',
  upi: 'upi',
  hosted: 'hosted'
  ,gcash: 'gcash'
};
const CHECKOUT_PROTOCOL_TTL_MS = 24 * 60 * 60 * 1000;
const CHECKOUT_PROTOCOLS = new Set(['oaics', 'cs', 'unknown']);
const ACCOUNT_LIFECYCLES = new Set(['active', 'completed', 'deleted']);
const ACCOUNT_LIFECYCLE_LABELS = {
  active: '正常',
  completed: '已完成',
  deleted: '已注销/删除'
};
const accountEntries = [];
let activeAccountId = '';
let accountIdSeq = 0;
let accountCooldownTimer = 0;

const DEFAULT_PROXY_ASN_RECOMMENDATIONS = {
  GB: {
    label: '英国',
    items: [
      {asn: 'AS2856', provider: 'BT', tier: 'A', note: '综合首选 · 大型家庭宽带'},
      {asn: 'AS5607', provider: 'Sky UK', tier: 'A', note: '家庭宽带 · 覆盖较广'},
      {asn: 'AS5089', provider: 'Virgin Media', tier: 'A', note: '家庭宽带 · 固定线路'},
      {asn: 'AS13285', provider: 'TalkTalk', tier: 'A', note: '家庭 ISP · 覆盖较广'},
      {asn: 'AS13037', provider: 'Zen', tier: 'A', note: '家庭 ISP · 网络质量稳定'},
      {asn: 'AS6871', provider: 'Plusnet', tier: 'A', note: '家庭 ISP · BT 体系'},
      {asn: 'AS9105', provider: 'TalkTalk', tier: 'B', note: 'TalkTalk 相关家庭网络'},
      {asn: 'AS12390', provider: 'KCOM', tier: 'B', note: '区域 ISP · 主要覆盖 Hull 一带'},
      {asn: 'AS43915', provider: 'TrueSpeed', tier: 'B', note: '区域 FTTP · 西南英格兰'},
      {asn: 'AS201838', provider: 'Community Fibre', tier: 'B', note: '伦敦本地光纤'},
      {asn: 'AS56478', provider: 'Hyperoptic', tier: 'B', note: '城市光纤 · 覆盖受限'},
      {asn: 'AS48101', provider: 'Trooli', tier: 'B', note: '区域光纤'},
      {asn: 'AS56329', provider: 'Gigaclear', tier: 'B', note: '乡村光纤 · 覆盖受限'},
      {asn: 'AS5482', provider: 'AllPoints Fibre', tier: 'B', note: '区域光纤'},
      {asn: 'AS212655', provider: 'YouFibre', tier: 'B', note: '区域光纤'},
      {asn: 'AS207995', provider: 'Lightning Fibre', tier: 'B', note: '区域光纤'},
      {asn: 'AS60377', provider: 'toob', tier: 'B', note: '区域 FTTH'},
      {asn: 'AS48294', provider: 'Ogi Networks', tier: 'B', note: '威尔士本地光纤'},
      {asn: 'AS42611', provider: 'Full Fibre', tier: 'B', note: '区域光纤'},
      {asn: 'AS205847', provider: 'GoFibre', tier: 'B', note: '苏格兰区域光纤'},
      {asn: 'AS199775', provider: 'Connexin', tier: 'B', note: '区域宽带/光纤'},
      {asn: 'AS199468', provider: 'Grain', tier: 'B', note: '区域光纤'},
      {asn: 'AS213671', provider: 'Vision Fibre', tier: 'B', note: '区域光纤'},
      {asn: 'AS60426', provider: 'WightFibre', tier: 'B', note: '区域光纤 · 覆盖受限'},
      {asn: 'AS57099', provider: 'Quickline', tier: 'B', note: '乡村宽带 · 覆盖受限'},
      {asn: 'AS207645', provider: 'F&W Networks', tier: 'B', note: '小型区域 ISP · 需核验城市'},
      {asn: 'AS35437', provider: 'Zone Telecom', tier: 'B', note: '小型 ISP · 需核验具体 IP'},
      {asn: 'AS206067', provider: 'Three UK', tier: 'C', note: '移动网络 · 可能 CGNAT'},
      {asn: 'AS35228', provider: 'O2 UK', tier: 'C', note: '移动网络 · 可能 CGNAT'},
      {asn: 'AS14593', provider: 'Starlink', tier: 'C', note: '卫星网络 · 不作为固定宽带首选'},
      {asn: 'AS25135', provider: 'Vodafone', tier: 'C', note: 'Vodafone 相关 · 需核验 IP 类型'},
      {asn: 'AS25310', provider: 'Vodafone', tier: 'C', note: 'Vodafone 相关 · 需核验 IP 类型'},
      {asn: 'AS5378', provider: 'Vodafone', tier: 'C', note: 'Vodafone 相关 · 需核验 IP 类型'},
      {asn: 'AS31655', provider: 'Gamma Telecom', tier: 'C', note: '企业/电信网络 · 需核验'},
      {asn: 'AS25369', provider: 'Hydra', tier: 'C', note: '企业/托管混合网络 · 需核验'}
    ]
  }
};

const proxyProfileNames = {
  hosted: 'Hosted', paypal: 'PayPal', ideal: 'iDEAL', upi: 'UPI', pix: 'PIX', gopay: 'Gopay'
};
const proxyProfileRails = Object.keys(proxyProfileNames);
let activeProxyRail = '';
let proxyProfiles = {};
let defaultProxyProfile = {entry: '', exit: ''};
let proxyInputDirty = false;
let manageProxyImportTarget = '';
let manageProxyImportPools = [];
let manageProxyImportRevision = 0;
let billingProfiles = {};
let activeBillingProfileKey = '';
let billingSaveTimer = 0;
let billingInputDirty = false;
let proxyAsnRecommendations = {};
let paypalBillingCountries = [];
let paypalBillingCountryPayloads = {};
let paypalBillingCatalogLoaded = false;
let paypalBillingCatalogPromise = null;
let paypalBillingRevision = 0;

const providerDefaults = {
  hosted: {country: 'US', currency: 'USD'}, paypal: {country: 'US', currency: 'USD'},
  ideal: {country: 'NL', currency: 'EUR'}, upi: {country: 'IN', currency: 'INR'},
  pix: {country: 'BR', currency: 'BRL'}, gopay: {country: 'ID', currency: 'IDR'}
};
const countryCurrency = {US:'USD',DE:'EUR',FR:'EUR',NL:'EUR',IN:'INR',BR:'BRL',GB:'GBP',JP:'JPY',AU:'AUD',CA:'CAD',ID:'IDR'};
const railDisplayDetails = {
  hosted: {icon: '↗', title: 'Hosted', description: '官方 Checkout 托管，返回支付长链。', method: 'Checkout 长链'},
  paypal: {icon: 'P', title: 'PayPal', description: '生成 PayPal Approve 跳转，完成账单授权。', method: 'PayPal 跳转'},
  ideal: {icon: 'iD', title: 'iDEAL', description: '使用荷兰 iDEAL 银行授权完成支付。', method: '银行授权'},
  upi: {icon: '₹', title: 'UPI', description: '生成印度 UPI 支付二维码。', method: 'UPI 二维码'},
  pix: {icon: '◇', title: 'PIX', description: '生成巴西 PIX 即时支付二维码。', method: 'PIX 二维码'},
  gopay: {icon: 'G', title: 'Gopay', description: '使用印尼 Gopay 电子钱包完成支付。', method: 'Gopay 钱包'}
};

function proxyLines(node){
  return node.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
}
function updateProxyCount(node, counter){
  const count = proxyLines(node).length;
  counter.textContent = `${count} / 500`;
  counter.classList.toggle('over-limit', count > 500);
  node.setCustomValidity(count > 500 ? '每个代理池最多填写 500 条' : '');
  return count;
}
function setProxyProbeResult(node, text, state=''){
  node.textContent = text;
  node.className = `proxy-probe-result${state ? ` ${state}` : ''}`;
}
async function probeProxyPool(inputId, buttonId, resultId, poolLabel){
  const input = $(inputId), button = $(buttonId), result = $(resultId);
  const proxies = proxyLines(input);
  if (!proxies.length){
    setProxyProbeResult(result, '请先填写至少 1 条代理。', 'error');
    input.focus();
    return;
  }
  button.disabled = true;
  setProxyProbeResult(result, '正在随机检测 1 条代理……');
  try{
    const response = await fetch('/api/proxy-probe', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pool: poolLabel, proxies})
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const country = [data.country, data.country_name].filter(Boolean).join(' / ');
    setProxyProbeResult(
      result,
      `随机第 ${data.selected_index}/${data.pool_size} 条：IP ${data.ip || '?'} · ${country || '国家未知'}`,
      'success'
    );
  }catch(error){
    setProxyProbeResult(result, `检测失败：${error.message || error}`, 'error');
  }finally{
    button.disabled = false;
  }
}
function setProxySaveState(text, failed=false){
  const node = $('proxySaveState');
  node.textContent = text;
  node.classList.toggle('save-failed', failed);
}

function emptyProxyProfile(){ return {entry: '', exit: ''}; }
function cloneProxyProfile(raw){
  return {entry: String(raw?.entry ?? ''), exit: String(raw?.exit ?? '')};
}
function hasProxyProfile(rail){
  return Object.prototype.hasOwnProperty.call(proxyProfiles, rail);
}
function proxyProfileHasContent(profile){
  return Boolean(String(profile?.entry || '').trim() || String(profile?.exit || '').trim());
}
function readProxyProfile(){
  return {entry: $('entryProxy').value, exit: $('exitProxy').value};
}
function proxyProfileForRail(rail){
  return hasProxyProfile(rail) ? cloneProxyProfile(proxyProfiles[rail]) : cloneProxyProfile(defaultProxyProfile);
}
function persistProxyProfiles(){
  const profiles = {};
  proxyProfileRails.forEach(rail => {
    if (hasProxyProfile(rail)) profiles[rail] = cloneProxyProfile(proxyProfiles[rail]);
  });
  localStorage.setItem(PROXY_STORAGE_KEYS.profiles, JSON.stringify({
    version: 1,
    default: cloneProxyProfile(defaultProxyProfile),
    profiles
  }));
}
function updateProxyProfileState(rail=activeProxyRail){
  if (!rail || !$('proxyProfileState')) return;
  const explicit = hasProxyProfile(rail);
  const label = proxyProfileNames[rail] || rail;
  $('proxyProfileState').textContent = `${label} · ${explicit ? '专属配置' : '默认共享'}`;
  $('proxyProfileState').title = explicit
    ? '当前支付方式使用自己的代理池配置，切换方式时会自动保存和恢复。'
    : '当前支付方式继承默认共享代理池，编辑后会保存为该方式专属配置。';
}
function applyProxyProfile(rail){
  const profile = proxyProfileForRail(rail);
  $('entryProxy').value = profile.entry;
  $('exitProxy').value = profile.exit;
  proxyInputDirty = false;
  updateProxyCount($('entryProxy'), $('entryProxyCount'));
  updateProxyCount($('exitProxy'), $('exitProxyCount'));
  updateProxyProfileState(rail);
}
function saveActiveProxyProfile(){
  if (!activeProxyRail || !proxyInputDirty) return false;
  const profile = readProxyProfile();
  if (!proxyProfileHasContent(defaultProxyProfile) && !Object.keys(proxyProfiles).length && proxyProfileHasContent(profile)) {
    defaultProxyProfile = cloneProxyProfile(profile);
  }
  proxyProfiles[activeProxyRail] = profile;
  proxyInputDirty = false;
  persistProxyProfiles();
  updateProxyProfileState();
  return true;
}
function scheduleProxyProfileSave(){
  clearTimeout(proxySaveTimer);
  proxySaveTimer = setTimeout(() => {
    try {
      saveActiveProxyProfile();
      setProxySaveState('已保存当前方式');
    } catch (error) {
      setProxySaveState('本地保存失败', true);
    }
  }, 220);
}
function saveProxyPools(){
  proxyInputDirty = true;
  scheduleProxyProfileSave();
}

function proxyImportTargetLabel(target){
  return target === 'exit' ? '代理池 2' : '代理池 1';
}
function proxyImportPoolKindLabel(kind){
  return kind === 'exit' ? '出口池' : kind === 'entry' ? '入口池' : '共享池';
}
function setProxyImportStatus(text, state=''){
  const node = $('proxyImportStatus');
  if (!node) return;
  node.textContent = text;
  node.className = `proxy-import-status${state ? ` ${state}` : ''}`;
}
function renderProxyImportLoginHint(message){
  const list = $('proxyImportPoolList');
  if (list) {
    list.replaceChildren();
    const empty = document.createElement('div');
    empty.className = 'proxy-import-empty';
    empty.textContent = message;
    const link = document.createElement('a');
    link.className = 'proxy-import-login';
    link.href = '/manage#proxies';
    link.textContent = '打开管理中心登录';
    empty.append(link);
    list.append(empty);
  }
}
function proxyImportPoolCandidates(target){
  const targetKind = target === 'exit' ? 'exit' : 'entry';
  return manageProxyImportPools
    .filter(item => item && item.enabled !== false)
    .map((item, index) => ({item, index}))
    .sort((left, right) => {
      const leftRank = left.item.pool_kind === targetKind ? 0 : left.item.pool_kind === 'entry' || left.item.pool_kind === 'exit' ? 1 : 2;
      const rightRank = right.item.pool_kind === targetKind ? 0 : right.item.pool_kind === 'entry' || right.item.pool_kind === 'exit' ? 1 : 2;
      return leftRank - rightRank || String(left.item.name || '').localeCompare(String(right.item.name || ''), 'zh-CN') || left.index - right.index;
    })
    .map(item => item.item);
}
function renderProxyImportPools(){
  const list = $('proxyImportPoolList');
  if (!list) return;
  list.replaceChildren();
  const target = manageProxyImportTarget || 'entry';
  const candidates = proxyImportPoolCandidates(target);
  if (!candidates.length) {
    setProxyImportStatus('管理中心暂无可导入的启用代理池。', 'error');
    const empty = document.createElement('div');
    empty.className = 'proxy-import-empty';
    empty.textContent = '请先在管理中心新增并启用代理池。';
    list.append(empty);
    return;
  }
  setProxyImportStatus(`已读取 ${candidates.length} 个可用代理池，选择后读取实际线路。`, 'ready');
  candidates.forEach(item => {
    const row = document.createElement('article');
    row.className = 'proxy-import-item';
    const main = document.createElement('div');
    main.className = 'proxy-import-item-main';
    const title = document.createElement('div');
    title.className = 'proxy-import-item-title';
    const name = document.createElement('b');
    name.textContent = String(item.name || `代理池 ${item.id || ''}`).trim() || '未命名代理池';
    const kind = document.createElement('small');
    kind.textContent = proxyImportPoolKindLabel(String(item.pool_kind || '').toLowerCase());
    title.append(name, kind);
    const meta = document.createElement('div');
    meta.className = 'proxy-import-item-meta';
    meta.textContent = [item.rail && item.rail !== 'shared' ? String(item.rail).toUpperCase() : '共享', item.country || '未指定地区', `${Number(item.proxy_count) || 0} 条`].join(' · ');
    const preview = document.createElement('div');
    preview.className = 'proxy-import-item-preview';
    preview.textContent = Array.isArray(item.proxy_preview) && item.proxy_preview.length ? item.proxy_preview.join(' · ') : '线路内容按需读取';
    main.append(title, meta, preview);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'proxy-import-item-button';
    button.textContent = `导入到${proxyImportTargetLabel(target)}`;
    button.addEventListener('click', () => void importManagedProxyPool(item.id, button));
    row.append(main, button);
    list.append(row);
  });
}
async function loadManageProxyImportPools(){
  const revision = manageProxyImportRevision;
  setProxyImportStatus('正在读取管理中心代理池……', 'loading');
  renderProxyImportLoginHint('正在检查管理中心登录状态。');
  try {
    const sessionResponse = await fetch('/api/manage/session', {cache: 'no-store', credentials: 'same-origin'});
    const session = await sessionResponse.json().catch(() => ({}));
    if (revision !== manageProxyImportRevision) return;
    if (!sessionResponse.ok || !session.configured) {
      setProxyImportStatus('管理中心未启用，暂时无法读取代理池。', 'error');
      renderProxyImportLoginHint('请先在服务端启用管理中心后再导入。');
      return;
    }
    if (!session.authenticated) {
      setProxyImportStatus('请先登录管理中心，再读取代理池。', 'error');
      renderProxyImportLoginHint('当前浏览器尚未登录管理中心。');
      return;
    }
    const response = await fetch('/api/manage/proxy-pools', {cache: 'no-store', credentials: 'same-origin'});
    const data = await response.json().catch(() => ({}));
    if (revision !== manageProxyImportRevision) return;
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    manageProxyImportPools = Array.isArray(data.items) ? data.items : [];
    renderProxyImportPools();
  } catch (error) {
    if (revision !== manageProxyImportRevision) return;
    manageProxyImportPools = [];
    setProxyImportStatus(`读取失败：${error.message || error}`, 'error');
    renderProxyImportLoginHint('管理中心暂时不可用，请检查登录状态或服务端配置。');
  }
}
function openManageProxyImport(target){
  manageProxyImportTarget = target === 'exit' ? 'exit' : 'entry';
  const panel = $('proxyImportPanel');
  if (!panel) return;
  panel.hidden = false;
  $('proxyImportTarget').textContent = `目标：${proxyImportTargetLabel(manageProxyImportTarget)}`;
  manageProxyImportRevision += 1;
  manageProxyImportPools = [];
  void loadManageProxyImportPools();
}
function closeManageProxyImport(){
  manageProxyImportRevision += 1;
  manageProxyImportTarget = '';
  manageProxyImportPools = [];
  if ($('proxyImportPanel')) $('proxyImportPanel').hidden = true;
}
async function importManagedProxyPool(poolId, button){
  const target = manageProxyImportTarget === 'exit' ? 'exit' : 'entry';
  const input = $(target === 'exit' ? 'exitProxy' : 'entryProxy');
  const count = $(target === 'exit' ? 'exitProxyCount' : 'entryProxyCount');
  const probe = $(target === 'exit' ? 'exitProxyProbe' : 'entryProxyProbe');
  const pool = manageProxyImportPools.find(item => String(item.id) === String(poolId));
  if (!input || !pool) return;
  if (proxyLines(input).length && typeof window.confirm === 'function' && !window.confirm(`导入“${pool.name || pool.id}”会替换${proxyImportTargetLabel(target)}当前内容，是否继续？`)) return;
  button.disabled = true;
  setProxyImportStatus(`正在读取“${pool.name || pool.id}”的实际线路……`, 'loading');
  try {
    const response = await fetch(`/api/manage/proxy-pools/${encodeURIComponent(poolId)}?reveal=1`, {cache: 'no-store', credentials: 'same-origin'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const item = data.item || data;
    const proxies = Array.isArray(item.proxies) ? item.proxies.map(value => String(value || '').trim()).filter(Boolean) : [];
    if (!proxies.length) throw new Error('该代理池没有可用线路');
    input.value = proxies.join('\n');
    updateProxyCount(input, count);
    saveProxyPools();
    setProxyProbeResult(probe, `已导入 ${proxies.length} 条线路：${item.name || pool.name || pool.id}`, 'success');
    setProxyImportStatus(`已导入 ${proxies.length} 条线路到${proxyImportTargetLabel(target)}，本地配置会自动保存。`, 'ready');
    setProxySaveState(`已导入${proxyImportTargetLabel(target)}`);
  } catch (error) {
    setProxyImportStatus(`导入失败：${error.message || error}`, 'error');
  } finally {
    button.disabled = false;
  }
}
function switchProxyProfile(rail){
  if (!rail || rail === activeProxyRail) return;
  clearTimeout(proxySaveTimer);
  saveActiveProxyProfile();
  activeProxyRail = rail;
  applyProxyProfile(rail);
  setProxySaveState(hasProxyProfile(rail) ? '已恢复方式专属配置' : '已恢复默认共享');
}
function saveCurrentAsDefault(){
  clearTimeout(proxySaveTimer);
  try {
    defaultProxyProfile = readProxyProfile();
    if (activeProxyRail) delete proxyProfiles[activeProxyRail];
    proxyInputDirty = false;
    persistProxyProfiles();
    updateProxyProfileState();
    setProxySaveState('默认共享配置已更新');
  } catch (error) {
    setProxySaveState('本地保存不可用', true);
  }
}
function loadProxyProfiles(){
  proxyProfiles = {};
  defaultProxyProfile = emptyProxyProfile();
  let loadedProfiles = false;
  try {
    const raw = localStorage.getItem(PROXY_STORAGE_KEYS.profiles);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed?.version === 1) {
        defaultProxyProfile = cloneProxyProfile(parsed.default);
        const savedProfiles = parsed.profiles && typeof parsed.profiles === 'object' ? parsed.profiles : {};
        proxyProfileRails.forEach(rail => {
          if (savedProfiles[rail] && typeof savedProfiles[rail] === 'object') {
            proxyProfiles[rail] = cloneProxyProfile(savedProfiles[rail]);
          }
        });
        loadedProfiles = true;
      }
    }
    if (!loadedProfiles) {
      const legacy = {
        entry: localStorage.getItem(PROXY_STORAGE_KEYS.legacyEntry) || '',
        exit: localStorage.getItem(PROXY_STORAGE_KEYS.legacyExit) || ''
      };
      if (proxyProfileHasContent(legacy)) {
        defaultProxyProfile = legacy;
        persistProxyProfiles();
        setProxySaveState('已迁移默认代理配置');
        return;
      }
    }
    setProxySaveState(loadedProfiles ? '已恢复代理配置' : '本地自动保存');
  } catch (error) {
    setProxySaveState('本地保存不可用', true);
  }
}
function initializeProxyProfiles(){
  loadProxyProfiles();
  activeProxyRail = selected('link_type');
  applyProxyProfile(activeProxyRail);
}

function normalizeProxyAsn(raw){
  const match = String(raw ?? '').trim().toUpperCase().match(/^AS?(\d{1,10})$/);
  return match ? `AS${match[1]}` : '';
}
function cloneProxyAsnRecommendation(raw){
  const items = Array.isArray(raw?.items) ? raw.items.map(item => {
    const asn = normalizeProxyAsn(item?.asn);
    if (!asn) return null;
    return {
      asn,
      provider: String(item?.provider ?? '').trim().slice(0, 80),
      tier: ['A', 'B', 'C'].includes(String(item?.tier || '').toUpperCase()) ? String(item.tier).toUpperCase() : 'B',
      note: String(item?.note ?? '').trim().slice(0, 160)
    };
  }).filter(Boolean) : [];
  const uniqueItems = [];
  const seen = new Set();
  items.forEach(item => {
    if (seen.has(item.asn)) return;
    seen.add(item.asn);
    uniqueItems.push(item);
  });
  return {
    label: String(raw?.label ?? '').trim().slice(0, 80),
    items: uniqueItems
  };
}
function persistProxyAsnRecommendations(){
  const regions = {};
  Object.entries(proxyAsnRecommendations).forEach(([country, value]) => {
    const normalizedCountry = String(country || '').trim().toUpperCase();
    const normalized = cloneProxyAsnRecommendation(value);
    if (/^[A-Z]{2}$/.test(normalizedCountry) && normalized.items.length) {
      regions[normalizedCountry] = normalized;
    }
  });
  localStorage.setItem(PROXY_ASN_RECOMMENDATION_STORAGE_KEY, JSON.stringify({version: 1, regions}));
}
function setProxyAsnSaveState(text, failed=false){
  const node = $('proxyAsnSaveState');
  if (!node) return;
  node.textContent = text;
  node.classList.toggle('save-failed', failed);
}
function loadProxyAsnRecommendations(){
  proxyAsnRecommendations = {};
  let hadStoredConfig = false;
  try {
    const raw = localStorage.getItem(PROXY_ASN_RECOMMENDATION_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed?.version === 1 && parsed.regions && typeof parsed.regions === 'object') {
      Object.entries(parsed.regions).forEach(([country, value]) => {
        const normalizedCountry = String(country || '').trim().toUpperCase();
        const normalized = cloneProxyAsnRecommendation(value);
        if (/^[A-Z]{2}$/.test(normalizedCountry) && normalized.items.length) {
          proxyAsnRecommendations[normalizedCountry] = normalized;
        }
      });
      hadStoredConfig = Object.keys(proxyAsnRecommendations).length > 0;
    }
    Object.entries(DEFAULT_PROXY_ASN_RECOMMENDATIONS).forEach(([country, value]) => {
      if (!Object.prototype.hasOwnProperty.call(proxyAsnRecommendations, country)) {
        proxyAsnRecommendations[country] = cloneProxyAsnRecommendation(value);
      }
    });
    persistProxyAsnRecommendations();
    setProxyAsnSaveState(hadStoredConfig ? '已恢复本地顺序' : '已保存本地顺序');
  } catch (error) {
    Object.entries(DEFAULT_PROXY_ASN_RECOMMENDATIONS).forEach(([country, value]) => {
      proxyAsnRecommendations[country] = cloneProxyAsnRecommendation(value);
    });
    setProxyAsnSaveState('本地保存不可用', true);
  }
}
function renderProxyAsnRecommendations(){
  const list = $('proxyAsnList');
  const hint = $('proxyAsnRecommendationHint');
  const note = $('proxyAsnRecommendationNote');
  if (!list || !hint || !note) return;
  const country = String($('country')?.value || '').trim().toUpperCase();
  const recommendation = proxyAsnRecommendations[country];
  list.replaceChildren();
  if (!recommendation?.items?.length) {
    hint.textContent = `${country || '当前地区'} · 暂无本地 ASN 推荐顺序`;
    const empty = document.createElement('li');
    empty.className = 'proxy-asn-empty';
    empty.textContent = '后续可按国家/地区继续加入推荐顺序。';
    list.appendChild(empty);
    note.textContent = '当前只保存英国 GB 推荐顺序；本地配置不会修改代理池内容。';
    return;
  }
  hint.textContent = `${country} · ${recommendation.label} · 共 ${recommendation.items.length} 个候选`;
  recommendation.items.forEach((item, index) => {
    const row = document.createElement('li');
    row.className = `proxy-asn-item tier-${item.tier.toLowerCase()}`;
    const rank = document.createElement('span');
    rank.className = 'proxy-asn-rank';
    rank.textContent = String(index + 1);
    const asn = document.createElement('code');
    asn.textContent = item.asn;
    const detail = document.createElement('span');
    detail.className = 'proxy-asn-detail';
    const provider = document.createElement('b');
    provider.textContent = item.provider || '未命名网络';
    const itemNote = document.createElement('small');
    itemNote.textContent = item.note;
    detail.append(provider, itemNote);
    row.append(rank, asn, detail);
    list.appendChild(row);
  });
  note.textContent = '按 ASN 画像保存为选择参考；不会自动把代理池中的实际 IP 重排，也不代表每个 IP 都同样干净。';
}
function initializeProxyAsnRecommendations(){
  loadProxyAsnRecommendations();
  renderProxyAsnRecommendations();
}

function emptyBillingProfile(){
  return {country: '', name: '', email: '', line1: '', line2: '', city: '', state: '', postal_code: ''};
}
function cloneBillingProfile(raw){
  const profile = emptyBillingProfile();
  if (!raw || typeof raw !== 'object') return profile;
  profile.country = String(raw.country ?? '').trim().toUpperCase();
  BILLING_PROFILE_FIELDS.forEach(field => { profile[field] = String(raw[field] ?? ''); });
  return profile;
}
function billingProfileKey(rail=selected('link_type'), country=$('country')?.value){
  return `${rail || 'hosted'}:${String(country || 'US').toUpperCase()}`;
}
function billingProfileHasContent(profile){
  return BILLING_PROFILE_FIELDS.some(field => String(profile?.[field] || '').trim());
}
function readBillingProfile(){
  const profile = emptyBillingProfile();
  profile.country = String($('country')?.value || '').toUpperCase();
  BILLING_PROFILE_FIELDS.forEach(field => {
    const node = $(`billing${field === 'postal_code' ? 'PostalCode' : field[0].toUpperCase() + field.slice(1)}`);
    if (node) profile[field] = node.value;
  });
  return profile;
}
function persistBillingProfiles(){
  const profiles = {};
  Object.entries(billingProfiles).forEach(([key, value]) => {
    if (billingProfileHasContent(value)) profiles[key] = cloneBillingProfile(value);
  });
  localStorage.setItem(BILLING_STORAGE_KEY, JSON.stringify({version: 1, profiles}));
}
function setBillingSaveState(text, failed=false){
  const node = $('billingSaveState');
  if (!node) return;
  node.textContent = text;
  node.classList.toggle('save-failed', failed);
}
function updateBillingProfileState(){
  const block = $('billingBlock');
  if (!block) return;
  const key = billingProfileKey();
  activeBillingProfileKey = key;
  const explicit = billingProfileHasContent(billingProfiles[key]);
  const rail = selected('link_type');
  const country = String($('country')?.value || '').toUpperCase();
  const option = $('country')?.selectedOptions?.[0];
  const countryLabel = option ? option.textContent.trim() : country;
  $('billingCountry').textContent = `${countryLabel || country}`;
  $('billingProfileState').textContent = explicit ? `${country} · 已配置` : `${country} · 待填写`;
  $('billingProfileState').title = explicit
    ? '当前支付方式已保存账单档案，提交时会使用该档案。'
    : '当前支付方式尚未保存账单档案。';
  $('billingRequiredTag').hidden = rail !== 'gopay';
  block.classList.toggle('billing-missing', rail === 'gopay' && !explicit);
  $('billingFootHint').textContent = explicit
    ? `已恢复 ${key} 档案；编辑后自动保存。`
    : `尚未配置 ${key} 档案；Gopay 需要先填写。`;
}
function applyBillingProfile(){
  const key = billingProfileKey();
  activeBillingProfileKey = key;
  const profile = cloneBillingProfile(billingProfiles[key]);
  const fieldNodes = {
    name: $('billingName'), email: $('billingEmail'), line1: $('billingLine1'),
    line2: $('billingLine2'), city: $('billingCity'), state: $('billingState'),
    postal_code: $('billingPostalCode')
  };
  Object.entries(fieldNodes).forEach(([field, node]) => { if (node) node.value = profile[field] || ''; });
  billingInputDirty = false;
  updateBillingProfileState();
}
function saveBillingProfile(){
  if (!activeBillingProfileKey) activeBillingProfileKey = billingProfileKey();
  const profile = readBillingProfile();
  if (billingProfileHasContent(profile)) billingProfiles[activeBillingProfileKey] = profile;
  else delete billingProfiles[activeBillingProfileKey];
  billingInputDirty = false;
  persistBillingProfiles();
  updateBillingProfileState();
  setBillingSaveState('已保存当前账单档案');
}
function scheduleBillingProfileSave(){
  clearTimeout(billingSaveTimer);
  billingSaveTimer = setTimeout(() => {
    if (!billingInputDirty) return;
    try { saveBillingProfile(); }
    catch (error) { setBillingSaveState('本地保存失败', true); }
  }, 220);
}
function saveBillingInputs(){
  billingInputDirty = true;
  updateBillingProfileState();
  scheduleBillingProfileSave();
}
function clearBillingProfile(){
  clearTimeout(billingSaveTimer);
  delete billingProfiles[billingProfileKey()];
  billingInputDirty = false;
  try {
    persistBillingProfiles();
    applyBillingProfile();
    setBillingSaveState('当前档案已清空');
  } catch (error) { setBillingSaveState('本地保存失败', true); }
}
function loadBillingProfiles(){
  billingProfiles = {};
  try {
    const raw = localStorage.getItem(BILLING_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed?.version !== 1 || !parsed.profiles || typeof parsed.profiles !== 'object') {
      setBillingSaveState('本地自动保存');
      return;
    }
    Object.entries(parsed.profiles).forEach(([key, value]) => {
      const profile = cloneBillingProfile(value);
      if (billingProfileHasContent(profile)) billingProfiles[key] = profile;
    });
    setBillingSaveState('已恢复账单档案');
  } catch (error) { setBillingSaveState('本地保存不可用', true); }
}
function initializeBillingProfiles(){
  loadBillingProfiles();
  applyBillingProfile();
}
function syncBillingFields(){
  const rail = selected('link_type');
  const visible = rail === 'gopay';
  $('billingBlock').hidden = !visible;
  ['billingName', 'billingLine1', 'billingCity', 'billingPostalCode'].forEach(id => {
    $(id).required = visible;
  });
  if (visible) applyBillingProfile();
  else $('billingBlock').classList.remove('billing-missing');
}
function billingProfileMissing(profile){
  const labels = {name: '账单姓名', line1: '地址第一行', city: '城市', postal_code: '邮编'};
  return Object.entries(labels).filter(([field]) => !String(profile?.[field] || '').trim()).map(([, label]) => label);
}

function setPaypalBillingStatus(text, state=''){
  const node = $('paypalBillingStatus');
  if (!node) return;
  node.textContent = text;
  node.className = `paypal-billing-status${state ? ` ${state}` : ''}`;
}
function setPaypalBillingReloading(loading){
  const button = $('paypalBillingReload');
  if (!button) return;
  button.disabled = loading;
  button.textContent = loading ? '正在读取…' : '重新读取';
}
function paypalBillingSource(){
  return $('paypalBillingSource')?.value || 'auto';
}
function replacePaypalSelect(select, rows, emptyLabel){
  select.replaceChildren();
  if (!rows.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = emptyLabel;
    select.appendChild(option);
    return;
  }
  rows.forEach(row => {
    const option = document.createElement('option');
    option.value = String(row.value ?? '');
    option.textContent = row.label;
    select.appendChild(option);
  });
}
function resetPaypalBillingAddress(label='请先选择地址国家'){
  const address = $('paypalBillingAddress');
  if (!address) return;
  replacePaypalSelect(address, [], label);
  address.disabled = true;
}
function renderPaypalBillingCountries(){
  const source = paypalBillingSource();
  const countrySelect = $('paypalBillingCountry');
  const previous = countrySelect.value;
  if (source === 'auto') {
    replacePaypalSelect(countrySelect, [], '自动模式无需选择');
    countrySelect.disabled = true;
    resetPaypalBillingAddress('自动模式无需选择');
    return '';
  }
  const countKey = source === 'manage_profile' ? 'manual_count' : 'builtin_count';
  const noun = source === 'manage_profile' ? '个手工档案' : '条内置地址';
  const available = paypalBillingCountries
    .filter(item => Number(item?.[countKey] || 0) > 0)
    .map(item => ({
      value: String(item.country || '').toUpperCase(),
      label: `${String(item.country || '').toUpperCase()} · ${Number(item[countKey] || 0)} ${noun}`
    }));
  replacePaypalSelect(countrySelect, available, `Manage 中没有${noun}`);
  if (available.some(item => item.value === previous)) countrySelect.value = previous;
  countrySelect.disabled = !available.length;
  resetPaypalBillingAddress(available.length ? '正在读取地址…' : `Manage 中没有${noun}`);
  return countrySelect.value;
}
function paypalBillingAddressLabel(item, source){
  if (source === 'manage_profile') {
    return [item.profile_key || `Manage #${item.id}`, item.name_masked, item.address_masked]
      .filter(Boolean).join(' · ');
  }
  return [item.name, item.line1, item.city, item.postal_code].filter(Boolean).join(' · ');
}
function renderPaypalBillingAddresses(payload){
  const source = paypalBillingSource();
  const address = $('paypalBillingAddress');
  const previous = address.value;
  const items = source === 'manage_profile'
    ? (payload?.manual_profiles || [])
    : (payload?.builtin_addresses || []);
  const rows = items.map(item => ({
    value: item.id,
    label: paypalBillingAddressLabel(item, source)
  }));
  replacePaypalSelect(address, rows, '当前国家暂无可选地址');
  if (rows.some(item => String(item.value) === previous)) address.value = previous;
  address.disabled = !rows.length;
  if (!rows.length) {
    setPaypalBillingStatus(`${$('paypalBillingCountry').value || '当前国家'} 暂无该来源的地址。`, 'error');
    return;
  }
  const sourceLabel = source === 'manage_profile' ? '手工档案' : '内置公共地址';
  setPaypalBillingStatus(`已载入 ${rows.length} 个${sourceLabel}；提交时按 ID 由服务端重新读取。`, 'ready');
}
async function parsePaypalBillingResponse(response){
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}
async function ensurePaypalBillingCatalog(force=false){
  if (paypalBillingCatalogLoaded && !force) return;
  if (paypalBillingCatalogPromise && !force) return paypalBillingCatalogPromise;
  const promise = (async () => {
    const response = await fetch('/api/manage/paypal-billing-options', {cache: 'no-store'});
    const data = await parsePaypalBillingResponse(response);
    paypalBillingCountries = Array.isArray(data.countries) ? data.countries : [];
    paypalBillingCatalogLoaded = true;
  })();
  paypalBillingCatalogPromise = promise;
  try { await promise; }
  finally {
    if (paypalBillingCatalogPromise === promise) paypalBillingCatalogPromise = null;
  }
}
async function paypalBillingCountryPayload(country, force=false){
  country = String(country || '').toUpperCase();
  if (!country) return null;
  if (paypalBillingCountryPayloads[country] && !force) {
    return paypalBillingCountryPayloads[country];
  }
  const response = await fetch(
    `/api/manage/paypal-billing-options?country=${encodeURIComponent(country)}`,
    {cache: 'no-store'}
  );
  const data = await parsePaypalBillingResponse(response);
  if (Array.isArray(data.countries)) paypalBillingCountries = data.countries;
  paypalBillingCountryPayloads[country] = data;
  return data;
}
async function refreshPaypalBillingSelector({forceCatalog=false, forceCountry=false}={}){
  if (selected('link_type') !== 'paypal') return;
  const revision = ++paypalBillingRevision;
  const source = paypalBillingSource();
  renderPaypalBillingCountries();
  setPaypalBillingReloading(true);
  if (source === 'auto') {
    setPaypalBillingStatus('自动模式：正在检查 Manage 地址库连接…', 'loading');
  } else {
    setPaypalBillingStatus('正在读取 Manage 地址库…', 'loading');
  }
  try {
    await ensurePaypalBillingCatalog(forceCatalog);
    if (revision !== paypalBillingRevision || selected('link_type') !== 'paypal') return;
    if (source === 'auto') {
      renderPaypalBillingCountries();
      setPaypalBillingStatus('自动模式：已连接 Manage；需要时可切换为指定地址。', 'ready');
      return;
    }
    const country = renderPaypalBillingCountries();
    if (!country) return;
    const payload = await paypalBillingCountryPayload(country, forceCountry);
    if (revision !== paypalBillingRevision || source !== paypalBillingSource()) return;
    renderPaypalBillingAddresses(payload);
  } catch (error) {
    if (revision !== paypalBillingRevision) return;
    const prefix = source === 'auto' ? '自动模式仍可使用；' : '';
    const action = error?.status === 401
      ? '请先在 Manage 地址库登录，然后点“重新读取”。'
      : (error?.message || String(error));
    $('paypalBillingCountry').disabled = true;
    resetPaypalBillingAddress('Manage 地址库暂不可用');
    setPaypalBillingStatus(`${prefix}${action}`, 'error');
  } finally {
    if (revision === paypalBillingRevision) setPaypalBillingReloading(false);
  }
}
function readPaypalBillingSelection(){
  if (selected('link_type') !== 'paypal') return null;
  const kind = paypalBillingSource();
  if (kind === 'auto') return null;
  const id = $('paypalBillingAddress').value;
  const country = $('paypalBillingCountry').value;
  if (!id || !country) return null;
  return {
    kind,
    id: kind === 'manage_profile' ? Number(id) : id,
    country
  };
}

const planDisplayNames = {plus:'Plus', pro:'Pro', team:'Team', codex_low:'Codex'};
const railDisplayNames = {hosted:'Hosted', paypal:'PayPal', ideal:'iDEAL', upi:'UPI', pix:'PIX', gopay:'Gopay'};
const COLLAPSIBLE_STORAGE_KEY = 'pay153.collapsible_sections.v1';

function updateRailDetails(){
  const rail = selected('link_type');
  const details = railDisplayDetails[rail] || {icon: '·', title: '未选择', description: '请选择一个支付路径。', method: '待选择'};
  if ($('railDetailsIcon')) $('railDetailsIcon').textContent = details.icon;
  if ($('railDetailsTitle')) $('railDetailsTitle').textContent = details.title;
  if ($('railDetailsDescription')) $('railDetailsDescription').textContent = details.description;
  if ($('railDetailsMethod')) $('railDetailsMethod').textContent = details.method;
}
function updateSelectionSummaries(){
  const plan = selected('plan');
  const rail = selected('link_type');
  if ($('planSelection')) $('planSelection').textContent = planDisplayNames[plan] || '未选择';
  if ($('railSelection')) $('railSelection').textContent = railDisplayNames[rail] || '未选择';
  updateRailDetails();
}

function initializeCollapsibleSections(){
  const defaults = {plan: true, rail: true};
  try{
    const stored = JSON.parse(localStorage.getItem(COLLAPSIBLE_STORAGE_KEY) || '{}');
    Object.keys(defaults).forEach(key => {
      const node = $(key === 'plan' ? 'planSection' : 'railSection');
      if (node && typeof stored[key] === 'boolean') node.open = stored[key];
    });
  }catch{ /* use open defaults */ }
  Object.keys(defaults).forEach(key => {
    const node = $(key === 'plan' ? 'planSection' : 'railSection');
    node?.addEventListener('toggle', () => {
      try{
        const stored = JSON.parse(localStorage.getItem(COLLAPSIBLE_STORAGE_KEY) || '{}');
        stored[key] = node.open;
        localStorage.setItem(COLLAPSIBLE_STORAGE_KEY, JSON.stringify(stored));
      }catch{ /* private preference is best effort */ }
    });
  });
}

function selected(name){ return form.querySelector(`input[name="${name}"]:checked`)?.value || ''; }
function bindChoices(group, onChange){
  group.querySelectorAll('label').forEach(label => label.addEventListener('click', () => {
    group.querySelectorAll('label').forEach(x => x.classList.remove('active'));
    label.classList.add('active');
    setTimeout(onChange, 0);
  }));
}
bindChoices($('planGrid'), () => syncFields(false));
bindChoices($('railGrid'), () => syncFields(true));

function syncFields(applyRailDefault=false){
  const plan = selected('plan'), rail = selected('link_type');
  updateSelectionSummaries();
  if (activeProxyRail && rail !== activeProxyRail) switchProxyProfile(rail);
  $('teamFields').hidden = plan !== 'team';
  $('codexFields').hidden = plan !== 'codex_low';
  $('idealOptions').hidden = rail !== 'ideal';
  $('paypalOptions').hidden = rail !== 'paypal';
  $('pixOptions').hidden = rail !== 'pix';
  $('regionFields').hidden = rail === 'paypal';
  $('regionAutoHint').hidden = rail !== 'paypal';
  $('pixTaxId').required = false;
  const promoSupported = plan === 'plus';
  $('promoLine').style.display = promoSupported ? 'flex' : 'none';
  $('plusPromoFields').hidden = !promoSupported || !$('usePromo').checked;
  const needsExit = rail !== 'hosted' && rail !== 'pix';
  $('proxyGrid').classList.toggle('single', !needsExit);
  $('exitProxyField').hidden = !needsExit;
  $('exitProxy').required = needsExit;
  $('copyEntryProxy').hidden = !needsExit;
  const recommendations = {
    hosted: '推荐代理：使用账号常用地区。',
    paypal: '\u63a8\u8350\u4ee3\u7406\uff1a\u7cfb\u7edf\u4f18\u5148\u4f7f\u7528\u4ee3\u7406\u6c60 2 \u5f53\u524d\u56fd\u5bb6\u7684 PayPal \u8d26\u5355\uff1b\u82e5\u8be5\u56fd\u5bb6 Checkout \u672a\u5f00\u653e PayPal\uff0c\u5219\u81ea\u52a8\u56de\u9000\u5fb7\u56fd DE/EUR \u8d26\u5355\u3002',
    ideal: '推荐代理：两个代理池均使用 NL。',
    upi: '推荐代理：代理池 1 使用可获得优惠资格的国家或地区（如 TR、JP、BR），代理池 2 使用 IN 创建并处理 UPI。',
    pix: '推荐代理：代理池 1 使用 BR。',
    gopay: '推荐代理：代理池 1 使用 TH（泰国）更新优惠，代理池 2 使用 ID（印尼）创建并处理 Gopay。'
  };
  const pool2Hints = {paypal:'巴西 PayPal 推荐 BR',ideal:'推荐 NL',upi:'推荐 IN',gopay:'推荐 ID'};
  const recommendation = recommendations[rail] || '推荐代理：使用与所选地区一致的代理。';
  $('proxyRecommendation').textContent = recommendation;
  $('proxyFootHint').textContent = recommendation;
  $('exitProxyHint').textContent = pool2Hints[rail] || '推荐同地区';
  if (applyRailDefault && providerDefaults[rail]) {
    $('country').value = providerDefaults[rail].country;
    $('currency').value = providerDefaults[rail].currency;
  }
  renderProxyAsnRecommendations();
  syncBillingFields();
  if (rail === 'paypal') void refreshPaypalBillingSelector();
  else paypalBillingRevision += 1;
}
$('country').addEventListener('change', () => {
  $('currency').value = countryCurrency[$('country').value] || 'USD';
  renderProxyAsnRecommendations();
  syncBillingFields();
});
$('paypalBillingSource').addEventListener('change', () => void refreshPaypalBillingSelector());
$('paypalBillingCountry').addEventListener('change', () => void refreshPaypalBillingSelector());
$('paypalBillingAddress').addEventListener('change', () => {
  const option = $('paypalBillingAddress').selectedOptions?.[0];
  if (option?.value) setPaypalBillingStatus(`已选择：${option.textContent}`, 'ready');
});
$('paypalBillingReload').addEventListener('click', () => {
  paypalBillingCatalogLoaded = false;
  paypalBillingCountryPayloads = {};
  void refreshPaypalBillingSelector({forceCatalog: true, forceCountry: true});
});
$('usePromo').addEventListener('change', () => syncFields(false));
$('entryProxy').addEventListener('input', () => { updateProxyCount($('entryProxy'), $('entryProxyCount')); saveProxyPools(); });
$('exitProxy').addEventListener('input', () => { updateProxyCount($('exitProxy'), $('exitProxyCount')); saveProxyPools(); });
$('probeEntryProxy').addEventListener('click', () => probeProxyPool('entryProxy', 'probeEntryProxy', 'entryProxyProbe', '代理池 1'));
$('probeExitProxy').addEventListener('click', () => probeProxyPool('exitProxy', 'probeExitProxy', 'exitProxyProbe', '代理池 2'));
$('importEntryProxy').addEventListener('click', () => openManageProxyImport('entry'));
$('importExitProxy').addEventListener('click', () => openManageProxyImport('exit'));
$('closeProxyImport').addEventListener('click', closeManageProxyImport);
$('saveProxyDefault').addEventListener('click', saveCurrentAsDefault);
$('clearBillingProfile').addEventListener('click', clearBillingProfile);
['billingName', 'billingEmail', 'billingLine1', 'billingLine2', 'billingCity', 'billingState', 'billingPostalCode']
  .forEach(id => $(id).addEventListener('input', saveBillingInputs));
$('copyEntryProxy').addEventListener('click', () => {
  $('exitProxy').value = $('entryProxy').value.trim();
  updateProxyCount($('exitProxy'), $('exitProxyCount'));
  saveProxyPools();
  $('exitProxy').focus();
});

function paintProgress(value){
  const p = Math.max(0, Math.min(100, value));
  $('progressValue').textContent = `${Math.round(p)}%`;
  $('orbitValue').style.strokeDashoffset = String(320.44 * (1 - p / 100));
  $('progressBar').style.width = `${p}%`;
}
function animateProgress(timestamp){
  const dt = Math.min(.08, Math.max(.001, (timestamp - (progressLastTick || timestamp)) / 1000));
  progressLastTick = timestamp;
  if (progressStatus === 'running' && targetProgress < 96) {
    targetProgress = Math.min(96, targetProgress + dt * .28);
  }
  const diff = targetProgress - displayedProgress;
  if (Math.abs(diff) > .02) {
    const rate = progressStatus === 'done' ? 42 : Math.max(7, Math.abs(diff) * 1.35);
    displayedProgress += Math.sign(diff) * Math.min(Math.abs(diff), rate * dt);
    paintProgress(displayedProgress);
  } else {
    displayedProgress = targetProgress;
    paintProgress(displayedProgress);
  }
  if (progressStatus === 'running' || Math.abs(targetProgress - displayedProgress) > .02) {
    progressFrame = requestAnimationFrame(animateProgress);
  } else {
    progressFrame = 0;
    progressLastTick = 0;
  }
}
function resetProgress(){
  if (progressFrame) cancelAnimationFrame(progressFrame);
  displayedProgress = 0;
  targetProgress = 0;
  progressStatus = 'idle';
  progressFrame = 0;
  progressLastTick = 0;
  paintProgress(0);
}
function setProgress(percent, text, status='running'){
  const p = Math.max(0, Math.min(100, Number(percent)||0));
  const retryReset = status === 'running' && p <= 10 && Math.max(displayedProgress, targetProgress) >= 20;
  if (retryReset) {
    displayedProgress = p;
    targetProgress = p;
    paintProgress(p);
  } else if (status === 'running') {
    targetProgress = Math.max(targetProgress, p);
  } else {
    targetProgress = p;
  }
  progressStatus = status;
  $('progressText').textContent = text || '处理中';
  const badge = $('statusBadge'); badge.className = `status-badge ${status}`;
  badge.textContent = status === 'done' ? '完成' : status === 'error' ? '异常' : status === 'cancelled' ? '已停止' : status === 'queued' ? '排队中' : status === 'running' ? '运行中' : '等待';
  $('progressStage').textContent = status === 'done' ? '任务完成' : status === 'error' ? '任务异常' : status === 'cancelled' ? '任务已停止' : status === 'queued' ? '等待执行' : status === 'running' ? '正在处理' : '等待开始';
  if (!progressFrame) progressFrame = requestAnimationFrame(animateProgress);
}
function renderLogs(logs){
  const box = $('logBox');
  if (!logs?.length) return;
  const nextKey = logs.map(x => `${x.time}|${x.message}`).join('\n');
  if (nextKey === renderedLogKey) return;
  const previousTop = box.scrollTop;
  const wasFollowing = logAutoFollow;
  box.innerHTML = logs.map(x => `<div class="log-row"><time>${escapeHtml(x.time)}</time><span>${escapeHtml(x.message)}</span></div>`).join('');
  renderedLogKey = nextKey;
  if (wasFollowing) box.scrollTop = box.scrollHeight;
  else box.scrollTop = previousTop;
}
function escapeHtml(v){ return String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function setRunning(running, mode=''){
  if (running && mode) activeRunMode = mode;
  if (!running) activeRunMode = '';
  if ($('submitButton')) $('submitButton').disabled = running;
  if ($('accountDetectProtocol')) $('accountDetectProtocol').disabled = running;
  if ($('accountBatchDetect')) $('accountBatchDetect').disabled = running;
  if ($('cancelButton')) $('cancelButton').hidden = !running || activeRunMode !== 'single';
  if ($('batchCancelButton')) $('batchCancelButton').hidden = !running || activeRunMode !== 'batch';
  updateBatchControls();
}

function base64UrlDecode(part){
  const normalized = String(part || '').replace(/-/g, '+').replace(/_/g, '/');
  const pad = normalized.length % 4 === 0 ? '' : '='.repeat(4 - (normalized.length % 4));
  try{
    const binary = atob(normalized + pad);
    if (typeof TextDecoder !== 'undefined') {
      return new TextDecoder().decode(Uint8Array.from(binary, ch => ch.charCodeAt(0)));
    }
    return binary;
  }catch{
    return '';
  }
}

function decodeJwtClaims(token){
  const parts = String(token || '').split('.');
  if (parts.length < 2) return {};
  try{
    const raw = base64UrlDecode(parts[1]);
    return raw ? JSON.parse(raw) : {};
  }catch{
    return {};
  }
}

function extractJwtCandidate(raw){
  const text = String(raw || '').trim();
  if (!text) return '';
  const match = text.match(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/);
  return match ? match[0] : '';
}

function parseAccountRaw(raw, sourceLabel=''){
  const textValue = String(raw || '').trim();
  if (!textValue) throw new Error('内容为空');
  let token = '';
  let email = '';
  let accountId = '';
  let exp = 0;
  let kind = 'token';
  if (textValue.startsWith('{')) {
    let data;
    try{ data = JSON.parse(textValue); }
    catch{ throw new Error('JSON 无法解析'); }
    token = String(data.accessToken || data.access_token || '').trim();
    const account = data.account && typeof data.account === 'object' ? data.account : {};
    email = String(data.user?.email || account.email || data.email || '').trim();
    accountId = String(account.id || data.account_id || '').trim();
    kind = 'session';
  }
  if (!token) token = extractJwtCandidate(textValue);
  if (!token || token.split('.').length < 3) throw new Error('未识别到 Access Token');
  const claims = decodeJwtClaims(token);
  const auth = claims['https://api.openai.com/auth'] || {};
  email = email || String(claims.email || claims['https://api.openai.com/profile']?.email || '').trim();
  accountId = accountId || String(auth.chatgpt_account_id || claims.chatgpt_account_id || '').trim();
  exp = Number(claims.exp || 0) || 0;
  const expired = exp > 0 && exp * 1000 <= Date.now();
  const shortId = accountId ? accountId.slice(0, 8) : token.slice(0, 10);
  const label = email || (accountId ? `账号 ${shortId}` : `${kind === 'session' ? 'Session' : 'Token'} ${shortId}`);
  return {
    id: `acct_${Date.now()}_${++accountIdSeq}`,
    raw: textValue,
    token,
    email,
    accountId,
    exp,
    expired,
    kind,
    source: sourceLabel || (kind === 'session' ? '粘贴 Session' : '粘贴 Token'),
    label,
    cooldownUntil: 0,
    lastDeclineAt: 0,
    consecutiveDeclines: 0,
    consecutiveBlocks: 0,
    frozenAt: 0,
    promoStatus: 'unknown',
    promoReason: '',
    paymentMethods: {},
    checkoutProtocols: {},
    lifecycle: 'active',
    riskStatus: 'unknown',
    riskReason: '',
    lastError: '',
    lastStatus: '',
    lastJobId: '',
    lastLinkType: '',
    lastCountry: '',
    lastCurrency: '',
    lastPaymentCountry: '',
    lastResultUrl: '',
    lastCheckedAt: 0,
    addedAt: Date.now(),
    updatedAt: Date.now()
  };
}

function accountFingerprint(entry){
  return String(entry?.token || entry?.raw || '').trim();
}

function accountIdentityKey(entry){
  const accountId = String(entry?.accountId || '').trim();
  if (accountId) return `id:${accountId}`;
  const email = String(entry?.email || '').trim().toLowerCase();
  if (email) return `email:${email}`;
  return `fp:${accountFingerprint(entry).slice(0, 48)}`;
}

function normalizeAccountPaymentMethod(value){
  const raw = String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_');
  if (!raw) return '';
  if (raw.startsWith('paypal')) return 'paypal';
  return ACCOUNT_PAYMENT_METHOD_ALIASES[raw] || raw.slice(0, 40);
}

function normalizeAccountPaymentMethods(value){
  const output = {};
  if (Array.isArray(value)) {
    value.forEach(method => {
      const normalized = normalizeAccountPaymentMethod(method);
      if (normalized) output[normalized] = 'supported';
    });
    return output;
  }
  if (!value || typeof value !== 'object') return output;
  Object.entries(value).forEach(([method, state]) => {
    const normalized = normalizeAccountPaymentMethod(method);
    if (!normalized) return;
    const status = typeof state === 'string' ? state : state?.status;
    output[normalized] = ['supported', 'rejected', 'unknown'].includes(status) ? status : 'supported';
  });
  return output;
}

function normalizeCheckoutProtocol(value){
  const normalized = String(value || '').trim().toLowerCase();
  return CHECKOUT_PROTOCOLS.has(normalized) ? normalized : 'unknown';
}

function normalizeAccountLifecycle(value){
  const normalized = String(value || '').trim().toLowerCase();
  return ACCOUNT_LIFECYCLES.has(normalized) ? normalized : 'active';
}

function isAccountArchived(entry){
  return normalizeAccountLifecycle(entry?.lifecycle) !== 'active';
}

function checkoutProtocolKey(country, currency, method='paypal'){
  const rail = normalizeAccountPaymentMethod(method) || 'paypal';
  const normalizedCountry = String(country || '').trim().toUpperCase();
  const normalizedCurrency = String(currency || '').trim().toUpperCase();
  return `${rail}:${normalizedCountry}:${normalizedCurrency}`;
}

function normalizeAccountCheckoutProtocols(value){
  const output = {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) return output;
  Object.entries(value).slice(0, 100).forEach(([key, raw]) => {
    if (!raw || typeof raw !== 'object') return;
    const protocol = normalizeCheckoutProtocol(raw.protocol);
    const country = String(raw.country || '').trim().toUpperCase().slice(0, 8);
    const currency = String(raw.currency || '').trim().toUpperCase().slice(0, 8);
    const checkedAt = Number(raw.checkedAt || raw.checked_at || 0);
    if (!country || !currency || !checkedAt) return;
    output[String(key).slice(0, 80)] = {
      protocol,
      country,
      currency,
      checkedAt: checkedAt < 100000000000 ? checkedAt * 1000 : checkedAt,
      baseline: Boolean(raw.baseline),
      source: String(raw.source || 'checkout').slice(0, 40),
      paymentMethods: normalizeAccountPaymentMethods(raw.paymentMethods || raw.payment_method_types)
    };
  });
  return output;
}

function freshCheckoutProtocolRecord(entry, country, currency, method='paypal', now=Date.now()){
  const protocols = normalizeAccountCheckoutProtocols(entry?.checkoutProtocols);
  const exact = protocols[checkoutProtocolKey(country, currency, method)];
  const fresh = record => record && now - Number(record.checkedAt || 0) <= CHECKOUT_PROTOCOL_TTL_MS;
  if (fresh(exact)) return {...exact, baseline: Boolean(exact.baseline), scope: 'region'};
  if (normalizeAccountPaymentMethod(method) === 'paypal') {
    const baseline = protocols[checkoutProtocolKey('DE', 'EUR', 'paypal')];
    if (fresh(baseline)) return {...baseline, baseline: true, scope: 'de_baseline'};
  }
  return null;
}

function restoreAccountStatus(target, source){
  target.lifecycle = normalizeAccountLifecycle(source?.lifecycle || target.lifecycle);
  target.cooldownUntil = Number(source?.cooldownUntil || target.cooldownUntil || 0);
  target.lastDeclineAt = Number(source?.lastDeclineAt || target.lastDeclineAt || 0);
  target.consecutiveDeclines = Number(source?.consecutiveDeclines || target.consecutiveDeclines || 0);
  target.consecutiveBlocks = Number(source?.consecutiveBlocks || target.consecutiveBlocks || 0);
  target.frozenAt = Number(source?.frozenAt || target.frozenAt || 0);
  target.promoStatus = ['supported', 'unsupported', 'unknown'].includes(source?.promoStatus)
    ? source.promoStatus : (target.promoStatus || 'unknown');
  target.promoReason = String(source?.promoReason || target.promoReason || '').slice(0, 240);
  target.note = String(source?.note || target.note || '').slice(0, 500);
  target.discounts = source?.discounts && typeof source.discounts === 'object' ? source.discounts : (target.discounts || {global: {percent: 0, fixed: 0}, regions: []});
  target.paymentMethods = normalizeAccountPaymentMethods(source?.paymentMethods || target.paymentMethods);
  target.checkoutProtocols = normalizeAccountCheckoutProtocols(source?.checkoutProtocols || target.checkoutProtocols);
  target.riskStatus = ['clear', 'rejected', 'cooldown', 'blocked', 'frozen', 'unknown'].includes(source?.riskStatus)
    ? source.riskStatus : (target.riskStatus || 'unknown');
  target.riskReason = String(source?.riskReason || target.riskReason || '').slice(0, 240);
  target.lastError = String(source?.lastError || target.lastError || '').slice(0, 240);
  target.lastStatus = String(source?.lastStatus || target.lastStatus || '').slice(0, 40);
  target.lastJobId = String(source?.lastJobId || target.lastJobId || '').slice(0, 120);
  target.lastLinkType = normalizeAccountPaymentMethod(source?.lastLinkType || target.lastLinkType);
  target.lastCountry = String(source?.lastCountry || target.lastCountry || '').trim().toUpperCase().slice(0, 8);
  target.lastCurrency = String(source?.lastCurrency || target.lastCurrency || '').trim().toUpperCase().slice(0, 8);
  target.lastPaymentCountry = String(source?.lastPaymentCountry || target.lastPaymentCountry || '').trim().toUpperCase().slice(0, 8);
  target.lastResultUrl = String(source?.lastResultUrl || target.lastResultUrl || '').slice(0, 2000);
  target.lastCheckedAt = Number(source?.lastCheckedAt || target.lastCheckedAt || 0);
  return target;
}

function isAccountInCooldown(entry, now=Date.now()){
  return Number(entry?.cooldownUntil || 0) > now;
}

function isAccountFrozen(entry){
  return String(entry?.riskStatus || '') === 'frozen' || Number(entry?.frozenAt || 0) > 0;
}

function formatCooldownRemaining(entry, now=Date.now()){
  const until = Number(entry?.cooldownUntil || 0);
  if (!until || until <= now) return '';
  const mins = Math.ceil((until - now) / 60000);
  if (mins >= 60) {
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m ? `${h} 小时 ${m} 分` : `${h} 小时`;
  }
  return `${Math.max(1, mins)} 分钟`;
}

function formatCooldownUntil(entry){
  const until = Number(entry?.cooldownUntil || 0);
  if (!until) return '';
  try{ return new Date(until).toLocaleString('zh-CN', {hour12:false}); }
  catch{ return ''; }
}

function persistAccounts(){
  const payload = {
    version: 1,
    activeId: activeAccountId || '',
    selectedIds: [...batchSelectedAccountIds],
    // 私有化本机明文存储；勿提交到 git / 勿同步到公网。
    accounts: accountEntries.map(entry => ({
      id: entry.id,
      raw: entry.raw,
      token: entry.token,
      email: entry.email || '',
      accountId: entry.accountId || '',
      exp: entry.exp || 0,
      kind: entry.kind || 'token',
      source: entry.source || '',
      label: entry.label || '',
      cooldownUntil: Number(entry.cooldownUntil || 0),
      lastDeclineAt: Number(entry.lastDeclineAt || 0),
      consecutiveDeclines: Number(entry.consecutiveDeclines || 0),
      consecutiveBlocks: Number(entry.consecutiveBlocks || 0),
      frozenAt: Number(entry.frozenAt || 0),
      promoStatus: entry.promoStatus || 'unknown',
      promoReason: String(entry.promoReason || '').slice(0, 240),
      note: String(entry.note || '').slice(0, 500),
      discounts: entry.discounts || {global: {percent: 0, fixed: 0}, regions: []},
      paymentMethods: normalizeAccountPaymentMethods(entry.paymentMethods),
      checkoutProtocols: normalizeAccountCheckoutProtocols(entry.checkoutProtocols),
      lifecycle: normalizeAccountLifecycle(entry.lifecycle),
      riskStatus: entry.riskStatus || 'unknown',
      riskReason: String(entry.riskReason || '').slice(0, 240),
      lastError: String(entry.lastError || '').slice(0, 240),
      lastStatus: String(entry.lastStatus || '').slice(0, 40),
      lastJobId: String(entry.lastJobId || '').slice(0, 120),
      lastLinkType: normalizeAccountPaymentMethod(entry.lastLinkType),
      lastCountry: String(entry.lastCountry || '').trim().toUpperCase().slice(0, 8),
      lastCurrency: String(entry.lastCurrency || '').trim().toUpperCase().slice(0, 8),
      lastPaymentCountry: String(entry.lastPaymentCountry || '').trim().toUpperCase().slice(0, 8),
      lastResultUrl: String(entry.lastResultUrl || '').slice(0, 2000),
      lastCheckedAt: Number(entry.lastCheckedAt || 0),
      addedAt: Number(entry.addedAt || entry.createdAt || entry.joinedAt || entry.updatedAt || Date.now()),
      updatedAt: Number(entry.updatedAt || Date.now())
    }))
  };
  try{ localStorage.setItem(ACCOUNT_STORAGE_KEY, JSON.stringify(payload)); }
  catch(error){ setAccountImportStatus(`本机保存失败：${error.message || error}`, 'error'); }
}

function loadAccountsFromStorage(){
  accountEntries.length = 0;
  activeAccountId = '';
  batchSelectedAccountIds.clear();
  try{
    const raw = localStorage.getItem(ACCOUNT_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    const list = Array.isArray(parsed?.accounts) ? parsed.accounts : [];
    list.forEach(item => {
      if (!item || typeof item !== 'object') return;
      const rawToken = String(item.raw || item.token || '').trim();
      if (!rawToken) return;
      let entry;
      try{ entry = parseAccountRaw(rawToken, item.source || '本机保存'); }
      catch{ return; }
      entry.id = String(item.id || entry.id);
      entry.cooldownUntil = Number(item.cooldownUntil || 0);
      entry.lastDeclineAt = Number(item.lastDeclineAt || 0);
      entry.consecutiveDeclines = Number(item.consecutiveDeclines || 0);
      restoreAccountStatus(entry, item);
      entry.addedAt = Number(item.addedAt || item.createdAt || item.joinedAt || item.updatedAt || entry.addedAt || Date.now());
      entry.updatedAt = Number(item.updatedAt || Date.now());
      if (item.label) entry.label = String(item.label);
      accountEntries.push(entry);
    });
    const wanted = String(parsed?.activeId || '');
    if (wanted && accountEntries.some(item => item.id === wanted && !isAccountArchived(item))) activeAccountId = wanted;
    else activeAccountId = accountEntries.find(item => !isAccountArchived(item))?.id || '';
    const storedSelectedIds = Array.isArray(parsed?.selectedIds) ? parsed.selectedIds.map(id => String(id)) : [];
    const availableIds = new Set(accountEntries.filter(entry => accountCanBatch(entry)).map(entry => entry.id));
    storedSelectedIds.forEach(id => {
      if (availableIds.has(id)) batchSelectedAccountIds.add(id);
    });
  }catch{
    accountEntries.length = 0;
    activeAccountId = '';
  }
}

function setAccountImportStatus(message, tone=''){
  const node = $('accountImportStatus');
  if (!node) return;
  node.textContent = message || '本机保存 · 与账号绑定冷却';
  node.classList.toggle('is-error', tone === 'error');
  node.classList.toggle('is-ok', tone === 'ok');
}

function accountCanBatch(entry, now=Date.now()){
  return Boolean(entry && !isAccountArchived(entry) && !entry.expired && !isAccountInCooldown(entry, now) && !isAccountFrozen(entry));
}

function getBatchSelectedAccounts(){
  const now = Date.now();
  return accountEntries.filter(entry => batchSelectedAccountIds.has(entry.id) && accountCanBatch(entry, now));
}

function updateExecutionControls(selectedAccounts=getBatchSelectedAccounts()){
  const selectedList = Array.isArray(selectedAccounts) ? selectedAccounts : [];
  const selectedCount = selectedList.length;
  const submitButton = $('submitButton');
  const submitLabel = submitButton?.querySelector('span');
  const tokenField = $('token');
  const executionHint = $('accountExecutionHint');
  const gatewayHint = $('accountGatewaySelectionHint');
  const selectedEntry = selectedList[0];

  if (selectedCount >= 2) {
    if (submitLabel) submitLabel.textContent = `并发提链（${selectedCount} 个已选）`;
    if (submitButton) {
      submitButton.title = `并发执行已勾选的 ${selectedCount} 个账号；输入框内容不会作为本次任务目标`;
      submitButton.dataset.executionMode = 'batch';
    }
    if (tokenField) tokenField.required = false;
    if (gatewayHint) gatewayHint.textContent = `已选 ${selectedCount} 个可用账号；底部按钮和“并发提链”都会执行这些账号，每个账号独立建任务。`;
    if (executionHint) executionHint.textContent = `并发模式：将执行已勾选的 ${selectedCount} 个账号，不读取输入框内容。`;
  } else if (selectedCount === 1) {
    if (submitLabel) submitLabel.textContent = '开始提链（已选账号）';
    if (submitButton) {
      submitButton.title = `执行已勾选账号：${selectedEntry?.label || '当前账号'}；输入框内容不会覆盖该选择`;
      submitButton.dataset.executionMode = 'single-selected';
    }
    if (tokenField) tokenField.required = false;
    if (gatewayHint) gatewayHint.textContent = `已选 1 个可用账号：${selectedEntry?.label || '当前账号'}；底部按钮将执行该账号。`;
    if (executionHint) executionHint.textContent = `单账号模式：将执行已勾选的“${selectedEntry?.label || '当前账号'}”，输入框内容不会覆盖该选择。`;
  } else {
    if (submitLabel) submitLabel.textContent = '开始提链（输入框账号）';
    if (submitButton) {
      submitButton.title = '执行下方输入框中的单个 Token';
      submitButton.dataset.executionMode = 'manual';
    }
    if (tokenField) tokenField.required = true;
    if (gatewayHint) gatewayHint.textContent = '未勾选账号：底部按钮执行输入框中的账号；勾选后会自动切换为所选账号模式。';
    if (executionHint) executionHint.textContent = '当前为单账号模式：开始提链将执行输入框中的账号。';
  }
  if (executionHint) {
    executionHint.classList.toggle('is-selection', selectedCount > 0);
    executionHint.classList.toggle('is-batch', selectedCount >= 2);
  }
  if (submitButton) submitButton.disabled = Boolean(activeRunMode);
}

function updateBatchControls(){
  const selectedCount = getBatchSelectedAccounts().length;
  const batchButton = $('accountBatchRun');
  if (batchButton) {
    batchButton.textContent = `并发提链（${selectedCount}）`;
    batchButton.disabled = selectedCount < 2 || Boolean(activeRunMode);
    batchButton.title = selectedCount < 2 ? '至少勾选 2 个有效账号' : '同时创建多个独立提链任务';
  }
  const detectButton = $('accountBatchDetect');
  if (detectButton) {
    detectButton.textContent = `批量检测协议（${selectedCount}）`;
    detectButton.disabled = selectedCount < 2 || Boolean(activeRunMode);
    detectButton.title = selectedCount < 2 ? '至少勾选 2 个有效账号' : '同时检测所选账号的 DE/EUR PayPal 协议';
  }
  const selectAll = $('accountSelectAll');
  if (selectAll) {
    const available = accountEntries.filter(entry => accountCanBatch(entry));
    const allSelected = available.length > 0 && available.every(entry => batchSelectedAccountIds.has(entry.id));
    selectAll.disabled = !available.length || Boolean(activeRunMode);
    selectAll.textContent = allSelected ? '取消全选' : '全选可用';
  }
  updateExecutionControls(getBatchSelectedAccounts());
}

function formatAccountExpiry(entry){
  if (!entry?.exp) return '有效期未知';
  if (entry.expired) return '已过期';
  try{ return `至 ${new Date(entry.exp * 1000).toLocaleString('zh-CN', {hour12:false})}`; }
  catch{ return '有效期未知'; }
}

function accountHasMarker(entry, now=Date.now()){
  return Boolean(
    entry?.expired
    || isAccountInCooldown(entry, now)
    || isAccountFrozen(entry)
    || ['rejected', 'blocked', 'frozen'].includes(String(entry?.riskStatus || ''))
    || entry?.promoStatus === 'unsupported'
  );
}

function accountMarkerView(entry, now=Date.now()){
  if (isAccountFrozen(entry)) return ['冻结', 'danger'];
  if (isAccountInCooldown(entry, now)) return ['冷却', 'warn'];
  if (String(entry?.riskStatus || '') === 'blocked') return ['疑似封禁', 'danger'];
  if (entry?.expired) return ['已过期', 'danger'];
  if (String(entry?.riskStatus || '') === 'rejected') return ['最近被拒', 'warn'];
  if (entry?.promoStatus === 'unsupported') return ['优惠未生效', 'warn'];
  if (entry?.promoStatus === 'supported' || String(entry?.riskStatus || '') === 'clear') return ['可选', 'good'];
  return ['待检测', 'neutral'];
}

function accountProtocolView(entry, now=Date.now()){
  const exact = entry?.lastCountry && entry?.lastCurrency
    ? freshCheckoutProtocolRecord(entry, entry.lastCountry, entry.lastCurrency, 'paypal', now)
    : null;
  const record = exact || freshCheckoutProtocolRecord(entry, 'DE', 'EUR', 'paypal', now);
  if (!record) return null;
  const protocol = record.protocol === 'oaics' ? 'OAICS' : record.protocol === 'cs' ? 'CS' : '未知';
  const scope = `${record.country}/${record.currency}`;
  return {
    protocol: record.protocol,
    scope,
    label: `协议 ${protocol} · ${scope}${record.baseline ? ' 基线' : ''}`,
    tone: record.protocol === 'unknown' ? 'neutral' : 'good'
  };
}

function accountMethodLabel(method){
  return railDisplayNames[method] || ({card: 'Card', link: 'Link'}[method] || String(method || '').toUpperCase());
}

function accountChipBadge(label, tone='neutral'){
  const badge = document.createElement('span');
  badge.className = `account-chip-badge ${tone}`;
  badge.textContent = label;
  return badge;
}

function selectionAccountEntries(now=Date.now()){
  return accountEntries
    .filter(entry => !isAccountArchived(entry))
    .map((entry, index) => ({entry, index}))
    .sort((left, right) => {
      const markedOrder = Number(accountHasMarker(left.entry, now)) - Number(accountHasMarker(right.entry, now));
      if (markedOrder) return markedOrder;
      const activeOrder = Number(right.entry.id === activeAccountId) - Number(left.entry.id === activeAccountId);
      return activeOrder || left.index - right.index;
    })
    .map(item => item.entry);
}

function scheduleAccountCooldownTick(){
  if (accountCooldownTimer) {
    clearInterval(accountCooldownTimer);
    accountCooldownTimer = 0;
  }
  if (!accountEntries.some(item => isAccountInCooldown(item))) return;
  accountCooldownTimer = window.setInterval(() => {
    let changed = false;
    const now = Date.now();
    accountEntries.forEach(entry => {
      if (entry.cooldownUntil && entry.cooldownUntil <= now) {
        entry.cooldownUntil = 0;
        entry.consecutiveDeclines = 0;
        if (entry.riskStatus === 'cooldown') {
          entry.riskStatus = 'rejected';
          entry.riskReason = '本机冷却已结束，尚未重新验证支付侧状态';
        }
        entry.updatedAt = now;
        changed = true;
      }
    });
    if (changed) persistAccounts();
    renderAccountList();
    if (!accountEntries.some(item => isAccountInCooldown(item))) {
      clearInterval(accountCooldownTimer);
      accountCooldownTimer = 0;
    }
  }, 30000);
}

function renderAccountList(){
  const list = $('accountList');
  if (!list) { updateBatchControls(); return; }
  list.innerHTML = '';
  if (!accountEntries.length) {
    list.hidden = true;
    if ($('accountListHint')) $('accountListHint').hidden = true;
    if ($('tokenHint')) $('tokenHint').textContent = '自动识别账号信息 · 本机保存';
    updateBatchControls();
    return;
  }
  const now = Date.now();
  const visibleEntries = selectionAccountEntries(now);
  const archivedCount = accountEntries.filter(isAccountArchived).length;
  const archivedLabel = `${ACCOUNT_LIFECYCLE_LABELS.completed}/${ACCOUNT_LIFECYCLE_LABELS.deleted}`;
  if (!visibleEntries.length) {
    list.hidden = true;
    if ($('accountListHint')) {
      $('accountListHint').hidden = false;
      $('accountListHint').textContent = `已隐藏 ${archivedCount} 个${archivedLabel}账号；可前往管理中心查询并恢复状态`;
    }
    if ($('tokenHint')) $('tokenHint').textContent = `当前没有正常账号 · 管理中心仍保留 ${archivedCount} 个账号记录`;
    updateBatchControls();
    return;
  }
  list.hidden = false;
  const groupDefinitions = [
    {key: 'oaics', label: 'OAICS', description: 'OpenAI Checkout', tone: 'oaics'},
    {key: 'cs', label: 'CS', description: 'Stripe Checkout', tone: 'cs'},
    {key: 'unknown', label: '待检测', description: '尚未识别协议', tone: 'unknown'}
  ];
  const groupedEntries = Object.fromEntries(groupDefinitions.map(group => [group.key, []]));
  visibleEntries.forEach(entry => {
    const protocolView = accountProtocolView(entry, now);
    const groupKey = protocolView?.protocol === 'oaics' || protocolView?.protocol === 'cs'
      ? protocolView.protocol
      : 'unknown';
    groupedEntries[groupKey].push({entry, protocolView});
  });

  groupDefinitions.forEach(group => {
    const entries = groupedEntries[group.key];
    if (!entries.length) return;

    const section = document.createElement('section');
    section.className = `account-protocol-group is-${group.tone}`;
    const headingId = `account-protocol-group-${group.key}`;
    section.setAttribute('aria-labelledby', headingId);

    const heading = document.createElement('div');
    heading.className = 'account-protocol-group-head';
    const headingMain = document.createElement('div');
    headingMain.className = 'account-protocol-group-title';
    const marker = document.createElement('i');
    marker.className = 'account-protocol-group-marker';
    marker.setAttribute('aria-hidden', 'true');
    const headingCopy = document.createElement('span');
    const headingLabel = document.createElement('b');
    headingLabel.id = headingId;
    headingLabel.textContent = group.label;
    const headingDescription = document.createElement('small');
    headingDescription.textContent = group.description;
    headingCopy.append(headingLabel, headingDescription);
    headingMain.append(marker, headingCopy);
    const count = document.createElement('span');
    count.className = 'account-protocol-group-count';
    count.textContent = `${entries.length}`;
    heading.append(headingMain, count);

    const groupList = document.createElement('div');
    groupList.className = 'account-protocol-group-list';
    entries.forEach(({entry, protocolView}) => {
      const cooling = isAccountInCooldown(entry, now);
      const frozen = isAccountFrozen(entry);
      const marked = accountHasMarker(entry, now);
      const available = accountCanBatch(entry, now);
      const row = document.createElement('div');
      row.className = 'account-chip'
        + (entry.id === activeAccountId ? ' is-active' : '')
        + (batchSelectedAccountIds.has(entry.id) ? ' is-batch-selected' : '')
        + (entry.expired ? ' is-expired' : '')
        + (cooling ? ' is-cooldown' : '')
        + (frozen ? ' is-frozen' : '')
        + (marked ? ' is-marked' : '');
      row.dataset.accountId = entry.id;

      const selectWrap = document.createElement('label');
      selectWrap.className = 'account-batch-select';
      selectWrap.title = available ? '加入本次执行选择（1 个=单账号，2 个以上=并发）' : (frozen ? '账号冻结中' : (cooling ? '账号冷却中' : '账号已过期'));
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'account-batch-check';
      checkbox.checked = batchSelectedAccountIds.has(entry.id);
      checkbox.disabled = !available;
      checkbox.setAttribute('aria-label', `选择 ${entry.label} 作为提链执行账号`);
      checkbox.addEventListener('click', event => event.stopPropagation());
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) batchSelectedAccountIds.add(entry.id);
        else batchSelectedAccountIds.delete(entry.id);
        persistAccounts();
        updateBatchControls();
      });
      selectWrap.appendChild(checkbox);

      const main = document.createElement('button');
      main.type = 'button';
      main.className = 'account-chip-main';
      main.title = '点击选用此账号并填入输入框';
      main.setAttribute('aria-pressed', String(entry.id === activeAccountId));
      const title = document.createElement('span');
      title.className = 'account-chip-title';
      title.textContent = entry.label;
      const summary = document.createElement('span');
      summary.className = 'account-chip-summary';
      const accountMarker = accountMarkerView(entry, now);
      summary.append(accountChipBadge(accountMarker[0], accountMarker[1]));
      if (entry.promoStatus === 'supported') summary.append(accountChipBadge('优惠支持', 'good'));
      if (entry.promoStatus === 'unsupported' && accountMarker[0] !== '优惠未生效') {
        summary.append(accountChipBadge('优惠未生效', 'warn'));
      }
      const supportedMethods = Object.keys(normalizeAccountPaymentMethods(entry.paymentMethods))
        .filter(method => entry.paymentMethods[method] === 'supported');
      if (supportedMethods.length) {
        summary.append(accountChipBadge(`方式 ${supportedMethods.slice(0, 3).map(accountMethodLabel).join(' / ')}`, 'neutral'));
      }
      const lastRegion = [entry.lastCountry, entry.lastCurrency].filter(Boolean).join('/') || protocolView?.scope || '';
      if (lastRegion) summary.append(accountChipBadge(`地区 ${lastRegion}`, 'neutral'));
      const meta = document.createElement('span');
      meta.className = 'account-chip-meta' + (marked ? ' is-marked' : '');
      const bits = [entry.source];
      if (entry.accountId) bits.push(`id ${entry.accountId.slice(0, 8)}`);
      if (frozen) bits.push(`连续 ${Math.max(ACCOUNT_BLOCK_STREAK_LIMIT, Number(entry.consecutiveBlocks || 0))} 次 block · 需手动解冻`);
      else if (cooling) bits.push(`冷却剩余 ${formatCooldownRemaining(entry, now)} · 至 ${formatCooldownUntil(entry)}`);
      meta.textContent = bits.filter(Boolean).join(' · ');
      main.append(title, summary, meta);
      main.addEventListener('click', () => selectAccount(entry.id));

      const actions = document.createElement('div');
      actions.className = 'account-chip-actions';
      if (frozen) {
        const clearFreeze = document.createElement('button');
        clearFreeze.type = 'button';
        clearFreeze.className = 'account-chip-remove';
        clearFreeze.textContent = '解冻';
        clearFreeze.title = '仅清除本机冻结标记，不代表平台侧状态已恢复';
        clearFreeze.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          clearAccountFreeze(entry.id);
        });
        actions.appendChild(clearFreeze);
      } else if (cooling) {
        const clearCd = document.createElement('button');
        clearCd.type = 'button';
        clearCd.className = 'account-chip-remove';
        clearCd.textContent = '清冷却';
        clearCd.title = '仅清除本机冷却标记，不会让支付侧风控消失';
        clearCd.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          clearAccountCooldown(entry.id);
        });
        actions.appendChild(clearCd);
      }
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'account-chip-remove';
      remove.textContent = '移除';
      remove.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        removeAccount(entry.id);
      });
      actions.appendChild(remove);

      row.append(selectWrap, main, actions);
      row.addEventListener('click', (event) => {
        if (event.target.closest('button.account-chip-remove')) return;
        selectAccount(entry.id);
      });
      groupList.appendChild(row);
    });
    section.append(heading, groupList);
    list.appendChild(section);
  });
  if ($('accountListHint')) {
    const markedCount = visibleEntries.filter(entry => accountHasMarker(entry, now)).length;
    const groupSummary = groupDefinitions
      .filter(group => groupedEntries[group.key].length)
      .map(group => `${group.label} ${groupedEntries[group.key].length}`)
      .join(' · ');
    const archivedSummary = archivedCount ? ` · 已隐藏 ${archivedCount} 个${archivedLabel}账号` : '';
    $('accountListHint').hidden = false;
    $('accountListHint').textContent = markedCount
      ? `${groupSummary} · ${visibleEntries.length - markedCount} 个账号优先显示 · ${markedCount} 个已标记账号已排到后方${archivedSummary}`
      : `${groupSummary} · 点击账号行即可选用${archivedSummary}`;
  }
  if ($('tokenHint')) {
    const active = accountEntries.find(item => item.id === activeAccountId);
    if (active && isAccountInCooldown(active)) {
      $('tokenHint').textContent = `冷却中 ${active.label} · 剩余 ${formatCooldownRemaining(active)}`;
    } else if (active) {
      $('tokenHint').textContent = `已选 ${active.label} · 当前可用 ${visibleEntries.length} 个账号${archivedCount ? ` · 已隐藏 ${archivedCount} 个` : ''}`;
    } else {
      $('tokenHint').textContent = `已保存 ${visibleEntries.length} 个可用账号 · 点击选用${archivedCount ? ` · 已隐藏 ${archivedCount} 个` : ''}`;
    }
  }
  scheduleAccountCooldownTick();
  updateBatchControls();
}

function selectAccount(id){
  const entry = accountEntries.find(item => item.id === id);
  if (!entry || isAccountArchived(entry)) return;
  activeAccountId = entry.id;
  if ($('token')) $('token').value = entry.raw;
  persistAccounts();
  renderAccountList();
  if (isAccountFrozen(entry)) {
    setAccountImportStatus(
      `已选用 ${entry.label}（本机冻结，连续 ${Math.max(ACCOUNT_BLOCK_STREAK_LIMIT, Number(entry.consecutiveBlocks || 0))} 次 block）`,
      'error'
    );
  } else if (isAccountInCooldown(entry)) {
    setAccountImportStatus(
      `已选用 ${entry.label}（冷却中，剩余 ${formatCooldownRemaining(entry)}，至 ${formatCooldownUntil(entry)}）`,
      'error'
    );
  } else {
    setAccountImportStatus(
      entry.expired ? `已选用 ${entry.label}（已过期，提交可能失败）` : `已选用 ${entry.label}`,
      entry.expired ? 'error' : 'ok'
    );
  }
}

function removeAccount(id){
  const index = accountEntries.findIndex(item => item.id === id);
  if (index < 0) return;
  const removed = accountEntries.splice(index, 1)[0];
  batchSelectedAccountIds.delete(id);
  if (activeAccountId === id) {
    activeAccountId = accountEntries.find(item => !isAccountArchived(item))?.id || '';
    if ($('token')) {
      const next = accountEntries.find(item => item.id === activeAccountId);
      $('token').value = next ? next.raw : '';
    }
  }
  persistAccounts();
  renderAccountList();
  setAccountImportStatus(accountEntries.length ? `已移除 ${removed.label}` : '列表已空');
}

function clearAllAccounts(){
  accountEntries.length = 0;
  activeAccountId = '';
  batchSelectedAccountIds.clear();
  if ($('token')) $('token').value = '';
  persistAccounts();
  renderAccountList();
  setAccountImportStatus('已清空本机账号列表');
}

function clearAccountRestriction(id, label='限制'){
  const entry = accountEntries.find(item => item.id === id);
  if (!entry) return;
  entry.cooldownUntil = 0;
  entry.consecutiveDeclines = 0;
  entry.frozenAt = 0;
  entry.consecutiveBlocks = 0;
  if (['cooldown', 'frozen'].includes(entry.riskStatus)) {
    entry.riskStatus = 'rejected';
    entry.riskReason = `已清除本机${label}，支付侧状态仍需重新验证`;
  }
  entry.updatedAt = Date.now();
  persistAccounts();
  renderAccountList();
  setAccountImportStatus(`已清除 ${entry.label} 的本机${label}标记`, 'ok');
}

function clearAccountCooldown(id){
  clearAccountRestriction(id, '冷却');
}

function clearAccountFreeze(id){
  clearAccountRestriction(id, '冻结');
}

function markAccountCooldown(target, ms=ACCOUNT_COOLDOWN_MS, reason=''){
  if (!target) return null;
  const now = Date.now();
  const frozen = isAccountFrozen(target);
  target.cooldownUntil = now + Math.max(60_000, Number(ms) || ACCOUNT_COOLDOWN_MS);
  target.lastDeclineAt = now;
  target.consecutiveDeclines = Math.max(3, Number(target.consecutiveDeclines || 0) + 1);
  target.riskStatus = frozen ? 'frozen' : 'cooldown';
  target.riskReason = String(
    frozen ? (target.riskReason || '账号已冻结；PayPal 风控熔断未解除冻结') : (reason || 'PayPal 风控熔断，已进入本机冷却')
  ).slice(0, 240);
  target.lastError = target.riskReason;
  target.lastCheckedAt = now;
  target.updatedAt = now;
  activeAccountId = target.id;
  batchSelectedAccountIds.delete(target.id);
  persistAccounts();
  renderAccountList();
  setAccountImportStatus(
    `${target.label} 已进入冷却 ${formatCooldownRemaining(target)}（至 ${formatCooldownUntil(target)}）${reason ? ' · ' + reason : ''}`,
    'error'
  );
  return target;
}

function markActiveAccountCooldown(ms=ACCOUNT_COOLDOWN_MS, reason=''){
  let target = accountEntries.find(item => item.id === activeAccountId);
  const tokenRaw = String($('token')?.value || '').trim();
  if (!target && tokenRaw) {
    try{
      const parsed = parseAccountRaw(tokenRaw, '当前输入');
      target = accountEntries.find(item => accountIdentityKey(item) === accountIdentityKey(parsed));
      if (!target) {
        target = upsertAccountEntry(parsed).entry;
        activeAccountId = target.id;
      }
    }catch{ target = null; }
  }
  if (!target) {
    setAccountImportStatus('任务已熔断，但未能匹配到本机账号（可先导入/点选账号）', 'error');
    return null;
  }
  return markAccountCooldown(target, ms, reason);
}

function getActiveAccountCooldownBlocker(tokenValue=''){
  const tokenRaw = String(tokenValue || $('token')?.value || '').trim();
  if (!tokenRaw) return null;
  let parsed = null;
  try{ parsed = parseAccountRaw(tokenRaw, 'submit-check'); }catch{ /* 交给后端 */ }
  const matched = accountEntries.find(item => {
    if (activeAccountId && item.id === activeAccountId && String(item.raw || '').trim() === tokenRaw) return true;
    if (parsed && accountIdentityKey(item) === accountIdentityKey(parsed)) return true;
    return accountFingerprint(item) === accountFingerprint({token: extractJwtCandidate(tokenRaw), raw: tokenRaw});
  });
  if (matched && (isAccountInCooldown(matched) || isAccountFrozen(matched))) return matched;
  return null;
}

function upsertAccountEntry(entry){
  const identity = accountIdentityKey(entry);
  const existingIndex = accountEntries.findIndex(item =>
    accountIdentityKey(item) === identity || accountFingerprint(item) === accountFingerprint(entry)
  );
  if (existingIndex >= 0) {
    const old = accountEntries[existingIndex];
    entry.id = old.id;
    entry.cooldownUntil = Math.max(Number(entry.cooldownUntil || 0), Number(old.cooldownUntil || 0));
    entry.lastDeclineAt = Number(old.lastDeclineAt || entry.lastDeclineAt || 0);
    entry.consecutiveDeclines = Number(old.consecutiveDeclines || entry.consecutiveDeclines || 0);
    restoreAccountStatus(entry, old);
    entry.addedAt = Number(old.addedAt || old.createdAt || old.joinedAt || entry.addedAt || Date.now());
    entry.updatedAt = Date.now();
    accountEntries[existingIndex] = entry;
    return {entry, added: false};
  }
  accountEntries.push(entry);
  return {entry, added: true};
}

function accountRiskFromFailure(data){
  const errorText = String(data?.error || data?.text || '');
  const errorCode = String(data?.error_code || '').toLowerCase();
  if (isPaypalFuse(data)) {
    return {status: 'cooldown', reason: 'PayPal 风控熔断，已进入本机冷却；不等同于账号永久封禁'};
  }
  if (
    /account_(?:blocked|banned|suspended|restricted)/i.test(errorCode)
    || /(?:account|账号|账户).{0,40}(?:blocked|banned|suspend|denied|封禁|停用|冻结|禁止|拒绝)/i.test(errorText)
  ) {
    return {status: 'blocked', reason: errorText.slice(0, 240)};
  }
  if (
    ['generic_decline', 'setup_attempt_failed', 'checkout_approval_payment_failure'].some(code => errorCode.includes(code))
    || /generic_decline|setup_attempt_failed|checkout_approval_payment_failure|支付被拒绝|支付通道拒绝|payment method.*declin|支付失败/i.test(errorText)
  ) {
    return {status: 'rejected', reason: errorText.slice(0, 240)};
  }
  return {status: 'unknown', reason: errorText.slice(0, 240)};
}

function recordAccountCheckoutProtocol(target, result){
  if (!target || !result || typeof result !== 'object') return null;
  const method = normalizeAccountPaymentMethod(result.link_type || 'paypal');
  if (method !== 'paypal') return null;
  const protocol = normalizeCheckoutProtocol(result.checkout_protocol);
  const country = String(result.checkout_protocol_country || result.checkout_country || '').trim().toUpperCase();
  const currency = String(result.checkout_protocol_currency || result.checkout_currency || '').trim().toUpperCase();
  if (!country || !currency) return null;
  const checkedAtRaw = Number(result.checkout_protocol_checked_at);
  const checkedAtValue = Number.isFinite(checkedAtRaw) && checkedAtRaw > 0 ? checkedAtRaw : Date.now();
  const checkedAt = checkedAtValue < 100000000000 ? checkedAtValue * 1000 : checkedAtValue;
  const key = checkoutProtocolKey(country, currency, method);
  const methods = normalizeAccountPaymentMethods(
    result.oaics_payment_method_types || result.payment_method_types || []
  );
  target.checkoutProtocols = normalizeAccountCheckoutProtocols(target.checkoutProtocols);
  const previous = target.checkoutProtocols[key];
  const previousIsKnown = previous && ['oaics', 'cs'].includes(previous.protocol);
  // An incomplete checkout response must not downgrade a confirmed protocol.
  // Keep the newer known record as well when an older poll result arrives late.
  if (
    previousIsKnown
    && (
      protocol === 'unknown'
      || Number(previous.checkedAt || 0) > checkedAt
    )
  ) return previous;
  target.checkoutProtocols[key] = {
    protocol,
    country: country.slice(0, 8),
    currency: currency.slice(0, 8),
    checkedAt,
    baseline: Boolean(result.checkout_protocol_baseline),
    source: String(result.checkout_protocol_source || (result.detection_only ? 'fixed_de' : 'checkout')).slice(0, 40),
    paymentMethods: methods
  };
  return target.checkoutProtocols[key];
}

function recordAccountOutcome(target, data, requestedMethod='', jobId=''){
  if (!target) return null;
  const now = Date.now();
  const result = data?.result && typeof data.result === 'object' ? data.result : {};
  const outcomeStatus = String(data?.status || '').toLowerCase();
  const frozenBeforeOutcome = isAccountFrozen(target);
  let protocolRecord = null;
  if (outcomeStatus === 'done' && result.checkout_protocol) {
    protocolRecord = recordAccountCheckoutProtocol(target, result);
  }
  const methods = normalizeAccountPaymentMethods(
    result.oaics_payment_method_types || result.payment_method_types || []
  );
  target.paymentMethods = normalizeAccountPaymentMethods(target.paymentMethods);
  Object.assign(target.paymentMethods, methods);
  const resultLinkType = normalizeAccountPaymentMethod(result.link_type || requestedMethod);
  if (resultLinkType && outcomeStatus === 'done') target.paymentMethods[resultLinkType] = 'supported';
  if (result.oaics_paypal_available === true) target.paymentMethods.paypal = 'supported';

  const promoSignals = [
    result.entry_trial_eligible,
    result.checkout_trial_eligible,
    result.promo_applied,
    result.promo_update_accepted
  ];
  const promoFailure = String(data?.error_code || '').toLowerCase() === 'promo_not_applied'
    || /优惠(?:金额)?校验失败|优惠.*未生效|优惠.*未归零/.test(String(data?.error || data?.text || ''));
  if (promoFailure) {
    target.promoStatus = 'unsupported';
    target.promoReason = '最终金额校验未归零，任务已停止重试';
  } else if (promoSignals.some(value => value === true)) {
    target.promoStatus = 'supported';
    target.promoReason = '最近一次 Checkout/优惠结果明确支持';
  } else if (promoSignals.some(value => value === false) || (result.promo_requested === true && outcomeStatus === 'done')) {
    target.promoStatus = 'unsupported';
    target.promoReason = '最近一次任务未确认优惠生效';
  }

  target.lastCheckedAt = now;
  target.lastJobId = String(jobId || target.lastJobId || '').slice(0, 120);
  target.lastStatus = outcomeStatus.slice(0, 40);
  target.lastError = String(data?.error || '').slice(0, 240);
  target.lastLinkType = resultLinkType || target.lastLinkType;
  target.lastCountry = String(result.checkout_country || result.country || target.lastCountry || '').trim().toUpperCase().slice(0, 8);
  target.lastCurrency = String(result.checkout_currency || result.currency || target.lastCurrency || '').trim().toUpperCase().slice(0, 8);
  target.lastPaymentCountry = String(result.payment_proxy_country || result.payment_country || target.lastPaymentCountry || '').trim().toUpperCase().slice(0, 8);
  if (outcomeStatus === 'done') {
    const resultLink = resultUrl(result);
    if (resultLink) target.lastResultUrl = resultLink;
    if (!frozenBeforeOutcome) {
      target.consecutiveBlocks = 0;
      target.riskStatus = 'clear';
      target.riskReason = '最近一次任务完成，未发现拒绝或封禁信号';
    }
    target.lastError = '';
  } else if (outcomeStatus === 'error') {
    const risk = accountRiskFromFailure(data);
    if (risk.status === 'blocked' && !frozenBeforeOutcome) {
      target.consecutiveBlocks = isAccountBlockFuse(data)
        ? ACCOUNT_BLOCK_STREAK_LIMIT
        : Math.max(0, Number(target.consecutiveBlocks || 0)) + 1;
      if (target.consecutiveBlocks >= ACCOUNT_BLOCK_STREAK_LIMIT) {
        target.frozenAt = now;
        target.cooldownUntil = 0;
        target.riskStatus = 'frozen';
        target.riskReason = `连续 ${target.consecutiveBlocks} 次明确 block，已进入本机冻结：${risk.reason || '账号封禁信号'}`.slice(0, 240);
        activeAccountId = target.id;
        batchSelectedAccountIds.delete(target.id);
      } else {
        target.riskStatus = 'blocked';
        target.riskReason = `${risk.reason || '检测到账号封禁信号'}（连续 ${target.consecutiveBlocks}/${ACCOUNT_BLOCK_STREAK_LIMIT} 次）`.slice(0, 240);
      }
    } else if (!frozenBeforeOutcome) {
      target.consecutiveBlocks = 0;
      target.riskStatus = risk.status;
      target.riskReason = risk.reason;
    }
    if (risk.status !== 'unknown' && resultLinkType) {
      target.paymentMethods[resultLinkType] = ['rejected', 'cooldown'].includes(risk.status) ? 'rejected' : 'unknown';
    }
  }
  target.updatedAt = now;
  persistAccounts();
  renderAccountList();
  if (result.detection_only && protocolRecord) {
    setAccountImportStatus(
      `${target.label} 协议已记录：${String(protocolRecord.protocol || 'unknown').toUpperCase()} · ${protocolRecord.country}/${protocolRecord.currency}`,
      protocolRecord.protocol === 'unknown' ? '' : 'ok'
    );
  }
  return target;
}

function findAccountForToken(tokenRaw, create=false){
  const raw = String(tokenRaw || '').trim();
  let target = accountEntries.find(item =>
    activeAccountId && item.id === activeAccountId && String(item.raw || '').trim() === raw
  );
  if (!target && raw) {
    try {
      const parsed = parseAccountRaw(raw, '任务记录');
      target = accountEntries.find(item => accountIdentityKey(item) === accountIdentityKey(parsed));
      if (!target && create) target = upsertAccountEntry(parsed).entry;
    } catch { /* 手动输入的非标准 Token 不写入账号状态列表 */ }
  }
  return target || null;
}

function recordActiveAccountOutcome(data, requestedMethod='', jobId=''){
  const target = findAccountForToken($('token')?.value || '', true);
  return target ? recordAccountOutcome(target, data, requestedMethod, jobId) : null;
}

function singleJobAccountEntry(){
  const binding = singleJobBinding;
  if (!binding) return null;
  return accountEntries.find(item => item.id === binding.entryId) || binding.entry || null;
}

function recordSingleJobOutcome(data, currentJobId=''){
  const binding = singleJobBinding;
  const target = singleJobAccountEntry();
  if (binding && target) {
    return recordAccountOutcome(target, data, binding.requestedMethod, currentJobId);
  }
  return recordActiveAccountOutcome(data, selected('link_type'), currentJobId);
}

function markSingleJobCooldown(ms=ACCOUNT_COOLDOWN_MS, reason=''){
  const binding = singleJobBinding;
  const target = singleJobAccountEntry();
  if (binding && target) return markAccountCooldown(target, ms, reason);
  return markActiveAccountCooldown(ms, reason);
}

function splitAccountImportText(raw, sourceLabel='手动粘贴'){
  const textValue = String(raw || '').trim();
  if (!textValue) return [{text: '', source: sourceLabel}];
  if (textValue.startsWith('{')) return [{text: textValue, source: sourceLabel}];
  const matches = [...textValue.matchAll(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g)]
    .map(match => match[0])
    .filter((token, index, list) => list.indexOf(token) === index);
  if (matches.length > 1) {
    return matches.map((token, index) => ({text: token, source: `${sourceLabel}#${index + 1}`}));
  }
  return [{text: textValue, source: sourceLabel}];
}

function importAccountTexts(items){
  let added = 0;
  let updated = 0;
  let failed = 0;
  const errors = [];
  Array.from(items || []).forEach(item => {
    try{
      const parsed = parseAccountRaw(item.text, item.source);
      const result = upsertAccountEntry(parsed);
      if (result.added) added += 1;
      else updated += 1;
      activeAccountId = result.entry.id;
      if ($('token')) $('token').value = result.entry.raw;
    }catch(error){
      failed += 1;
      errors.push(`${item.source}: ${error.message || error}`);
    }
  });
  persistAccounts();
  renderAccountList();
  if (!added && !updated) {
    setAccountImportStatus(errors[0] || '没有可导入的账号', 'error');
    return;
  }
  const parts = [];
  if (added) parts.push(`新增 ${added}`);
  if (updated) parts.push(`更新 ${updated}`);
  if (failed) parts.push(`失败 ${failed}`);
  setAccountImportStatus(parts.join(' · ') + ' · 已写入本机', failed && !added && !updated ? 'error' : 'ok');
}

function importPastedAccounts(){
  const raw = String($('token')?.value || '').trim();
  if (!raw) {
    setAccountImportStatus('请先在文本框粘贴 AT 或 Session JSON', 'error');
    $('token')?.focus();
    return;
  }
  importAccountTexts(splitAccountImportText(raw, '手动粘贴'));
}

async function importAccountFiles(fileList){
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const items = [];
  for (const file of files) {
    try{
      const textValue = await file.text();
      const trimmed = String(textValue || '').trim();
      if (!trimmed) { items.push({text: '', source: file.name}); continue; }
      items.push(...splitAccountImportText(trimmed, file.name));
    }catch(error){
      items.push({text: '', source: `${file.name}（读取失败: ${error.message || error}）`});
    }
  }
  importAccountTexts(items);
}

function initializeAccountManager(){
  loadAccountsFromStorage();
  window.addEventListener('storage', event => {
    if (event.key !== ACCOUNT_STORAGE_KEY) return;
    loadAccountsFromStorage();
    renderAccountList();
  });
  const fileInput = $('accountFileInput');
  const clearButton = $('accountClearAll');
  $('accountImportPaste')?.addEventListener('click', importPastedAccounts);
  $('accountSelectAll')?.addEventListener('click', () => {
    const available = accountEntries.filter(entry => accountCanBatch(entry));
    const allSelected = available.length > 0 && available.every(entry => batchSelectedAccountIds.has(entry.id));
    available.forEach(entry => {
      if (allSelected) batchSelectedAccountIds.delete(entry.id);
      else batchSelectedAccountIds.add(entry.id);
    });
    persistAccounts();
    renderAccountList();
    setAccountImportStatus(allSelected ? '已取消全部批量选择' : `已选择 ${available.length} 个可用账号`, 'ok');
  });
  $('accountBatchRun')?.addEventListener('click', () => void startBatchCheckout());
  $('accountBatchDetect')?.addEventListener('click', () => void startBatchProtocolDetection());
  if (fileInput) {
    fileInput.addEventListener('change', async () => {
      try{ await importAccountFiles(fileInput.files); }
      finally{ fileInput.value = ''; }
    });
  }
  clearButton?.addEventListener('click', () => {
    if (accountEntries.length && !window.confirm('确认清空本机保存的全部账号？')) return;
    clearAllAccounts();
  });
  $('accountDetectProtocol')?.addEventListener('click', () => void startProtocolDetection());
  $('token')?.addEventListener('input', () => {
    if (!activeAccountId) return;
    const active = accountEntries.find(item => item.id === activeAccountId);
    if (!active) return;
    if ($('token').value.trim() !== String(active.raw || '').trim()) {
      activeAccountId = '';
      persistAccounts();
      renderAccountList();
      setAccountImportStatus('已改为手动输入 Token');
    }
  });
  if (activeAccountId) {
    const active = accountEntries.find(item => item.id === activeAccountId);
    if (active && $('token') && !$('token').value.trim()) $('token').value = active.raw;
  }
  renderAccountList();
  if (accountEntries.length) setAccountImportStatus(`已从本机恢复 ${accountEntries.length} 个账号`, 'ok');
  else setAccountImportStatus('本机保存 · 与账号绑定冷却');
}

async function loadTaskLimits(){
  try{
    const response = await fetch('/api/config', {cache:'no-store'});
    const data = await response.json().catch(() => ({}));
    const limits = data.task_limits || {};
    taskLimits = {
      perIp: Math.max(1, Number(limits.per_ip_rpm) || taskLimits.perIp),
      global: Math.max(1, Number(limits.global_rpm) || taskLimits.global),
      workers: Math.max(1, Number(limits.workers) || taskLimits.workers)
    };
    updateBatchControls();
  }catch{ /* the local defaults keep batch selection usable offline */ }
}

function isTerminalJobStatus(status){ return ['done', 'skipped', 'error', 'cancelled'].includes(String(status || '')); }

function isPaypalFuse(data){
  const errorText = String(data?.error || data?.text || '');
  const errorCode = String(data?.error_code || '');
  return errorCode === 'paypal_generic_decline_fuse'
    || /连续\s*\d+\s*次\s*PayPal\s*风控拒绝/.test(errorText)
    || /PayPal 风控熔断/.test(errorText);
}

function isAccountBlockFuse(data){
  const errorCode = String(data?.error_code || '').toLowerCase();
  const errorText = String(data?.error || data?.text || '');
  return errorCode === ACCOUNT_BLOCK_FUSE_ERROR_CODE
    || /连续\s*\d+\s*次明确\s*account\s*block/i.test(errorText);
}

function resultUrl(result){
  const candidates = [
    result?.provider_redirect_url,
    result?.paypal_link,
    result?.url,
    result?.link,
    result?.checkout_url
  ];
  return candidates.map(value => String(value || '').trim()).find(value => {
    try{
      const parsed = new URL(value);
      return parsed.protocol === 'https:' || parsed.protocol === 'http:';
    }catch{ return false; }
  }) || '';
}

function renderResultPaymentMethods(result){
  const node = $('resultPaymentMethods');
  if (!node) return;
  node.replaceChildren();
  node.classList.remove('is-empty');
  const raw = result?.oaics_payment_method_types ?? result?.payment_method_types ?? result?.payment_method_type ?? [];
  const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
  const methods = [...new Set(values.map(value => {
    if (value && typeof value === 'object') return value.type || value.name || value.code || '';
    return value;
  }).map(normalizeAccountPaymentMethod).filter(Boolean))];
  if (!methods.length) {
    node.classList.add('is-empty');
    node.textContent = result?.detection_only
      ? '未暴露'
      : (railDisplayDetails[result?.link_type]?.method || '按路径生成');
    return;
  }
  methods.forEach(method => {
    const tag = document.createElement('span');
    tag.className = 'result-method-tag';
    tag.textContent = accountMethodLabel(method);
    node.append(tag);
  });
}

function showResult(result){
  if (!$('resultPanel')) return;
  const url = resultUrl(result);
  $('resultPanel').hidden = false;
  if ($('resultType')) $('resultType').textContent = result?.detection_only
    ? 'PayPal 协议检测'
    : (railDisplayNames[result?.link_type] || result?.link_type || '—');
  renderResultPaymentMethods(result);
  if ($('resultEmail')) $('resultEmail').textContent = result?.account_email || result?.account_id || '—';
  if ($('resultRegion')) $('resultRegion').textContent = [result?.checkout_country || result?.country, result?.checkout_currency || result?.currency].filter(Boolean).join(' / ') || '—';
  if ($('resultPromo')) {
    const promo = result?.detection_only
      ? `协议 ${String(result?.checkout_protocol || 'unknown').toUpperCase()}`
      : (result?.promo_applied === true || result?.promo_update_accepted === true ? '已应用' : result?.promo_requested ? '已尝试' : '未使用');
    $('resultPromo').textContent = promo;
  }
  if ($('resultSession')) $('resultSession').textContent = result?.detection_only
    ? `${result?.checkout_protocol || 'unknown'} · ${result?.checkout_protocol_source || '检测'}`
    : (result?.checkout_session_id || '—');
  if ($('resultValue')) $('resultValue').value = result?.detection_only
    ? '本次仅完成协议检测，未生成最终付款链接。'
    : url;
  if ($('openResult')) {
    $('openResult').href = url || '#';
    $('openResult').hidden = !url;
  }
}

function buildCheckoutBody(tokenValue, overrides={}){
  const plan = selected('plan');
  const linkType = selected('link_type');
  const billingProfile = linkType === 'gopay' ? readBillingProfile() : null;
  const paypalBillingSelection = readPaypalBillingSelection();
  const body = {
    token: String(tokenValue || ''), plan, link_type: linkType, country: $('country').value,
    currency: $('currency').value, entry_proxies: proxyLines($('entryProxy')), exit_proxies: proxyLines($('exitProxy')),
    billing_profile: billingProfile && billingProfileHasContent(billingProfile) ? billingProfile : null,
    billing_selection: paypalBillingSelection,
    retry_count: Math.max(1, Math.min(50, Number($('retryCount').value || 10))),
    use_promo: plan === 'plus' && $('usePromo').checked,
    promo_campaign: plan === 'plus' ? $('promoCampaign').value.trim() : '',
    promo_code: plan === 'team' ? $('promoCode').value.trim() : '',
    workspace_name: plan === 'codex_low' ? $('codexWorkspaceName').value.trim() : $('workspaceName').value.trim(),
    workspace_id: $('workspaceId').value.trim(), seat_quantity: Number($('seatQuantity').value || 5),
    price_interval: $('priceInterval').value, credit_quantity: Number($('creditQuantity').value || 13),
    ideal_bank: '',
    pix_tax_id: linkType === 'pix' ? $('pixTaxId').value.trim() : '',
    pix_auto_kind: linkType === 'pix' ? $('pixAutoKind').value : 'cpf'
  };
  const account = findAccountForToken(tokenValue || $('token')?.value || '', false);
  if (linkType === 'paypal' && !overrides.detectionOnly) {
    const protocol = freshCheckoutProtocolRecord(account, body.country, body.currency, 'paypal');
    if (protocol) {
      body.checkout_protocol_hint = protocol.protocol;
      body.checkout_protocol_hint_country = protocol.country;
      body.checkout_protocol_hint_currency = protocol.currency;
      body.checkout_protocol_hint_checked_at = protocol.checkedAt;
      body.checkout_protocol_hint_baseline = Boolean(protocol.baseline || protocol.scope === 'de_baseline');
    }
  }
  if (overrides.detectionOnly) {
    body.link_type = 'paypal';
    body.country = 'DE';
    body.currency = 'EUR';
    body.use_promo = false;
    body.promo_campaign = '';
    body.billing_selection = null;
    body.detection_only = true;
    body.detection_fixed_de = overrides.detectionFixedDe !== false;
    body.retry_count = 2;
  }
  return body;
}

function validateCheckoutOptions({batch=false, tokenValue=''}={}){
  const linkType = selected('link_type');
  const billingProfile = linkType === 'gopay' ? readBillingProfile() : null;
  const paypalBillingSelection = readPaypalBillingSelection();
  if (linkType === 'gopay') {
    const missing = billingProfileMissing(billingProfile);
    if (missing.length) {
      $('billingBlock').hidden = false;
      updateBillingProfileState();
      setBillingSaveState('账单档案未完成', true);
      setProgress(100, `Gopay 账单档案缺少：${missing.join('、')}`, 'error');
      const firstMissing = {name: 'billingName', line1: 'billingLine1', city: 'billingCity', postal_code: 'billingPostalCode'};
      $(firstMissing[Object.keys(firstMissing).find(field => !String(billingProfile[field] || '').trim())] || 'billingName')?.focus();
      return false;
    }
  }
  if (linkType === 'paypal' && paypalBillingSource() !== 'auto' && !paypalBillingSelection) {
    setPaypalBillingStatus('请先选择地址国家和具体账单地址。', 'error');
    setProgress(100, 'PayPal 指定账单地址尚未选择完成', 'error');
    const target = $('paypalBillingCountry').value ? $('paypalBillingAddress') : $('paypalBillingCountry');
    target?.focus();
    return false;
  }
  if (!batch) {
    const cooldownBlocker = getActiveAccountCooldownBlocker(tokenValue);
    if (cooldownBlocker) {
      const frozen = isAccountFrozen(cooldownBlocker);
      setProgress(
        100,
        frozen
          ? `${cooldownBlocker.label} 已冻结（连续 ${Math.max(ACCOUNT_BLOCK_STREAK_LIMIT, Number(cooldownBlocker.consecutiveBlocks || 0))} 次 block），请先手动解冻或更换账号。`
          : `${cooldownBlocker.label} 冷却中（剩余 ${formatCooldownRemaining(cooldownBlocker)}，至 ${formatCooldownUntil(cooldownBlocker)}）。请更换账号/代理或等待冷却结束。`,
        'error'
      );
      setAccountImportStatus(
        frozen
          ? `提交已拦截：${cooldownBlocker.label} 处于本机冻结状态`
          : `提交已拦截：${cooldownBlocker.label} 冷却剩余 ${formatCooldownRemaining(cooldownBlocker)}`,
        'error'
      );
      return false;
    }
  }
  return true;
}

function validateProtocolDetection(){
  if (selected('link_type') !== 'paypal') {
    setAccountImportStatus('协议检测目前仅用于 PayPal，请先切换到 PayPal', 'error');
    setProgress(100, '协议检测仅支持 PayPal', 'error');
    return false;
  }
  if (!String($('token')?.value || '').trim()) {
    setAccountImportStatus('请先选择或粘贴一个账号', 'error');
    $('token')?.focus();
    setProgress(100, '缺少 Access Token', 'error');
    return false;
  }
  if (!proxyLines($('entryProxy')).length || !proxyLines($('exitProxy')).length) {
    setAccountImportStatus('协议检测需要填写代理池 1 和代理池 2', 'error');
    setProgress(100, '缺少 PayPal 代理池', 'error');
    return false;
  }
  const blocker = getActiveAccountCooldownBlocker();
  if (blocker) {
    const frozen = isAccountFrozen(blocker);
    setAccountImportStatus(
      frozen ? `${blocker.label} 已冻结，暂不执行协议检测` : `${blocker.label} 冷却中，暂不执行协议检测`,
      'error'
    );
    setProgress(100, frozen ? '账号已冻结' : '账号冷却中', 'error');
    return false;
  }
  return true;
}

function validateFormForBatch(){
  const token = $('token');
  const required = token?.required;
  if (token) token.required = false;
  let valid = true;
  try{
    valid = typeof form.checkValidity !== 'function' || form.checkValidity();
    if (!valid) form.reportValidity?.();
  }finally{
    if (token) token.required = required;
  }
  return valid;
}

async function poll(){
  if (!jobId || activeRunMode !== 'single') return;
  try{
    const r = await fetch(`/api/checkout-progress?job_id=${encodeURIComponent(jobId)}`, {cache:'no-store'});
    const data = await r.json(); if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    setProgress(data.percent, data.text, data.status);
    renderLogs(data.logs);
    if (data.status === 'done') {
      clearInterval(pollTimer);
      setRunning(false);
      recordSingleJobOutcome(data, jobId);
      singleJobBinding = null;
      showResult(data.result || {});
    }
    if (data.status === 'error' || data.status === 'cancelled') {
      clearInterval(pollTimer);
      setRunning(false);
      recordSingleJobOutcome(data, jobId);
      if (data.error) renderLogs([...(data.logs||[]),{time:'ERROR',message:data.error}]);
      if (isPaypalFuse(data)) markSingleJobCooldown(ACCOUNT_COOLDOWN_MS, '任务风控熔断');
      singleJobBinding = null;
    }
  }catch(e){
    clearInterval(pollTimer);
    singleJobBinding = null;
    setRunning(false);
    setProgress(100, e.message || String(e), 'error');
  }
}

function batchStatusLabel(status){
  return ({creating:'创建中', queued:'排队中', running:'运行中', pending:'候补中', done:'完成', skipped:'已跳过', error:'失败', cancelled:'已停止'}[status] || '等待');
}

async function cancelBatchJob(job){
  if (!job?.jobId || isTerminalJobStatus(job.status) || job.cancelPending) return false;
  job.cancelPending = true;
  job.text = '正在停止…';
  renderBatchJobs();
  try{
    const response = await fetch('/api/checkout-cancel', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({job_id: job.jobId})
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || `取消失败（HTTP ${response.status}）`);
    job.status = 'cancelled';
    job.percent = 100;
    job.text = '任务已停止';
    job.error = '任务已停止';
    job.cancelPending = false;
    recordAccountOutcome(job.entry, {status: 'cancelled', error: '任务已停止'}, job.requestedMethod, job.jobId);
    renderBatchJobs();
    updateBatchAggregate();
    void pumpBatchQueue();
    return true;
  }catch(error){
    job.cancelPending = false;
    job.text = '取消失败';
    job.error = error.message || String(error);
    renderBatchJobs();
    updateBatchAggregate();
    return false;
  }
}

function renderBatchJobs(){
  const list = $('batchJobList');
  if (!list) return;
  list.innerHTML = '';
  batchJobs.forEach(job => {
    const row = document.createElement('div');
    row.className = `batch-job-row is-${isTerminalJobStatus(job.status) ? job.status : (job.status === 'creating' ? 'running' : job.status)}`;
    const main = document.createElement('div');
    main.className = 'batch-job-main';
    const title = document.createElement('b');
    title.className = 'batch-job-title';
    title.textContent = job.label;
    const text = document.createElement('small');
    text.className = 'batch-job-text';
    text.textContent = job.error || job.text || '等待任务';
    const progress = document.createElement('div');
    progress.className = 'batch-job-progress';
    const progressValue = document.createElement('i');
    progressValue.style.width = `${Math.max(0, Math.min(100, Number(job.percent) || 0))}%`;
    progress.appendChild(progressValue);
    main.append(title, text, progress);
    const side = document.createElement('div');
    side.className = 'batch-job-side';
    const status = document.createElement('span');
    status.className = 'batch-job-status';
    status.textContent = batchStatusLabel(job.status);
    side.appendChild(status);
    const url = resultUrl(job.result);
    if (url) {
      const link = document.createElement('a');
      link.className = 'batch-job-link';
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = '打开结果 ↗';
      side.appendChild(link);
    }
    if (job.jobId && !isTerminalJobStatus(job.status)) {
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'batch-job-cancel';
      cancel.textContent = job.cancelPending ? '正在停止…' : '停止';
      cancel.disabled = Boolean(job.cancelPending);
      cancel.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        void cancelBatchJob(job);
      });
      side.appendChild(cancel);
    }
    row.append(main, side);
    list.appendChild(row);
  });
}

function renderBatchLogs(){
  const rows = [];
  batchJobs.forEach(job => {
    const logs = Array.isArray(job.logs) ? job.logs.slice(-15) : [];
    logs.forEach(item => rows.push({time:item.time, message:`${job.label} · ${item.message}`}));
    if (job.error && isTerminalJobStatus(job.status) && !logs.length) rows.push({time:'ERROR', message:`${job.label} · ${job.error}`});
  });
  rows.sort((a, b) => String(a.time).localeCompare(String(b.time)));
  renderLogs(rows.slice(-180));
}

function updateBatchAggregate(){
  if (!batchJobs.length) return;
  const total = batchJobs.length;
  const done = batchJobs.filter(job => job.status === 'done').length;
  const skipped = batchJobs.filter(job => job.status === 'skipped').length;
  const failed = batchJobs.filter(job => job.status === 'error').length;
  const cancelled = batchJobs.filter(job => job.status === 'cancelled').length;
  const waiting = batchJobs.filter(job => job.status === 'pending').length;
  const terminal = done + skipped + failed + cancelled;
  const active = total - terminal;
  const percent = Math.round(batchJobs.reduce((sum, job) => sum + Math.max(0, Math.min(100, Number(job.percent) || 0)), 0) / total);
  const complete = terminal === total;
  const status = complete
    ? (failed || cancelled ? 'error' : 'done')
    : 'running';
  const actionLabel = activeBatchTaskType === 'protocol_detection' ? '协议检测' : '批量提链';
  const summary = complete
    ? `${actionLabel}结束：${done} 个完成${skipped ? ` · ${skipped} 个跳过` : ''}${failed ? ` · ${failed} 个失败` : ''}${cancelled ? ` · ${cancelled} 个已停止` : ''}`
    : `${actionLabel}：${done}/${total} 个完成${skipped ? ` · ${skipped} 个跳过` : ''} · ${active - waiting} 个处理中${waiting ? ` · ${waiting} 个候补等待` : ''}`;
  if ($('batchSummary')) $('batchSummary').textContent = summary;
  if ($('batchBadge')) {
    $('batchBadge').className = `status-badge ${status}`;
    $('batchBadge').textContent = complete ? (status === 'done' ? '完成' : status === 'cancelled' ? '已停止' : '部分异常') : '运行中';
  }
  setProgress(percent, summary, status);
  if (complete && activeRunMode === 'batch') {
    clearInterval(batchPollTimer);
    batchPollTimer = 0;
    if (batchPumpTimer) {
      clearTimeout(batchPumpTimer);
      batchPumpTimer = 0;
    }
    setRunning(false);
  }
}

function batchConcurrencyLimit(){
  const perIp = Math.max(1, Number(taskLimits.perIp) || 1);
  const workers = Math.max(1, Number(taskLimits.workers) || perIp);
  return Math.max(1, Math.min(perIp, workers));
}

function batchActiveCount(){
  return batchJobs.filter(job => (
    job.status === 'creating'
    || (job.jobId && !isTerminalJobStatus(job.status))
  )).length;
}

function scheduleBatchPump(delayMs=1000){
  if (activeRunMode !== 'batch') return;
  if (batchPumpTimer) clearTimeout(batchPumpTimer);
  const waitMs = Math.max(250, Number(delayMs) || 0, batchCreateReadyAt - Date.now());
  batchPumpTimer = setTimeout(() => {
    batchPumpTimer = 0;
    void pumpBatchQueue();
  }, waitMs);
}

async function submitBatchJob(job){
  const detection = activeBatchTaskType === 'protocol_detection';
  job.status = 'creating';
  job.percent = Math.max(1, Number(job.percent) || 1);
  job.text = activeBatchTaskType === 'protocol_detection' ? '正在创建检测任务' : '正在创建任务';
  job.error = '';
  renderBatchJobs();
  try{
    const response = await fetch(detection ? '/api/checkout-detect' : '/api/checkout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(detection
        ? buildCheckoutBody(job.entry.raw, {detectionOnly: true, detectionFixedDe: true})
        : buildCheckoutBody(job.entry.raw))
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 429) {
      const headerRetry = Number(response.headers?.get?.('Retry-After') || 0);
      const retryAfter = Math.max(1, headerRetry || Number(data.retry_after) || 60);
      batchCreateReadyAt = Math.max(batchCreateReadyAt, Date.now() + retryAfter * 1000);
      job.status = 'pending';
      job.percent = 1;
      job.text = `候补等待创建窗口 · ${retryAfter} 秒后自动重试`;
      job.error = '';
      scheduleBatchPump(retryAfter * 1000);
      return false;
    }
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    job.jobId = String(data.job_id || '');
    if (!job.jobId) throw new Error('服务未返回任务 ID');
    job.status = 'queued';
    job.percent = Number(data.queue_position) > 0 ? 2 : 3;
    job.text = Number(data.queue_position) > 0
      ? `${detection ? '检测' : ''}排队中 · 前方 ${data.queue_position - 1} 个任务`
      : (detection ? '等待检测' : '等待执行');
    return true;
  }catch(error){
    job.status = 'error';
    job.percent = 100;
    job.error = error.message || String(error);
    job.text = detection ? '检测任务创建失败' : '创建失败';
    recordAccountOutcome(job.entry, {status: 'error', error: job.error}, job.requestedMethod);
    return false;
  }
}

async function pumpBatchQueue(){
  if (batchPumpRunning || activeRunMode !== 'batch') return;
  batchPumpRunning = true;
  try{
    if (batchCreateReadyAt > Date.now()) {
      scheduleBatchPump(batchCreateReadyAt - Date.now());
      return;
    }
    const limit = batchConcurrencyLimit();
    while (activeRunMode === 'batch' && batchActiveCount() < limit) {
      const next = batchJobs.find(job => job.status === 'pending' && !job.jobId);
      if (!next) break;
      const accepted = await submitBatchJob(next);
      if (!accepted && next.status === 'pending') break;
    }
    renderBatchJobs();
    updateBatchAggregate();
  }finally{
    batchPumpRunning = false;
  }
}

async function pollBatch(){
  if (!batchJobs.length || activeRunMode !== 'batch') return;
  const activeJobs = batchJobs.filter(job => job.jobId && !isTerminalJobStatus(job.status));
  if (!activeJobs.length) {
    updateBatchAggregate();
    void pumpBatchQueue();
    return;
  }
  await Promise.all(activeJobs.map(async job => {
    try{
      const response = await fetch(`/api/checkout-progress?job_id=${encodeURIComponent(job.jobId)}`, {cache:'no-store'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      job.status = data.status || job.status;
      job.percent = Number(data.percent) || 0;
      job.text = String(data.text || '处理中');
      job.error = String(data.error || '');
      job.result = data.result || job.result;
      job.logs = Array.isArray(data.logs) ? data.logs : job.logs;
      if (isTerminalJobStatus(job.status)) recordAccountOutcome(job.entry, data, job.requestedMethod, job.jobId);
      if (isPaypalFuse(data)) markAccountCooldown(job.entry, ACCOUNT_COOLDOWN_MS, '批量任务风控熔断');
    }catch(error){
      job.status = 'error';
      job.percent = 100;
      job.error = error.message || String(error);
      job.text = '任务轮询失败';
      recordAccountOutcome(job.entry, {status: 'error', error: job.error}, job.requestedMethod, job.jobId);
    }
  }));
  renderBatchJobs();
  renderBatchLogs();
  updateBatchAggregate();
  void pumpBatchQueue();
}

async function startProtocolDetection(){
  if (activeRunMode || !validateProtocolDetection()) return;
  resetProgress();
  $('resultPanel').hidden = true;
  $('batchPanel').hidden = true;
  $('logBox').innerHTML = '<div class="empty-log">正在执行 DE/EUR PayPal 协议检测…</div>';
  renderedLogKey = '';
  logAutoFollow = true;
  setRunning(true, 'single');
  setProgress(3, '提交协议检测任务', 'running');
  const body = buildCheckoutBody($('token').value, {detectionOnly: true, detectionFixedDe: true});
  try{
    const r = await fetch('/api/checkout-detect', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    jobId = data.job_id;
    if (data.queue_position > 0) setProgress(2, `检测任务已排队，当前第 ${data.queue_position} 位`, 'queued');
    clearInterval(pollTimer); await poll();
    if (activeRunMode === 'single') pollTimer = setInterval(poll, 1200);
  }catch(error){
    setRunning(false);
    setProgress(100, error.message || String(error), 'error');
  }
}

async function startBatchProtocolDetection(){
  if (activeRunMode) return;
  const accounts = getBatchSelectedAccounts();
  if (accounts.length < 2) {
    setAccountImportStatus('请至少勾选 2 个有效账号后再批量检测协议', 'error');
    return;
  }
  if (selected('link_type') !== 'paypal') {
    setAccountImportStatus('批量协议检测仅支持 PayPal，请先切换到 PayPal', 'error');
    setProgress(100, '批量协议检测仅支持 PayPal', 'error');
    return;
  }
  if (!proxyLines($('entryProxy')).length || !proxyLines($('exitProxy')).length) {
    setAccountImportStatus('批量协议检测需要填写代理池 1 和代理池 2', 'error');
    setProgress(100, '缺少 PayPal 代理池', 'error');
    return;
  }
  const skippedAccounts = accounts
    .map(entry => ({entry, record: freshCheckoutProtocolRecord(entry, 'DE', 'EUR', 'paypal')}))
    .filter(item => item.record);
  const pendingAccounts = accounts.filter(entry => !skippedAccounts.some(item => item.entry.id === entry.id));
  resetProgress();
  $('resultPanel').hidden = true;
  $('batchPanel').hidden = false;
  if ($('batchPanelTitle')) $('batchPanelTitle').textContent = '批量协议检测';
  $('logBox').innerHTML = `<div class="empty-log">正在排队检测 ${pendingAccounts.length} 个账号的 DE/EUR 协议${skippedAccounts.length ? `，已跳过 ${skippedAccounts.length} 个已有标识账号` : ''}…</div>`;
  renderedLogKey = '';
  logAutoFollow = true;
  activeBatchTaskType = 'protocol_detection';
  batchJobs = [
    ...skippedAccounts.map(({entry, record}) => ({
      entry,
      label: entry.label,
      requestedMethod: 'paypal',
      jobId: '',
      status: 'skipped',
      percent: 100,
      text: `已检测 ${String(record.protocol || 'unknown').toUpperCase()} · DE/EUR`,
      error: '',
      result: {
        detection_only: true,
        link_type: 'paypal',
        checkout_protocol: record.protocol,
        checkout_country: 'DE',
        checkout_currency: 'EUR'
      },
      logs: []
    })),
    ...pendingAccounts.map(entry => ({
      entry,
      label: entry.label,
      requestedMethod: 'paypal',
      jobId: '',
      status: 'pending',
      percent: 0,
      text: '候补队列 · 等待并发槽位',
      error: '',
      result: null,
      logs: []
    }))
  ];
  renderBatchJobs();
  setRunning(true, 'batch');
  updateBatchAggregate();
  await pumpBatchQueue();
  renderBatchJobs();
  updateBatchAggregate();
  if (activeRunMode === 'batch' && batchJobs.some(job => !isTerminalJobStatus(job.status))) {
    clearInterval(batchPollTimer);
    await pollBatch();
    if (activeRunMode === 'batch') batchPollTimer = setInterval(pollBatch, 1200);
  }
}

async function startSingleCheckout(selectedEntry=null){
  const submittedToken = selectedEntry
    ? String(selectedEntry.raw || selectedEntry.token || '').trim()
    : String($('token').value || '').trim();
  if (!submittedToken) {
    setAccountImportStatus(
      selectedEntry ? '所选账号没有可用 Token，请重新导入账号' : '请先在输入框粘贴一个 Access Token / Session JSON',
      'error'
    );
    $('token')?.focus();
    return;
  }
  if (!validateCheckoutOptions({tokenValue: submittedToken})) return;
  resetProgress();
  $('resultPanel').hidden = true;
  $('batchPanel').hidden = true;
  $('logBox').innerHTML = '<div class="empty-log">正在创建任务…</div>';
  renderedLogKey = '';
  logAutoFollow = true;
  setRunning(true, 'single');
  setProgress(3, '提交任务', 'running');
  const accountEntry = selectedEntry || findAccountForToken(submittedToken, true);
  singleJobBinding = {
    entry: accountEntry,
    entryId: accountEntry?.id || '',
    requestedMethod: selected('link_type'),
    token: submittedToken
  };
  const body = buildCheckoutBody(submittedToken);
  try{
    const r = await fetch('/api/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await r.json(); if(!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    jobId = data.job_id;
    if (data.queue_position > 0) setProgress(2, `任务已进入队列，当前第 ${data.queue_position} 位`, 'queued');
    clearInterval(pollTimer); await poll();
    if (activeRunMode === 'single') pollTimer=setInterval(poll,1200);
  }catch(e){ singleJobBinding = null; setRunning(false); setProgress(100,e.message||String(e),'error'); }
}

async function startBatchCheckout(){
  if (activeRunMode) return;
  const accounts = getBatchSelectedAccounts();
  if (accounts.length < 2) {
    setAccountImportStatus('请至少勾选 2 个有效账号后再并发提链', 'error');
    return;
  }
  if (!validateFormForBatch() || !validateCheckoutOptions({batch:true})) return;
  resetProgress();
  $('resultPanel').hidden = true;
  $('batchPanel').hidden = false;
  activeBatchTaskType = 'checkout';
  if ($('batchPanelTitle')) $('batchPanelTitle').textContent = '并发提链';
  $('logBox').innerHTML = `<div class="empty-log">正在同时创建 ${accounts.length} 个账号任务…</div>`;
  renderedLogKey = '';
  logAutoFollow = true;
  batchJobs = accounts.map(entry => ({
    entry, label: entry.label, requestedMethod: selected('link_type'), jobId: '', status: 'creating', percent: 1,
    text: '正在创建任务', error: '', result: null, logs: []
  }));
  batchJobs.forEach(job => {
    job.status = 'pending';
    job.percent = 0;
    job.text = '候补队列 · 等待并发槽位';
  });
  renderBatchJobs();
  setRunning(true, 'batch');
  updateBatchAggregate();
  await pumpBatchQueue();
  renderBatchJobs();
  updateBatchAggregate();
  if (activeRunMode === 'batch' && batchJobs.some(job => !isTerminalJobStatus(job.status))) {
    clearInterval(batchPollTimer);
    await pollBatch();
    if (activeRunMode === 'batch') batchPollTimer = setInterval(pollBatch, 1200);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (activeRunMode) return;
  const selectedAccounts = getBatchSelectedAccounts();
  if (selectedAccounts.length >= 2) {
    await startBatchCheckout();
  } else if (selectedAccounts.length === 1) {
    await startSingleCheckout(selectedAccounts[0]);
  } else {
    await startSingleCheckout();
  }
});

$('cancelButton').addEventListener('click', async () => {
  if(!jobId) return;
  const currentJobId = jobId;
  clearInterval(pollTimer);
  setRunning(false);
  setProgress(100,'任务已停止','cancelled');
  await fetch('/api/checkout-cancel',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:currentJobId})
  });
  singleJobBinding = null;
});

$('batchCancelButton')?.addEventListener('click', async () => {
  const pending = batchJobs.filter(job => !isTerminalJobStatus(job.status));
  if (!pending.length) return;
  clearInterval(batchPollTimer);
  batchPollTimer = 0;
  if (batchPumpTimer) {
    clearTimeout(batchPumpTimer);
    batchPumpTimer = 0;
  }
  pending.filter(job => !job.jobId).forEach(job => {
    job.status = 'cancelled';
    job.percent = 100;
    job.text = '任务已停止';
    job.error = '任务已停止';
  });
  await Promise.all(pending.filter(job => job.jobId).map(job => cancelBatchJob(job)));
  renderBatchJobs();
  updateBatchAggregate();
});

$('copyResult').addEventListener('click', async () => {
  const value = $('resultValue').value || '';
  try{ await navigator.clipboard.writeText(value); }catch{ $('resultValue').select(); document.execCommand?.('copy'); }
  const old=$('copyResult').textContent;
  $('copyResult').textContent='已复制';
  setTimeout(()=>$('copyResult').textContent=old,1200);
});

function applyTheme(dark){
  document.documentElement.classList.toggle('dark',dark);
  localStorage.setItem('pay153-theme',dark?'dark':'light');
  $('themeToggle').textContent = dark ? '☀' : '☾';
  $('themeToggle').setAttribute('aria-label', dark ? '切换到浅色模式' : '切换到深色模式');
}
const requestedTheme = new URLSearchParams(location.search).get('theme');
const saved=localStorage.getItem('pay153-theme');
applyTheme(requestedTheme ? requestedTheme === 'dark' : (saved ? saved==='dark' : matchMedia('(prefers-color-scheme: dark)').matches));
$('themeToggle').addEventListener('click',()=>applyTheme(!document.documentElement.classList.contains('dark')));
initializeProxyAsnRecommendations();
initializeBillingProfiles();
initializeProxyProfiles();
initializeAccountManager();
initializeCollapsibleSections();
syncFields(true);
void loadTaskLimits();
