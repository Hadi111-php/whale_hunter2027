export const DEFAULT_SETTINGS = Object.freeze({
  // LIVE is intentional: the app never silently falls back to synthetic candles.
  dataMode: 'live',
  dataBaseUrl: '/api/bybit',
  mockBaseUrl: '/api/mock/bybit',
  bybitCategory: 'linear',
  tickerPath: '/v5/market/tickers?category={category}&symbol={symbol}',
  klinePath: '/v5/market/kline?category={category}&symbol={symbol}&interval={timeframe}&limit=200',
  useClosedCandle: 'true',
  realWebhookUrl: '/api/lbank/order',
  realVenue: 'lbank-futures',
  symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT'],
  symbolMap: {},
  timeframe: '60', // پیش‌فرض ۱ ساعته طلایی (۱h) برای حذف نویزها
  riskProfile: 'medium',

  // Medium profile defaults (تایم‌فریم ۱ ساعته با فیلتر دقیق شکست و RSI)
  minScore: 85,
  minMovePct: 0.45,
  volumeSpikeX: 1.8,
  atrStopMult: 2.2,
  takeProfitR: 2.0,
  cooldownSec: 300,
  maxHoldMinutes: 120,

  // --- 🎯 موتور خروج شناور (Floating Profit Engine) ---
  // profitMode='float': حد سود «باز» است؛ سود با نمودار بالا می‌رود و فقط با
  //   برگشت روند (ترلینگ/چرخشRSI/کراس EMA/محو مومنتوم/سیگنال مخالف) بسته می‌شود.
  // profitMode='fixed': حد سود قاطع در takeProfitR اجرا می‌شود.
  profitMode: 'float',
  trailAtrMult: 1.25,      // فاصلهٔ ترلینگ استاپ پشت سقف/کف سود شناور (×ATR)
  breakevenBufferPct: 0.2, // بافر انتقال استاپ به نقطهٔ ورود (٪)
  breakevenMinAtr: 1.0,    // 🎯 گیت بریک‌ایون بالغ: انتقال استاپ به ورود فقط بعد از حرکت موافق ≥ N×ATR
                           //    (۰ = رفتار قدیم/فوری؛ ممیزی مرحله‌ای نشان داد انتقال فوری، برنده‌ها را
                           //     تقریباً صفر می‌بندد — خروج‌های نزدیک بریک‌ایون ۱۹ از ۲۷ در 6h)
  reversalRsiHigh: 68,     // خروج از خرید: RSI بالای این حد + شروع برگشت
  reversalRsiLow: 32,      // خروج از فروش: RSI زیر این حد + شروع برگشت
  reversalMovePct: 0.15,   // حداقل حرکت مخالف ٪ برای تایید برگشت
  reversalVolX: 1.3,       // حداقل جهش حجم برای تایید کراس EMA مخالف
  fadeCandles: 2,          // N کندلِ بستهٔ مخالف پی‌درپی = محو مومنتوم → خروج (۰ = خاموش)
  profitLockOn: 'on',      // 🔒 قفل سود (v2.10): 'on'/'off' — نجات سود هنگام پس‌گرفتن از اوج
  profitLockMinPeakR: 1.0, //    قفل فقط وقتی مسلح می‌شود که سودِ اوج ≥ N برابرِ ریسک اولیه باشد
  profitLockGivebackPct: 50, //  اگر از اوجِ سود بیش از این ٪ پس داده شد → بستن فوری (PROFIT_LOCK)
  flipMinScore: 72,        // 🔄 حداقل امتیاز سیگنال مخالف برای چرخش روند و بستن معامله (TREND_FLIP)
  signalCheckMinutes: 15,  // ⏱ زمان قضاوت سیگنال توسط اعتبارسنج (دقیقه) — «دقت سیگنال Nm»
  signalThresholdPct: 1.5, // 📏 حرکت چند ٪ در جهت سیگنال = درست‌شمردن (اعتبارسنج)

  // --- 🧮 فرمول‌ساز پارامتریک ---
  // formulaMode:
  //   'off'    — فقط موتور اجماع چند اندیکاتوری
  //   'filter' — عبارت پارامتریک (فرمول پایین) باید > 0 باشد تا ورود آزاد شود؛
  //              در صورت تایید، formulaBonusPct امتیاز اضافه می‌گیرد
  //   'signal' — بلوک JS کامل که {side, score, why} برمی‌گرداند و جایگزین موتور می‌شود
  formulaMode: 'off',
  formulaBonusPct: 10,
  customFormula: '(rsi < 40 && volX > 1.4) || (rsi > 62 && movePct < -0.2)',

  // Paper account. Fee values are editable taker-fee percentages.
  paperInitialEquity: 1000,
  orderMargin: 40,
  leverage: 5,
  feeOpenPct: 0.055,
  feeClosePct: 0.055,
  slippagePct: 0.02,
  dailyLossLimitPct: 3,
  maxOpenPositions: 3,

  // --- فیلتر تاییدیه هم‌جهتی کندل‌های ریز (Micro-Candle Momentum Filter) ---
  // قبل از ورود، N کندل متوالی بسته‌شده تایم‌فریم ریز بررسی می‌شود؛
  // هم‌جهتی کامل با سمت سیگنال، وزن داینامیک درصدی به امتیاز همان سمت اضافه می‌کند.
  microCandleCheck: 'true',
  microCandleCount: 3,
  microCandleTf: '1',
  microCandleBoostPct: 15,

  // --- هشدار صوتی زنده (Web Audio API — بدون فایل خارجی) ---
  // سطح ۱: چایم ملایم هنگام عبور امتیاز نماد از آستانه Pre-Alert
  // سطح ۲: دو بوق صعودی برای باز شدن خرید و دو بوق نزولی برای فروش
  audioAlerts: 'true',
  audioVolume: 0.5,
  preAlertScore: 75,
  preAlertCooldownSec: 120,

  // --- پل اختیاری به Pump/Dump Lab (پیش‌فرض خاموش؛ رادار مستقل در apps/pump-dump-lab) ---
  pumpBridgeUrl: '',

  scanIntervalSec: 5,
  paperAutoDefault: 'true',
  webhookToken: '',
  cloudServerUrl: '',
  activeAccount: 'hadi'
});

export const RISK_PROFILES = Object.freeze({
  low: Object.freeze({
    minScore: 82,
    minMovePct: 0.25,
    volumeSpikeX: 2.0,
    atrStopMult: 1.5,
    takeProfitR: 1.5,
    cooldownSec: 240,
    maxHoldMinutes: 15,
    orderMargin: 20,
    leverage: 3,
    dailyLossLimitPct: 1.5,
    maxOpenPositions: 2
  }),
  medium: Object.freeze({
    minScore: 72,
    minMovePct: 0.18,
    volumeSpikeX: 1.65,
    atrStopMult: 1.25,
    takeProfitR: 1.35,
    cooldownSec: 150,
    maxHoldMinutes: 20,
    orderMargin: 40,
    leverage: 5,
    dailyLossLimitPct: 3,
    maxOpenPositions: 3
  }),
  high: Object.freeze({
    minScore: 65,
    minMovePct: 0.12,
    volumeSpikeX: 1.35,
    atrStopMult: 1.0,
    takeProfitR: 1.1,
    cooldownSec: 60,
    maxHoldMinutes: 30,
    orderMargin: 80,
    leverage: 10,
    dailyLossLimitPct: 5,
    maxOpenPositions: 5
  })
});

export const RISK_PROFILE_LABELS = Object.freeze({
  low: 'کم‌ریسک — فیلتر قوی، حجم/اهرم کمتر',
  medium: 'متوسط — تعادل سیگنال و ریسک',
  high: 'پرریسک — سیگنال بیشتر، اهرم/اکسپوژر بالاتر'
});

export const STORAGE_KEYS = Object.freeze({
  settings: 'scalp.lab.settings.v3',
  state: 'scalp.lab.state.v3',
  logs: 'scalp.lab.logs.v3',
});

export const DATA_MODES = Object.freeze({
  LIVE: 'live',
  MOCK_SERVER: 'mock-server',
  MOCK_LOCAL: 'mock-local'
});
