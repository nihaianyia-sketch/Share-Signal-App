"use client";

import { useEffect, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://share-signal-app.onrender.com";

type BenchmarkItem = {
  name: string;
  ts_code: string;
  close?: number | null;
  pct_chg?: number | null;
};

type MarketMood = {
  score?: number | null;
  label?: string | null;
  indices?: Array<{
    name: string;
    ts_code: string;
    close?: number | null;
    pct_chg?: number | null;
    mood_score?: number | null;
  }>;
  available?: boolean | null;
  error?: string | null;
};

type MarketSentiment = {
  available?: boolean | null;
  score?: number | null;
  label?: string | null;
  components?: Record<string, number | null>;
  stats?: Record<string, unknown>;
  error?: string | null;
  source?: string | null;
};

type MarketOverviewResponse = {
  error?: string | null;
  benchmarks?: BenchmarkItem[];
  benchmark_available?: boolean;
  market_mood?: MarketMood;
  market_sentiment?: MarketSentiment;
  cache_time?: number | null;
};

function fmtNum(v: number | null | undefined, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return Number(v).toFixed(digits);
}

export default function MarketPage() {
  const [data, setData] = useState<MarketOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${API_BASE_URL}/market/overview`, {
          cache: "no-store",
        });
        const json: MarketOverviewResponse = await res.json();
        setData(json);
      } catch {
        setData({
          error: "市场总览暂不可用",
          benchmarks: [],
          benchmark_available: false,
          market_mood: {
            available: false,
            label: "中性",
            score: 0,
            indices: [],
            error: "市场温度暂不可用",
          },
          market_sentiment: {
            available: false,
            label: "中性",
            score: 0,
            error: "市场情绪暂不可用",
            source: "fallback",
          },
        });
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  return (
    <main className="min-h-screen bg-white text-black px-4 py-6">
      <div className="max-w-5xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">市场总览</h1>
          <p className="text-sm text-gray-500 mt-1">
            单独页面展示大盘、指数气氛与市场情绪，不影响单股页速度。
          </p>
        </div>

        {loading ? (
          <div className="text-sm text-gray-500">加载中...</div>
        ) : (
          <div className="space-y-6">
            <section className="border border-gray-300 rounded p-4 bg-white">
              <h2 className="text-lg font-semibold mb-3">对应大盘</h2>
              {data?.benchmark_available ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {(data?.benchmarks || []).map((b) => (
                    <div
                      key={b.ts_code}
                      className="border border-gray-200 rounded p-3"
                    >
                      <div className="font-medium">{b.name}</div>
                      <div className="text-sm text-gray-500">{b.ts_code}</div>
                      <div className="mt-2 text-sm">点位：{fmtNum(b.close)}</div>
                      <div className="text-sm">涨跌幅：{fmtNum(b.pct_chg)}%</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-gray-500">基准缓存暂不可用</div>
              )}
            </section>

            <section className="border border-gray-300 rounded p-4 bg-white">
              <h2 className="text-lg font-semibold mb-3">指数气氛</h2>
              <div className="text-sm mb-2">
                标签：{data?.market_mood?.label || "中性"}
              </div>
              <div className="text-sm mb-3">
                分数：{fmtNum(data?.market_mood?.score ?? null, 0)}
              </div>

              {(data?.market_mood?.indices || []).length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {(data?.market_mood?.indices || []).map((item) => (
                    <div
                      key={item.ts_code}
                      className="border border-gray-200 rounded p-3"
                    >
                      <div className="font-medium">{item.name}</div>
                      <div className="text-sm text-gray-500">{item.ts_code}</div>
                      <div className="mt-2 text-sm">点位：{fmtNum(item.close)}</div>
                      <div className="text-sm">涨跌幅：{fmtNum(item.pct_chg)}%</div>
                      <div className="text-sm">
                        气氛分：{fmtNum(item.mood_score ?? null, 0)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-gray-500">
                  {data?.market_mood?.error || "指数气氛暂不可用"}
                </div>
              )}
            </section>

            <section className="border border-gray-300 rounded p-4 bg-white">
              <h2 className="text-lg font-semibold mb-1">市场情绪指数</h2>
              <div className="text-xs text-gray-500 mb-3">
                来源：{data?.market_sentiment?.source || "fallback"}
              </div>
              <div className="text-sm mb-2">
                标签：{data?.market_sentiment?.label || "中性"}
              </div>
              <div className="text-sm mb-3">
                分数：{fmtNum(data?.market_sentiment?.score ?? null, 0)}
              </div>
              <div className="text-sm text-gray-500">
                {data?.market_sentiment?.error || "无额外说明"}
              </div>
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
