'use client';

import { useMemo, useState } from 'react';

type ComponentScores = {
  trend_ma?: number;
  price_vs_ma5?: number;
  rsi?: number;
  macd?: number;
  volume_price?: number;
  breakout_20d?: number;
  daily_strength?: number;
};

type SignalData = {
  label: string;
  score: number;
  reasons: string[];
  indicators?: {
    close?: number;
    ma5?: number;
    ma10?: number;
    ma20?: number;
    rsi14?: number;
    vol_ratio_5?: number;
    macd?: number;
    macd_signal?: number;
    macd_hist?: number;
    high_20?: number;
    low_20?: number;
  };
  component_scores?: ComponentScores;
};

type HistoryItem = {
  ts_code: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  pre_close: number;
  change: number;
  pct_chg: number;
  vol: number;
  amount: number;
};

type HistoryResponse = {
  symbol?: string;
  ts_code?: string;
  history?: HistoryItem[];
  signal?: SignalData;
  error?: string;
  detail?: string;
};

function formatDate(s: string) {
  if (!s || s.length !== 8) return s;
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
}

function safeText(s?: string) {
  if (!s) return '';
  try {
    return decodeURIComponent(escape(s));
  } catch {
    return s;
  }
}

function signalStyle(label?: string) {
  if (label === '偏多' || label === '轻度偏多') {
    return 'bg-green-100 text-green-900 border-green-400';
  }
  if (label === '偏空' || label === '轻度偏空') {
    return 'bg-red-100 text-red-900 border-red-400';
  }
  return 'bg-yellow-100 text-yellow-900 border-yellow-400';
}

function PriceLineChart({ data }: { data: HistoryItem[] }) {
  const points = useMemo(() => {
    if (!data.length) return '';

    const closes = data.map((d) => Number(d.close));
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const width = 760;
    const height = 260;
    const pad = 24;
    const range = max - min || 1;

    return data
      .map((d, i) => {
        const x = pad + (i * (width - pad * 2)) / Math.max(data.length - 1, 1);
        const y =
          height - pad - ((Number(d.close) - min) / range) * (height - pad * 2);
        return `${x},${y}`;
      })
      .join(' ');
  }, [data]);

  const closes = data.map((d) => Number(d.close));
  const min = closes.length ? Math.min(...closes) : 0;
  const max = closes.length ? Math.max(...closes) : 0;

  return (
    <div className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
      <h2 className="text-xl font-semibold mb-3 text-black">最近20日收盘价走势</h2>
      <svg viewBox="0 0 760 260" className="w-full h-auto">
        <line x1="24" y1="236" x2="736" y2="236" stroke="#666" opacity="0.6" />
        <line x1="24" y1="24" x2="24" y2="236" stroke="#666" opacity="0.6" />
        <polyline fill="none" stroke="#111" strokeWidth="3" points={points} />
      </svg>
      <div className="flex justify-between text-sm text-black mt-2">
        <span>最低：{min}</span>
        <span>最高：{max}</span>
      </div>
    </div>
  );
}

function IndicatorCard({
  title,
  value,
}: {
  title: string;
  value: string | number | undefined | null;
}) {
  return (
    <div className="border border-gray-300 rounded p-3 bg-white">
      <div className="text-sm font-semibold text-gray-700 mb-1">{title}</div>
      <div className="text-lg font-bold text-black">{value ?? '-'}</div>
    </div>
  );
}

function ScoreBar({
  title,
  score,
}: {
  title: string;
  score: number;
}) {
  const clamped = Math.max(-10, Math.min(10, score));
  const leftPercent = ((clamped + 10) / 20) * 100;

  const scoreColor =
    clamped > 0 ? 'text-green-700' : clamped < 0 ? 'text-red-700' : 'text-gray-700';

  return (
    <div className="mb-4">
      <div className="flex justify-between items-center mb-1">
        <span className="font-medium text-black">{title}</span>
        <span className={`font-bold ${scoreColor}`}>{clamped}</span>
      </div>

      <div className="relative h-6 rounded-full overflow-hidden border border-gray-300">
        <div className="absolute inset-y-0 left-0 w-1/2 bg-red-200" />
        <div className="absolute inset-y-0 right-0 w-1/2 bg-green-200" />
        <div className="absolute inset-y-0 left-1/2 w-px bg-black" />

        <div
          className="absolute top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-black border border-white shadow"
          style={{
            left: `calc(${leftPercent}% - 8px)`,
          }}
        />
      </div>

      <div className="flex justify-between text-xs text-gray-700 mt-1">
        <span>-10</span>
        <span>0</span>
        <span>+10</span>
      </div>
    </div>
  );
}

function componentTitle(key: keyof ComponentScores): string {
  const map: Record<keyof ComponentScores, string> = {
    trend_ma: '均线结构',
    price_vs_ma5: '收盘相对MA5',
    rsi: 'RSI',
    macd: 'MACD',
    volume_price: '量价关系',
    breakout_20d: '20日突破',
    daily_strength: '当日强弱',
  };
  return map[key];
}

export default function HomePage() {
  const [symbol, setSymbol] = useState('600519');
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleSearch() {
    setLoading(true);
    setError('');
    setData(null);

    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
      const res = await fetch(`${baseUrl}/history?symbol=${symbol}`);
      const json: HistoryResponse = await res.json();

      if (!res.ok) {
        throw new Error(`请求失败: ${res.status}`);
      }

      if (json.error) {
        throw new Error(
          json.detail ? `${safeText(json.error)}: ${safeText(json.detail)}` : safeText(json.error)
        );
      }

      if (json.signal) {
        json.signal = {
          ...json.signal,
          label: safeText(json.signal.label),
          reasons: (json.signal.reasons || []).map((r) => safeText(r)),
        };
      }

      setData(json);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }

  const latest = data?.history?.[data.history.length - 1];
  const chartData = data?.history?.slice(-20) || [];
  const indicators = data?.signal?.indicators;
  const componentScores = data?.signal?.component_scores;

  return (
    <main className="min-h-screen max-w-5xl mx-auto p-6 bg-white text-black">
      <h1 className="text-3xl font-bold mb-6 text-black">A股买卖点助手 V4</h1>

      <div className="flex gap-3 mb-6">
        <input
          className="border border-gray-500 rounded px-3 py-2 flex-1 bg-white text-black placeholder:text-gray-700"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="输入股票代码，例如 600519"
        />
        <button
          onClick={handleSearch}
          className="bg-black text-white px-4 py-2 rounded border border-black"
        >
          查询
        </button>
      </div>

      {loading && <p className="text-black">加载中...</p>}
      {error && <p className="text-red-700 mb-4 font-medium">{error}</p>}

      {data && latest && (
        <>
          <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
            <h2 className="text-xl font-semibold mb-3 text-black">
              {data.symbol} {data.ts_code ? `(${data.ts_code})` : ''}
            </h2>
            <p className="text-black">最新交易日：{formatDate(latest.trade_date)}</p>
            <p className="text-black">收盘价：{latest.close}</p>
            <p className="text-black">涨跌额：{latest.change}</p>
            <p className="text-black">涨跌幅：{latest.pct_chg}%</p>
            <p className="text-black">开盘 / 最高 / 最低：{latest.open} / {latest.high} / {latest.low}</p>
            <p className="text-black">成交量：{latest.vol}</p>
            <p className="text-black">成交额：{latest.amount}</p>
          </section>

          {data.signal && (
            <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
              <h2 className="text-xl font-semibold mb-3 text-black">交易参考信号</h2>
              <div
                className={`inline-block px-3 py-1 rounded-full border text-sm font-semibold mb-3 ${signalStyle(
                  data.signal.label
                )}`}
              >
                {data.signal.label}
              </div>
              <p className="text-black font-medium">综合分数：{data.signal.score}</p>
              <div className="mt-3">
                <p className="font-semibold mb-2 text-black">原因：</p>
                <ul className="list-disc pl-5 space-y-1 text-black">
                  {data.signal.reasons?.map((reason, idx) => (
                    <li key={idx}>{reason}</li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          {componentScores && (
            <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
              <h2 className="text-xl font-semibold mb-4 text-black">单项技术评分</h2>
              {(
                Object.entries(componentScores) as [keyof ComponentScores, number][]
              ).map(([key, value]) => (
                <ScoreBar key={key} title={componentTitle(key)} score={value ?? 0} />
              ))}
            </section>
          )}

          {indicators && (
            <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
              <h2 className="text-xl font-semibold mb-3 text-black">技术指标</h2>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <IndicatorCard title="MA5" value={indicators.ma5} />
                <IndicatorCard title="MA10" value={indicators.ma10} />
                <IndicatorCard title="MA20" value={indicators.ma20} />
                <IndicatorCard title="RSI14" value={indicators.rsi14} />
                <IndicatorCard title="量比(5日)" value={indicators.vol_ratio_5} />
                <IndicatorCard title="MACD" value={indicators.macd} />
                <IndicatorCard title="MACD Signal" value={indicators.macd_signal} />
                <IndicatorCard title="MACD Hist" value={indicators.macd_hist} />
                <IndicatorCard title="20日高点" value={indicators.high_20} />
                <IndicatorCard title="20日低点" value={indicators.low_20} />
              </div>
            </section>
          )}

          <PriceLineChart data={chartData} />

          <section className="border border-gray-400 rounded p-4 bg-white text-black">
            <h2 className="text-xl font-semibold mb-3 text-black">最近20个交易日</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-sm text-black">
                <thead>
                  <tr className="border-b border-gray-400">
                    <th className="text-left py-2 pr-4 text-black font-semibold">日期</th>
                    <th className="text-left py-2 pr-4 text-black font-semibold">开盘</th>
                    <th className="text-left py-2 pr-4 text-black font-semibold">最高</th>
                    <th className="text-left py-2 pr-4 text-black font-semibold">最低</th>
                    <th className="text-left py-2 pr-4 text-black font-semibold">收盘</th>
                    <th className="text-left py-2 pr-4 text-black font-semibold">涨跌幅%</th>
                    <th className="text-left py-2 pr-4 text-black font-semibold">成交量</th>
                  </tr>
                </thead>
                <tbody>
                  {data.history?.slice(-20).reverse().map((item, idx) => (
                    <tr key={idx} className="border-b border-gray-300">
                      <td className="py-2 pr-4 text-black">{formatDate(item.trade_date)}</td>
                      <td className="py-2 pr-4 text-black">{item.open}</td>
                      <td className="py-2 pr-4 text-black">{item.high}</td>
                      <td className="py-2 pr-4 text-black">{item.low}</td>
                      <td className="py-2 pr-4 text-black">{item.close}</td>
                      <td className="py-2 pr-4 text-black">{item.pct_chg}</td>
                      <td className="py-2 pr-4 text-black">{item.vol}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
