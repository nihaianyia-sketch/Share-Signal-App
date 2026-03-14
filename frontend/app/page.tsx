'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

type ComponentScores = {
  trend_ma?: number;
  price_vs_ma5?: number;
  rsi?: number;
  macd?: number;
  volume_price?: number;
  breakout_20d?: number;
  daily_strength?: number;
  kdj?: number;
  relative_strength?: number;
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
    kdj_k?: number;
    kdj_d?: number;
    kdj_j?: number;
    atr14?: number;
    atr_ratio?: number;
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

type BenchmarkData = {
  name?: string;
  ts_code?: string;
  trade_date?: string | null;
  close?: number | null;
  pct_chg?: number | null;
  available?: boolean;
  error?: string | null;
};

type MarketMoodIndex = {
  name?: string;
  ts_code?: string;
  trade_date?: string | null;
  close?: number | null;
  pct_chg?: number | null;
  mood_score?: number | null;
};

type MarketMoodData = {
  score?: number;
  label?: string;
  indices?: MarketMoodIndex[];
  available?: boolean;
  error?: string | null;
};

type RelativeStrengthData = {
  available?: boolean;
  benchmark_name?: string;
  rs_day?: number | null;
  rs_5?: number | null;
  rs_10?: number | null;
  rs_20?: number | null;
  score?: number;
  error?: string | null;
};


type MarketSentimentData = {
  available?: boolean;
  score?: number;
  label?: string;
  components?: {
    index_move?: number;
    breadth?: number;
    limit_up_down?: number;
  };
  stats?: {
    up_count?: number | null;
    down_count?: number | null;
    limit_up?: number | null;
    limit_down?: number | null;
    breadth_error?: string | null;
    limit_error?: string | null;
  };
  error?: string | null;
};


type StatusJudgementData = {
  label?: string;
  reasons?: string[];
  atr_ratio?: number | null;
  rs_score?: number | null;
};

type TradingDecisionData = {
  action?: string;
  bias?: string;
  confidence?: number;
  summary?: string;
  reasons?: string[];
  composite_score?: number;
};

type HistoryResponse = {
  symbol?: string;
  name?: string | null;
  ts_code?: string;
  history?: HistoryItem[];
  signal?: SignalData;
  benchmark?: BenchmarkData;
  market_mood?: MarketMoodData;
  market_sentiment?: MarketSentimentData;
  relative_strength?: RelativeStrengthData;
  status_judgement?: StatusJudgementData;
  trading_decision?: TradingDecisionData;
  error?: string;
  detail?: string;
};

type FavoriteItem = {
  symbol: string;
  name?: string | null;
  close?: number | null;
  label?: string | null;
};

type SearchItem = {
  symbol: string;
  ts_code: string;
  name: string;
  initials: string;
};

function formatDate(s: string) {
  if (!s || s.length !== 8) return s;
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
}

function safeText(s?: string | null) {
  if (!s) return '';
  try {
    return decodeURIComponent(escape(s));
  } catch {
    return s;
  }
}

function signalStyle(label?: string) {
  if (label === '偏多' || label === '轻度偏多' || label === '偏暖' || label === '偏热') {
    return 'bg-green-100 text-green-900 border-green-400';
  }
  if (label === '偏空' || label === '轻度偏空' || label === '偏弱' || label === '偏冷') {
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

  return (
    <div className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
      <h2 className="text-xl font-semibold mb-3 text-black">最近20日收盘价走势</h2>
      <svg viewBox="0 0 760 260" className="w-full h-auto">
        <line x1="24" y1="236" x2="736" y2="236" stroke="#666" opacity="0.6" />
        <line x1="24" y1="24" x2="24" y2="236" stroke="#666" opacity="0.6" />
        <polyline fill="none" stroke="#111" strokeWidth="3" points={points} />
      </svg>
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
          style={{ left: `calc(${leftPercent}% - 8px)` }}
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
    kdj: 'KDJ',
    relative_strength: '相对强弱评分',
  };
  return map[key];
}

export default function HomePage() {
  const [symbol, setSymbol] = useState('600519');
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [favorites, setFavorites] = useState<FavoriteItem[]>([]);
  const [searchIndex, setSearchIndex] = useState<SearchItem[]>([]);
  const [suggestions, setSuggestions] = useState<SearchItem[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem('favoriteStocksV2');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setFavorites(parsed);
      }
    } catch {}
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem('favoriteStocksV2', JSON.stringify(favorites));
    } catch {}
  }, [favorites]);

  useEffect(() => {
    fetch('/stock_search.json')
      .then((r) => r.json())
      .then((json) => {
        if (Array.isArray(json)) setSearchIndex(json);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const q = symbol.trim().toLowerCase();
    if (!q) {
      setSuggestions([]);
      return;
    }

    const matched = searchIndex
      .filter((item) => {
        return (
          item.symbol.includes(q) ||
          item.name.includes(symbol.trim()) ||
          item.initials.startsWith(q)
        );
      })
      .slice(0, 8);

    setSuggestions(matched);
  }, [symbol, searchIndex]);

  async function handleSearch(targetSymbol?: string) {
    const finalSymbol = (targetSymbol ?? symbol).trim();
    if (!finalSymbol) return;

    setLoading(true);
    setError('');
    setData(null);
    setSymbol(finalSymbol);
    setShowSuggestions(false);

    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
      const res = await fetch(`${baseUrl}/history?symbol=${finalSymbol}`);
      const json: HistoryResponse = await res.json();

      if (!res.ok) throw new Error(`请求失败: ${res.status}`);
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

      if (json.market_mood) {
        json.market_mood = {
          ...json.market_mood,
          label: safeText(json.market_mood.label),
          error: safeText(json.market_mood.error),
        };
      }

      if (json.benchmark) {
        json.benchmark = {
          ...json.benchmark,
          name: safeText(json.benchmark.name),
          error: safeText(json.benchmark.error),
        };
      }

      if (json.relative_strength) {
        json.relative_strength = {
          ...json.relative_strength,
          benchmark_name: safeText(json.relative_strength.benchmark_name),
          error: safeText(json.relative_strength.error),
        };
      }

      if (json.market_sentiment) {
        json.market_sentiment = {
          ...json.market_sentiment,
          label: safeText(json.market_sentiment.label),
          error: safeText(json.market_sentiment.error),
          stats: json.market_sentiment.stats
            ? {
                ...json.market_sentiment.stats,
                breadth_error: safeText(json.market_sentiment.stats.breadth_error),
                limit_error: safeText(json.market_sentiment.stats.limit_error),
              }
            : undefined,
        };
      }

      if (json.status_judgement) {
        json.status_judgement = {
          ...json.status_judgement,
          label: safeText(json.status_judgement.label),
          reasons: (json.status_judgement.reasons || []).map((r) => safeText(r)),
        };
      }

      if (json.trading_decision) {
        json.trading_decision = {
          ...json.trading_decision,
          action: safeText(json.trading_decision.action),
          bias: safeText(json.trading_decision.bias),
          summary: safeText(json.trading_decision.summary),
          reasons: (json.trading_decision.reasons || []).map((r) => safeText(r)),
        };
      }

      json.name = safeText(json.name);

      setData(json);

      setFavorites((prev) =>
        prev.map((item) =>
          item.symbol === finalSymbol
            ? {
                ...item,
                name: json.name || item.name,
                close: json.history?.[json.history.length - 1]?.close ?? item.close,
                label: json.signal?.label || item.label,
              }
            : item
        )
      );
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    handleSearch('600519');
  }, []);

  function chooseSuggestion(item: SearchItem) {
    setSymbol(item.symbol);
    handleSearch(item.symbol);
  }

  function toggleFavorite() {
    const s = symbol.trim();
    if (!s) return;

    setFavorites((prev) => {
      const exists = prev.some((x) => x.symbol === s);
      if (exists) {
        return prev.filter((x) => x.symbol !== s);
      }

      const latest = data?.history?.[data.history.length - 1];
      const matched = searchIndex.find((x) => x.symbol === s);

      const item: FavoriteItem = {
        symbol: s,
        name: data?.symbol === s ? data?.name : matched?.name ?? null,
        close: data?.symbol === s ? latest?.close ?? null : null,
        label: data?.symbol === s ? data?.signal?.label ?? null : null,
      };

      return [item, ...prev].slice(0, 20);
    });
  }

  function removeFavorite(s: string) {
    setFavorites((prev) => prev.filter((x) => x.symbol !== s));
  }

  const latest = data?.history?.[data.history.length - 1];
  const chartData = data?.history?.slice(-20) || [];
  const indicators = data?.signal?.indicators;
  const componentScores = data?.signal?.component_scores;
  const benchmark = data?.benchmark;
  const marketMood = data?.market_mood;
  const marketSentiment = data?.market_sentiment;
  const relativeStrength = data?.relative_strength;
  const statusJudgement = data?.status_judgement;
  const tradingDecision = data?.trading_decision;
  const isFavorite = favorites.some((x) => x.symbol === symbol.trim());

  return (
    <main className="min-h-screen max-w-7xl mx-auto p-6 bg-white text-black">
      <h1 className="text-3xl font-bold mb-6 text-black">A股买卖点助手 V9</h1>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <aside className="lg:col-span-1">
          <section className="border border-gray-400 rounded p-4 bg-white mb-6">
            <div className="relative mb-3">
              <input
                ref={inputRef}
                className="border border-gray-500 rounded px-3 py-2 w-full bg-white text-black placeholder:text-gray-700"
                value={symbol}
                onChange={(e) => {
                  setSymbol(e.target.value);
                  setShowSuggestions(true);
                }}
                onFocus={() => setShowSuggestions(true)}
                placeholder="股票代码 / 中文名 / 拼音首字母"
              />

              {showSuggestions && suggestions.length > 0 && (
                <div className="absolute z-10 mt-1 w-full bg-white border border-gray-300 rounded shadow">
                  {suggestions.map((item) => (
                    <button
                      key={item.ts_code}
                      onClick={() => chooseSuggestion(item)}
                      className="block w-full text-left px-3 py-2 hover:bg-gray-100"
                    >
                      <div className="font-medium">{item.name}</div>
                      <div className="text-sm text-gray-700">
                        {item.symbol} · {item.initials}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => handleSearch()}
                className="bg-black text-white px-4 py-2 rounded border border-black flex-1"
              >
                查询
              </button>
              <button
                onClick={toggleFavorite}
                className="bg-white text-black px-4 py-2 rounded border border-gray-500"
              >
                {isFavorite ? '取消收藏' : '收藏'}
              </button>
            </div>
          </section>

          <section className="border border-gray-400 rounded p-4 bg-white">
            <h2 className="text-xl font-semibold mb-3">自选股</h2>
            {favorites.length === 0 ? (
              <p className="text-gray-700">暂无收藏</p>
            ) : (
              <div className="space-y-2">
                {favorites.map((fav) => {
                  const active = fav.symbol === symbol.trim();
                  return (
                    <div
                      key={fav.symbol}
                      className={`border rounded p-3 ${
                        active ? 'border-black bg-gray-100' : 'border-gray-300'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <button
                          onClick={() => handleSearch(fav.symbol)}
                          className="text-left flex-1"
                        >
                          <div className="font-semibold text-black">
                            {fav.name || '未命名股票'}
                          </div>
                          <div className="text-sm text-gray-700">{fav.symbol}</div>
                        </button>
                        <button
                          onClick={() => removeFavorite(fav.symbol)}
                          className="text-red-700"
                        >
                          ×
                        </button>
                      </div>

                      <div className="mt-2 text-sm text-gray-800">
                        <div>最新价：{fav.close ?? '-'}</div>
                        <div>信号：{fav.label ?? '-'}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </aside>

        <section className="lg:col-span-3">
          {loading && <p className="text-black">加载中...</p>}
          {error && <p className="text-red-700 mb-4 font-medium">{error}</p>}

          {data && latest && (
            <>
              <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                <h2 className="text-xl font-semibold mb-3">
                  {data.name || '未命名股票'} {data.symbol ? `(${data.symbol})` : ''}
                </h2>
                <p>最新交易日：{formatDate(latest.trade_date)}</p>
                <p>收盘价：{latest.close}</p>
                <p>涨跌额：{latest.change}</p>
                <p>涨跌幅：{latest.pct_chg}%</p>
                <p>开盘 / 最高 / 最低：{latest.open} / {latest.high} / {latest.low}</p>
                <p>成交量：{latest.vol}</p>
                <p>成交额：{latest.amount}</p>
              </section>

              {tradingDecision && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">交易决策</h2>
                  <div className={`inline-block px-3 py-1 rounded-full border text-sm font-semibold mb-3 ${signalStyle(
                    tradingDecision.bias
                  )}`}>
                    {tradingDecision.action}
                  </div>
                  <p><span className="font-semibold">方向偏向：</span>{tradingDecision.bias || '-'}</p>
                  <p><span className="font-semibold">置信度：</span>{tradingDecision.confidence ?? '-'} / 100</p>
                  <p className="mt-2"><span className="font-semibold">一句话结论：</span>{tradingDecision.summary || '-'}</p>
                  <p className="mt-2"><span className="font-semibold">综合分：</span>{tradingDecision.composite_score ?? '-'}</p>
                  {tradingDecision.reasons && tradingDecision.reasons.length > 0 && (
                    <div className="mt-3">
                      <p className="font-semibold mb-2">主要依据：</p>
                      <ul className="list-disc pl-5 space-y-1">
                        {tradingDecision.reasons.map((reason, idx) => (
                          <li key={idx}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </section>
              )}

              {statusJudgement && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">状态判断</h2>
                  <div className={`inline-block px-3 py-1 rounded-full border text-sm font-semibold mb-3 ${signalStyle(
                    statusJudgement.label
                  )}`}>
                    {statusJudgement.label}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-2 gap-3 mb-3">
                    <IndicatorCard title="ATR比率" value={statusJudgement.atr_ratio} />
                    <IndicatorCard title="相对强弱分" value={statusJudgement.rs_score} />
                  </div>
                  {statusJudgement.reasons && statusJudgement.reasons.length > 0 && (
                    <div>
                      <p className="font-semibold mb-2">状态依据：</p>
                      <ul className="list-disc pl-5 space-y-1">
                        {statusJudgement.reasons.map((reason, idx) => (
                          <li key={idx}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </section>
              )}

              {data.signal && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">交易参考信号</h2>
                  <div
                    className={`inline-block px-3 py-1 rounded-full border text-sm font-semibold mb-3 ${signalStyle(
                      data.signal.label
                    )}`}
                  >
                    {data.signal.label}
                  </div>
                  <p className="font-medium">综合分数：{data.signal.score}</p>
                  <div className="mt-3">
                    <p className="font-semibold mb-2">原因：</p>
                    <ul className="list-disc pl-5 space-y-1">
                      {data.signal.reasons?.map((reason, idx) => (
                        <li key={idx}>{reason}</li>
                      ))}
                    </ul>
                  </div>
                </section>
              )}

              {benchmark && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">对应大盘</h2>
                  {benchmark.available ? (
                    <>
                      <p>指数：{benchmark.name}</p>
                      <p>最新价：{benchmark.close ?? '-'}</p>
                      <p>涨跌幅：{benchmark.pct_chg ?? '-'}%</p>
                    </>
                  ) : (
                    <p className="text-gray-700">
                      暂不可用：{benchmark.error || '当前未获取到指数数据'}
                    </p>
                  )}
                </section>
              )}

              {marketMood && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">指数气氛</h2>
                  {marketMood.available ? (
                    <>
                      <div
                        className={`inline-block px-3 py-1 rounded-full border text-sm font-semibold mb-3 ${signalStyle(
                          marketMood.label
                        )}`}
                      >
                        {marketMood.label}
                      </div>
                      <ScoreBar title="指数气氛" score={marketMood.score ?? 0} />
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {(marketMood.indices || []).map((idx) => (
                          <div key={idx.ts_code} className="border border-gray-300 rounded p-3">
                            <p className="font-semibold">{idx.name}</p>
                            <p>涨跌幅：{idx.pct_chg ?? '-'}%</p>
                            <p>气氛分：{idx.mood_score ?? '-'}</p>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-gray-700">
                      暂不可用：{marketMood.error || '当前未获取到市场气氛数据'}
                    </p>
                  )}
                </section>
              )}

              {marketSentiment && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">市场情绪指数</h2>
                  {marketSentiment.available ? (
                    <>
                      <div
                        className={`inline-block px-3 py-1 rounded-full border text-sm font-semibold mb-3 ${signalStyle(
                          marketSentiment.label
                        )}`}
                      >
                        {marketSentiment.label}
                      </div>

                      <ScoreBar title="市场情绪总分" score={marketSentiment.score ?? 0} />

                      <div className="mt-4">
                        <ScoreBar
                          title="指数涨跌"
                          score={marketSentiment.components?.index_move ?? 0}
                        />
                        <ScoreBar
                          title="涨跌家数"
                          score={marketSentiment.components?.breadth ?? 0}
                        />
                        <ScoreBar
                          title="涨停跌停"
                          score={marketSentiment.components?.limit_up_down ?? 0}
                        />
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
                        <IndicatorCard title="上涨家数" value={marketSentiment.stats?.up_count} />
                        <IndicatorCard title="下跌家数" value={marketSentiment.stats?.down_count} />
                        <IndicatorCard title="涨停数" value={marketSentiment.stats?.limit_up} />
                        <IndicatorCard title="跌停数" value={marketSentiment.stats?.limit_down} />
                      </div>

                      {(marketSentiment.stats?.breadth_error || marketSentiment.stats?.limit_error) && (
                        <div className="mt-4 text-sm text-gray-600">
                          {marketSentiment.stats?.breadth_error && (
                            <p>涨跌家数数据源提示：{marketSentiment.stats.breadth_error}</p>
                          )}
                          {marketSentiment.stats?.limit_error && (
                            <p>涨停跌停数据源提示：{marketSentiment.stats.limit_error}</p>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-gray-700">
                      暂不可用：{marketSentiment.error || '当前未获取到市场情绪数据'}
                    </p>
                  )}
                </section>
              )}

              {relativeStrength && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">相对大盘强弱明细</h2>
                  {relativeStrength.available ? (
                    <>
                      <p>基准：{relativeStrength.benchmark_name || '-'}</p>
                      <div className="mt-3">
                        <ScoreBar title="相对大盘强弱" score={relativeStrength.score ?? 0} />
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                        <IndicatorCard title="当日RS" value={relativeStrength.rs_day} />
                        <IndicatorCard title="5日RS" value={relativeStrength.rs_5} />
                        <IndicatorCard title="10日RS" value={relativeStrength.rs_10} />
                        <IndicatorCard title="20日RS" value={relativeStrength.rs_20} />
                      </div>
                    </>
                  ) : (
                    <p className="text-gray-700">
                      暂不可用：{relativeStrength.error || '对应大盘历史数据暂不可用'}
                    </p>
                  )}
                </section>
              )}

              {componentScores && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-4">单项技术评分</h2>
                  {(
                    Object.entries(componentScores) as [keyof ComponentScores, number][]
                  ).map(([key, value]) => (
                    <ScoreBar key={key} title={componentTitle(key)} score={value ?? 0} />
                  ))}
                </section>
              )}

              {indicators && (
                <section className="border border-gray-400 rounded p-4 mb-6 bg-white text-black">
                  <h2 className="text-xl font-semibold mb-3">技术指标</h2>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    <IndicatorCard title="MA5" value={indicators.ma5} />
                    <IndicatorCard title="MA10" value={indicators.ma10} />
                    <IndicatorCard title="MA20" value={indicators.ma20} />
                    <IndicatorCard title="RSI14" value={indicators.rsi14} />
                    <IndicatorCard title="量比(5日)" value={indicators.vol_ratio_5} />
                    <IndicatorCard title="MACD" value={indicators.macd} />
                    <IndicatorCard title="MACD Signal" value={indicators.macd_signal} />
                    <IndicatorCard title="MACD Hist" value={indicators.macd_hist} />
                    <IndicatorCard title="K" value={indicators.kdj_k} />
                    <IndicatorCard title="D" value={indicators.kdj_d} />
                    <IndicatorCard title="J" value={indicators.kdj_j} />
                    <IndicatorCard title="ATR14" value={indicators.atr14} />
                    <IndicatorCard title="ATR比率" value={indicators.atr_ratio} />
                    <IndicatorCard title="20日高点" value={indicators.high_20} />
                    <IndicatorCard title="20日低点" value={indicators.low_20} />
                  </div>
                </section>
              )}

              <PriceLineChart data={chartData} />

              <section className="border border-gray-400 rounded p-4 bg-white text-black">
                <h2 className="text-xl font-semibold mb-3">最近20个交易日</h2>
                <div className="overflow-x-auto">
                  <table className="min-w-full border-collapse text-sm text-black">
                    <thead>
                      <tr className="border-b border-gray-400">
                        <th className="text-left py-2 pr-4 font-semibold">日期</th>
                        <th className="text-left py-2 pr-4 font-semibold">开盘</th>
                        <th className="text-left py-2 pr-4 font-semibold">最高</th>
                        <th className="text-left py-2 pr-4 font-semibold">最低</th>
                        <th className="text-left py-2 pr-4 font-semibold">收盘</th>
                        <th className="text-left py-2 pr-4 font-semibold">涨跌幅%</th>
                        <th className="text-left py-2 pr-4 font-semibold">成交量</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.history?.slice(-20).reverse().map((item, idx) => (
                        <tr key={idx} className="border-b border-gray-300">
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
        </section>
      </div>
    </main>
  );
}
