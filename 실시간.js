/* ──────────────────────────────────────────────────────────────
   실시간.js — 인도 펀드 대시보드
   페이지 열 때마다 차트(NIFTY·Sensex)·기술지표·뉴스신호를 실시간 갱신.
   * NAV(기준가) 차트는 공공데이터포털 기반이라 업데이트.py가 채움 (여기서 건드리지 않음)
   * P/E·손절선 거리는 가격 API로 못 구함 → 정적 유지 + 안내
   원칙: 어떤 호출이 실패해도 화면이 깨지거나 빈칸이 되지 않는다.
   ────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  const PROXIES = [
    (u) => `https://corsproxy.io/?${encodeURIComponent(u)}`,
    (u) => `https://api.allorigins.win/raw?url=${encodeURIComponent(u)}`,
    (u) => `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(u)}`,
  ];

  async function proxyText(url, timeoutMs) {
    for (const make of PROXIES) {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), timeoutMs || 8000);
        const r = await fetch(make(url), { signal: ctrl.signal });
        clearTimeout(t);
        if (!r.ok) continue;
        const txt = await r.text();
        if (txt && txt.length > 0) return txt;
      } catch (e) {}
    }
    return null;
  }
  async function proxyJSON(url, timeoutMs) {
    const txt = await proxyText(url, timeoutMs);
    if (!txt) return null;
    try { return JSON.parse(txt); } catch (e) { return null; }
  }

  async function fetchRange(ticker, interval, range, labelMode) {
    const url = `https://query2.finance.yahoo.com/v8/finance/chart/${ticker}?interval=${interval}&range=${range}`;
    const j = await proxyJSON(url, 9000);
    try {
      const res = j.chart.result[0];
      const ts = res.timestamp || [];
      const closes = res.indicators.quote[0].close || [];
      const labels = [], prices = [];
      for (let i = 0; i < ts.length; i++) {
        if (closes[i] == null) continue;
        const dt = new Date(ts[i] * 1000);
        labels.push(labelMode === 'time'
          ? dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
          : (dt.getMonth() + 1) + '/' + dt.getDate());
        prices.push(+closes[i].toFixed(2));
      }
      if (prices.length < 2) return null;
      return { labels, prices, meta: res.meta };
    } catch (e) { return null; }
  }

  const RANGE_DEFS = [
    { key: 'd1',  interval: '5m',  range: '1d',  mode: 'time' },
    { key: 'd5',  interval: '1d',  range: '5d',  mode: 'date' },
    { key: 'd30', interval: '1d',  range: '1mo', mode: 'date' },
    { key: 'mo3', interval: '1d',  range: '3mo', mode: 'date' },
    { key: 'mo6', interval: '1wk', range: '6mo', mode: 'date' },
    { key: 'yr1', interval: '1wk', range: '1y',  mode: 'date' },
  ];

  function findActivePeriod(prefix) {
    const tabs = document.querySelectorAll(`#${prefix}-tabs .period-tab.active`);
    if (!tabs.length) return null;
    const oc = tabs[0].getAttribute('onclick') || '';
    const m = oc.match(/'(d1|d5|d30|mo3|mo6|yr1)'/);
    return m ? m[1] : null;
  }

  async function refreshChart(canvasId, ticker, tabPrefix) {
    const c = window._charts && window._charts[canvasId];
    if (!c) return null;
    let lastMeta = null;
    await Promise.allSettled(RANGE_DEFS.map(async (d) => {
      const got = await fetchRange(ticker, d.interval, d.range, d.mode);
      if (got) {
        c.data[d.key] = { labels: got.labels, prices: got.prices };
        if (d.key === 'yr1' && got.meta) lastMeta = got.meta;
      }
    }));
    try {
      const key = findActivePeriod(tabPrefix) || 'd1';
      if (c.data[key] && typeof makeDatasets === 'function') {
        c.inst.data.labels = c.data[key].labels;
        // 인도펀드 makeDatasets 시그니처: (prices, key, name, sl)
        c.inst.data.datasets = makeDatasets(c.data[key].prices, key, c.data.name, c.data.sl);
        c.inst.update();
      }
    } catch (e) {}
    return lastMeta;
  }

  function setBadge(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'badge ' + cls;
  }

  function calcRSI(prices, n) {
    if (prices.length < n + 1) return null;
    let gain = 0, loss = 0;
    for (let i = prices.length - n; i < prices.length; i++) {
      const diff = prices[i] - prices[i - 1];
      if (diff >= 0) gain += diff; else loss -= diff;
    }
    if (loss === 0) return 100;
    const rs = (gain / n) / (loss / n);
    return 100 - 100 / (1 + rs);
  }
  function sma(prices, n) {
    if (prices.length < n) return null;
    return prices.slice(prices.length - n).reduce((a, b) => a + b, 0) / n;
  }

  function updateTechnicals(meta, weeklyPrices) {
    if (!weeklyPrices || weeklyPrices.length < 6) return;
    const cur = weeklyPrices[weeklyPrices.length - 1];

    const rsi = calcRSI(weeklyPrices, 14);
    if (rsi != null) {
      let lbl, cls;
      if (rsi >= 75) { lbl = '과열'; cls = 'badge-r'; }
      else if (rsi >= 45) { lbl = '중립'; cls = 'badge-b'; }
      else if (rsi >= 30) { lbl = '약세'; cls = 'badge-y'; }
      else { lbl = '과매도 — 반등 기대'; cls = 'badge-g'; }
      setBadge('ind-rsi', `RSI ${rsi.toFixed(1)} — ${lbl}`, cls);
    }

    const ma5 = sma(weeklyPrices, 5), ma13 = sma(weeklyPrices, 13), ma26 = sma(weeklyPrices, 26);
    if (ma5 != null && ma13 != null && ma26 != null) {
      let lbl, cls;
      if (cur > ma5 && ma5 > ma13 && ma13 > ma26) { lbl = '정배열(상승)'; cls = 'badge-g'; }
      else if (cur < ma5 && ma5 < ma13 && ma13 < ma26) { lbl = '역배열(하락)'; cls = 'badge-r'; }
      else { lbl = '혼조'; cls = 'badge-y'; }
      setBadge('ind-ma', lbl, cls);
    }

    if (weeklyPrices.length >= 5) {
      const past = weeklyPrices[weeklyPrices.length - 5];
      const mom = (cur - past) / past * 100;
      const arrow = mom >= 0 ? '▲' : '▼';
      const cls = mom >= 2 ? 'badge-g' : mom <= -2 ? 'badge-r' : 'badge-y';
      setBadge('ind-mom', `${arrow} ${Math.abs(mom).toFixed(1)}% (4주 변화)`, cls);
    }

    // 변동성 (최근 12주 주간수익률 표준편차)
    if (weeklyPrices.length >= 13) {
      const rets = [];
      for (let i = weeklyPrices.length - 12; i < weeklyPrices.length; i++) {
        rets.push((weeklyPrices[i] - weeklyPrices[i - 1]) / weeklyPrices[i - 1] * 100);
      }
      const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
      const variance = rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length;
      const std = Math.sqrt(variance);
      let lbl, cls;
      if (std < 1.0) { lbl = '낮음'; cls = 'badge-g'; }
      else if (std < 2.0) { lbl = '보통'; cls = 'badge-y'; }
      else { lbl = '고변동'; cls = 'badge-r'; }
      setBadge('ind-vol', `주간 ±${std.toFixed(2)}% — ${lbl}`, cls);
    }

    let hi = meta && meta.fiftyTwoWeekHigh, lo = meta && meta.fiftyTwoWeekLow;
    if (!hi || !lo) { hi = Math.max(...weeklyPrices); lo = Math.min(...weeklyPrices); }
    if (hi && lo && hi > lo) {
      const fromHi = (cur - hi) / hi * 100;
      const fromLo = (cur - lo) / lo * 100;
      const pos = (cur - lo) / (hi - lo);
      const cls = pos < 0.5 ? 'badge-g' : pos > 0.85 ? 'badge-y' : 'badge-b';
      setBadge('ind-pos', `52주 고점 대비 ${fromHi.toFixed(1)}% / 저점 대비 +${fromLo.toFixed(1)}%`, cls);
    }
  }

  // ── 뉴스 신호 AI 분류 ──
  function getAnthropicKey() { return localStorage.getItem('anthropic_api_key') || ''; }

  const NEWS_TOPICS = {
    fii:     'India FII foreign institutional investor flows',
    dii:     'India DII domestic institutional investor buying',
    rbi:     'RBI Reserve Bank India interest rate decision',
    pmi:     'India PMI manufacturing services activity',
    cpi:     'India CPI inflation',
    trade:   'India US trade deal tariff',
    mideast: 'Middle East geopolitics oil price',
    fed:     'US Federal Reserve interest rate decision',
  };

  async function fetchHeadlines(query) {
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en&gl=US&ceid=US:en`;
    const xml = await proxyText(url, 6000);
    if (!xml) return [];
    try {
      const doc = new DOMParser().parseFromString(xml, 'text/xml');
      return [...doc.querySelectorAll('item')].slice(0, 3)
        .map((it) => (it.querySelector('title')?.textContent || '').split(' - ')[0].trim())
        .filter(Boolean);
    } catch (e) { return []; }
  }

  async function updateNewsSignals() {
    const key = getAnthropicKey();
    const note = document.getElementById('news-live-note');
    if (!key) {
      if (note) note.textContent = '🔑 AI 키 입력 시 뉴스 신호가 실시간 갱신됩니다';
      return;
    }
    const entries = Object.entries(NEWS_TOPICS);
    const sets = await Promise.all(entries.map(([k, q]) => fetchHeadlines(q)));
    let block = '';
    entries.forEach(([k], i) => { if (sets[i].length) block += `[${k}] ${sets[i].join(' / ')}\n`; });
    if (!block) return;

    const sys = '당신은 인도 증시·펀드 뉴스 분석가입니다. 헤드라인을 보고 평가하세요. 반드시 JSON만 출력합니다.';
    const prompt = `아래는 인도 증시 관련 최신 헤드라인입니다.\n${block}\n각 항목(fii, dii, rbi, pmi, cpi, trade, mideast, fed)에 대해 한국어 14자 이내 요약 label 과 인도 증시에 미치는 영향 sentiment(good=호재, bad=악재, neutral=중립)를 매기세요.\n다음 형식의 JSON만 출력:\n{"fii":{"label":"...","sentiment":"good|bad|neutral"},"dii":{...},"rbi":{...},"pmi":{...},"cpi":{...},"trade":{...},"mideast":{...},"fed":{...}}`;
    try {
      const r = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 700, system: sys, messages: [{ role: 'user', content: prompt }] }),
      });
      const d = await r.json();
      const text = d.content?.[0]?.text || '';
      const m = text.match(/\{[\s\S]*\}/);
      if (!m) return;
      const obj = JSON.parse(m[0]);
      const sentCls = { good: 'badge-g', bad: 'badge-r', neutral: 'badge-y' };
      for (const [k, v] of Object.entries(obj)) {
        if (!v || !v.label) continue;
        setBadge('ind-' + k, v.label, sentCls[v.sentiment] || 'badge-y');
      }
      if (note) note.textContent = '✓ 뉴스 신호 방금 갱신됨';
    } catch (e) {}
  }

  // ── AI 차트 분석 카드를 실시간 지표로 다시 작성 (AI 불필요·항상 일치) ──
  function buildAnalysis(name, weekly, d5, meta, scale) {
    const el = document.getElementById('ai-chart-analysis');
    if (!el || !weekly || weekly.length < 14) return;
    const cur = weekly[weekly.length - 1];
    let pct = null;
    if (d5 && d5.length >= 2) pct = (d5[d5.length - 1] - d5[d5.length - 2]) / d5[d5.length - 2] * 100;
    const rsi = calcRSI(weekly, 14);
    const ma5 = sma(weekly, 5), ma13 = sma(weekly, 13), ma26 = sma(weekly, 26);
    let maState = '혼조';
    if (cur > ma5 && ma5 > ma13 && ma13 > ma26) maState = '정배열(상승)';
    else if (cur < ma5 && ma5 < ma13 && ma13 < ma26) maState = '역배열(하락)';
    const mom = (cur - weekly[weekly.length - 5]) / weekly[weekly.length - 5] * 100;
    const rets = [];
    for (let i = weekly.length - 12; i < weekly.length; i++) rets.push((weekly[i] - weekly[i - 1]) / weekly[i - 1] * 100);
    const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
    const std = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length);
    let hi = meta && meta.fiftyTwoWeekHigh, lo = meta && meta.fiftyTwoWeekLow;
    if (scale) { if (hi) hi *= scale; if (lo) lo *= scale; }
    if (!hi || !lo) { hi = Math.max(...weekly); lo = Math.min(...weekly); }
    const fromHi = (cur - hi) / hi * 100, fromLo = (cur - lo) / lo * 100;
    const posRatio = (cur - lo) / (hi - lo);
    const today = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
    const rsiLvl = rsi >= 70 ? '과열권' : rsi >= 55 ? '중립대 상단' : rsi >= 45 ? '중립' : rsi >= 30 ? '약세' : '과매도권';
    const momLvl = mom >= 2 ? '견조한 상승 동력' : mom >= 0 ? '약한 상승 힘' : mom > -2 ? '약한 하락 압력' : '뚜렷한 하락 압력';
    const volLvl = std < 1 ? '낮은' : std < 2 ? '보통' : '높은';
    const posLvl = posRatio < 0.4 ? '저점 부근' : posRatio > 0.8 ? '고점 부근' : '중간값 근처';
    let concl;
    if (maState.indexOf('정배열') >= 0 && mom > 0) concl = '추세·모멘텀이 우호적이라 분할 매수를 고려할 만합니다.';
    else if (maState.indexOf('역배열') >= 0) concl = '추세가 약해 신규 진입보다 반등 확인 후 대응이 바람직합니다.';
    else concl = '방향성이 불명확해 의미 있는 신호 전까지 관망이 최선입니다.';
    const fmt = (n) => Math.round(n).toLocaleString('ko-KR');
    el.innerHTML =
      `# ${name} 주간 차트 분석 (${today})<br><br>` +
      `• <strong>현재 지수</strong>: ${fmt(cur)}${pct != null ? ` — 전일 대비 ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : ''}<br><br>` +
      `• <strong>추세 (이평)</strong>: 5주·13주·26주 이평 기준 <strong>${maState}</strong>${maState === '혼조' ? ' — 방향성 불명확' : ''}<br><br>` +
      `• <strong>모멘텀</strong>: RSI ${rsi.toFixed(1)} (${rsiLvl}), 4주 모멘텀 ${mom >= 0 ? '+' : ''}${mom.toFixed(1)}% — ${momLvl}<br><br>` +
      `• <strong>변동성</strong>: 주간 ±${std.toFixed(2)}%로 ${volLvl} 수준<br><br>` +
      `• <strong>위치</strong>: 52주 고점(${fmt(hi)}) 대비 ${fromHi.toFixed(1)}%, 저점(${fmt(lo)}) 대비 +${fromLo.toFixed(1)}% — ${posLvl}<br><br>` +
      `• <strong>한 줄 결론</strong>: ${concl}<br><br>` +
      `<span style="color:var(--text3);font-size:11px;">* 열 때마다 실시간 지표로 자동 작성됩니다</span>`;
  }

  // ── 📰 주요 뉴스 (제목+링크, 열 때마다 실시간) — 인도 현지 RSS ──
  const NEWS_FEEDS = [
    { url: 'https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms', source: 'ET Markets' },
    { url: 'https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms', source: 'ET Economy' },
  ];

  function relTime(ts) {
    if (!ts) return '';
    const diff = Date.now() / 1000 - ts;
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + '분 전';
    if (diff < 86400) return Math.round(diff / 3600) + '시간 전';
    return Math.round(diff / 86400) + '일 전';
  }

  async function fetchNewsItems() {
    const sets = await Promise.all(NEWS_FEEDS.map(async (f) => {
      const xml = await proxyText(f.url, 8000);
      if (!xml) return [];
      try {
        const doc = new DOMParser().parseFromString(xml, 'text/xml');
        return [...doc.querySelectorAll('item')].slice(0, 12).map((it) => {
          let link = (it.querySelector('link')?.textContent || '').trim();
          if (!link) link = (it.querySelector('guid')?.textContent || '').trim();
          const pd = it.querySelector('pubDate')?.textContent || '';
          return {
            title: (it.querySelector('title')?.textContent || '').trim(),
            link,
            source: f.source,
            ts: (new Date(pd).getTime() || 0) / 1000,
          };
        }).filter((x) => x.title && x.link.startsWith('http'));
      } catch (e) { return []; }
    }));
    const all = [], seen = new Set();
    sets.forEach((s) => s.forEach((n) => {
      const k = n.title.toLowerCase().slice(0, 60);
      if (seen.has(k)) return;
      seen.add(k); all.push(n);
    }));
    all.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    return all.slice(0, 8);
  }

  function ensureNewsCard() {
    if (document.getElementById('major-news')) return;
    const anchor = document.querySelector('.section-label') || document.querySelector('.nifty-header');
    if (!anchor || !anchor.parentNode) return;
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = '<div class="card-title">📰 주요 뉴스 <span style="font-size:11px;font-weight:400;color:var(--text3);">— 실시간 · 인도 시장</span></div><div id="major-news"><div style="font-size:12px;color:var(--text3);">뉴스 불러오는 중…</div></div>';
    anchor.parentNode.insertBefore(card, anchor);
  }

  async function renderMajorNews() {
    ensureNewsCard();
    const box = document.getElementById('major-news');
    if (!box) return;
    const items = await fetchNewsItems();
    if (!items.length) { box.innerHTML = '<div style="font-size:12px;color:var(--text3);">뉴스를 불러오지 못했어요 (잠시 후 새로고침)</div>'; return; }
    box.innerHTML = items.map((n) => {
      const title = n.title.replace(/&/g, '&amp;').replace(/</g, '&lt;');
      const meta = [n.source, relTime(n.ts)].filter(Boolean).join(' · ');
      return `<a href="${n.link}" target="_blank" rel="noopener" style="display:block;padding:9px 0;border-bottom:0.5px solid var(--border);text-decoration:none;color:var(--text);"><div style="font-size:13px;line-height:1.45;">${title}</div><div style="font-size:11px;color:var(--text3);margin-top:3px;">${meta} ↗</div></a>`;
    }).join('');
  }

  async function runRealtime() {
    let niftyMeta = null;
    try {
      niftyMeta = await refreshChart('chartNifty', '%5ENSEI', 'nifty');
      await refreshChart('chartSensex', '%5EBSESN', 'sensex');
    } catch (e) {}
    try {
      const c = window._charts && window._charts['chartNifty'];
      const weekly = c && c.data && c.data.yr1 && c.data.yr1.prices;
      if (weekly) {
        updateTechnicals(niftyMeta, weekly);
        buildAnalysis('NIFTY 50', weekly, c.data.d5 && c.data.d5.prices, niftyMeta, 1);
      }
    } catch (e) {}
    try { await updateNewsSignals(); } catch (e) {}
    try { await renderMajorNews(); } catch (e) {}
    try { if (typeof recalcScorecard === 'function') recalcScorecard(); } catch (e) {}
  }

  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', () => setTimeout(runRealtime, 300));
  } else {
    setTimeout(runRealtime, 300);
  }
  setInterval(runRealtime, 5 * 60 * 1000);
})();
