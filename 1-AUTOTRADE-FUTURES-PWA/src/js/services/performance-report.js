import { exitLayerOf } from './paper-broker.js';

export class PerformanceReport {
  summarize(state, initialEquity, profile = null) {
    const allTrades = Array.isArray(state?.paperTrades) ? state.paperTrades : [];
    const trades = profile ? allTrades.filter(trade => trade.riskProfile === profile) : allTrades;
    const chronological = [...trades].reverse();
    const profileStart = profile ? state?.profileStarts?.[profile] : null;
    const startingEquity = Number(profileStart ?? initialEquity) || 0;
    let netPnl = 0;
    let fees = 0;
    let grossPnl = 0;
    let grossProfit = 0;
    let grossLoss = 0;
    let holdSeconds = 0;
    let peak = startingEquity;
    let curve = startingEquity;
    let maxDrawdown = 0;

    for (const trade of chronological) {
      const net = Number(trade.pnl || 0);
      const gross = Number(trade.grossPnl || 0);
      const tradeFees = Number(trade.fees || Number(trade.feeOpen || 0) + Number(trade.feeClose || 0));
      netPnl += net;
      grossPnl += gross;
      fees += tradeFees;
      holdSeconds += Number(trade.durationSec || 0);
      if (net > 0) grossProfit += net;
      if (net < 0) grossLoss += Math.abs(net);
      curve += net;
      peak = Math.max(peak, curve);
      maxDrawdown = Math.max(maxDrawdown, peak - curve);
    }

    const wins = trades.filter(trade => Number(trade.pnl || 0) > 0).length;
    const losses = trades.filter(trade => Number(trade.pnl || 0) < 0).length;
    const count = trades.length;
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;

    return {
      profile: profile || 'all',
      scope: profile ? `closed paper trades / ${profile} / net after fees` : 'closed paper trades / net after fees',
      count,
      wins,
      losses,
      winRate: count ? wins / count * 100 : null,
      netPnl,
      grossPnl,
      fees,
      grossProfit,
      grossLoss,
      profitFactor,
      expectancy: count ? netPnl / count : null,
      averageWin: wins ? grossProfit / wins : null,
      averageLoss: losses ? grossLoss / losses : null,
      averageHoldSec: count ? holdSeconds / count : null,
      maxDrawdown,
      maxDrawdownPct: startingEquity > 0 ? maxDrawdown / startingEquity * 100 : null
    };
  }
}

// 🪜 نردبان داده (v2.6): خلاصهٔ لایه‌ای معاملات — «هر لایهٔ خروج چند بار بست و چند داد؟»
// این تابع خالص است و هم در UI (خروجی JSON) و هم در ممیزی روی دیتای واقعی استفاده می‌شود.

export const LAYER_NAMES = {
  0: 'دستی/سایر',
  1: 'SL سخت',
  2: 'بریک‌ایون',
  3: 'ترلینگ',
  4: 'برگشتی RSI/EMA',
  5: 'محو مومنتوم',
  6: 'چرخش روند',
  7: 'MaxHold',
  8: 'TP ثابت',
  9: 'پایان داده'
};

export function ladderRollup(trades) {
  const byLayer = {};
  const byReason = {};
  const monthly = {};
  let fees = 0;
  let grossWin = 0;
  let sumPeak = 0;
  let netOfPeakTrades = 0;
  let peakPositive = 0;
  let gaveBackToLoss = 0;
  for (const t of (Array.isArray(trades) ? trades : [])) {
    if (!t) continue;
    const layer = Number(t?.ladder?.exitLayer ?? exitLayerOf(t?.reason, t?.ladder?.stopSource));
    const name = LAYER_NAMES[layer] || `لایهٔ ${layer}`;
    if (!byLayer[name]) byLayer[name] = { layer, count: 0, net: 0, wins: 0 };
    byLayer[name].count += 1;
    byLayer[name].net += Number(t.pnl || 0);
    if (Number(t.pnl) > 0) byLayer[name].wins += 1;

    const rk = t.reason || 'UNKNOWN';
    if (!byReason[rk]) byReason[rk] = { count: 0, net: 0 };
    byReason[rk].count += 1;
    byReason[rk].net += Number(t.pnl || 0);

    const mk = Number.isFinite(Number(t.time)) ? new Date(t.time).toISOString().slice(0, 7) : '?';
    if (!monthly[mk]) monthly[mk] = { count: 0, net: 0 };
    monthly[mk].count += 1;
    monthly[mk].net += Number(t.pnl || 0);

    fees += Number(t.fees || 0);
    if (Number(t.pnl) > 0) grossWin += Number(t.pnl);
    if (Number(t.peakPnl || 0) > 0.5) {
      peakPositive += 1;
      sumPeak += Number(t.peakPnl);
      netOfPeakTrades += Number(t.pnl);
      if (Number(t.pnl) <= 0) gaveBackToLoss += 1;
    }
  }
  return {
    byLayer, byReason, monthly,
    fees, grossWin,
    capture: {
      peakPositiveTrades: peakPositive,
      sumPeak: Number(sumPeak.toFixed(4)),
      netOfPeakTrades: Number(netOfPeakTrades.toFixed(4)),
      pct: sumPeak > 0 ? Number((netOfPeakTrades / sumPeak * 100).toFixed(1)) : null
    },
    gaveBackToLoss
  };
}
