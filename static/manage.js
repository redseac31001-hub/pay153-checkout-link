const $ = (id) => document.getElementById(id);
const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

const STORAGE_KEYS = {
  proxy: 'pay153.proxy_profiles.v1',
  billing: 'pay153.billing_profiles.v1',
  asn: 'pay153.proxy_asn_recommendations.v1'
};
const ACCOUNT_STORAGE_KEY = 'pay153.accounts.v1';

const state = {
  proxies: [],
  billing: [],
  addresses: [],
  asn: [],
  accounts: [],
  successes: [],
  activeSection: 'overview'
};

function text(value, fallback = '—') {
  const output = String(value ?? '').trim();
  return output || fallback;
}

function makeCell(value, className = '') {
  const cell = document.createElement('td');
  if (className) cell.className = className;
  cell.textContent = text(value);
  return cell;
}

function makeButton(label, action, danger = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `table-action${danger ? ' danger' : ''}`;
  button.textContent = label;
  button.dataset.action = action;
  return button;
}

function makeActions(...buttons) {
  const cell = document.createElement('td');
  const wrap = document.createElement('div');
  wrap.className = 'table-actions';
  buttons.forEach((button) => wrap.append(button));
  cell.append(wrap);
  return cell;
}

function show(element, visible) {
  if (element) element.hidden = !visible;
}

function setMessage(element, value, isError = false) {
  if (!element) return;
  element.textContent = value || '';
  element.classList.toggle('error', Boolean(isError));
}

function formatTime(value) {
  const output = String(value || '').replace('T', ' ');
  return output.length > 16 ? output.slice(0, 16) : text(output);
}

function accountExpiryView(exp) {
  const timestamp = Number(exp || 0) * 1000;
  if (!timestamp) return ['有效期未知', 'neutral'];
  if (timestamp <= Date.now()) return ['已过期', 'danger'];
  return [`至 ${formatTime(new Date(timestamp).toISOString())}`, 'good'];
}

const ACCOUNT_METHOD_LABELS = {
  card: 'Card',
  gopay: 'Gopay',
  ideal: 'iDEAL',
  paypal: 'PayPal',
  pix: 'PIX',
  upi: 'UPI',
  hosted: 'Hosted'
};

function maskLocalAccount(value) {
  const raw = String(value || '').trim();
  if (!raw) return '未识别账号';
  if (raw.includes('@')) {
    const [local, domain] = raw.split('@', 2);
    return `${(local || '').slice(0, 2)}***@${domain || ''}`;
  }
  return raw.length > 10 ? `${raw.slice(0, 4)}…${raw.slice(-4)}` : raw;
}

function safeLocalResultUrl(value) {
  try {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const parsed = new window.URL(raw, window.location.origin);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '';
  } catch (_) {
    return '';
  }
}

function accountMethods(value) {
  if (Array.isArray(value)) return value.reduce((result, method) => {
    const key = String(method || '').trim().toLowerCase();
    if (key) result[key] = 'supported';
    return result;
  }, {});
  if (!value || typeof value !== 'object') return {};
  return Object.entries(value).reduce((result, [method, state]) => {
    const key = String(method || '').trim().toLowerCase();
    if (!key) return result;
    const status = typeof state === 'string' ? state : state?.status;
    result[key] = ['supported', 'rejected', 'unknown'].includes(status) ? status : 'supported';
    return result;
  }, {});
}

function accountPromoView(status) {
  return {
    supported: ['支持', 'good'],
    unsupported: ['不支持 / 未生效', 'warn'],
    unknown: ['未检测', 'neutral']
  }[status] || ['未检测', 'neutral'];
}

function accountRiskView(status) {
  return {
    clear: ['未发现拒绝', 'good'],
    rejected: ['最近被拒', 'warn'],
    cooldown: ['本机冷却', 'warn'],
    blocked: ['疑似封禁', 'danger'],
    frozen: ['冻结（连续 block）', 'danger'],
    unknown: ['未检测', 'neutral']
  }[status] || ['未检测', 'neutral'];
}

function accountMethodView(status) {
  return {
    supported: ['支持', 'good'],
    rejected: ['被拒', 'warn'],
    unknown: ['未确认', 'neutral']
  }[status] || ['未确认', 'neutral'];
}

function makeStatusPill(label, tone = 'neutral') {
  const pill = document.createElement('span');
  pill.className = `status-pill ${tone}`;
  pill.textContent = label;
  return pill;
}

function localAccountList() {
  const payload = parseStorage(ACCOUNT_STORAGE_KEY);
  const list = Array.isArray(payload?.accounts) ? payload.accounts : [];
  return list.filter(item => item && typeof item === 'object').map(item => ({
    id: String(item.id || ''),
    label: String(item.label || item.email || item.accountId || '').trim(),
    email: String(item.email || '').trim(),
    accountId: String(item.accountId || '').trim(),
    exp: Number(item.exp || 0),
    kind: String(item.kind || 'token'),
    source: String(item.source || '本机'),
    promoStatus: ['supported', 'unsupported', 'unknown'].includes(item.promoStatus) ? item.promoStatus : 'unknown',
    promoReason: String(item.promoReason || '').slice(0, 240),
    paymentMethods: accountMethods(item.paymentMethods),
    riskStatus: ['clear', 'rejected', 'cooldown', 'blocked', 'frozen', 'unknown'].includes(item.riskStatus) ? item.riskStatus : 'unknown',
    riskReason: String(item.riskReason || '').slice(0, 240),
    cooldownUntil: Number(item.cooldownUntil || 0),
    lastStatus: String(item.lastStatus || '').slice(0, 40),
    lastLinkType: String(item.lastLinkType || '').slice(0, 40),
    lastCountry: String(item.lastCountry || '').trim().toUpperCase().slice(0, 8),
    lastCurrency: String(item.lastCurrency || '').trim().toUpperCase().slice(0, 8),
    lastPaymentCountry: String(item.lastPaymentCountry || '').trim().toUpperCase().slice(0, 8),
    lastResultUrl: String(item.lastResultUrl || '').slice(0, 2000),
    lastCheckedAt: Number(item.lastCheckedAt || 0),
    lastJobId: String(item.lastJobId || '').slice(0, 120)
  }));
}

function accountMatchesFilters(item) {
  const query = String($('accountQuery')?.value || '').trim().toLowerCase();
  const promo = String($('accountPromoFilter')?.value || '');
  const risk = String($('accountRiskFilter')?.value || '');
  const method = String($('accountMethodFilter')?.value || '').toLowerCase();
  const haystack = [item.label, item.email, item.accountId, item.source, item.lastError, item.riskReason, item.promoReason]
    .map(value => String(value || '').toLowerCase()).join(' ');
  if (query && !haystack.includes(query)) return false;
  if (promo && item.promoStatus !== promo) return false;
  if (risk && item.riskStatus !== risk) return false;
  if (method && item.paymentMethods?.[method] !== 'supported') return false;
  return true;
}

function renderAccounts(items) {
  const table = $('accountTable');
  if (!table) return;
  table.replaceChildren();
  items.forEach(item => {
    const row = document.createElement('tr');
    const identity = document.createElement('td');
    const title = document.createElement('strong');
    title.className = 'account-manage-title';
    title.textContent = maskLocalAccount(item.label || item.email || item.accountId);
    const identityMeta = document.createElement('div');
    identityMeta.className = 'subtle';
    identityMeta.textContent = item.accountId ? `ID ${maskLocalAccount(item.accountId)}` : text(item.kind, 'Token');
    identity.append(title, identityMeta);

    const expiry = accountExpiryView(item.exp);
    const expiryCell = document.createElement('td');
    expiryCell.append(makeStatusPill(expiry[0], expiry[1]));
    if (item.exp) {
      expiryCell.title = expiry[0];
    }

    const promo = accountPromoView(item.promoStatus);
    const promoCell = document.createElement('td');
    promoCell.append(makeStatusPill(promo[0], promo[1]));
    if (item.promoReason) {
      const note = document.createElement('div');
      note.className = 'account-status-note';
      note.textContent = item.promoReason;
      promoCell.append(note);
    }

    const methodsCell = document.createElement('td');
    const methods = Object.entries(item.paymentMethods || {});
    if (!methods.length) {
      methodsCell.append(makeStatusPill('未检测', 'neutral'));
    } else {
      const methodsList = document.createElement('div');
      methodsList.className = 'account-method-list';
      methods.forEach(([method, status]) => {
        const view = accountMethodView(status);
        const chip = makeStatusPill(`${ACCOUNT_METHOD_LABELS[method] || method} · ${view[0]}`, view[1]);
        methodsList.append(chip);
      });
      methodsCell.append(methodsList);
    }

    const risk = accountRiskView(item.riskStatus);
    const riskCell = document.createElement('td');
    riskCell.append(makeStatusPill(risk[0], risk[1]));
    if (item.riskStatus === 'cooldown' && item.cooldownUntil > Date.now()) {
      const until = document.createElement('div');
      until.className = 'account-status-note';
      until.textContent = `本机冷却至 ${formatTime(new Date(item.cooldownUntil).toISOString())}`;
      riskCell.append(until);
    }
    if (item.riskReason) {
      const note = document.createElement('div');
      note.className = 'account-status-note';
      note.textContent = item.riskReason;
      riskCell.append(note);
    }

    const checked = item.lastCheckedAt ? new Date(Number(item.lastCheckedAt)).toISOString() : '';
    const lastCell = document.createElement('td');
    lastCell.textContent = formatTime(checked);
    const lastMeta = document.createElement('div');
    lastMeta.className = 'subtle';
    const region = [item.lastCountry, item.lastCurrency].filter(Boolean).join('/');
    const paymentRegion = item.lastPaymentCountry && item.lastPaymentCountry !== item.lastCountry
      ? `支付 ${item.lastPaymentCountry}` : '';
    lastMeta.textContent = [item.lastStatus, item.lastLinkType, region, paymentRegion].filter(Boolean).join(' · ') || '尚未执行任务';
    lastCell.append(lastMeta);
    const resultLink = safeLocalResultUrl(item.lastResultUrl);
    if (resultLink) {
      const link = document.createElement('a');
      link.className = 'account-result-link';
      link.href = resultLink;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = '打开最近结果 ↗';
      lastCell.append(link);
    }

    const sourceCell = document.createElement('td');
    sourceCell.textContent = text(item.source, '本机');
    const sourceMeta = document.createElement('div');
    sourceMeta.className = 'subtle';
    sourceMeta.textContent = item.lastJobId ? `Job ${item.lastJobId}` : 'Token 仅保存在本机';
    sourceCell.append(sourceMeta);

    row.append(identity, expiryCell, promoCell, methodsCell, riskCell, lastCell, sourceCell);
    table.append(row);
  });
  setTableState('accountTable', 'accountEmpty', items.length, '当前浏览器没有本机账号记录。请先回工作台导入或粘贴账号。');
  const riskCount = state.accounts.filter(item => ['rejected', 'cooldown', 'blocked', 'frozen'].includes(item.riskStatus)).length;
  if ($('accountListMeta')) $('accountListMeta').textContent = `${items.length} 个账号 · ${riskCount} 个需要关注`;
  if ($('statAccounts')) $('statAccounts').textContent = text(state.accounts.length, '0');
  if ($('statAccountRisk')) $('statAccountRisk').textContent = riskCount ? `${riskCount} 个需要关注` : '暂无拒绝 / 冷却信号';
}

function renderFilteredAccounts() {
  renderAccounts(state.accounts.filter(accountMatchesFilters));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    ...options
  });
  let payload = {};
  try { payload = await response.json(); } catch (_) { payload = {}; }
  if (!response.ok) {
    if (response.status === 401) {
      showLogin('管理会话已过期，请重新登录。');
    }
    throw new Error(payload.error || `请求失败（${response.status}）`);
  }
  return payload;
}

function showLogin(message = '') {
  show($('manageLogin'), true);
  show($('manageApp'), false);
  setMessage($('manageLoginStatus'), message, Boolean(message));
}

function showApp() {
  show($('manageLogin'), false);
  show($('manageApp'), true);
}

function applyTheme(dark) {
  document.documentElement.classList.toggle('dark', dark);
  localStorage.setItem('pay153-theme', dark ? 'dark' : 'light');
  const toggle = $('manageThemeToggle');
  if (toggle) {
    toggle.textContent = dark ? '☀' : '☾';
    toggle.setAttribute('aria-label', dark ? '切换到浅色模式' : '切换到深色模式');
  }
}

function initializeTheme() {
  const saved = localStorage.getItem('pay153-theme');
  applyTheme(saved ? saved === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches);
  $('manageThemeToggle')?.addEventListener('click', () => {
    applyTheme(!document.documentElement.classList.contains('dark'));
  });
}

function activateSection(section) {
  state.activeSection = section;
  qsa('.manage-nav-item').forEach((button) => button.classList.toggle('active', button.dataset.section === section));
  qsa('.manage-section').forEach((panel) => {
    const active = panel.dataset.panel === section;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

function renderSummary(summary) {
  $('statProxyPools').textContent = text(summary.proxy_pools, '0');
  $('statBillingProfiles').textContent = text(summary.billing_profiles, '0');
  $('statAsnRegions').textContent = text(summary.asn_regions, '0');
  $('statSuccessRecords').textContent = text(summary.success_records, '0');
  const latest = summary.last_success;
  $('statLastSuccess').textContent = latest ? formatTime(latest.recorded_at) : '—';
  $('statLastSuccessMeta').textContent = latest ? `${text(latest.country, '??')} · ${text(latest.link_type, 'unknown')}` : '等待成功任务';
}

function setTableState(id, emptyId, count, emptyText) {
  const table = $(id);
  const empty = $(emptyId);
  if (table) table.parentElement?.classList.toggle('is-empty', count === 0);
  if (empty) {
    empty.textContent = count ? '' : emptyText;
    empty.hidden = count !== 0;
  }
}

function renderOverviewSuccesses(items) {
  const table = $('overviewSuccessTable');
  table.replaceChildren();
  items.slice(0, 8).forEach((item) => {
    const row = document.createElement('tr');
    row.append(
      makeCell(formatTime(item.recorded_at), 'subtle'),
      makeCell(item.link_type),
      makeCell(item.account, 'masked'),
      makeCell(`${text(item.entry_ip)} / ${text(item.payment_ip)}`, 'masked'),
      makeCell(`${text(item.entry_country, '??')} → ${text(item.payment_country, '??')}`),
      makeCell('已记录', 'status-pill')
    );
    table.append(row);
  });
  setTableState('overviewSuccessTable', 'overviewSuccessEmpty', items.length, '还没有成功节点记录。完成一次任务后，这里会自动出现复盘数据。');
}

function renderProxies(items) {
  const table = $('proxyTable');
  table.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement('tr');
    const identity = document.createElement('div');
    identity.textContent = text(item.name);
    const key = document.createElement('div');
    key.className = 'subtle';
    key.textContent = text(item.external_key, 'manual');
    const nameCell = document.createElement('td');
    nameCell.append(identity, key);
    row.append(nameCell);
    row.append(makeCell(`${text(item.rail, 'shared')} · ${text(item.country, '??')}`));
    row.append(makeCell(item.pool_kind === 'exit' ? '支付出口' : '入口 / 优惠'));
    row.append(makeCell(item.proxy_count, 'masked'));
    row.append(makeCell((item.proxy_preview || []).join(' · '), 'masked'));
    const status = document.createElement('td');
    const pill = document.createElement('span');
    pill.className = `status-pill${item.enabled ? '' : ' off'}`;
    pill.textContent = item.enabled ? '启用' : '停用';
    status.append(pill);
    row.append(status, makeActions(makeButton('编辑', 'edit-proxy'), makeButton('删除', 'delete-proxy', true)));
    row.dataset.id = item.id;
    table.append(row);
  });
  setTableState('proxyTable', 'proxyEmpty', items.length, '还没有代理池。可以先维护 shared 默认池，再补支付方式专用池。');
}

function renderBilling(items) {
  const table = $('billingTable');
  table.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement('tr');
    row.append(
      makeCell(item.profile_key, 'masked'),
      makeCell(`${text(item.rail, '—')} · ${text(item.country, '??')}`),
      makeCell(item.name_masked),
      makeCell(item.email_masked, 'masked'),
      makeCell(item.address_masked),
      makeCell(item.source, 'subtle'),
      makeActions(makeButton('编辑', 'edit-billing'), makeButton('删除', 'delete-billing', true))
    );
    row.dataset.id = item.id;
    table.append(row);
  });
  setTableState('billingTable', 'billingEmpty', items.length, '还没有账单档案。Gopay 建议先创建 gopay:ID。');
}

function renderAddresses(items, metadata) {
  const table = $('addressesTable');
  table.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement('tr');
    const typeLabel = {
      'residential': '住宅',
      'student': '学生宿舍',
      'school': '学校/大学',
      'office': '办公室',
      'company': '企业'
    }[item.type] || item.type || '—';

    row.append(
      makeCell(item.country),
      makeCell(typeLabel),
      makeCell(item.name),
      makeCell(item.line1),
      makeCell(item.city),
      makeCell(item.state || '—'),
      makeCell(item.postal_code)
    );
    table.append(row);
  });

  // 更新国家下拉框
  const countrySelect = $('addressCountryFilter');
  const currentCountry = countrySelect.value;
  countrySelect.innerHTML = '<option value="">全部国家</option>';
  (metadata.countries || []).forEach((country) => {
    const option = document.createElement('option');
    option.value = country;
    option.textContent = country;
    if (country === currentCountry) option.selected = true;
    countrySelect.append(option);
  });

  // 更新统计信息
  $('addressesCount').textContent = `${items.length} 条地址`;
  $('statBuiltinAddresses').textContent = text(metadata.library_total ?? metadata.total ?? items.length, '0');
  $('statBuiltinCountries').textContent = `${(metadata.countries || []).length} 个国家 · 只读候选地址`;
  setTableState('addressesTable', 'addressesEmpty', items.length, '当前没有地址数据。');
}


function renderAsn(items) {
  const list = $('asnTable');
  list.replaceChildren();
  items.forEach((item) => {
    const card = document.createElement('article');
    card.className = 'asn-manage-card';
    const head = document.createElement('div');
    head.className = 'asn-manage-head';
    const title = document.createElement('div');
    const h3 = document.createElement('h3');
    h3.textContent = `${text(item.country)} · ${text(item.label, item.country)}`;
    const note = document.createElement('p');
    note.textContent = `${text(item.region, '未设置地区')} · ${item.items?.length || 0} 个推荐项`;
    title.append(h3, note);
    head.append(title, makeButton('编辑', 'edit-asn'));
    card.append(head);
    const chips = document.createElement('div');
    chips.className = 'asn-manage-items';
    (item.items || []).forEach((asn, index) => {
      const chip = document.createElement('span');
      chip.className = 'asn-chip';
      const rank = document.createElement('b');
      rank.textContent = `${index + 1}`.padStart(2, '0');
      chip.append(rank, document.createTextNode(text(asn.asn)));
      if (asn.provider) chip.title = `${asn.provider}${asn.note ? ` · ${asn.note}` : ''}`;
      chips.append(chip);
    });
    card.append(chips);
    card.dataset.country = item.country;
    list.append(card);
  });
  setTableState('asnTable', 'asnEmpty', items.length, '还没有国家 ASN 推荐。');
}

function renderSuccesses(items) {
  const table = $('successTable');
  table.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement('tr');
    const job = document.createElement('td');
    const code = document.createElement('code');
    code.textContent = text(item.job_id);
    job.append(code);
    row.append(makeCell(formatTime(item.recorded_at), 'subtle'), job);
    row.append(makeCell(`${text(item.link_type)} · ${text(item.plan, '—')}`));
    row.append(makeCell(item.account, 'masked'));
    row.append(makeCell(`${text(item.entry_ip)} ${text(item.entry_country, '??')}`, 'masked'));
    row.append(makeCell(`${text(item.payment_ip)} ${text(item.payment_country, '??')}`, 'masked'));
    row.append(makeCell(`${text(item.entry_region, '—')} → ${text(item.payment_region, '—')}`));
    row.append(makeCell(`${text(item.checkout_amount)} ${text(item.currency, '')}`));
    table.append(row);
  });
  setTableState('successTable', 'successEmpty', items.length, '当前筛选条件下没有成功节点。');
}

function renderLogs(items) {
  const list = $('logsTable');
  list.replaceChildren();
  items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'manage-log-row';
    const time = document.createElement('time');
    time.textContent = text(item.time, '—');
    const kind = document.createElement('span');
    kind.className = 'log-kind';
    kind.textContent = text(item.kind, 'LOG');
    const job = document.createElement('code');
    job.textContent = text(item.job_id);
    const message = document.createElement('p');
    message.textContent = text(item.message, '—');
    row.append(time, kind, job, message);
    list.append(row);
  });
  const empty = $('logsEmpty');
  empty.textContent = items.length ? '' : '当前日期或筛选条件下没有日志。';
  empty.hidden = items.length !== 0;
}

async function loadSummary() {
  renderSummary(await api('/api/manage/summary'));
}

async function loadProxies() {
  state.proxies = (await api('/api/manage/proxy-pools')).items || [];
  renderProxies(state.proxies);
}

async function loadBilling() {
  const response = await api('/api/manage/billing-profiles');
  state.billing = response.items || [];
  renderBilling(state.billing);
}

async function loadAddresses() {
  const params = new URLSearchParams();
  if ($('addressCountryFilter').value) params.set('country', $('addressCountryFilter').value);
  if ($('addressTypeFilter').value) params.set('type', $('addressTypeFilter').value);
  const response = await api(`/api/manage/builtin-addresses?${params}`);
  state.addresses = response.addresses || [];
  renderAddresses(state.addresses, response);
}

async function loadAsn() {
  state.asn = (await api('/api/manage/asn-recommendations')).items || [];
  renderAsn(state.asn);
}

function loadAccounts() {
  state.accounts = localAccountList();
  renderFilteredAccounts();
}

async function loadSuccesses() {
  const params = new URLSearchParams({limit: '200'});
  if ($('successQuery').value.trim()) params.set('q', $('successQuery').value.trim());
  if ($('successCountry').value.trim()) params.set('country', $('successCountry').value.trim());
  if ($('successLinkType').value) params.set('link_type', $('successLinkType').value);
  state.successes = (await api(`/api/manage/success-records?${params}`)).items || [];
  renderSuccesses(state.successes);
  renderOverviewSuccesses(state.successes);
}

async function loadLogs() {
  const params = new URLSearchParams({limit: '300'});
  if ($('logDay').value) params.set('day', $('logDay').value);
  if ($('logJobId').value.trim()) params.set('job_id', $('logJobId').value.trim());
  if ($('logQuery').value.trim()) params.set('q', $('logQuery').value.trim());
  renderLogs((await api(`/api/manage/logs?${params}`)).items || []);
}

async function loadAll() {
  setMessage($('manageGlobalMessage'), '正在同步管理数据…');
  try {
    await Promise.all([loadSummary(), loadAccounts(), loadProxies(), loadBilling(), loadAddresses(), loadAsn(), loadSuccesses(), loadLogs()]);
    setMessage($('manageGlobalMessage'), '数据已更新。');
    window.setTimeout(() => setMessage($('manageGlobalMessage'), ''), 1800);
  } catch (error) {
    setMessage($('manageGlobalMessage'), error.message, true);
  }
}

function proxyPayload() {
  return {
    name: $('proxyName').value.trim(),
    rail: $('proxyRail').value.trim(),
    country: $('proxyCountry').value.trim().toUpperCase(),
    region: $('proxyRegion').value.trim(),
    pool_kind: $('proxyKind').value,
    enabled: $('proxyEnabled').checked,
    proxies: $('proxyData').value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
  };
}

function resetProxyForm() {
  $('proxyForm').reset();
  $('proxyId').value = '';
  $('proxyFormTitle').textContent = '新增代理池';
  setMessage($('proxyFormStatus'), '');
}

async function editProxy(id) {
  try {
    const item = await api(`/api/manage/proxy-pools/${id}?reveal=1`);
    $('proxyId').value = item.id;
    $('proxyName').value = item.name || '';
    $('proxyRail').value = item.rail || '';
    $('proxyCountry').value = item.country || '';
    $('proxyRegion').value = item.region || '';
    $('proxyKind').value = item.pool_kind || 'entry';
    $('proxyEnabled').checked = Boolean(item.enabled);
    $('proxyData').value = (item.proxies || []).join('\n');
    $('proxyFormTitle').textContent = `编辑代理池 · ${text(item.name)}`;
    activateSection('proxies');
  } catch (error) { setMessage($('manageGlobalMessage'), error.message, true); }
}

async function saveProxy(event) {
  event.preventDefault();
  const id = $('proxyId').value;
  setMessage($('proxyFormStatus'), '正在保存…');
  try {
    const response = await api(id ? `/api/manage/proxy-pools/${id}` : '/api/manage/proxy-pools', {
      method: id ? 'PUT' : 'POST', body: JSON.stringify(proxyPayload())
    });
    setMessage($('proxyFormStatus'), `已保存 ${text(response.item?.name, '代理池')}`);
    resetProxyForm();
    await Promise.all([loadProxies(), loadSummary()]);
  } catch (error) { setMessage($('proxyFormStatus'), error.message, true); }
}

function billingPayload() {
  return {
    profile_key: $('billingProfileKey').value.trim(),
    rail: $('billingRail').value.trim(),
    country: $('billingCountry').value.trim().toUpperCase(),
    region: $('billingRegion').value.trim(),
    name: $('billingName').value.trim(),
    email: $('billingEmail').value.trim(),
    line1: $('billingLine1').value.trim(),
    line2: $('billingLine2').value.trim(),
    city: $('billingCity').value.trim(),
    state: $('billingState').value.trim(),
    postal_code: $('billingPostalCode').value.trim(),
    source: 'manage'
  };
}

function resetBillingForm() {
  $('billingForm').reset();
  $('billingId').value = '';
  $('billingFormTitle').textContent = '新增账单档案';
  setMessage($('billingFormStatus'), '');
}

async function editBilling(id) {
  try {
    const item = await api(`/api/manage/billing-profiles/${id}?reveal=1`);
    const profile = item.profile || {};
    $('billingId').value = item.id;
    $('billingProfileKey').value = item.profile_key || '';
    $('billingRail').value = item.rail || '';
    $('billingCountry').value = item.country || '';
    $('billingRegion').value = item.region || '';
    ['name', 'email', 'line1', 'line2', 'city', 'state', 'postal_code'].forEach((key) => {
      const field = $(`billing${key === 'postal_code' ? 'PostalCode' : key[0].toUpperCase() + key.slice(1)}`);
      if (field) field.value = profile[key] || '';
    });
    $('billingFormTitle').textContent = `编辑账单档案 · ${text(item.profile_key)}`;
    activateSection('billing');
  } catch (error) { setMessage($('manageGlobalMessage'), error.message, true); }
}

async function saveBilling(event) {
  event.preventDefault();
  const id = $('billingId').value;
  setMessage($('billingFormStatus'), '正在保存…');
  try {
    const response = await api(id ? `/api/manage/billing-profiles/${id}` : '/api/manage/billing-profiles', {
      method: id ? 'PUT' : 'POST', body: JSON.stringify(billingPayload())
    });
    setMessage($('billingFormStatus'), `已保存 ${text(response.item?.profile_key, '账单档案')}`);
    resetBillingForm();
    await Promise.all([loadBilling(), loadSummary()]);
  } catch (error) { setMessage($('billingFormStatus'), error.message, true); }
}

function resetAsnForm() {
  $('asnForm').reset();
  setMessage($('asnFormStatus'), '');
}

function editAsn(country) {
  const item = state.asn.find((candidate) => candidate.country === country);
  if (!item) return;
  $('asnCountry').value = item.country || '';
  $('asnRegion').value = item.region || '';
  $('asnLabel').value = item.label || '';
  $('asnItems').value = (item.items || []).map((asn) => asn.asn).join('\n');
  activateSection('asn');
}

async function saveAsn(event) {
  event.preventDefault();
  setMessage($('asnFormStatus'), '正在保存…');
  try {
    const response = await api('/api/manage/asn-recommendations', {
      method: 'PUT',
      body: JSON.stringify({country: $('asnCountry').value.trim().toUpperCase(), region: $('asnRegion').value.trim(), label: $('asnLabel').value.trim(), items: $('asnItems').value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)})
    });
    setMessage($('asnFormStatus'), `已保存 ${text(response.item?.country, '国家推荐')}`);
    await Promise.all([loadAsn(), loadSummary()]);
  } catch (error) { setMessage($('asnFormStatus'), error.message, true); }
}

function parseStorage(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    return value && typeof value === 'object' ? value : null;
  } catch (_) { return null; }
}

async function importLocalConfig() {
  const payload = {
    proxy_profiles: parseStorage(STORAGE_KEYS.proxy),
    billing_profiles: parseStorage(STORAGE_KEYS.billing),
    asn_recommendations: parseStorage(STORAGE_KEYS.asn)
  };
  const hasConfig = Object.values(payload).some(Boolean);
  if (!hasConfig) {
    setMessage($('manageGlobalMessage'), '当前浏览器没有可导入的代理、账单或 ASN 配置。', true);
    return;
  }
  const confirmed = window.confirm('将把当前浏览器 localStorage 中的代理池（含凭据）、账单档案和 ASN 推荐上传到本地管理数据库；Token 不包含。是否继续？');
  if (!confirmed) return;
  try {
    const result = await api('/api/manage/import-local', {method: 'POST', body: JSON.stringify(payload)});
    const imported = result.imported || {};
    setMessage($('manageGlobalMessage'), `导入完成：代理池 ${imported.proxy_pools || 0}，账单 ${imported.billing_profiles || 0}，ASN ${imported.asn_regions || 0}。`);
    await loadAll();
  } catch (error) { setMessage($('manageGlobalMessage'), error.message, true); }
}

async function deleteRecord(kind, id) {
  const label = kind === 'proxy' ? '代理池' : '账单档案';
  if (!window.confirm(`确定删除这个${label}吗？此操作不会删除浏览器工作台缓存。`)) return;
  try {
    await api(`/api/manage/${kind === 'proxy' ? 'proxy-pools' : 'billing-profiles'}/${id}`, {method: 'DELETE'});
    await Promise.all([kind === 'proxy' ? loadProxies() : loadBilling(), loadSummary()]);
  } catch (error) { setMessage($('manageGlobalMessage'), error.message, true); }
}

function bindTableActions() {
  $('proxyTable').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const id = button.closest('tr')?.dataset.id;
    if (button.dataset.action === 'edit-proxy') editProxy(id);
    if (button.dataset.action === 'delete-proxy') deleteRecord('proxy', id);
  });
  $('billingTable').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const id = button.closest('tr')?.dataset.id;
    if (button.dataset.action === 'edit-billing') editBilling(id);
    if (button.dataset.action === 'delete-billing') deleteRecord('billing', id);
  });
  $('asnTable').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action="edit-asn"]');
    if (button) editAsn(button.closest('.asn-manage-card')?.dataset.country);
  });
}

function bindEvents() {
  qsa('.manage-nav-item').forEach((button) => button.addEventListener('click', () => activateSection(button.dataset.section)));
  qsa('[data-jump]').forEach((button) => button.addEventListener('click', () => activateSection(button.dataset.jump)));
  $('manageLoginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    setMessage($('manageLoginStatus'), '正在验证…');
    try {
      await api('/api/manage/login', {method: 'POST', body: JSON.stringify({password: $('managePassword').value})});
      $('managePassword').value = '';
      showApp();
      await loadAll();
    } catch (error) { setMessage($('manageLoginStatus'), error.message, true); }
  });
  $('manageLogout').addEventListener('click', async () => {
    await api('/api/manage/logout', {method: 'POST'}).catch(() => {});
    showLogin('已退出管理会话。');
  });
  $('refreshAll').addEventListener('click', loadAll);
  $('importLocalConfig').addEventListener('click', importLocalConfig);
  $('proxyForm').addEventListener('submit', saveProxy);
  $('billingForm').addEventListener('submit', saveBilling);
  $('asnForm').addEventListener('submit', saveAsn);
  $('resetProxyForm').addEventListener('click', resetProxyForm);
  $('resetBillingForm').addEventListener('click', resetBillingForm);
  $('resetAsnForm').addEventListener('click', resetAsnForm);
  $('refreshProxies').addEventListener('click', loadProxies);
  $('refreshBilling').addEventListener('click', loadBilling);
  $('refreshAddresses').addEventListener('click', loadAddresses);
  $('addressCountryFilter').addEventListener('change', loadAddresses);
  $('addressTypeFilter').addEventListener('change', loadAddresses);
  $('refreshAccounts').addEventListener('click', loadAccounts);
  ['accountQuery', 'accountPromoFilter', 'accountRiskFilter', 'accountMethodFilter'].forEach((id) => {
    $(id)?.addEventListener('input', renderFilteredAccounts);
    $(id)?.addEventListener('change', renderFilteredAccounts);
  });
  $('refreshAsn').addEventListener('click', loadAsn);
  $('refreshSuccesses').addEventListener('click', loadSuccesses);
  $('refreshLogs').addEventListener('click', loadLogs);
  bindTableActions();
  window.addEventListener('storage', (event) => {
    if (event.key === ACCOUNT_STORAGE_KEY) loadAccounts();
  });
}

async function bootstrap() {
  initializeTheme();
  $('logDay').value = new Date().toISOString().slice(0, 10);
  bindEvents();
  try {
    const sessionState = await api('/api/manage/session');
    if (!sessionState.configured) {
      showLogin('管理中心未启用：请在服务端设置 PAY153_MANAGE_PASSWORD。');
      $('managePassword').disabled = true;
      $('manageLoginForm').querySelector('button').disabled = true;
      return;
    }
    if (!sessionState.authenticated) {
      showLogin();
      return;
    }
    showApp();
    await loadAll();
  } catch (error) {
    showLogin(error.message);
  }
}

bootstrap();
