const $ = (id) => document.getElementById(id);
const form = $('checkoutForm');
let jobId = '';
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

const PROXY_STORAGE_KEYS = {
  profiles: 'pay153.proxy_profiles.v1',
  legacyEntry: 'pay153.proxy_pool_1',
  legacyExit: 'pay153.proxy_pool_2'
};
const BILLING_STORAGE_KEY = 'pay153.billing_profiles.v1';
const PROXY_ASN_RECOMMENDATION_STORAGE_KEY = 'pay153.proxy_asn_recommendations.v1';
const BILLING_PROFILE_FIELDS = ['name', 'email', 'line1', 'line2', 'city', 'state', 'postal_code'];

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
let billingProfiles = {};
let activeBillingProfileKey = '';
let billingSaveTimer = 0;
let billingInputDirty = false;
let proxyAsnRecommendations = {};

const providerDefaults = {
  hosted: {country: 'US', currency: 'USD'}, paypal: {country: 'US', currency: 'USD'},
  ideal: {country: 'NL', currency: 'EUR'}, upi: {country: 'IN', currency: 'INR'},
  pix: {country: 'BR', currency: 'BRL'}, gopay: {country: 'ID', currency: 'IDR'}
};
const countryCurrency = {US:'USD',DE:'EUR',FR:'EUR',NL:'EUR',IN:'INR',BR:'BRL',GB:'GBP',JP:'JPY',AU:'AUD',CA:'CAD',ID:'IDR'};

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
}
$('country').addEventListener('change', () => {
  $('currency').value = countryCurrency[$('country').value] || 'USD';
  renderProxyAsnRecommendations();
  syncBillingFields();
});
$('usePromo').addEventListener('change', () => syncFields(false));
$('entryProxy').addEventListener('input', () => { updateProxyCount($('entryProxy'), $('entryProxyCount')); saveProxyPools(); });
$('exitProxy').addEventListener('input', () => { updateProxyCount($('exitProxy'), $('exitProxyCount')); saveProxyPools(); });
$('probeEntryProxy').addEventListener('click', () => probeProxyPool('entryProxy', 'probeEntryProxy', 'entryProxyProbe', '代理池 1'));
$('probeExitProxy').addEventListener('click', () => probeProxyPool('exitProxy', 'probeExitProxy', 'exitProxyProbe', '代理池 2'));
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
function setRunning(running){ $('submitButton').disabled = running; $('cancelButton').hidden = !running; }
$('logBox').addEventListener('scroll', () => {
  const box = $('logBox');
  logAutoFollow = box.scrollHeight - box.clientHeight - box.scrollTop < 28;
});

function showResult(result){
  $('resultPanel').hidden = false;
  const managedSuffix = result.checkout_flow === 'openai_managed' ? ' · OPENAI 官方托管' : '';
  $('resultType').textContent = `${String(result.plan||'').toUpperCase()} · ${String(result.link_type||'').toUpperCase()}${managedSuffix}`;
  $('resultEmail').textContent = result.account_email || '—';
  $('resultRegion').textContent = `${result.country || '—'} / ${result.currency || '—'}`;
  $('resultPromo').textContent = !result.promo_requested ? '未请求' : result.promo_applied === true ? '已生效 · 今日应付 0' : result.promo_applied === false ? '未生效' : '打开结账页确认';
  $('resultSession').textContent = result.checkout_session_id || '—';
  const finalValue = result.qr_data || result.provider_redirect_url || result.checkout_url || '';
  $('resultValue').value = finalValue;
  const openUrl = result.provider_redirect_url || result.checkout_url || '';
  $('openResult').href = openUrl || '#';
  $('openResult').textContent = result.checkout_flow === 'openai_managed' ? '打开官方结账页' : '打开链接';
  $('openResult').style.display = openUrl ? 'inline-flex' : 'none';
  const qr = result.qr_image_png || result.qr_image_svg || '';
  $('qrWrap').hidden = !qr;
  if (qr) $('qrImage').src = qr;
  startCountdown(result.expires_at);
  $('resultPanel').scrollIntoView({behavior:'smooth',block:'nearest'});
}
function startCountdown(expiresAt){
  clearInterval(countdownTimer); const node = $('qrCountdown');
  if (!expiresAt) { node.textContent = ''; return; }
  const render = () => { const remain = Math.max(0, Number(expiresAt)*1000-Date.now()); const m=Math.floor(remain/60000),s=Math.floor(remain%60000/1000); node.textContent=remain?`二维码剩余 ${m}:${String(s).padStart(2,'0')}`:'二维码已到期'; };
  render(); countdownTimer=setInterval(render,1000);
}

async function poll(){
  if (!jobId) return;
  try{
    const r = await fetch(`/api/checkout-progress?job_id=${encodeURIComponent(jobId)}`, {cache:'no-store'});
    const data = await r.json(); if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    setProgress(data.percent, data.text, data.status);
    renderLogs(data.logs);
    if (data.status === 'done') { clearInterval(pollTimer); setRunning(false); showResult(data.result || {}); }
    if (data.status === 'error' || data.status === 'cancelled') { clearInterval(pollTimer); setRunning(false); if(data.error) renderLogs([...(data.logs||[]),{time:'ERROR',message:data.error}]); }
  }catch(e){ clearInterval(pollTimer); setRunning(false); setProgress(100, e.message || String(e), 'error'); }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault(); $('resultPanel').hidden = true; $('logBox').innerHTML = '<div class="empty-log">正在创建任务…</div>';
  renderedLogKey = '';
  logAutoFollow = true;
  const plan = selected('plan');
  const linkType = selected('link_type');
  const billingProfile = readBillingProfile();
  if (linkType === 'gopay') {
    const missing = billingProfileMissing(billingProfile);
    if (missing.length) {
      $('billingBlock').hidden = false;
      updateBillingProfileState();
      setBillingSaveState('账单档案未完成', true);
      setProgress(100, `Gopay 账单档案缺少：${missing.join('、')}`, 'error');
      const firstMissing = {name: 'billingName', line1: 'billingLine1', city: 'billingCity', postal_code: 'billingPostalCode'};
      $(firstMissing[Object.keys(firstMissing).find(field => !String(billingProfile[field] || '').trim())] || 'billingName')?.focus();
      return;
    }
  }
  resetProgress();
  setRunning(true); setProgress(3, '提交任务', 'running');
  const body = {
    token: $('token').value, plan, link_type: linkType, country: $('country').value,
    currency: $('currency').value, entry_proxies: proxyLines($('entryProxy')), exit_proxies: proxyLines($('exitProxy')),
    billing_profile: billingProfileHasContent(billingProfile) ? billingProfile : null,
    retry_count: Math.max(1, Math.min(50, Number($('retryCount').value || 10))),
    use_promo: plan === 'plus' && $('usePromo').checked,
    promo_campaign: plan === 'plus' ? $('promoCampaign').value.trim() : '',
    promo_code: plan === 'team' ? $('promoCode').value.trim() : '',
    workspace_name: plan === 'codex_low' ? $('codexWorkspaceName').value.trim() : $('workspaceName').value.trim(),
    workspace_id: $('workspaceId').value.trim(), seat_quantity: Number($('seatQuantity').value || 5),
    price_interval: $('priceInterval').value, credit_quantity: Number($('creditQuantity').value || 13),
    ideal_bank: '',
    pix_tax_id: selected('link_type') === 'pix' ? $('pixTaxId').value.trim() : '',
    pix_auto_kind: selected('link_type') === 'pix' ? $('pixAutoKind').value : 'cpf'
  };
  try{
    const r = await fetch('/api/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await r.json(); if(!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    jobId = data.job_id;
    if (data.queue_position > 0) setProgress(2, `任务已进入队列，当前第 ${data.queue_position} 位`, 'queued');
    clearInterval(pollTimer); await poll(); pollTimer=setInterval(poll,1200);
  }catch(e){ setRunning(false); setProgress(100,e.message||String(e),'error'); }
});

$('cancelButton').addEventListener('click', async () => {
  if(!jobId) return;
  setRunning(false);
  setProgress(100,'任务已停止','cancelled');
  await fetch('/api/checkout-cancel',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId})
  });
});
$('copyResult').addEventListener('click', async () => { await navigator.clipboard.writeText($('resultValue').value || ''); const old=$('copyResult').textContent; $('copyResult').textContent='已复制'; setTimeout(()=>$('copyResult').textContent=old,1200); });

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
syncFields(true);
