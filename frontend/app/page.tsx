'use client';

import { useState } from 'react';

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
        throw new Error(json.detail ? `${json.error}: ${json.detail}` : json.error);
      }

      setData(json);
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }

  const latest = data?.history?.[data.history.length - 1];

  return (
    <main className="min-h-screen max-w-5xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">A股买卖点助手</h1>

      <div className="flex gap-3 mb-6">
        <input
          className="border rounded px-3 py-2 flex-1"
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
          <section className="border rounded p-4 mb-6">
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
            <section className="border rounded p-4 mb-6">
              <h2 className="text-xl font-semibold mb-3">信号结果</h2>
              <p>标签：{data.signal.label}</p>
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

          <section className="border rounded p-4">
            <h2 className="text-xl font-semibold mb-3">最近20个交易日</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse">
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
