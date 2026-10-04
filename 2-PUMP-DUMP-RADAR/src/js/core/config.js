export const DEFAULT_SETTINGS = Object.freeze({
  // --- رادار کل بازار (کشف) ---
  radarEnabled: 'true',
  radarWindowMin: 60,
  radarPumpThresholdPct: 10,
  radarDumpThresholdPct: -10,
  radarMinTurnover24h: 10000000,
  radarMaxSymbols: 8,
  radarTtlMin: 120,
  radarPollSec: 30,
  radarCheckMinutes: 10,   // ⏱ زمان قضاوت رویداد پامپ/دامپ توسط اعتبارسنج (دقیقه) — «دقت رادار Nm»
  radarThresholdPct: 1.5,  // 📏 حرکت چند ٪ در جهت رویداد = درست‌شمردن (اعتبارسنج)
  radarHistoryResolutionSec: 300,
  radarNewListingAlert: 'true',
  radarNewListingMin: 720,
  radarWarmupFallback: 'true',
  radarBlacklist: 'USDCUSDT,FDUSDUSDT,TUSDUSDT,DAIUSDT,USDPUSDT,USD1USDT,BUSDUSDT,EURUSDT,AEURUSDT',

  // --- موتور ورود Ignition (پس از کشف) ---
  entryTimeframe: '1',
  ignitionMinScore: 70,
  ignitionRsiMin: 45,
  ignitionRsiMax: 78,
  ignitionVolumeX: 1.6,
  ignitionMicroCheck: 'true',
  ignitionMicroCount: 2,
  ignitionAtrStopMult: 1.4,
  ignitionTakeProfitR: 1.6,
  ignitionMaxHoldMin: 45,

  // --- ریسک و کارمزد Paper ---
  paperInitialEquity: 1000,
  orderMargin: 30,
  leverage: 5,
  feeOpenPct: 0.055,
  feeClosePct: 0.055,
  slippagePct: 0.03,
  dailyLossLimitPct: 4,
  maxOpenPositions: 4,
  cooldownSec: 90,

  // --- هشدار صوتی ---
  audioAlerts: 'true',
  audioVolume: 0.6,

  scanIntervalSec: 8,
  paperAutoDefault: 'true',

  // --- پل یک‌طرفه به اتوتریدر (اختیاری، پیش‌فرض خاموش) ---
  bridgePublish: 'true'
});

export const STORAGE_KEYS = Object.freeze({
  settings: 'pump.lab.settings.v1',
  state: 'pump.lab.state.v1',
  logs: 'pump.lab.logs.v1',
  radarHistory: 'pump.lab.radar.history.v1',
  radarFirstSeen: 'pump.lab.radar.firstseen.v1'
});
