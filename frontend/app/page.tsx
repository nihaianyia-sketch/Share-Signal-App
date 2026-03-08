'use client';

import { useMemo, useState } from 'react';

type SignalData = {
  label: string;
  score: number;
  reasons: string[];
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
  if (label === '偏多') {
    return 'bg-green-100 text-green-700 border-green-200';
  }
  if (label === '偏空') {
    return 'bg-red-100 text-red-700 border-red-200';
  }
  return 'bg-yellow-100 text-yellow-700 border-yellow-200';
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
        const x =
          pad + (i * (width - pad * 2)) / Math.max(data.length - 1, 1);
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
    <div className="border rounded p-4 mb-6 bg-white">
      <h2 className="text-xl font-semibold mb-3">最近20日收盘价走势</h2>
      <svg viewBox="0 0 760 260" className="w-full h-auto">
        <line x1="24" y1="236" x2="736" y2="236" stroke="currentColor" opacity="0.2" />
        <line x1="24" y1="24" x2="24" y2="236" stroke="currentColor" opacity="0.2" />
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          points={points}
        />
      </svg>
      <div className="flex justify-between text-sm text-gray-500 mt-2">
        <span>最低：{min}</span>
        <span>最高：{max}</span>
      </div>
    </div>
  );
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
        throw new Error(json.detail ? `${safeText(json.error)}: ${safeText(json.detail)}` : safeText(json.error));
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

  return (
    <main className="min-h-screen max-w-5xl mx-auto p-6 bg-gray-50">
      <h1 className="text-3xl font-bold mb-6">A股买卖点助手</h1>

      <div className="flex gap-3 mb-6">
        <input
          className="border rounded px-3 py-2 flex-1 bg-white"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="输入股票代码，例如 600519"
        />
        <button
          onClick={handleSearch}
          className="bg-black text-white px-4 py-2 rounded"
        >
          查询
        </button>
      </div>

      {loading && <p>加载中...</p>}
      {error && <p className="text-red-600 mb-4">{error}</p>}

      {data && latest && (
        <>
          <section className="border rounded p-4 mb-6 bg-white">
            <h2 className="text-xl font-semibold mb-3">
              {data.symbol} {data.ts_code ? `(${data.ts_code})` : ''}
            </h2>
            <p>最新交易日：{formatDate(latest.trade_date)}</p>
            <p>收盘价：{latest.close}</p>
            <p>涨跌额：{latest.change}</p>
            <p>涨跌幅：{latest.pct_chg}%</p>
            <p>开盘 / 最高 / 最低：{latest.open} / {latest.high} / {latest.low}</p>
            <p>成交量：{latest.vol}</p>
            <p>成交额：{latest.amount}</p>
          </section>

          {data.signal && (
            <section className="border rounded p-4 mb-6 bg-white">
              <h2 className="text-xl font-semibold mb-3">信号结果</h2>
              <div
                className={`inline-block px-3 py-1 rounded-full border text-sm font-medium mb-3 ${signalStyle(
                  data.signal.label
                )}`}
              >
                {data.signal.label}
              </div>
              <p>分数：{data.signal.score}</p>
              <div className="mt-3">
                <p className="font-medium mb-2">原因：</p>
                <ul className="list-disc pl-5 space-y-1">
                  {data.signal.reasons?.map((reason, idx) => (
                    <li key={idx}>{reason}</li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          <PriceLineChart data={chartData} />

          <section className="border rounded p-4 bg-white">
            <h2 className="text-xl font-semibold mb-3">最近20个交易日</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 pr-4">日期</th>
                    <th className="text-left py-2 pr-4">开盘</th>
                    <th className="text-left py-2 pr-4">最高</th>
                    <th className="text-left py-2 pr-4">最低</th>
                    <th className="text-left py-2 pr-4">收盘</th>
                    <th className="text-left py-2 pr-4">涨跌幅%</th>
                    <th className="text-left py-2 pr-4">成交量</th>
                  </tr>
                </thead>
                <tbody>
                  {data.history?.slice(-20).reverse().map((item, idx) => (
                    <tr key={idx} className="border-b">
                      <td className="py-2 pr-4">{formatDate(item.trade_date)}</td>
                      <td className="py-2 pr-4">{item.open}</td>
                      <td className="py-2 pr-4">{item.high}</td>
                      <td className="py-2 pr-4">{item.low}</td>
                      <td className="py-2 pr-4">{item.close}</td>
                      <td className="py-2 pr-4">{item.pct_chg}</td>
                      <td className="py-2 pr-4">{item.vol}</td>
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
