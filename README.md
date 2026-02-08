# 🐋 Whale Hunter Pro v6.0 - Advanced Edition

## نسخه پیشرفته با الگوریتم‌های هوش مصنوعی و تحلیل کوانتی

### ✨ ویژگی‌های نسخه 6.0

#### 📊 الگوریتم‌های پیشرفته تحلیل
- ✅ **OI Delta Analysis** - تحلیل تغییرات Open Interest
- ✅ **Iceberg Orders Detection** - تشخیص سفارشات کوه یخی
- ✅ **Order Flow Analysis** - تحلیل جریان سفارشات
- ✅ **Trend Reversal Pressure** - الگوهای فشار تغییر روند
- ✅ **CNN-BiLSTM Scoring** - امتیازدهی با شبکه‌های عصبی (شبیه‌سازی شده)
- ✅ **Hedging Detection** - تشخیص معاملات پوششی
- ✅ **Quantitative Analysis** - تحلیل کمی مالی

#### 🤖 سیستم اتو ترید دوگانه
- **Paper Trading Mode**: معامله فرضی برای تست و آنالیز
- **Live Trading Mode**: معامله واقعی با اتصال به صرافی
- **Auto Switch**: تعویض خودکار بین حالت‌ها
- **Risk Management**: مدیریت ریسک پیشرفته

#### 💾 سیستم کش و بازیابی
- **Cache System**: ذخیره موقت داده‌ها برای سرعت بیشتر
- **Reconnection Handler**: بازیابی پس از قطع اتصال
- **State Persistence**: نگهداری وضعیت سیستم
- **Price Cache**: کش قیمت‌ها برای نمایش سریع

#### 🎯 ویژگی‌های UI جدید
- **Ctrl+1+Right Click**: نمایش قیمت لحظه‌ای ارز
- **Auto Cleanup**: پاک‌سازی خودکار سیگنال‌های منقضی
- **Real-time Updates**: به‌روزرسانی لحظه‌ای
- **Advanced Dashboard**: داشبورد پیشرفته

#### 📡 منابع داده
- **Bybit Futures**: معاملات آتی Bybit (پیش‌فرض)
- **OKX Futures**: معاملات آتی OKX
- **Auto Failover**: جایگزینی خودکار در صورت خطا

---

## 🚀 نصب و راه‌اندازی

### پیش‌نیازها
```bash
# Go 1.21 یا بالاتر
go version

# نصب SQLite driver
go get github.com/mattn/go-sqlite3
```

### نصب
```bash
# دانلود پروژه
git clone <repository>
cd whale-hunter-v6

# نصب وابستگی‌ها
go mod init whale-hunter
go get github.com/mattn/go-sqlite3

# اجرا
go run whale_hunter_v6.go
```

### یا ساخت فایل اجرایی
```bash
go build -o whale_hunter whale_hunter_v6.go
./whale_hunter
```

---

## ⚙️ تنظیمات

### تنظیمات اصلی در کد:

```go
config := Config{
    APISource:            "bybit",        // یا "okx"
    TradingMode:          "paper",        // یا "live"
    WhaleThreshold:       500000,         // حداقل حجم نهنگ (USDT)
    PumpThreshold:        3,              // حداقل تغییر برای پامپ/دامپ (%)
    
    // اعتبارسنجی
    ValidationTimes:      []int{1, 2, 4}, // زمان‌های اعتبارسنجی (دقیقه)
    ValidationWeights:    []int{20, 30, 50}, // وزن هر مرحله
    MinPriceChange:       0.1,            // حداقل تغییر قیمت (%)
    
    // الگوریتم‌های پیشرفته
    UseOIDelta:           true,
    UseIcebergDetect:     true,
    UseOrderFlow:         true,
    UseTrendReversal:     true,
    UseCNNBiLSTM:         true,
    UseHedging:           true,
    
    // معامله
    TradeAmount:          5,              // مبلغ هر معامله (USDT)
    Leverage:             5,              // اهرم
    StopLoss:             2,              // حد ضرر (%)
    TakeProfit:           4,              // حد سود (%)
    
    // ریسک
    MaxDailyTrades:       4,              // حداکثر معاملات روزانه
    MaxConsecutiveLosses: 4,              // حداکثر ضررهای متوالی
    MinScoreForTrade:     70,             // حداقل امتیاز برای معامله
    
    // کش
    EnableCache:          true,
    CacheExpiry:          30,             // انقضای کش (دقیقه)
    AutoCleanupExpired:   true,
    SignalExpiryMinutes:  10,             // انقضای سیگنال (دقیقه)
}
```

---

## 📖 نحوه استفاده

### 1. راه‌اندازی اولیه
```bash
# اجرای برنامه
go run whale_hunter_v6.go

# باز کردن مرورگر
http://localhost:8080
```

### 2. اتصال به صرافی (برای Live Trading)
- وارد تب "اتو ترید" شوید
- کلیدهای API خود را وارد کنید
- روی "تست اتصال" کلیک کنید
- پس از موفقیت، حالت را به "Live" تغییر دهید

### 3. شروع اتو ترید
- **Paper Mode**: برای تست و آنالیز بدون ریسک
- **Live Mode**: برای معاملات واقعی

```
توجه: حتماً ابتدا در Paper Mode تست کنید!
```

### 4. نمایش قیمت لحظه‌ای
- `Ctrl+1` را نگه دارید
- روی نام ارز Right Click کنید
- قیمت لحظه‌ای نمایش داده می‌شود

---

## 🧮 فرمول‌های اعتبارسنجی

### سیستم امتیازدهی سیگنال

```
Score = (W1 × Valid1Min) + (W2 × Valid2Min) + (W3 × Valid4Min) + Bonus
```

**Bonus Scores:**
- Trend Match: +10
- Whale Flow Match: +10
- Iceberg Detected: +5
- Trend Reversal: +0~10 (بر اساس قدرت)
- CNN-BiLSTM > 70: +10

**سیگنال معتبر:**
- حداقل 2 از 3 مرحله Valid
- یا امتیاز کل ≥ MinScoreForTrade

---

## 📊 الگوریتم‌های پیشرفته

### 1. OI Delta Analysis
```
OI Delta = Current OI - Previous OI
```
- مثبت = افزایش موقعیت‌ها (صعودی)
- منفی = کاهش موقعیت‌ها (نزولی)

### 2. Iceberg Orders Detection
```
Score = (Volume / Bid-Ask Spread) / Threshold
```
- نسبت حجم به spread بالا = احتمال Iceberg

### 3. Order Flow Analysis
```
Buy Flow = Volume × (1 + Change%) / 2
Sell Flow = Volume × (1 - Change%) / 2
Net Flow = Buy Flow - Sell Flow
```

### 4. Trend Reversal Pressure
```
If |OI Delta| > 10% of OI AND Price moves opposite:
    Reversal Strength = |OI Delta| / OI × 100
```

### 5. Hedging Detection
```
Hedging Ratio = Open Interest / Volume
```
- نسبت 5~20 = احتمال Hedging

### 6. CNN-BiLSTM Score (Simulated)
```
Score = Base(50) + Momentum(15) + Volume(20) + OI Trend(15)
```

### 7. Quantitative Score
```
Score = Base(50) + Return/Vol Ratio + Liquidity Score
```

---

## 🗃️ ساختار دیتابیس

### جداول اصلی:

#### `whales` - نهنگ‌های شناسایی شده
- الگوریتم‌های پیشرفته
- سیگنال‌های OI، Iceberg، Order Flow
- امتیازات CNN-BiLSTM و Quant

#### `signals` - سیگنال‌های معاملاتی
- اعتبارسنجی 3 مرحله‌ای
- امتیاز کل و وضعیت
- زمان انقضا

#### `trades` - معاملات واقعی (Live)
- اتصال به صرافی
- Order ID واقعی

#### `paper_trades` - معاملات فرضی (Paper)
- تست بدون ریسک
- آنالیز استراتژی

#### `cache_state` - وضعیت کش
#### `price_cache` - کش قیمت‌ها

---

## 🔌 API Endpoints

### Market Data
```
GET /api/market?source=bybit
GET /api/market?source=okx
```

### Price Query
```
GET /api/price?symbol=BTCUSDT
Response: {"success": true, "symbol": "BTCUSDT", "price": 43250.5, "time": "..."}
```

### Auto Trade Control
```
POST /api/auto-trade/start
POST /api/auto-trade/stop
GET  /api/auto-trade/stats
```

### Configuration
```
GET  /api/config
POST /api/config
```

---

## 🛡️ مدیریت ریسک

### محدودیت‌های پیش‌فرض:
- **حداکثر معاملات روزانه**: 4
- **حداکثر ضررهای متوالی**: 4
- **حد ضرر**: 2%
- **حد سود**: 4%
- **اهرم**: 5x

### توصیه‌های ایمنی:
1. همیشه ابتدا در Paper Mode تست کنید
2. با مبالغ کم شروع کنید
3. Stop Loss را فعال نگه دارید
4. به محدودیت‌های روزانه پایبند باشید
5. از اهرم بالا خودداری کنید

---

## 🔧 عیب‌یابی

### مشکلات رایج:

#### 1. خطای اتصال به API
```
✅ بررسی اینترنت
✅ تست API با Postman
✅ فعال‌سازی Auto Switch
```

#### 2. سیگنال‌ها معتبر نمی‌شوند
```
✅ کاهش MinPriceChange
✅ افزایش ValidationTimes
✅ بررسی منبع داده
```

#### 3. اتو ترید کار نمی‌کند
```
✅ بررسی API Keys
✅ اطمینان از MinScoreForTrade مناسب
✅ چک کردن محدودیت‌های روزانه
```

#### 4. کش کار نمی‌کند
```
✅ فعال‌سازی EnableCache
✅ بررسی CacheExpiry
✅ حذف فایل دیتابیس و شروع مجدد
```

---

## 📈 نتایج و گزارش‌ها

### Dashboard Metrics:
- **نهنگ مادر**: تعداد نهنگ‌های شناسایی شده
- **سیگنال معتبر**: تعداد سیگنال‌های تایید شده
- **دقت سیگنال**: درصد موفقیت
- **Whale Flow**: جریان خالص نهنگ‌ها
- **PnL**: سود/زیان

### Paper Trading Analytics:
- **Win Rate**: نرخ برد
- **Average PnL**: میانگین سود
- **Max Drawdown**: حداکثر افت سرمایه
- **Sharpe Ratio**: (می‌تواند اضافه شود)

---

## 🚧 محدودیت‌ها و توسعه آینده

### محدودیت‌های فعلی:
- ❌ CNN-BiLSTM واقعی نیست (شبیه‌سازی شده)
- ❌ API صرافی‌ها شبیه‌سازی است
- ❌ Backtesting موجود نیست

### توسعه‌های آینده:
- 🔜 مدل ML واقعی با TensorFlow
- 🔜 اتصال واقعی به Bybit/OKX API
- 🔜 Backtesting Engine
- 🔜 Advanced Charting
- 🔜 Telegram/Discord Notifications
- 🔜 Multi-Account Support

---

## 📞 پشتیبانی

در صورت بروز مشکل:
1. Log های terminal را بررسی کنید
2. فایل `whale_hunter_v6.db` را حذف و مجدداً اجرا کنید
3. مطمئن شوید Go نسخه 1.21+ دارید
4. وابستگی‌ها را دوباره نصب کنید

---

## ⚖️ مسئولیت

```
⚠️ هشدار مهم:
این نرم‌افزار صرفاً برای اهداف آموزشی ارائه شده است.
استفاده از آن در معاملات واقعی کاملاً به مسئولیت شخصی شماست.
هیچ تضمینی برای سودآوری وجود ندارد.
لطفاً قبل از استفاده واقعی، به طور کامل تست کنید.
```

---

## 📜 لایسنس

MIT License - استفاده آزاد با حفظ کپی‌رایت

---

## 🙏 تشکر

از تمام توسعه‌دهندگان، تحلیلگران و معامله‌گرانی که در بهبود این پروژه کمک کرده‌اند.

**موفق باشید! 🚀**
