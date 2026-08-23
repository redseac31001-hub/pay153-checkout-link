const $ = (id) => document.getElementById(id);
const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

const STORAGE_KEYS = {
  proxy: 'pay153.proxy_profiles.v1',
  billing: 'pay153.billing_profiles.v1',
  asn: 'pay153.proxy_asn_recommendations.v1'
};
const ACCOUNT_STORAGE_KEY = 'pay153.accounts.v1';
const ACCOUNT_PAGE_SIZE = 20;
const ACCOUNT_LIFECYCLES = ['active', 'completed', 'deleted'];
const ACCOUNT_LIFECYCLE_LABELS = {
  active: '正常',
  completed: '已完成',
  deleted: '已注销/删除'
};
const MANAGE_DETECTION_CONCURRENCY_KEY = 'pay153.manage.detection.concurrency.v1';
const MANAGE_DETECTION_PROXY_CONFIG_KEY = 'pay153.manage.detection.proxy_config.v1';
const DEFAULT_MANAGE_DETECTION_CONCURRENCY = 3;
const DEFAULT_TASK_LIMITS = {perIp: 3, global: 20, workers: 20};

const state = {
  proxies: [],
  billing: [],
  addresses: [],
  asn: [],
  accounts: [],
  successes: [],
  activeSection: 'overview',
  activeAccountId: '',
  selectedAccountIds: new Set(),
  accountSequence: 0,
  accountPage: 1,
  taskLimits: {...DEFAULT_TASK_LIMITS},
  detectionConcurrency: DEFAULT_MANAGE_DETECTION_CONCURRENCY,
  detectionJobs: [],
  detectionRunning: false
};
const revealedManageEmailIds = new Set();

function text(value, fallback = '—') {
  const output = String(value ?? '').trim();
  return output || fallback;
}

function manageAccountEmail(item) {
  const email = String(item?.email || '').trim();
  if (email) return email;
  const label = String(item?.label || '').trim();
  return label.includes('@') ? label : '';
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

function accountTimestamp(value) {
  const timestamp = Number(value || 0);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return 0;
  return timestamp < 100000000000 ? timestamp * 1000 : timestamp;
}

function normalizeAccountLifecycle(value) {
  const normalized = String(value || '').trim().toLowerCase();
  return ACCOUNT_LIFECYCLES.includes(normalized) ? normalized : 'active';
}

function accountLifecycleView(value) {
  const lifecycle = normalizeAccountLifecycle(value);
  const tone = lifecycle === 'active' ? 'good' : lifecycle === 'completed' ? 'warn' : 'danger';
  return {value: lifecycle, label: ACCOUNT_LIFECYCLE_LABELS[lifecycle], tone};
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
  ,gcash: 'GCash'
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

function normalizeAccountDiscounts(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const clean = item => ({percent: Math.max(0, Math.min(100, Number(item?.percent || 0) || 0)), fixed: Math.max(0, Number(item?.fixed || 0) || 0)});
  const regions = Array.isArray(source.regions) ? source.regions.slice(0, 30).map(item => ({country: String(item?.country || '').trim().toUpperCase().slice(0, 8), currency: String(item?.currency || '').trim().toUpperCase().slice(0, 8), ...clean(item)})).filter(item => item.country || item.currency) : [];
  return {global: clean(source.global), regions};
}

function normalizeAccountProtocol(value) {
  const normalized = String(value || '').trim().toLowerCase();
  return ['oaics', 'cs', 'unknown'].includes(normalized) ? normalized : 'unknown';
}

function normalizeAccountProtocolCheckedAt(value, fallback = Date.now()) {
  const parsed = Number(value);
  const timestamp = Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  return timestamp < 100000000000 ? timestamp * 1000 : timestamp;
}

function accountProtocols(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.entries(value).slice(0, 100).reduce((result, [key, raw]) => {
    if (!raw || typeof raw !== 'object') return result;
    const country = String(raw.country || '').trim().toUpperCase().slice(0, 8);
    const currency = String(raw.currency || '').trim().toUpperCase().slice(0, 8);
    const checkedAtRaw = Number(raw.checkedAt || raw.checked_at || 0);
    if (!country || !currency || !checkedAtRaw) return result;
    result[String(key).slice(0, 80)] = {
      protocol: normalizeAccountProtocol(raw.protocol),
      country,
      currency,
      checkedAt: checkedAtRaw < 100000000000 ? checkedAtRaw * 1000 : checkedAtRaw,
      baseline: Boolean(raw.baseline),
      source: String(raw.source || 'checkout').slice(0, 40),
      paymentMethods: accountMethods(raw.paymentMethods || raw.payment_method_types)
    };
    return result;
  }, {});
}

function accountProtocolView(item, now = Date.now()) {
  const records = accountProtocols(item?.checkoutProtocols);
  const exactKey = `paypal:${item?.lastCountry || 'DE'}:${item?.lastCurrency || 'EUR'}`;
  const record = records[exactKey] || records['paypal:DE:EUR'];
  if (!record || now - Number(record.checkedAt || 0) > 24 * 60 * 60 * 1000) {
    return {protocol: 'unknown', label: '待检测', scope: '—', tone: 'neutral'};
  }
  const protocol = normalizeAccountProtocol(record.protocol);
  return {
    protocol,
    label: protocol === 'oaics' ? 'OAICS' : protocol === 'cs' ? 'CS' : '未知',
    scope: `${record.country}/${record.currency}`,
    tone: protocol === 'oaics' ? 'protocol-oaics' : protocol === 'cs' ? 'protocol-cs' : 'neutral'
  };
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
    raw: String(item.raw || item.token || '').trim(),
    token: String(item.token || item.raw || '').trim(),
    label: String(item.label || item.email || item.accountId || '').trim(),
    email: String(item.email || '').trim(),
    accountId: String(item.accountId || '').trim(),
    exp: Number(item.exp || 0),
    kind: String(item.kind || 'token'),
    source: String(item.source || '本机'),
    promoStatus: ['supported', 'unsupported', 'unknown'].includes(item.promoStatus) ? item.promoStatus : 'unknown',
    promoReason: String(item.promoReason || '').slice(0, 240),
    note: String(item.note || '').slice(0, 500),
    discounts: normalizeAccountDiscounts(item.discounts),
    paymentMethods: accountMethods(item.paymentMethods),
    checkoutProtocols: accountProtocols(item.checkoutProtocols),
    lifecycle: normalizeAccountLifecycle(item.lifecycle),
    riskStatus: ['clear', 'rejected', 'cooldown', 'blocked', 'frozen', 'unknown'].includes(item.riskStatus) ? item.riskStatus : 'unknown',
    riskReason: String(item.riskReason || '').slice(0, 240),
    cooldownUntil: Number(item.cooldownUntil || 0),
    consecutiveDeclines: Number(item.consecutiveDeclines || 0),
    consecutiveBlocks: Number(item.consecutiveBlocks || 0),
    frozenAt: Number(item.frozenAt || 0),
    addedAt: accountTimestamp(item.addedAt || item.createdAt || item.joinedAt || item.updatedAt),
    updatedAt: Number(item.updatedAt || 0),
    lastError: String(item.lastError || '').slice(0, 240),
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
  const protocol = String($('accountProtocolFilter')?.value || '').toLowerCase();
  const promo = String($('accountPromoFilter')?.value || '');
  const risk = String($('accountRiskFilter')?.value || '');
  const method = String($('accountMethodFilter')?.value || '').toLowerCase();
  const lifecycle = String($('accountLifecycleFilter')?.value || '').toLowerCase();
  const lifecycleView = accountLifecycleView(item.lifecycle);
  const haystack = [item.label, item.email, item.accountId, item.source, item.lastError, item.riskReason, item.promoReason, lifecycleView.label]
    .map(value => String(value || '').toLowerCase()).join(' ');
  if (query && !haystack.includes(query)) return false;
  if (protocol && accountProtocolView(item).protocol !== protocol) return false;
  if (promo && item.promoStatus !== promo) return false;
  if (risk && item.riskStatus !== risk) return false;
  if (method && item.paymentMethods?.[method] !== 'supported') return false;
  if (lifecycle && item.lifecycle !== lifecycle) return false;
  return true;
}

function compareAccountsByAddedAt(left, right) {
  const addedAtDifference = accountTimestamp(right.addedAt) - accountTimestamp(left.addedAt);
  if (addedAtDifference) return addedAtDifference;
  return String(right.id || '').localeCompare(String(left.id || ''));
}

function makeAccountLifecycleCell(item) {
  const cell = document.createElement('td');
  cell.className = 'account-lifecycle-cell';
  const view = accountLifecycleView(item.lifecycle);
  cell.append(makeStatusPill(view.label, view.tone));
  const select = document.createElement('select');
  select.className = 'account-lifecycle-select';
  select.setAttribute('aria-label', `编辑 ${item.label || item.email || item.accountId} 生命周期`);
  ACCOUNT_LIFECYCLES.forEach(value => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = ACCOUNT_LIFECYCLE_LABELS[value];
    option.selected = value === view.value;
    select.append(option);
  });
  select.title = view.value === 'active' ? '主面板会展示此账号' : '主面板会隐藏此账号，管理中心仍保留记录';
  select.addEventListener('click', event => event.stopPropagation());
  select.addEventListener('change', () => setManageAccountLifecycle(item.id, select.value));
  const note = document.createElement('div');
  note.className = 'account-status-note';
  note.textContent = view.value === 'active' ? '主面板展示' : '主面板隐藏';
  cell.append(select, note);
  return cell;
}

function renderAccounts(items, pagination = {}) {
  const table = $('accountTable');
  if (!table) return;
  table.replaceChildren();
  items.forEach(item => {
    const row = document.createElement('tr');
    row.dataset.id = item.id;
    row.classList.toggle('is-active-account', item.id === state.activeAccountId);
    const selectCell = document.createElement('td');
    selectCell.className = 'account-select-cell';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'manage-account-check';
    checkbox.checked = state.selectedAccountIds.has(item.id);
    checkbox.disabled = !manageAccountCanBatch(item) || state.detectionRunning;
    checkbox.setAttribute('aria-label', `选择 ${item.label || item.email || item.accountId} 批量检测或并发提链`);
    checkbox.addEventListener('click', event => event.stopPropagation());
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.selectedAccountIds.add(item.id);
      else state.selectedAccountIds.delete(item.id);
      persistManageAccounts();
      updateManageAccountControls();
      renderFilteredAccounts();
    });
    selectCell.append(checkbox);

    const identity = document.createElement('td');
    const title = document.createElement('strong');
    title.className = 'account-manage-title';
    title.textContent = maskLocalAccount(item.label || item.email || item.accountId);
    const identityMeta = document.createElement('div');
    identityMeta.className = 'subtle';
    identityMeta.textContent = item.accountId ? `ID ${maskLocalAccount(item.accountId)}` : text(item.kind, 'Token');
    identity.append(title, identityMeta);
    if (item.note) { const note = document.createElement('div'); note.className = 'account-row-note'; note.textContent = `备注：${item.note}`; identity.append(note); }
    const email = manageAccountEmail(item);
    if (revealedManageEmailIds.has(item.id)) {
      const emailValue = document.createElement('div');
      emailValue.className = 'account-plain-email';
      emailValue.textContent = email || '未从 Token / Session 解析到邮箱';
      identity.append(emailValue);
    }

    const lifecycleCell = makeAccountLifecycleCell(item);
    const protocol = accountProtocolView(item);
    const expiry = accountExpiryView(item.exp);
    const protocolExpiryCell = document.createElement('td');
    protocolExpiryCell.append(makeStatusPill(protocol.label, protocol.tone));
    const protocolScope = document.createElement('div');
    protocolScope.className = 'account-status-note';
    protocolScope.textContent = protocol.scope === '—' ? 'PayPal DE/EUR' : protocol.scope;
    protocolExpiryCell.append(protocolScope);
    const expiryPill = makeStatusPill(expiry[0], expiry[1]);
    expiryPill.classList.add('account-combined-sep');
    protocolExpiryCell.append(expiryPill);
    if (item.exp) protocolExpiryCell.title = `有效期 ${expiry[0]}`;

    const promo = accountPromoView(item.promoStatus);
    const promoMethodsCell = document.createElement('td');
    promoMethodsCell.append(makeStatusPill(promo[0], promo[1]));
    if (item.promoReason) {
      const note = document.createElement('div');
      note.className = 'account-status-note';
      note.textContent = item.promoReason;
      promoMethodsCell.append(note);
    }
    const methods = Object.entries(item.paymentMethods || {});
    const methodsList = document.createElement('div');
    methodsList.className = 'account-method-list';
    if (!methods.length) {
      const sep = makeStatusPill('未检测', 'neutral');
      sep.classList.add('account-combined-sep');
      methodsList.append(sep);
    } else {
      methods.forEach(([method, status]) => {
        const view = accountMethodView(status);
        const chip = makeStatusPill(`${ACCOUNT_METHOD_LABELS[method] || method} · ${view[0]}`, view[1]);
        if (methodsList.children.length) chip.classList.add('account-combined-sep');
        methodsList.append(chip);
      });
    }
    promoMethodsCell.append(methodsList);

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

    const emailButton = makeButton(revealedManageEmailIds.has(item.id) ? '隐藏邮箱' : '查看邮箱', 'toggle-email');
    emailButton.disabled = !email;
    emailButton.title = email ? '仅在当前管理页面展开完整邮箱' : '当前账号没有可展示的邮箱';
    const useButton = makeButton('使用', 'use-account');
    const editButton = makeButton('编辑', 'edit-account');
    useButton.disabled = item.lifecycle !== 'active';
    useButton.title = item.lifecycle === 'active' ? '设为工作台当前账号' : '请先将生命周期改为正常';
    const detectButton = makeButton('检测', 'detect-account');
    detectButton.disabled = !manageAccountCanBatch(item) || state.detectionRunning;
    detectButton.title = item.lifecycle === 'active' ? '检测 PayPal DE/EUR 协议' : '已归档账号不参与检测';
    const actions = makeActions(
      emailButton,
      useButton,
      editButton,
      detectButton,
      makeButton('移除', 'remove-account', true)
    );
    row.append(selectCell, identity, lifecycleCell, protocolExpiryCell, promoMethodsCell, riskCell, lastCell, sourceCell, actions);
    table.append(row);
  });
  setTableState('accountTable', 'accountEmpty', items.length, state.accounts.length ? '当前筛选条件下没有匹配的账号。' : '当前浏览器没有本机账号记录。请先回工作台导入或粘贴账号。');
  const riskCount = state.accounts.filter(item => ['rejected', 'cooldown', 'blocked', 'frozen'].includes(item.riskStatus)).length;
  const activeCount = state.accounts.filter(item => normalizeAccountLifecycle(item.lifecycle) === 'active').length;
  const archivedCount = state.accounts.length - activeCount;
  const total = Number(pagination.total ?? items.length);
  const accountCount = total === state.accounts.length ? `${total} 个账号` : `${total} / ${state.accounts.length} 个账号`;
  if ($('accountListMeta')) $('accountListMeta').textContent = `${accountCount} · 正常 ${activeCount} · 已归档 ${archivedCount} · 已选 ${manageSelectedAccounts().length} · ${riskCount} 个需要关注`;
  if ($('statAccounts')) $('statAccounts').textContent = text(state.accounts.length, '0');
  if ($('statAccountRisk')) $('statAccountRisk').textContent = riskCount ? `${riskCount} 个需要关注` : '暂无拒绝 / 冷却信号';
}

function renderFilteredAccounts() {
  const filtered = state.accounts.filter(accountMatchesFilters).sort(compareAccountsByAddedAt);
  const totalPages = Math.max(1, Math.ceil(filtered.length / ACCOUNT_PAGE_SIZE));
  state.accountPage = Math.min(Math.max(1, Number(state.accountPage) || 1), totalPages);
  const start = (state.accountPage - 1) * ACCOUNT_PAGE_SIZE;
  const pageItems = filtered.slice(start, start + ACCOUNT_PAGE_SIZE);
  renderAccounts(pageItems, {
    total: filtered.length,
    page: state.accountPage,
    totalPages,
    start,
    end: start + pageItems.length
  });
  renderAccountPagination(filtered.length, state.accountPage, totalPages, start, pageItems.length);
}

function renderAccountPagination(total, page, totalPages, start, pageLength) {
  const pagination = $('accountPagination');
  if (!pagination) return;
  const hasPagination = total > ACCOUNT_PAGE_SIZE;
  show(pagination, hasPagination);
  if (!hasPagination) return;
  const summary = $('accountPaginationSummary');
  if (summary) summary.textContent = `显示 ${start + 1}–${start + pageLength} / ${total} 个账号`;
  const pageStatus = $('accountPageStatus');
  if (pageStatus) pageStatus.textContent = `第 ${page} / ${totalPages} 页`;
  const previous = $('accountPrevPage');
  if (previous) previous.disabled = page <= 1;
  const next = $('accountNextPage');
  if (next) next.disabled = page >= totalPages;
}

function manageAccountCanBatch(item, now = Date.now()) {
  return Boolean(
    item?.raw
    && normalizeAccountLifecycle(item.lifecycle) === 'active'
    && (!item.exp || Number(item.exp) * 1000 > now)
    && !['cooldown', 'frozen'].includes(String(item.riskStatus || ''))
  );
}

function manageSelectedAccounts() {
  return state.accounts.filter(item => state.selectedAccountIds.has(item.id) && manageAccountCanBatch(item));
}
function manageFilteredBatchableAccounts() {
  return state.accounts.filter(item => item.lifecycle !== 'deleted').filter(accountMatchesFilters).filter(manageAccountCanBatch);
}

function manageDecodeJwtPart(value) {
  try {
    const normalized = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized + '='.repeat((4 - normalized.length % 4) % 4);
    return JSON.parse(decodeURIComponent(Array.from(window.atob(padded), character => `%${character.charCodeAt(0).toString(16).padStart(2, '0')}`).join('')));
  } catch (_) {
    return {};
  }
}

function manageJwtCandidate(value) {
  return String(value || '').match(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/)?.[0] || '';
}

function splitManageAccountText(raw, source = '手动粘贴') {
  const value = String(raw || '').trim();
  if (!value) return [];
  if (value.startsWith('{')) return [{text: value, source}];
  const matches = [...value.matchAll(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g)]
    .map(match => match[0])
    .filter((token, index, list) => list.indexOf(token) === index);
  if (matches.length) return matches.map((token, index) => ({text: token, source: `${source}#${index + 1}`}));
  return value.split(/\r?\n/).map(item => item.trim()).filter(Boolean).map((item, index) => ({text: item, source: `${source}#${index + 1}`}));
}

function parseManageAccountRaw(raw, source = '手动粘贴') {
  const value = String(raw || '').trim();
  if (!value) throw new Error('内容为空');
  let token = '';
  let email = '';
  let accountId = '';
  let kind = 'token';
  if (value.startsWith('{')) {
    let data;
    try { data = JSON.parse(value); } catch (_) { throw new Error('Session JSON 无法解析'); }
    token = String(data.accessToken || data.access_token || data.token || '').trim();
    const account = data.account && typeof data.account === 'object' ? data.account : {};
    email = String(data.user?.email || account.email || data.email || '').trim();
    accountId = String(account.id || data.account_id || '').trim();
    kind = 'session';
  }
  token = token || manageJwtCandidate(value);
  if (!token || token.split('.').length < 3) throw new Error('未识别到 Access Token');
  const claims = manageDecodeJwtPart(token.split('.')[1]);
  const auth = claims['https://api.openai.com/auth'] || {};
  email = email || String(claims.email || claims['https://api.openai.com/profile']?.email || '').trim();
  accountId = accountId || String(auth.chatgpt_account_id || claims.chatgpt_account_id || '').trim();
  const exp = Number(claims.exp || 0) || 0;
  const shortId = accountId ? accountId.slice(0, 8) : token.slice(0, 10);
  return {
    id: `acct_manage_${Date.now()}_${++state.accountSequence}`,
    raw: value,
    token,
    email,
    accountId,
    exp,
    kind,
    source: source || (kind === 'session' ? '粘贴 Session' : '粘贴 Token'),
    label: email || (accountId ? `账号 ${shortId}` : `${kind === 'session' ? 'Session' : 'Token'} ${shortId}`),
    promoStatus: 'unknown',
    promoReason: '',
    note: '',
    discounts: normalizeAccountDiscounts(),
    paymentMethods: {},
    checkoutProtocols: {},
    lifecycle: 'active',
    riskStatus: 'unknown',
    riskReason: '',
    cooldownUntil: 0,
    consecutiveDeclines: 0,
    consecutiveBlocks: 0,
    frozenAt: 0,
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

function manageAccountIdentity(item) {
  if (item?.accountId) return `id:${String(item.accountId).trim()}`;
  if (item?.email) return `email:${String(item.email).trim().toLowerCase()}`;
  return `token:${String(item?.token || item?.raw || '').trim().slice(0, 80)}`;
}

function upsertManageAccount(entry) {
  const identity = manageAccountIdentity(entry);
  const index = state.accounts.findIndex(item => manageAccountIdentity(item) === identity || (item.token && item.token === entry.token));
  if (index >= 0) {
    const previous = state.accounts[index];
    state.accounts[index] = {
      ...entry,
      ...previous,
      raw: entry.raw,
      token: entry.token,
      email: entry.email || previous.email,
      accountId: entry.accountId || previous.accountId,
      exp: entry.exp || previous.exp,
      kind: entry.kind || previous.kind,
      source: entry.source || previous.source,
      label: previous.label || entry.label,
      addedAt: accountTimestamp(previous.addedAt || entry.addedAt || Date.now()),
      updatedAt: Date.now()
    };
    return {entry: state.accounts[index], added: false};
  }
  state.accounts.push(entry);
  return {entry, added: true};
}

function persistManageAccounts() {
  const payload = {
    version: 1,
    activeId: state.activeAccountId || '',
    selectedIds: [...state.selectedAccountIds],
    accounts: state.accounts.map(item => ({
      id: item.id,
      raw: item.raw || '',
      token: item.token || '',
      email: item.email || '',
      accountId: item.accountId || '',
      exp: Number(item.exp || 0),
      kind: item.kind || 'token',
      source: item.source || '',
      label: item.label || '',
      cooldownUntil: Number(item.cooldownUntil || 0),
      lastDeclineAt: Number(item.lastDeclineAt || 0),
      consecutiveDeclines: Number(item.consecutiveDeclines || 0),
      consecutiveBlocks: Number(item.consecutiveBlocks || 0),
      frozenAt: Number(item.frozenAt || 0),
      promoStatus: item.promoStatus || 'unknown',
      promoReason: String(item.promoReason || '').slice(0, 240),
      note: String(item.note || '').slice(0, 500),
      discounts: normalizeAccountDiscounts(item.discounts),
      paymentMethods: accountMethods(item.paymentMethods),
      checkoutProtocols: accountProtocols(item.checkoutProtocols),
      lifecycle: normalizeAccountLifecycle(item.lifecycle),
      riskStatus: item.riskStatus || 'unknown',
      riskReason: String(item.riskReason || '').slice(0, 240),
      lastError: String(item.lastError || '').slice(0, 240),
      lastStatus: String(item.lastStatus || '').slice(0, 40),
      lastJobId: String(item.lastJobId || '').slice(0, 120),
      lastLinkType: String(item.lastLinkType || '').slice(0, 40),
      lastCountry: String(item.lastCountry || '').trim().toUpperCase().slice(0, 8),
      lastCurrency: String(item.lastCurrency || '').trim().toUpperCase().slice(0, 8),
      lastPaymentCountry: String(item.lastPaymentCountry || '').trim().toUpperCase().slice(0, 8),
      lastResultUrl: String(item.lastResultUrl || '').slice(0, 2000),
      lastCheckedAt: Number(item.lastCheckedAt || 0),
      addedAt: accountTimestamp(item.addedAt || item.createdAt || item.joinedAt || item.updatedAt || Date.now()),
      updatedAt: Number(item.updatedAt || Date.now())
    }))
  };
  try {
    localStorage.setItem(ACCOUNT_STORAGE_KEY, JSON.stringify(payload));
  } catch (error) {
    setMessage($('manageAccountStatus'), `本机保存失败：${error.message || error}`, true);
  }
}

function accountConfigPayload() {
  const stored = parseStorage(ACCOUNT_STORAGE_KEY) || {};
  return {
    format: 'pay153.manage.accounts',
    version: 2,
    exportedAt: new Date().toISOString(),
    activeId: state.activeAccountId || '',
    selectedIds: [...state.selectedAccountIds],
    accounts: Array.isArray(stored.accounts) ? stored.accounts : state.accounts.map(item => ({...item}))
  };
}

function downloadManageJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function exportManageAccounts() {
  if (!state.accounts.length) {
    setMessage($('manageAccountStatus'), '当前账号库没有可导出的账号', true);
    return;
  }
  downloadManageJson(`pay153-account-config-${new Date().toISOString().slice(0, 10)}.json`, accountConfigPayload());
  setMessage($('manageAccountStatus'), `已导出 ${state.accounts.length} 个账号及其备注、优惠、支付方式配置`);
}

function importManageAccountConfig(file) {
  if (!file) return;
  file.text().then(raw => {
    let payload;
    try { payload = JSON.parse(raw); } catch (_) { throw new Error('账号配置 JSON 无法解析'); }
    if (payload?.format !== 'pay153.manage.accounts' || !Array.isArray(payload.accounts)) {
      throw new Error('不是 PAY.153 账号配置文件');
    }
    let added = 0;
    let updated = 0;
    for (const source of payload.accounts) {
      if (!source || typeof source !== 'object') continue;
      const token = String(source.token || source.raw || '').trim();
      if (!token) continue;
      const parsed = parseManageAccountRaw(token, '账号配置导入');
      const restored = {
        ...parsed,
        ...source,
        id: String(source.id || parsed.id),
        raw: String(source.raw || parsed.raw || token),
        token,
        email: String(source.email || parsed.email || ''),
        accountId: String(source.accountId || parsed.accountId || ''),
        note: String(source.note || '').slice(0, 500),
        discounts: normalizeAccountDiscounts(source.discounts),
        paymentMethods: accountMethods(source.paymentMethods),
        checkoutProtocols: accountProtocols(source.checkoutProtocols),
        lifecycle: normalizeAccountLifecycle(source.lifecycle),
        updatedAt: Number(source.updatedAt || Date.now())
      };
      const result = upsertManageAccount(restored);
      if (result.added) added += 1; else updated += 1;
    }
    persistManageAccounts();
    refreshManageAccountState();
    setMessage($('manageAccountStatus'), `配置导入完成：新增 ${added}，更新 ${updated}；备注、优惠、支付方式已恢复`);
  }).catch(error => setMessage($('manageAccountStatus'), error.message || String(error), true));
}

function refreshManageAccountState() {
  const payload = parseStorage(ACCOUNT_STORAGE_KEY) || {};
  state.accounts = localAccountList();
  state.accountPage = 1;
  state.activeAccountId = String(payload.activeId || '');
  if (!state.accounts.some(item => item.id === state.activeAccountId && normalizeAccountLifecycle(item.lifecycle) === 'active')) {
    state.activeAccountId = state.accounts.find(item => normalizeAccountLifecycle(item.lifecycle) === 'active')?.id || '';
  }
  const storedSelectedIds = Array.isArray(payload.selectedIds) ? payload.selectedIds.map(id => String(id)) : [];
  const availableIds = new Set(state.accounts.filter(manageAccountCanBatch).map(item => item.id));
  state.selectedAccountIds = new Set(storedSelectedIds.filter(id => availableIds.has(id)));
  renderFilteredAccounts();
  updateManageAccountControls();
}

function importManageAccountItems(items) {
  let added = 0;
  let updated = 0;
  let failed = 0;
  const errors = [];
  Array.from(items || []).forEach(item => {
    try {
      const result = upsertManageAccount(parseManageAccountRaw(item.text, item.source));
      if (result.added) added += 1;
      else updated += 1;
      state.activeAccountId = result.entry.id;
    } catch (error) {
      failed += 1;
      errors.push(`${item.source || '内容'}：${error.message || error}`);
    }
  });
  persistManageAccounts();
  refreshManageAccountState();
  const parts = [];
  if (added) parts.push(`新增 ${added}`);
  if (updated) parts.push(`更新 ${updated}`);
  if (failed) parts.push(`失败 ${failed}`);
  setMessage($('manageAccountStatus'), parts.length ? `${parts.join(' · ')} · 已保存到本机` : errors[0] || '没有可导入的账号', Boolean(failed && !added && !updated));
}

function importManagePastedAccounts() {
  const raw = String($('manageAccountInput')?.value || '').trim();
  if (!raw) {
    setMessage($('manageAccountStatus'), '请先粘贴 AT 或 Session JSON', true);
    $('manageAccountInput')?.focus();
    return;
  }
  importManageAccountItems(splitManageAccountText(raw));
  $('manageAccountInput').value = '';
}

async function importManageAccountFiles(fileList) {
  const items = [];
  for (const file of Array.from(fileList || [])) {
    try {
      const value = String(await file.text() || '').trim();
      items.push(...splitManageAccountText(value, file.name));
    } catch (error) {
      items.push({text: '', source: `${file.name}（读取失败）`});
    }
  }
  importManageAccountItems(items);
}

function setManageAccountLifecycle(id, value) {
  const item = state.accounts.find(account => account.id === id);
  if (!item) return;
  const lifecycle = normalizeAccountLifecycle(value);
  if (item.lifecycle === lifecycle) return;
  item.lifecycle = lifecycle;
  item.updatedAt = Date.now();
  if (lifecycle === 'active') {
    if (!state.activeAccountId) state.activeAccountId = id;
  } else {
    state.selectedAccountIds.delete(id);
    if (state.activeAccountId === id) {
      state.activeAccountId = state.accounts.find(account => account.id !== id && account.lifecycle === 'active')?.id || '';
    }
  }
  persistManageAccounts();
  refreshManageAccountState();
  const message = lifecycle === 'active'
    ? `${maskLocalAccount(item.label)} 已恢复为正常，主面板会重新展示`
    : `${maskLocalAccount(item.label)} 已标记为${ACCOUNT_LIFECYCLE_LABELS[lifecycle]}，主面板将隐藏`;
  setMessage($('manageAccountStatus'), message);
}

function useManageAccount(id) {
  const item = state.accounts.find(account => account.id === id);
  if (!item) return;
  if (normalizeAccountLifecycle(item.lifecycle) !== 'active') {
    setMessage($('manageAccountStatus'), '已完成或已注销/删除账号不能设为工作台当前账号，请先恢复为正常。', true);
    return;
  }
  state.activeAccountId = id;
  persistManageAccounts();
  renderFilteredAccounts();
  setMessage($('manageAccountStatus'), `已选用 ${maskLocalAccount(item.label)}；返回工作台即可提交`, false);
}

function toggleManageAccountEmail(id) {
  const item = state.accounts.find(account => account.id === id);
  if (!item || !manageAccountEmail(item)) return;
  if (revealedManageEmailIds.has(id)) revealedManageEmailIds.delete(id);
  else revealedManageEmailIds.add(id);
  renderFilteredAccounts();
}

function removeManageAccount(id) {
  const item = state.accounts.find(account => account.id === id);
  if (!item || !window.confirm(`确认移除本机账号 ${maskLocalAccount(item.label)}？`)) return;
  state.accounts = state.accounts.filter(account => account.id !== id);
  state.selectedAccountIds.delete(id);
  revealedManageEmailIds.delete(id);
  if (state.activeAccountId === id) state.activeAccountId = state.accounts[0]?.id || '';
  persistManageAccounts();
  refreshManageAccountState();
  setMessage($('manageAccountStatus'), `已移除 ${maskLocalAccount(item.label)}`);
}

function clearManageAccounts() {
  if (state.accounts.length && !window.confirm('确认清空本机账号列表？Token 只会从当前浏览器 localStorage 移除。')) return;
  state.accounts = [];
  state.activeAccountId = '';
  state.selectedAccountIds.clear();
  revealedManageEmailIds.clear();
  persistManageAccounts();
  refreshManageAccountState();
  setMessage($('manageAccountStatus'), '已清空本机账号列表');
}

function exportManageAccountEmails() {
  const seen = new Set();
  const emails = state.accounts
    .map(item => manageAccountEmail(item))
    .map(value => String(value || '').trim())
    .filter(email => {
      const key = email.toLowerCase();
      if (!email || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  if (!emails.length) {
    setMessage($('manageAccountStatus'), '当前账号库没有可导出的邮箱名称', true);
    return;
  }
  const content = `${emails.join('\n')}\n`;
  const blob = new Blob([content], {type: 'text/plain;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `pay153-email-names-${new Date().toISOString().slice(0, 10)}.txt`;
  link.style.display = 'none';
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
  setMessage($('manageAccountStatus'), `已导出 ${emails.length} 个邮箱名称`);
}

function updateManageAccountControls() {
  const selected = manageSelectedAccounts();
  const detect = $('manageDetectSelected');
  if (detect) {
    detect.textContent = `批量检测选中（${selected.length}）`;
    detect.disabled = selected.length < 1 || state.detectionRunning;
  }
  const current = $('manageDetectCurrent');
  if (current) current.disabled = !state.accounts.some(item => item.id === state.activeAccountId && manageAccountCanBatch(item)) || state.detectionRunning;
  const selectAll = $('manageSelectAll');
  if (selectAll) {
    const available = manageFilteredBatchableAccounts();
    const allSelected = available.length > 0 && available.every(item => state.selectedAccountIds.has(item.id));
    selectAll.disabled = !available.length || allSelected || state.detectionRunning;
    selectAll.textContent = available.length ? `全选筛选结果（${available.length}）` : '全选筛选结果';
  }
  const clearSelection = $('manageClearSelection');
  if (clearSelection) {
    clearSelection.disabled = !selected.length || state.detectionRunning;
    clearSelection.textContent = selected.length ? `取消勾选（${selected.length}）` : '取消勾选';
  }
}

function clearManageAccountSelection(accountIds = null, message = '') {
  if (Array.isArray(accountIds)) {
    accountIds.forEach(id => state.selectedAccountIds.delete(String(id)));
  } else {
    state.selectedAccountIds.clear();
  }
  persistManageAccounts();
  renderFilteredAccounts();
  updateManageAccountControls();
  if (message) setMessage($('manageAccountStatus'), message);
}

function manageProxyCandidates(kind) {
  const enabled = state.proxies.filter(item => item.enabled !== false);
  const preferred = enabled.filter(item => kind === 'exit' ? item.pool_kind === 'exit' : item.pool_kind !== 'exit');
  return preferred.length ? preferred : enabled;
}

function renderManageProxyOptions() {
  [['manageDetectEntryPool', 'entry'], ['manageDetectExitPool', 'exit']].forEach(([id, kind]) => {
    const select = $(id);
    if (!select) return;
    const current = select.value;
    select.replaceChildren();
    const candidates = manageProxyCandidates(kind);
    if (!candidates.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = kind === 'exit' ? '先维护支付出口池' : '先维护入口代理池';
      select.append(option);
      return;
    }
    candidates.forEach(item => {
      const option = document.createElement('option');
      option.value = String(item.id);
      option.textContent = `${text(item.name)} · ${text(item.country, '??')} · ${item.pool_kind === 'exit' ? '出口' : '入口'} · ${item.proxy_count || 0} 条`;
      option.selected = String(item.id) === current;
      select.append(option);
    });
    if (!candidates.some(item => String(item.id) === current)) {
      const saved = select.dataset.savedValue;
      select.value = (saved && candidates.some(item => String(item.id) === saved)) ? saved : String(candidates[0].id);
    }
  });
  const hint = $('manageDetectionStatus');
  if (hint && !state.detectionRunning) {
    hint.textContent = state.proxies.length ? '检测任务会使用已保存代理池，不会修改代理配置。' : '请先在“代理池”模块保存入口和支付出口代理。';
  }
  syncManageDetectionProxyMode();
}

function manageDetectionProxyMode() {
  return $('manageDetectProxyMode')?.value || 'pool';
}

function syncManageDetectionProxyMode() {
  const mode = manageDetectionProxyMode();
  show($('manageDetectionPoolFields'), mode === 'pool');
  show($('manageDetectionLocalFields'), mode === 'local');
  show($('manageDetectionManualFields'), mode === 'manual');
  const hint = $('manageDetectionStatus');
  if (!hint || state.detectionRunning) return;
  if (mode === 'local') {
    hint.textContent = '本地代理会同时用于入口和支付出口，仅用于本次检测。';
  } else if (mode === 'manual') {
    hint.textContent = '手工代理列表仅用于本次检测；已保存代理池可在下方代理池模块编辑。';
  } else {
    hint.textContent = state.proxies.length ? '检测任务会使用已保存代理池，不会修改代理配置。' : '请先在“代理池”模块保存入口和支付出口代理。';
  }
  persistManageDetectionProxyConfig();
}

function setManageDetectionStatus(value, isError = false) {
  setMessage($('manageDetectionStatus'), value, isError);
}

function positiveInteger(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.max(1, Math.floor(parsed)) : fallback;
}

function manageDetectionWorkerLimit() {
  return positiveInteger(state.taskLimits?.workers, DEFAULT_TASK_LIMITS.workers);
}

function clampManageDetectionConcurrency(value) {
  return Math.min(
    manageDetectionWorkerLimit(),
    Math.max(1, positiveInteger(value, DEFAULT_MANAGE_DETECTION_CONCURRENCY))
  );
}

function manageDetectionConcurrencyLimit() {
  const input = $('manageDetectConcurrency');
  const requested = Number(input?.value);
  const value = clampManageDetectionConcurrency(
    Number.isFinite(requested) && requested > 0 ? requested : state.detectionConcurrency
  );
  state.detectionConcurrency = value;
  if (input) input.value = String(value);
  return value;
}

function syncManageDetectionConcurrency() {
  const input = $('manageDetectConcurrency');
  const value = clampManageDetectionConcurrency(state.detectionConcurrency);
  state.detectionConcurrency = value;
  if (input) {
    input.max = String(manageDetectionWorkerLimit());
    input.value = String(value);
  }
  const note = $('manageDetectionConcurrencyNote');
  if (note) {
    const recommended = Math.min(
      positiveInteger(state.taskLimits?.perIp, DEFAULT_TASK_LIMITS.perIp),
      manageDetectionWorkerLimit()
    );
    note.textContent = `当前并发 ${value}；服务端 worker 上限 ${manageDetectionWorkerLimit()}，单 IP 每分钟最多创建 ${positiveInteger(state.taskLimits?.perIp, DEFAULT_TASK_LIMITS.perIp)} 个任务，建议并发 ${recommended}。`;
  }
}

function loadManageDetectionConcurrencyPreference() {
  try {
    const stored = Number(localStorage.getItem(MANAGE_DETECTION_CONCURRENCY_KEY));
    if (Number.isFinite(stored) && stored > 0) state.detectionConcurrency = stored;
  } catch (_) {
    // 浏览器禁用 localStorage 时继续使用默认并发数。
  }
}

function persistManageDetectionConcurrency() {
  try {
    localStorage.setItem(MANAGE_DETECTION_CONCURRENCY_KEY, String(state.detectionConcurrency));
  } catch (_) {
    // 并发设置不影响检测任务本身，存储失败时仅对当前页面生效。
  }
}

function loadManageDetectionProxyConfig() {
  try {
    const raw = localStorage.getItem(MANAGE_DETECTION_PROXY_CONFIG_KEY);
    const saved = raw ? JSON.parse(raw) : null;
    if (saved && typeof saved === 'object') return saved;
  } catch (_) {
    // 读取失败时使用表单当前值。
  }
  return null;
}

function persistManageDetectionProxyConfig() {
  const config = currentManageDetectionProxyConfig();
  try {
    localStorage.setItem(MANAGE_DETECTION_PROXY_CONFIG_KEY, JSON.stringify(config));
  } catch (_) {
    // 代理来源记忆仅影响默认填充，存储失败时不影响检测任务。
  }
}

function currentManageDetectionProxyConfig() {
  return {
    mode: $('manageDetectProxyMode')?.value || 'pool',
    entryPoolId: String($('manageDetectEntryPool')?.value || ''),
    exitPoolId: String($('manageDetectExitPool')?.value || ''),
    localProxy: String($('manageDetectLocalProxy')?.value || ''),
    manualEntryProxy: String($('manageDetectManualEntryProxy')?.value || ''),
    manualExitProxy: String($('manageDetectManualExitProxy')?.value || '')
  };
}

function applyManageDetectionProxyConfig(config) {
  if (!config || typeof config !== 'object') return;
  const mode = $('manageDetectProxyMode');
  if (mode && config.mode) mode.value = config.mode;
  if (config.entryPoolId !== undefined && config.entryPoolId !== null) {
    const select = $('manageDetectEntryPool');
    if (select) select.dataset.savedValue = config.entryPoolId;
  }
  if (config.exitPoolId !== undefined && config.exitPoolId !== null) {
    const select = $('manageDetectExitPool');
    if (select) select.dataset.savedValue = config.exitPoolId;
  }
  const localProxy = $('manageDetectLocalProxy');
  if (localProxy && config.localProxy) localProxy.value = config.localProxy;
  const manualEntry = $('manageDetectManualEntryProxy');
  if (manualEntry && config.manualEntryProxy) manualEntry.value = config.manualEntryProxy;
  const manualExit = $('manageDetectManualExitProxy');
  if (manualExit && config.manualExitProxy) manualExit.value = config.manualExitProxy;
  syncManageDetectionProxyMode();
}


function updateManageDetectionConcurrency() {
  manageDetectionConcurrencyLimit();
  persistManageDetectionConcurrency();
  syncManageDetectionConcurrency();
}

async function loadManageTaskLimits() {
  try {
    const response = await api('/api/config');
    const limits = response.task_limits || {};
    state.taskLimits = {
      perIp: positiveInteger(limits.per_ip_rpm, DEFAULT_TASK_LIMITS.perIp),
      global: positiveInteger(limits.global_rpm, DEFAULT_TASK_LIMITS.global),
      workers: positiveInteger(limits.workers, DEFAULT_TASK_LIMITS.workers)
    };
  } catch (_) {
    state.taskLimits = {...DEFAULT_TASK_LIMITS};
  }
  syncManageDetectionConcurrency();
}

function manageDetectionTerminal(status) {
  return ['done', 'error', 'cancelled'].includes(String(status || ''));
}

function manageDetectionStatusLabel(status) {
  return {
    pending: '等待槽位',
    creating: '创建中',
    waiting: '等待创建窗口',
    queued: '排队中',
    running: '检测中',
    done: '完成',
    error: '失败',
    cancelled: '已停止'
  }[status] || '等待';
}

function renderManageDetectionJobs() {
  const list = $('manageDetectionJobs');
  if (!list) return;
  list.replaceChildren();
  list.hidden = !state.detectionJobs.length;
  state.detectionJobs.forEach(job => {
    const row = document.createElement('div');
    const stateClass = manageDetectionTerminal(job.status)
      ? job.status
      : job.status === 'pending' ? 'pending' : 'running';
    row.className = `manage-detection-job is-${stateClass}`;
    const main = document.createElement('div');
    main.className = 'manage-detection-job-main';
    const title = document.createElement('b');
    title.textContent = maskLocalAccount(job.label);
    const detail = document.createElement('small');
    detail.textContent = job.error || job.text || '等待检测';
    const progress = document.createElement('div');
    progress.className = 'manage-detection-progress';
    const progressValue = document.createElement('i');
    progressValue.style.width = `${Math.max(0, Math.min(100, Number(job.percent) || 0))}%`;
    progress.append(progressValue);
    main.append(title, detail, progress);
    const side = document.createElement('span');
    side.className = 'manage-detection-job-status';
    side.textContent = manageDetectionStatusLabel(job.status);
    row.append(main, side);
    list.append(row);
  });
}

function manageDetectionPayload(account, entryProxies, exitProxies) {
  return {
    token: account.raw || account.token,
    plan: 'plus',
    link_type: 'paypal',
    country: 'DE',
    currency: 'EUR',
    entry_proxies: entryProxies,
    exit_proxies: exitProxies,
    billing_profile: null,
    billing_selection: null,
    retry_count: 2,
    use_promo: false,
    promo_campaign: '',
    promo_code: '',
    workspace_name: '',
    workspace_id: '',
    seat_quantity: 5,
    price_interval: 'month',
    credit_quantity: 13,
    ideal_bank: '',
    pix_tax_id: '',
    pix_auto_kind: 'cpf',
    detection_only: true,
    detection_fixed_de: true
  };
}

async function revealManageProxyPool(id) {
  const response = await api(`/api/manage/proxy-pools/${encodeURIComponent(id)}?reveal=1`);
  const item = response.item || response;
  const proxies = Array.isArray(item.proxies) ? item.proxies.filter(Boolean) : [];
  if (!proxies.length) throw new Error(`代理池“${text(item.name, id)}”没有可用线路`);
  return proxies;
}

function manageDetectionProxyLines(value) {
  return String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean);
}

function validateManageDetectionProxyLine(value, label, index) {
  const raw = String(value || '').trim();
  if (/^[a-z][a-z\d+.-]*:\/\//i.test(raw)) {
    let parsed;
    try { parsed = new window.URL(raw); } catch (_) { parsed = null; }
    const protocols = ['http:', 'https:', 'socks4:', 'socks5:', 'socks5h:'];
    if (!parsed || !parsed.hostname || !protocols.includes(parsed.protocol)) {
      throw new Error(`${label}第 ${index + 1} 行不是有效的代理 URL`);
    }
    return raw;
  }
  if (!/^[^:\s]+:\d{1,5}(?::.*)?$/.test(raw)) {
    throw new Error(`${label}第 ${index + 1} 行请填写 URL 或 host:port:用户名:密码`);
  }
  return raw;
}

function validateManageDetectionProxyLines(values, label) {
  if (!values.length) throw new Error(`请填写${label}`);
  return values.map((value, index) => validateManageDetectionProxyLine(value, label, index));
}

async function resolveManageDetectionProxies() {
  const mode = manageDetectionProxyMode();
  if (mode === 'local') {
    const localProxy = String($('manageDetectLocalProxy')?.value || '').trim();
    const [proxy] = validateManageDetectionProxyLines([localProxy], '本地代理');
    return {entryProxies: [proxy], exitProxies: [proxy], label: '本地代理'};
  }
  if (mode === 'manual') {
    const entryProxies = validateManageDetectionProxyLines(
      manageDetectionProxyLines($('manageDetectManualEntryProxy')?.value),
      '入口代理列表'
    );
    const exitProxies = validateManageDetectionProxyLines(
      manageDetectionProxyLines($('manageDetectManualExitProxy')?.value),
      '支付出口列表'
    );
    return {entryProxies, exitProxies, label: '手工代理列表'};
  }
  const entryPoolId = $('manageDetectEntryPool')?.value || '';
  const exitPoolId = $('manageDetectExitPool')?.value || '';
  if (!entryPoolId || !exitPoolId) {
    throw new Error('协议检测需要入口代理池和支付出口池，请先在代理池模块保存配置。');
  }
  const [entryProxies, exitProxies] = await Promise.all([
    revealManageProxyPool(entryPoolId),
    revealManageProxyPool(exitPoolId)
  ]);
  return {entryProxies, exitProxies, label: '已保存代理池'};
}

function manageRecordDetectionOutcome(job, data) {
  const item = state.accounts.find(account => account.id === job.accountId);
  if (!item) return;
  const result = data?.result && typeof data.result === 'object' ? data.result : {};
  const now = Date.now();
  item.lastCheckedAt = now;
  item.lastJobId = String(job.jobId || '').slice(0, 120);
  item.lastStatus = String(data?.status || job.status || '').slice(0, 40);
  item.lastLinkType = 'paypal';
  item.lastCountry = String(result.checkout_country || result.checkout_protocol_country || 'DE').trim().toUpperCase().slice(0, 8);
  item.lastCurrency = String(result.checkout_currency || result.checkout_protocol_currency || 'EUR').trim().toUpperCase().slice(0, 8);
  item.lastError = String(data?.error || '').slice(0, 240);
  if (data?.status === 'done') {
    const protocol = normalizeAccountProtocol(result.checkout_protocol);
    const country = String(result.checkout_protocol_country || result.checkout_country || 'DE').trim().toUpperCase().slice(0, 8);
    const currency = String(result.checkout_protocol_currency || result.checkout_currency || 'EUR').trim().toUpperCase().slice(0, 8);
    item.checkoutProtocols = accountProtocols(item.checkoutProtocols);
    const key = `paypal:${country}:${currency}`;
    const checkedAt = normalizeAccountProtocolCheckedAt(result.checkout_protocol_checked_at, now);
    const previous = item.checkoutProtocols[key];
    const previousIsKnown = previous && ['oaics', 'cs'].includes(previous.protocol);
    const preservePrevious = previousIsKnown && (
      protocol === 'unknown'
      || Number(previous.checkedAt || 0) > checkedAt
    );
    if (!preservePrevious) {
      item.checkoutProtocols[key] = {
        protocol,
        country,
        currency,
        checkedAt,
        baseline: Boolean(result.checkout_protocol_baseline),
        source: String(result.checkout_protocol_source || 'manage').slice(0, 40),
        paymentMethods: accountMethods(result.oaics_payment_method_types || result.payment_method_types || [])
      };
    }
    item.paymentMethods = accountMethods(item.paymentMethods);
    if (protocol === 'oaics' && result.oaics_paypal_available === true) item.paymentMethods.paypal = 'supported';
    item.riskStatus = item.riskStatus === 'frozen' ? 'frozen' : 'clear';
    item.riskReason = item.riskStatus === 'frozen' ? item.riskReason : '最近一次协议检测完成，未发现拒绝信号';
    item.lastError = '';
    const effectiveProtocol = preservePrevious ? previous.protocol : protocol;
    job.text = `协议 ${effectiveProtocol.toUpperCase()} · ${country}/${currency}`;
  } else {
    const error = String(data?.error || job.error || '协议检测失败');
    item.riskStatus = /account_(?:blocked|banned|suspended|restricted)|账号.*(?:封禁|冻结|拒绝)/i.test(error) ? 'blocked' : item.riskStatus;
    item.riskReason = error.slice(0, 240);
    item.lastError = error.slice(0, 240);
  }
  item.updatedAt = now;
  persistManageAccounts();
  refreshManageAccountState();
}

async function createManageDetectionJob(job, body) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    job.status = 'creating';
    job.text = '正在提交协议检测';
    renderManageDetectionJobs();
    const response = await fetch('/api/checkout-detect', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 429) {
      const retryAfter = Math.max(1, Number(response.headers?.get?.('Retry-After') || payload.retry_after) || 60);
      job.status = 'waiting';
      job.text = `创建频率受限，${retryAfter} 秒后重试`;
      renderManageDetectionJobs();
      await new Promise(resolve => window.setTimeout(resolve, retryAfter * 1000));
      continue;
    }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    job.jobId = String(payload.job_id || '');
    if (!job.jobId) throw new Error('服务未返回检测任务 ID');
    job.status = 'queued';
    job.percent = Number(payload.queue_position) > 0 ? 2 : 3;
    job.text = Number(payload.queue_position) > 0 ? `已排队 · 前方 ${payload.queue_position - 1} 个任务` : '等待检测';
    renderManageDetectionJobs();
    return;
  }
  throw new Error('连续多次触发创建频率限制，请稍后再试');
}

async function pollManageDetectionJob(job) {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    const data = await api(`/api/checkout-progress?job_id=${encodeURIComponent(job.jobId)}`);
    job.status = String(data.status || job.status);
    job.percent = Number(data.percent) || 0;
    job.text = String(data.text || '正在检测');
    job.error = String(data.error || '');
    if (manageDetectionTerminal(job.status)) {
      if (job.status === 'error') job.error = job.error || '协议检测失败';
      manageRecordDetectionOutcome(job, data);
      renderManageDetectionJobs();
      return;
    }
    renderManageDetectionJobs();
    await new Promise(resolve => window.setTimeout(resolve, 1200));
  }
  throw new Error('协议检测轮询超时');
}

async function runManageDetectionJob(job, entryProxies, exitProxies) {
  const account = state.accounts.find(item => item.id === job.accountId);
  if (!account) return;
  try {
    await createManageDetectionJob(job, manageDetectionPayload(account, entryProxies, exitProxies));
    await pollManageDetectionJob(job);
  } catch (error) {
    job.status = 'error';
    job.percent = 100;
    job.error = error.message || String(error);
    job.text = '检测失败';
    manageRecordDetectionOutcome(job, {status: 'error', error: job.error});
    renderManageDetectionJobs();
  }
}

async function runManageDetectionPool(entryProxies, exitProxies) {
  let nextIndex = 0;
  const active = new Set();
  const launchAvailable = () => {
    const limit = manageDetectionConcurrencyLimit();
    while (nextIndex < state.detectionJobs.length && active.size < limit) {
      const job = state.detectionJobs[nextIndex++];
      const task = runManageDetectionJob(job, entryProxies, exitProxies).finally(() => active.delete(task));
      active.add(task);
    }
  };

  while (nextIndex < state.detectionJobs.length || active.size) {
    launchAvailable();
    if (!active.size) continue;
    await Promise.race(active);
  }
}

async function startManageProtocolDetection(accountIds) {
  if (state.detectionRunning) return;
  const accounts = state.accounts.filter(item => accountIds.includes(item.id) && manageAccountCanBatch(item));
  if (!accounts.length) {
    setManageDetectionStatus('请先选择一个有效账号，或点击“使用”设为当前账号。', true);
    return;
  }
  let detectionProxies;
  try {
    detectionProxies = await resolveManageDetectionProxies();
  } catch (error) {
    setManageDetectionStatus(error.message || String(error), true);
    return;
  }
  state.detectionRunning = true;
  state.detectionJobs = accounts.map(account => ({
    accountId: account.id,
    label: account.label || account.email || account.accountId,
    jobId: '',
    status: 'pending',
    percent: 0,
    text: '等待并发槽位',
    error: ''
  }));
  renderManageDetectionJobs();
  updateManageAccountControls();
  const concurrency = manageDetectionConcurrencyLimit();
  setManageDetectionStatus(`正在检测 ${accounts.length} 个账号（并发 ${concurrency}），使用${detectionProxies.label}；结果会自动写回本机账号库。`);
  try {
    await runManageDetectionPool(detectionProxies.entryProxies, detectionProxies.exitProxies);
    const done = state.detectionJobs.filter(job => job.status === 'done').length;
    const failed = state.detectionJobs.length - done;
    setManageDetectionStatus(`协议检测结束：${done} 个完成${failed ? ` · ${failed} 个失败` : ''}。` , Boolean(failed));
  } catch (error) {
    setManageDetectionStatus(error.message || String(error), true);
  } finally {
    clearManageAccountSelection(accountIds);
    state.detectionRunning = false;
    updateManageAccountControls();
    renderManageDetectionJobs();
  }
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
  renderManageProxyOptions();
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
  refreshManageAccountState();
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
    await Promise.all([loadSummary(), loadAccounts(), loadProxies(), loadBilling(), loadAddresses(), loadAsn(), loadSuccesses(), loadLogs(), loadManageTaskLimits()]);
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
  $('accountTable').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const id = button.closest('tr')?.dataset.id;
    if (!id) return;
    if (button.dataset.action === 'use-account') useManageAccount(id);
    if (button.dataset.action === 'edit-account') openManageAccountEditor(id);
    if (button.dataset.action === 'toggle-email') toggleManageAccountEmail(id);
    if (button.dataset.action === 'detect-account') void startManageProtocolDetection([id]);
    if (button.dataset.action === 'remove-account') removeManageAccount(id);
  });
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

function openManageAccountEditor(id) {
  const item = state.accounts.find(account => account.id === id);
  if (!item) return;
  const modal = $('accountEditModal');
  modal.hidden = false;
  $('accountEditId').value = id;
  $('accountEditTitle').textContent = `编辑账号 · ${maskLocalAccount(item.label || item.email || item.accountId)}`;
  $('accountEditNote').value = item.note || '';
  const discounts = normalizeAccountDiscounts(item.discounts);
  $('accountDiscountPercent').value = discounts.global.percent || '';
  $('accountDiscountFixed').value = discounts.global.fixed || '';
  $('accountDiscountRegions').value = discounts.regions.map(region => [region.country, region.currency, region.percent || '', region.fixed || ''].join(',')).join('\n');
  const methods = item.paymentMethods || {};
  qsa('[data-account-method]', modal).forEach(input => { input.checked = methods[input.dataset.accountMethod] === 'supported'; });
}

function closeManageAccountEditor() { if ($('accountEditModal')) $('accountEditModal').hidden = true; }

function saveManageAccountEditor() {
  const item = state.accounts.find(account => account.id === $('accountEditId').value);
  if (!item) return;
  const regions = $('accountDiscountRegions').value.split(/\r?\n/).map(line => {
    const [country, currency, percent, fixed] = line.split(',').map(value => String(value || '').trim());
    return {country, currency, percent: Number(percent || 0), fixed: Number(fixed || 0)};
  }).filter(region => region.country || region.currency);
  item.note = String($('accountEditNote').value || '').trim().slice(0, 500);
  item.discounts = normalizeAccountDiscounts({global: {percent: $('accountDiscountPercent').value, fixed: $('accountDiscountFixed').value}, regions});
  item.paymentMethods = accountMethods(item.paymentMethods);
  qsa('[data-account-method]', $('accountEditModal')).forEach(input => { item.paymentMethods[input.dataset.accountMethod] = input.checked ? 'supported' : 'unknown'; });
  item.updatedAt = Date.now();
  persistManageAccounts(); refreshManageAccountState(); closeManageAccountEditor();
  setMessage($('manageAccountStatus'), '账号备注、优惠和支付方式已保存');
}

function bindEvents() {
  $('accountEditClose')?.addEventListener('click', closeManageAccountEditor);
  $('accountEditSave')?.addEventListener('click', saveManageAccountEditor);
  $('accountEditModal')?.addEventListener('click', event => { if (event.target.id === 'accountEditModal') closeManageAccountEditor(); });
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
  ['accountQuery', 'accountLifecycleFilter', 'accountProtocolFilter', 'accountPromoFilter', 'accountRiskFilter', 'accountMethodFilter'].forEach((id) => {
    const resetAccountPage = () => {
      state.accountPage = 1;
      renderFilteredAccounts();
    };
    $(id)?.addEventListener('input', resetAccountPage);
    $(id)?.addEventListener('change', resetAccountPage);
  });
  $('accountPrevPage')?.addEventListener('click', () => {
    if (state.accountPage <= 1) return;
    state.accountPage -= 1;
    renderFilteredAccounts();
  });
  $('accountNextPage')?.addEventListener('click', () => {
    const total = state.accounts.filter(accountMatchesFilters).length;
    const totalPages = Math.max(1, Math.ceil(total / ACCOUNT_PAGE_SIZE));
    if (state.accountPage >= totalPages) return;
    state.accountPage += 1;
    renderFilteredAccounts();
  });
  $('manageImportPaste')?.addEventListener('click', importManagePastedAccounts);
  $('manageAccountFileInput')?.addEventListener('change', async (event) => {
    try { await importManageAccountFiles(event.target.files); }
    finally { event.target.value = ''; }
  });
  $('manageSelectAll')?.addEventListener('click', () => {
    manageFilteredBatchableAccounts().forEach(item => state.selectedAccountIds.add(item.id));
    persistManageAccounts();
    renderFilteredAccounts();
    updateManageAccountControls();
  });
  $('manageClearSelection')?.addEventListener('click', () => {
    clearManageAccountSelection(null, '已取消全部账号勾选');
  });
  $('manageExportEmails')?.addEventListener('click', exportManageAccountEmails);
  $('manageExportAccounts')?.addEventListener('click', exportManageAccounts);
  $('manageAccountConfigInput')?.addEventListener('change', (event) => {
    importManageAccountConfig(event.target.files?.[0]);
    event.target.value = '';
  });
  $('manageClearAll')?.addEventListener('click', clearManageAccounts);
  $('manageDetectCurrent')?.addEventListener('click', () => {
    if (state.activeAccountId) void startManageProtocolDetection([state.activeAccountId]);
  });
  $('manageDetectSelected')?.addEventListener('click', () => {
    void startManageProtocolDetection(manageSelectedAccounts().map(item => item.id));
  });
  $('manageDetectConcurrency')?.addEventListener('input', updateManageDetectionConcurrency);
  $('manageDetectConcurrency')?.addEventListener('change', updateManageDetectionConcurrency);
  $('manageDetectProxyMode')?.addEventListener('change', syncManageDetectionProxyMode);
  $('manageDetectEntryPool')?.addEventListener('change', persistManageDetectionProxyConfig);
  $('manageDetectExitPool')?.addEventListener('change', persistManageDetectionProxyConfig);
  $('manageDetectLocalProxy')?.addEventListener('input', persistManageDetectionProxyConfig);
  $('manageDetectManualEntryProxy')?.addEventListener('input', persistManageDetectionProxyConfig);
  $('manageDetectManualExitProxy')?.addEventListener('input', persistManageDetectionProxyConfig);
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
  loadManageDetectionConcurrencyPreference();
  syncManageDetectionConcurrency();
  $('logDay').value = new Date().toISOString().slice(0, 10);
  bindEvents();
  applyManageDetectionProxyConfig(loadManageDetectionProxyConfig());
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
    const requestedSection = String(window.location.hash || '').replace(/^#/, '');
    if (requestedSection && qsa('.manage-nav-item').some(button => button.dataset.section === requestedSection)) {
      activateSection(requestedSection);
    }
  } catch (error) {
    showLogin(error.message);
  }
}

bootstrap();
