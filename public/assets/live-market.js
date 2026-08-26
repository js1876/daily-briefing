(() => {
  'use strict';

  const status = document.querySelector('[data-live-feed]');
  if (!status || !window.fetch) return;
  const feedUrl = status.dataset.liveFeed;
  const streamUrl = status.dataset.liveStream;
  const refreshMs = 20_000;
  let activePayload = null;
  const number = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
  const decimal = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const svgNs = 'http://www.w3.org/2000/svg';

  const validNumber = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const signedPrice = (value) => `${value >= 0 ? '+' : '-'}${number.format(Math.abs(value))}원`;
  const signedPct = (value) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  const dateLabel = (value, interval) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return interval === '1m'
      ? date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
      : `${date.getMonth() + 1}/${date.getDate()}`;
  };

  function setText(attribute, symbol, text) {
    document.querySelectorAll(`[${attribute}="${symbol}"]`).forEach((node) => {
      node.textContent = text;
      node.dataset.counted = 'true';
      node.dataset.finalText = text;
    });
  }

  function setDirection(symbol, changePct) {
    const direction = changePct >= 0 ? 'up' : 'down';
    document.querySelectorAll(`[data-live-card="${symbol}"], [data-live-trend-card="${symbol}"], [data-live-change-row="${symbol}"]`).forEach((node) => {
      node.classList.remove('up', 'down');
      node.classList.add(direction);
    });
    document.querySelectorAll(`[data-live-change="${symbol}"], [data-live-trend-change="${symbol}"]`).forEach((node) => {
      node.classList.remove('up', 'down');
      node.classList.add(direction);
    });
  }

  function updateTrend(symbol, instrument) {
    const points = Array.isArray(instrument.chart)
      ? instrument.chart.map((point) => ({ x: point.timestamp, y: validNumber(point.price) })).filter((point) => point.y !== null)
      : [];
    if (points.length < 2) return;
    const width = 320, height = 128, left = 18, right = 14, top = 14, bottom = 26;
    const values = points.map((point) => point.y);
    const min = Math.min(...values), max = Math.max(...values), spread = Math.max(max - min, 1);
    const chart = points.map((point, index) => ({
      x: left + index * ((width - left - right) / Math.max(points.length - 1, 1)),
      y: top + ((max - point.y) / spread) * (height - top - bottom),
    }));
    const svg = document.querySelector(`[data-live-trend="${symbol}"]`);
    if (svg) {
      svg.replaceChildren();
      const make = (tag, attributes) => {
        const el = document.createElementNS(svgNs, tag);
        Object.entries(attributes).forEach(([name, value]) => el.setAttribute(name, value));
        svg.append(el);
      };
      const coordinates = chart.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
      const area = `${chart[0].x.toFixed(1)},${height - bottom} ${coordinates} ${chart.at(-1).x.toFixed(1)},${height - bottom}`;
      make('polygon', { points: area });
      make('polyline', { points: coordinates });
      chart.forEach((point) => make('circle', { cx: point.x.toFixed(1), cy: point.y.toFixed(1), r: '3.2' }));
    }
    const labels = document.querySelector(`[data-live-trend-dates="${symbol}"]`);
    if (labels) {
      const pick = [points[0], points[Math.floor(points.length / 2)], points.at(-1)];
      labels.replaceChildren(...pick.map((point) => {
        const span = document.createElement('span');
        span.textContent = dateLabel(point.x, instrument.chartInterval);
        return span;
      }));
    }
  }

  function applyFeed(payload) {
    if (!payload || !Array.isArray(payload.instruments)) throw new Error('invalid live feed');
    activePayload = payload;
    const maxMove = Math.max(0.01, ...payload.instruments.map((item) => Math.abs(validNumber(item.changePct) ?? 0)));
    payload.instruments.forEach((instrument) => {
      const price = validNumber(instrument.price);
      const change = validNumber(instrument.change);
      const changePct = validNumber(instrument.changePct);
      if (price === null || change === null || changePct === null || !instrument.symbol) return;
      const symbol = String(instrument.symbol);
      setText('data-live-price', symbol, `${number.format(price)}원`);
      setText('data-live-change', symbol, `${signedPrice(change)} · ${signedPct(changePct)}`);
      setText('data-live-trend-price', symbol, `${number.format(price)}원`);
      setText('data-live-trend-change', symbol, signedPct(changePct));
      setText('data-live-change-pct', symbol, signedPct(changePct));
      const bar = document.querySelector(`[data-live-change-bar="${symbol}"]`);
      if (bar) bar.style.width = `${Math.max(4, Math.min(100, Math.abs(changePct) / maxMove * 100))}%`;
      setDirection(symbol, changePct);
      updateTrend(symbol, instrument);
    });
    const generated = new Date(payload.generatedAt);
    const time = Number.isNaN(generated.getTime())
      ? '시각 확인 중'
      : generated.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    status.textContent = `실시간 시세 · 토스증권 Open API · ${time} KST`;
    status.dataset.liveState = 'ok';
  }

  function applyTrade(event) {
    if (!activePayload || !event || event.type !== 'trade') return;
    const instrument = activePayload.instruments.find((item) => String(item.symbol) === String(event.symbol));
    if (!instrument) return;
    instrument.price = event.price;
    instrument.change = event.change;
    instrument.changePct = event.changePct;
    instrument.asOf = event.asOf;
    const chart = Array.isArray(instrument.chart) ? instrument.chart : (instrument.chart = []);
    const point = { timestamp: event.asOf, price: event.price };
    if (chart.length && String(chart.at(-1).timestamp).slice(0, 16) === String(event.asOf).slice(0, 16)) chart[chart.length - 1] = point;
    else chart.push(point);
    while (chart.length > 120) chart.shift();
    activePayload.generatedAt = event.asOf;
    applyFeed(activePayload);
  }

  function connectStream() {
    if (!streamUrl || !window.EventSource) return;
    const stream = new EventSource(streamUrl, { withCredentials: false });
    stream.onopen = () => { status.textContent = '실시간 체결 수신 중 · 토스증권 Open API'; };
    stream.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);
        if (event.type === 'snapshot') applyFeed(event.payload);
        else applyTrade(event);
      } catch (_) { /* keep static/JSON polling fallback active */ }
    };
    stream.onerror = () => {
      if (status.dataset.liveState !== 'ok') status.textContent = '실시간 체결 재연결 중 · 표시 가격은 마지막 수신값';
    };
  }

  async function refresh() {
    try {
      const url = new URL(feedUrl, window.location.href);
      url.searchParams.set('_', String(Date.now()));
      const response = await fetch(url, { cache: 'no-store', credentials: 'omit' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      applyFeed(await response.json());
    } catch (_) {
      if (status.dataset.liveState !== 'ok') status.textContent = '실시간 시세 연결 대기 · 표시 가격은 브리핑 생성 시점 기준';
    }
  }

  refresh();
  connectStream();
  window.setInterval(refresh, refreshMs);
})();
