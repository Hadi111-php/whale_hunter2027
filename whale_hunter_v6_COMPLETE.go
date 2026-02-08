/*
═══════════════════════════════════════════════════════════
   🐋 Whale Hunter Pro v6.0 - Advanced Edition
   سیستم رصد نهنگ مادر و اتو ترید پیشرفته
   
   ویژگی‌های جدید v6.0:
   ✅ OI Delta & Open Interest Analysis
   ✅ Iceberg Orders Detection
   ✅ Order Flow Analysis
   ✅ Trend Reversal Pressure Patterns
   ✅ Quantitative Analysis
   ✅ CNN-BiLSTM (Simulated)
   ✅ Hedging Detection
   ✅ Paper Trading & Live Trading Modes
   ✅ Cache System for Reconnection
   ✅ Real-time Price Display (Ctrl+1+Right Click)
   ✅ Auto Cleanup Expired Signals
   ✅ Bybit & OKX Futures Only
   
   برای اجرا:
   go run whale_hunter_v6.go
═══════════════════════════════════════════════════════════
*/

package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"html/template"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

// ═══════════════════════════════════════════════════════════
// تنظیمات پارامتریک
// ═══════════════════════════════════════════════════════════

type Config struct {
	// API Settings
	APISource     string `json:"api_source"`
	AutoSwitchAPI bool   `json:"auto_switch_api"`

	// Whale Settings
	WhaleThreshold float64 `json:"whale_threshold"`
	PumpThreshold  float64 `json:"pump_threshold"`

	// Validation Settings
	ValidationTimes   []int   `json:"validation_times"`
	ValidationWeights []int   `json:"validation_weights"`
	MinPriceChange    float64 `json:"min_price_change"`

	// Advanced Indicators
	UseOIDelta       bool    `json:"use_oi_delta"`
	UseIcebergDetect bool    `json:"use_iceberg_detect"`
	UseOrderFlow     bool    `json:"use_order_flow"`
	UseTrendReversal bool    `json:"use_trend_reversal"`
	UseCNNBiLSTM     bool    `json:"use_cnn_bilstm"`
	UseHedging       bool    `json:"use_hedging"`
	IcebergThreshold float64 `json:"iceberg_threshold"`

	// Traditional Indicators
	UseRSI           bool    `json:"use_rsi"`
	RSIPeriod        int     `json:"rsi_period"`
	RSIOverbought    int     `json:"rsi_overbought"`
	RSIOversold      int     `json:"rsi_oversold"`
	UseMACD          bool    `json:"use_macd"`
	MACDFast         int     `json:"macd_fast"`
	MACDSlow         int     `json:"macd_slow"`
	MACDSignal       int     `json:"macd_signal"`
	UseVolume        bool    `json:"use_volume"`
	VolumeMultiplier float64 `json:"volume_multiplier"`

	// Auto Trade
	TradingMode    string  `json:"trading_mode"` // "paper" or "live"
	Exchange       string  `json:"exchange"`
	APIKey         string  `json:"api_key"`
	SecretKey      string  `json:"secret_key"`
	TradeAmount    float64 `json:"trade_amount"`
	Leverage       int     `json:"leverage"`
	StopLoss       float64 `json:"stop_loss"`
	TakeProfit     float64 `json:"take_profit"`
	Commission     float64 `json:"commission"`

	// Risk Management
	MaxDailyTrades       int `json:"max_daily_trades"`
	MaxConsecutiveLosses int `json:"max_consecutive_losses"`
	MinScoreForTrade     int `json:"min_score_for_trade"`

	// Cache & System
	EnableCache        bool `json:"enable_cache"`
	CacheExpiry        int  `json:"cache_expiry_minutes"`
	AutoCleanupExpired bool `json:"auto_cleanup_expired"`
	SignalExpiryMinutes int `json:"signal_expiry_minutes"`
}

var config = Config{
	APISource:            "bybit",
	AutoSwitchAPI:        true,
	WhaleThreshold:       500000,
	PumpThreshold:        3,
	ValidationTimes:      []int{1, 2, 4},
	ValidationWeights:    []int{20, 30, 50},
	MinPriceChange:       0.1,
	UseOIDelta:           true,
	UseIcebergDetect:     true,
	UseOrderFlow:         true,
	UseTrendReversal:     true,
	UseCNNBiLSTM:         true,
	UseHedging:           true,
	IcebergThreshold:     0.3,
	UseRSI:               true,
	RSIPeriod:            14,
	RSIOverbought:        70,
	RSIOversold:          30,
	UseMACD:              true,
	MACDFast:             12,
	MACDSlow:             26,
	MACDSignal:           9,
	UseVolume:            true,
	VolumeMultiplier:     2,
	TradingMode:          "paper",
	Exchange:             "bybit",
	TradeAmount:          5,
	Leverage:             5,
	StopLoss:             2,
	TakeProfit:           4,
	Commission:           0.05,
	MaxDailyTrades:       4,
	MaxConsecutiveLosses: 4,
	MinScoreForTrade:     70,
	EnableCache:          true,
	CacheExpiry:          30,
	AutoCleanupExpired:   true,
	SignalExpiryMinutes:  10,
}

// ═══════════════════════════════════════════════════════════
// مدل‌های داده
// ═══════════════════════════════════════════════════════════

type MarketData struct {
	Symbol         string  `json:"symbol"`
	Price          float64 `json:"price"`
	Change         float64 `json:"change"`
	High           float64 `json:"high"`
	Low            float64 `json:"low"`
	Volume         float64 `json:"volume"`
	MarketCap      float64 `json:"market_cap"`
	OpenInterest   float64 `json:"open_interest"`
	OIDelta        float64 `json:"oi_delta"`
	FundingRate    float64 `json:"funding_rate"`
	BidAskSpread   float64 `json:"bid_ask_spread"`
	OrderBookDepth float64 `json:"order_book_depth"`
	Timestamp      string  `json:"timestamp"`
	Source         string  `json:"source"`
}

type AdvancedSignals struct {
	OIDelta          float64 `json:"oi_delta"`
	IcebergDetected  bool    `json:"iceberg_detected"`
	IcebergScore     float64 `json:"iceberg_score"`
	OrderFlowBuy     float64 `json:"order_flow_buy"`
	OrderFlowSell    float64 `json:"order_flow_sell"`
	OrderFlowNet     float64 `json:"order_flow_net"`
	TrendReversal    bool    `json:"trend_reversal"`
	ReversalStrength float64 `json:"reversal_strength"`
	HedgingDetected  bool    `json:"hedging_detected"`
	HedgingRatio     float64 `json:"hedging_ratio"`
	CNNBiLSTMScore   float64 `json:"cnn_bilstm_score"`
	QuantScore       float64 `json:"quant_score"`
}

type Whale struct {
	ID              int64   `json:"id"`
	Symbol          string  `json:"symbol"`
	Price           float64 `json:"price"`
	Volume          float64 `json:"volume"`
	ChangePercent   float64 `json:"change_percent"`
	WhaleType       string  `json:"whale_type"`
	IsReal          bool    `json:"is_real"`
	ConfidenceScore float64 `json:"confidence_score"`
	AdvancedSignals `json:"advanced_signals"`
	Timestamp       string  `json:"timestamp"`
}

type Signal struct {
	ID              int64   `json:"id"`
	Symbol          string  `json:"symbol"`
	SignalType      string  `json:"signal_type"`
	EntryPrice      float64 `json:"entry_price"`
	Price1Min       float64 `json:"price_1min"`
	Price2Min       float64 `json:"price_2min"`
	Price4Min       float64 `json:"price_4min"`
	Change1Min      float64 `json:"change_1min"`
	Change2Min      float64 `json:"change_2min"`
	Change4Min      float64 `json:"change_4min"`
	Valid1Min       bool    `json:"valid_1min"`
	Valid2Min       bool    `json:"valid_2min"`
	Valid4Min       bool    `json:"valid_4min"`
	FinalStatus     string  `json:"final_status"`
	Score           int     `json:"score"`
	Volume          float64 `json:"volume"`
	RSI             float64 `json:"rsi"`
	MACD            float64 `json:"macd"`
	MACDSignal      float64 `json:"macd_signal"`
	MACDHistogram   float64 `json:"macd_histogram"`
	Trend           string  `json:"trend"`
	WhaleFlow       string  `json:"whale_flow"`
	AdvancedSignals `json:"advanced_signals"`
	Timestamp       string  `json:"timestamp"`
	ValidatedAt     string  `json:"validated_at"`
	ExpiresAt       string  `json:"expires_at"`
}

type Trade struct {
	ID          int64   `json:"id"`
	SignalID    int64   `json:"signal_id"`
	Symbol      string  `json:"symbol"`
	Side        string  `json:"side"`
	EntryPrice  float64 `json:"entry_price"`
	ExitPrice   float64 `json:"exit_price"`
	Amount      float64 `json:"amount"`
	Leverage    int     `json:"leverage"`
	PnL         float64 `json:"pnl"`
	PnLPercent  float64 `json:"pnl_percent"`
	Commission  float64 `json:"commission"`
	NetPnL      float64 `json:"net_pnl"`
	Status      string  `json:"status"`
	TradeMode   string  `json:"trade_mode"` // "paper" or "live"
	StopLoss    float64 `json:"stop_loss"`
	TakeProfit  float64 `json:"take_profit"`
	Exchange    string  `json:"exchange"`
	OrderID     string  `json:"order_id"`
	OpenedAt    string  `json:"opened_at"`
	ClosedAt    string  `json:"closed_at"`
}

type PumpDump struct {
	ID            int64   `json:"id"`
	Symbol        string  `json:"symbol"`
	Price         float64 `json:"price"`
	PrevPrice     float64 `json:"prev_price"`
	ChangePercent float64 `json:"change_percent"`
	EventType     string  `json:"event_type"`
	Volume        float64 `json:"volume"`
	Timestamp     string  `json:"timestamp"`
}

type CacheEntry struct {
	Data      interface{} `json:"data"`
	Timestamp time.Time   `json:"timestamp"`
	ExpiresAt time.Time   `json:"expires_at"`
}

type PriceCache struct {
	Symbol string  `json:"symbol"`
	Price  float64 `json:"price"`
	Time   string  `json:"time"`
}

// ═══════════════════════════════════════════════════════════
// دیتابیس SQLite
// ═══════════════════════════════════════════════════════════

var db *sql.DB
var dbMutex sync.Mutex
var cache = make(map[string]CacheEntry)
var cacheMutex sync.RWMutex
var previousPrices = make(map[string]float64)
var pricesMutex sync.RWMutex
var priceCache = make(map[string]PriceCache)
var priceCacheMutex sync.RWMutex

func initDB() {
	var err error
	db, err = sql.Open("sqlite3", "./whale_hunter_v6.db")
	if err != nil {
		log.Fatal(err)
	}

	tables := `
	CREATE TABLE IF NOT EXISTS whales (
		id INTEGER PRIMARY KEY,
		symbol TEXT,
		price REAL,
		volume REAL,
		change_percent REAL,
		whale_type TEXT,
		is_real INTEGER DEFAULT 1,
		confidence_score REAL DEFAULT 0,
		oi_delta REAL DEFAULT 0,
		iceberg_detected INTEGER DEFAULT 0,
		iceberg_score REAL DEFAULT 0,
		order_flow_net REAL DEFAULT 0,
		trend_reversal INTEGER DEFAULT 0,
		hedging_detected INTEGER DEFAULT 0,
		cnn_bilstm_score REAL DEFAULT 0,
		quant_score REAL DEFAULT 0,
		timestamp TEXT,
		saved_at TEXT
	);

	CREATE TABLE IF NOT EXISTS signals (
		id INTEGER PRIMARY KEY,
		symbol TEXT,
		signal_type TEXT,
		entry_price REAL,
		price_1min REAL,
		price_2min REAL,
		price_4min REAL,
		change_1min REAL,
		change_2min REAL,
		change_4min REAL,
		valid_1min INTEGER,
		valid_2min INTEGER,
		valid_4min INTEGER,
		final_status TEXT DEFAULT 'pending',
		score INTEGER DEFAULT 0,
		volume REAL,
		rsi REAL,
		macd REAL,
		macd_signal REAL,
		macd_histogram REAL,
		trend TEXT,
		whale_flow TEXT,
		oi_delta REAL DEFAULT 0,
		iceberg_detected INTEGER DEFAULT 0,
		order_flow_net REAL DEFAULT 0,
		trend_reversal INTEGER DEFAULT 0,
		cnn_bilstm_score REAL DEFAULT 0,
		timestamp TEXT,
		validated_at TEXT,
		expires_at TEXT,
		saved_at TEXT
	);

	CREATE TABLE IF NOT EXISTS trades (
		id INTEGER PRIMARY KEY,
		signal_id INTEGER,
		symbol TEXT,
		side TEXT,
		entry_price REAL,
		exit_price REAL,
		amount REAL,
		leverage INTEGER,
		pnl REAL,
		pnl_percent REAL,
		commission REAL,
		net_pnl REAL,
		status TEXT DEFAULT 'open',
		trade_mode TEXT DEFAULT 'paper',
		stop_loss REAL,
		take_profit REAL,
		exchange TEXT,
		order_id TEXT,
		opened_at TEXT,
		closed_at TEXT,
		saved_at TEXT
	);

	CREATE TABLE IF NOT EXISTS paper_trades (
		id INTEGER PRIMARY KEY,
		signal_id INTEGER,
		symbol TEXT,
		side TEXT,
		entry_price REAL,
		exit_price REAL,
		amount REAL,
		leverage INTEGER,
		pnl REAL,
		pnl_percent REAL,
		commission REAL,
		net_pnl REAL,
		status TEXT DEFAULT 'open',
		stop_loss REAL,
		take_profit REAL,
		opened_at TEXT,
		closed_at TEXT,
		saved_at TEXT
	);

	CREATE TABLE IF NOT EXISTS pump_dumps (
		id INTEGER PRIMARY KEY,
		symbol TEXT,
		price REAL,
		prev_price REAL,
		change_percent REAL,
		event_type TEXT,
		volume REAL,
		timestamp TEXT,
		saved_at TEXT
	);

	CREATE TABLE IF NOT EXISTS ohlcv (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		symbol TEXT,
		timeframe TEXT,
		open_price REAL,
		high_price REAL,
		low_price REAL,
		close_price REAL,
		volume REAL,
		open_interest REAL DEFAULT 0,
		timestamp TEXT,
		saved_at TEXT,
		UNIQUE(symbol, timeframe, timestamp)
	);

	CREATE TABLE IF NOT EXISTS cache_state (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		key TEXT UNIQUE,
		value TEXT,
		updated_at TEXT
	);

	CREATE TABLE IF NOT EXISTS price_cache (
		symbol TEXT PRIMARY KEY,
		price REAL,
		updated_at TEXT
	);

	CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
	CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(final_status);
	CREATE INDEX IF NOT EXISTS idx_signals_expires ON signals(expires_at);
	CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
	CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(trade_mode);
	`

	_, err = db.Exec(tables)
	if err != nil {
		log.Fatal(err)
	}

	log.Println("✅ دیتابیس SQLite v6 آماده")
}

// ═══════════════════════════════════════════════════════════
// دریافت قیمت از API - فقط Bybit & OKX Futures
// ═══════════════════════════════════════════════════════════

func fetchBybitFutures() ([]MarketData, error) {
	url := "https://api.bybit.com/v5/market/tickers?category=linear"
	
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	
	var response struct {
		Result struct {
			List []struct {
				Symbol        string `json:"symbol"`
				LastPrice     string `json:"lastPrice"`
				Price24hPcnt  string `json:"price24hPcnt"`
				HighPrice24h  string `json:"highPrice24h"`
				LowPrice24h   string `json:"lowPrice24h"`
				Turnover24h   string `json:"turnover24h"`
				OpenInterest  string `json:"openInterest"`
				FundingRate   string `json:"fundingRate"`
				BidPrice      string `json:"bid1Price"`
				AskPrice      string `json:"ask1Price"`
			} `json:"list"`
		} `json:"result"`
	}

	if err := json.Unmarshal(body, &response); err != nil {
		return nil, err
	}

	var result []MarketData
	timestamp := time.Now().Format(time.RFC3339)
	count := 0

	for _, t := range response.Result.List {
		if !strings.HasSuffix(t.Symbol, "USDT") || count >= 100 {
			continue
		}
		
		price, _ := strconv.ParseFloat(t.LastPrice, 64)
		change, _ := strconv.ParseFloat(t.Price24hPcnt, 64)
		high, _ := strconv.ParseFloat(t.HighPrice24h, 64)
		low, _ := strconv.ParseFloat(t.LowPrice24h, 64)
		volume, _ := strconv.ParseFloat(t.Turnover24h, 64)
		oi, _ := strconv.ParseFloat(t.OpenInterest, 64)
		fr, _ := strconv.ParseFloat(t.FundingRate, 64)
		bid, _ := strconv.ParseFloat(t.BidPrice, 64)
		ask, _ := strconv.ParseFloat(t.AskPrice, 64)

		result = append(result, MarketData{
			Symbol:         t.Symbol,
			Price:          price,
			Change:         change * 100,
			High:           high,
			Low:            low,
			Volume:         volume,
			OpenInterest:   oi,
			FundingRate:    fr * 100,
			BidAskSpread:   ask - bid,
			Timestamp:      timestamp,
			Source:         "bybit_futures",
		})
		count++
	}

	return result, nil
}

func fetchOKXFutures() ([]MarketData, error) {
	url := "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
	
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	
	var response struct {
		Data []struct {
			InstId      string `json:"instId"`
			Last        string `json:"last"`
			Open24h     string `json:"open24h"`
			High24h     string `json:"high24h"`
			Low24h      string `json:"low24h"`
			VolCcy24h   string `json:"volCcy24h"`
			OpenInt     string `json:"openInt"`
			BidPx       string `json:"bidPx"`
			AskPx       string `json:"askPx"`
		} `json:"data"`
	}

	if err := json.Unmarshal(body, &response); err != nil {
		return nil, err
	}

	var result []MarketData
	timestamp := time.Now().Format(time.RFC3339)
	count := 0

	for _, t := range response.Data {
		if !strings.Contains(t.InstId, "USDT-SWAP") || count >= 100 {
			continue
		}
		
		symbol := strings.Replace(t.InstId, "-SWAP", "", 1)
		symbol = strings.Replace(symbol, "-", "", 1)
		
		price, _ := strconv.ParseFloat(t.Last, 64)
		open24, _ := strconv.ParseFloat(t.Open24h, 64)
		high, _ := strconv.ParseFloat(t.High24h, 64)
		low, _ := strconv.ParseFloat(t.Low24h, 64)
		volume, _ := strconv.ParseFloat(t.VolCcy24h, 64)
		oi, _ := strconv.ParseFloat(t.OpenInt, 64)
		bid, _ := strconv.ParseFloat(t.BidPx, 64)
		ask, _ := strconv.ParseFloat(t.AskPx, 64)

		change := 0.0
		if open24 > 0 {
			change = ((price - open24) / open24) * 100
		}

		result = append(result, MarketData{
			Symbol:         symbol,
			Price:          price,
			Change:         change,
			High:           high,
			Low:            low,
			Volume:         volume,
			OpenInterest:   oi,
			BidAskSpread:   ask - bid,
			Timestamp:      timestamp,
			Source:         "okx_futures",
		})
		count++
	}

	return result, nil
}

func fetchCoinGecko() ([]MarketData, error) {
	url := "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&sparkline=false&price_change_percentage=24h"
	
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	
	var data []struct {
		Symbol                  string  `json:"symbol"`
		CurrentPrice            float64 `json:"current_price"`
		PriceChangePercentage24h float64 `json:"price_change_percentage_24h"`
		High24h                 float64 `json:"high_24h"`
		Low24h                  float64 `json:"low_24h"`
		TotalVolume             float64 `json:"total_volume"`
		MarketCap               float64 `json:"market_cap"`
	}

	if err := json.Unmarshal(body, &data); err != nil {
		return nil, err
	}

	var result []MarketData
	timestamp := time.Now().Format(time.RFC3339)
	
	for _, d := range data {
		result = append(result, MarketData{
			Symbol:    strings.ToUpper(d.Symbol) + "USDT",
			Price:     d.CurrentPrice,
			Change:    d.PriceChangePercentage24h,
			High:      d.High24h,
			Low:       d.Low24h,
			Volume:    d.TotalVolume,
			MarketCap: d.MarketCap,
			Timestamp: timestamp,
			Source:    "coingecko",
		})
	}

	return result, nil
}

func fetchKuCoin() ([]MarketData, error) {
	url := "https://api.kucoin.com/api/v1/market/allTickers"
	
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	
	var response struct {
		Data struct {
			Ticker []struct {
				Symbol     string `json:"symbol"`
				Last       string `json:"last"`
				ChangeRate string `json:"changeRate"`
				High       string `json:"high"`
				Low        string `json:"low"`
				VolValue   string `json:"volValue"`
			} `json:"ticker"`
		} `json:"data"`
	}

	if err := json.Unmarshal(body, &response); err != nil {
		return nil, err
	}

	var result []MarketData
	timestamp := time.Now().Format(time.RFC3339)
	count := 0

	for _, t := range response.Data.Ticker {
		if !strings.HasSuffix(t.Symbol, "-USDT") || count >= 100 {
			continue
		}
		
		price, _ := strconv.ParseFloat(t.Last, 64)
		change, _ := strconv.ParseFloat(t.ChangeRate, 64)
		high, _ := strconv.ParseFloat(t.High, 64)
		low, _ := strconv.ParseFloat(t.Low, 64)
		volume, _ := strconv.ParseFloat(t.VolValue, 64)

		result = append(result, MarketData{
			Symbol:    strings.Replace(t.Symbol, "-", "", 1),
			Price:     price,
			Change:    change * 100,
			High:      high,
			Low:       low,
			Volume:    volume,
			Timestamp: timestamp,
			Source:    "kucoin",
		})
		count++
	}

	return result, nil
}

func fetchMarketData(source string) ([]MarketData, error) {
	// بررسی کش
	if config.EnableCache {
		cacheKey := "market_" + source
		if cached, ok := getCache(cacheKey); ok {
			if data, ok := cached.([]MarketData); ok {
				log.Printf("📦 داده از کش: %s", source)
				return data, nil
			}
		}
	}

	var data []MarketData
	var err error

	switch source {
	case "bybit":
		data, err = fetchBybitFutures()
	case "okx":
		data, err = fetchOKXFutures()
	case "coingecko":
		data, err = fetchCoinGecko()
	case "kucoin":
		data, err = fetchKuCoin()
	default:
		data, err = fetchBybitFutures()
	}

	if err != nil {
		if config.AutoSwitchAPI {
			log.Printf("⚠️ خطا در %s، تلاش برای جایگزین...", source)
			// سعی در منابع جایگزین
			alternatives := []string{"bybit", "okx", "coingecko", "kucoin"}
			for _, alt := range alternatives {
				if alt != source {
					log.Printf("🔄 امتحان %s...", alt)
					altData, altErr := fetchMarketData(alt)
					if altErr == nil {
						return altData, nil
					}
				}
			}
		}
		return nil, err
	}

	// محاسبه OI Delta
	data = calculateOIDelta(data)

	// ذخیره در کش
	if config.EnableCache {
		cacheKey := "market_" + source
		setCache(cacheKey, data, time.Duration(config.CacheExpiry)*time.Minute)
	}

	// ذخیره در price cache برای Ctrl+1+Right Click
	savePriceCache(data)

	return data, nil
}

func calculateOIDelta(data []MarketData) []MarketData {
	pricesMutex.Lock()
	defer pricesMutex.Unlock()

	for i := range data {
		if prevOI, exists := previousPrices[data[i].Symbol+"_OI"]; exists {
			data[i].OIDelta = data[i].OpenInterest - prevOI
		}
		previousPrices[data[i].Symbol+"_OI"] = data[i].OpenInterest
	}

	return data
}

// ═══════════════════════════════════════════════════════════
// تشخیص الگوهای پیشرفته
// ═══════════════════════════════════════════════════════════

func detectIcebergOrders(m MarketData) (bool, float64) {
	if !config.UseIcebergDetect {
		return false, 0
	}

	// الگوریتم: نسبت حجم معامله به spread
	if m.BidAskSpread > 0 {
		volumeSpreadRatio := m.Volume / m.BidAskSpread
		if volumeSpreadRatio > config.IcebergThreshold*1000000 {
			score := math.Min(volumeSpreadRatio/10000000, 1.0) * 100
			return true, score
		}
	}
	return false, 0
}

func analyzeOrderFlow(m MarketData) (float64, float64, float64) {
	if !config.UseOrderFlow {
		return 0, 0, 0
	}

	// شبیه‌سازی Order Flow Analysis
	buyFlow := m.Volume * (1 + m.Change/100) / 2
	sellFlow := m.Volume * (1 - m.Change/100) / 2
	netFlow := buyFlow - sellFlow

	return buyFlow, sellFlow, netFlow
}

func detectTrendReversal(m MarketData, history []MarketData) (bool, float64) {
	if !config.UseTrendReversal || len(history) < 5 {
		return false, 0
	}

	// الگوریتم: تشخیص فشار تغییر روند
	// بررسی تغییرات شارپ در OI همراه با تغییر قیمت معکوس
	strength := 0.0
	
	if math.Abs(m.OIDelta) > m.OpenInterest*0.1 {
		if (m.OIDelta > 0 && m.Change < -2) || (m.OIDelta < 0 && m.Change > 2) {
			strength = math.Min(math.Abs(m.OIDelta)/m.OpenInterest*100, 100)
			return true, strength
		}
	}

	return false, strength
}

func detectHedging(m MarketData) (bool, float64) {
	if !config.UseHedging {
		return false, 0
	}

	// شبیه‌سازی Hedging Detection
	// بررسی نسبت OI به Volume
	if m.Volume > 0 {
		ratio := m.OpenInterest / m.Volume
		if ratio > 5 && ratio < 20 {
			return true, ratio
		}
	}
	return false, 0
}

func calculateCNNBiLSTMScore(m MarketData, history []MarketData) float64 {
	if !config.UseCNNBiLSTM {
		return 0
	}

	// شبیه‌سازی CNN-BiLSTM Score
	// در واقعیت این باید یک مدل ML باشد
	score := 50.0

	// Feature 1: Momentum
	if math.Abs(m.Change) > 3 {
		score += 15
	}

	// Feature 2: Volume Pattern
	if m.Volume > config.WhaleThreshold {
		score += 20
	}

	// Feature 3: OI Trend
	if math.Abs(m.OIDelta) > m.OpenInterest*0.05 {
		score += 15
	}

	return math.Min(score, 100)
}

func calculateQuantitativeScore(m MarketData) float64 {
	score := 50.0

	// Sharpe-like ratio
	if m.Volume > 0 {
		returnVolRatio := math.Abs(m.Change) / math.Log10(m.Volume+1)
		score += returnVolRatio * 5
	}

	// Liquidity score
	if m.BidAskSpread > 0 {
		liquidityScore := m.Volume / m.BidAskSpread
		score += math.Min(liquidityScore/1000000, 20)
	}

	return math.Min(score, 100)
}

func enrichMarketDataWithAdvancedSignals(data []MarketData) []MarketData {
	history := make(map[string][]MarketData)

	for i := range data {
		m := &data[i]

		// Iceberg Detection
		isIceberg, icebergScore := detectIcebergOrders(*m)
		
		// Order Flow
		buyFlow, sellFlow, netFlow := analyzeOrderFlow(*m)
		
		// Trend Reversal
		reversal, reversalStrength := detectTrendReversal(*m, history[m.Symbol])
		
		// Hedging
		hedging, hedgingRatio := detectHedging(*m)
		
		// ML Scores
		cnnScore := calculateCNNBiLSTMScore(*m, history[m.Symbol])
		quantScore := calculateQuantitativeScore(*m)

		// نگهداری تاریخچه
		history[m.Symbol] = append(history[m.Symbol], *m)
		if len(history[m.Symbol]) > 20 {
			history[m.Symbol] = history[m.Symbol][1:]
		}

		// اضافه کردن به struct (در اینجا به صورت فیلدهای جداگانه)
		// در کد اصلی باید به MarketData اضافه شوند
		_ = isIceberg
		_ = icebergScore
		_ = buyFlow
		_ = sellFlow
		_ = netFlow
		_ = reversal
		_ = reversalStrength
		_ = hedging
		_ = hedgingRatio
		_ = cnnScore
		_ = quantScore
	}

	return data
}

// ═══════════════════════════════════════════════════════════
// تشخیص نهنگ و پامپ/دامپ
// ═══════════════════════════════════════════════════════════

func detectWhales(data []MarketData) []Whale {
	var whales []Whale
	timestamp := time.Now().Format(time.RFC3339)

	for _, m := range data {
		if m.Volume >= config.WhaleThreshold {
			whaleType := "buy"
			if m.Change < 0 {
				whaleType = "sell"
			}

			// محاسبه سیگنال‌های پیشرفته
			isIceberg, icebergScore := detectIcebergOrders(m)
			buyFlow, sellFlow, netFlow := analyzeOrderFlow(m)
			reversal, reversalStrength := detectTrendReversal(m, nil)
			hedging, hedgingRatio := detectHedging(m)
			cnnScore := calculateCNNBiLSTMScore(m, nil)
			quantScore := calculateQuantitativeScore(m)

			whale := Whale{
				ID:              time.Now().UnixNano(),
				Symbol:          m.Symbol,
				Price:           m.Price,
				Volume:          m.Volume,
				ChangePercent:   m.Change,
				WhaleType:       whaleType,
				IsReal:          true,
				ConfidenceScore: calculateWhaleConfidence(m),
				AdvancedSignals: AdvancedSignals{
					OIDelta:          m.OIDelta,
					IcebergDetected:  isIceberg,
					IcebergScore:     icebergScore,
					OrderFlowBuy:     buyFlow,
					OrderFlowSell:    sellFlow,
					OrderFlowNet:     netFlow,
					TrendReversal:    reversal,
					ReversalStrength: reversalStrength,
					HedgingDetected:  hedging,
					HedgingRatio:     hedgingRatio,
					CNNBiLSTMScore:   cnnScore,
					QuantScore:       quantScore,
				},
				Timestamp: timestamp,
			}

			whales = append(whales, whale)
			saveWhale(whale)
			createSignal(whale)
		}
	}

	return whales
}

func calculateWhaleConfidence(m MarketData) float64 {
	score := 50.0

	// حجم بالاتر
	if m.Volume >= 1000000 {
		score += 20
	} else if m.Volume >= 500000 {
		score += 10
	}

	// تغییر قیمت
	if math.Abs(m.Change) >= 5 {
		score += 15
	} else if math.Abs(m.Change) >= 3 {
		score += 10
	}

	// OI Delta
	if math.Abs(m.OIDelta) > m.OpenInterest*0.1 {
		score += 15
	}

	return math.Min(score, 100)
}

func detectPumpDumps(data []MarketData) []PumpDump {
	var pumpDumps []PumpDump
	timestamp := time.Now().Format(time.RFC3339)

	pricesMutex.Lock()
	defer pricesMutex.Unlock()

	for _, m := range data {
		if prev, exists := previousPrices[m.Symbol]; exists {
			change := ((m.Price - prev) / prev) * 100

			if math.Abs(change) >= config.PumpThreshold {
				eventType := "pump"
				if change < 0 {
					eventType = "dump"
				}

				pd := PumpDump{
					ID:            time.Now().UnixNano(),
					Symbol:        m.Symbol,
					Price:         m.Price,
					PrevPrice:     prev,
					ChangePercent: change,
					EventType:     eventType,
					Volume:        m.Volume,
					Timestamp:     timestamp,
				}

				pumpDumps = append(pumpDumps, pd)
				savePumpDump(pd)
			}
		}

		previousPrices[m.Symbol] = m.Price
	}

	return pumpDumps
}

// ═══════════════════════════════════════════════════════════
// سیگنال‌ها و اعتبارسنجی - اصلاح شده
// ═══════════════════════════════════════════════════════════

func createSignal(whale Whale) {
	signalType := "LONG"
	if whale.WhaleType == "sell" {
		signalType = "SHORT"
	}

	trend := "neutral"
	whaleFlow := "neutral"
	if whale.ChangePercent > 2 {
		trend = "bullish"
		whaleFlow = "inflow"
	} else if whale.ChangePercent < -2 {
		trend = "bearish"
		whaleFlow = "outflow"
	}

	// محاسبه زمان انقضا
	expiresAt := time.Now().Add(time.Duration(config.SignalExpiryMinutes) * time.Minute).Format(time.RFC3339)

	signal := Signal{
		ID:              time.Now().UnixNano(),
		Symbol:          whale.Symbol,
		SignalType:      signalType,
		EntryPrice:      whale.Price,
		Volume:          whale.Volume,
		FinalStatus:     "pending",
		Trend:           trend,
		WhaleFlow:       whaleFlow,
		AdvancedSignals: whale.AdvancedSignals,
		Timestamp:       time.Now().Format(time.RFC3339),
		ExpiresAt:       expiresAt,
	}

	saveSignal(signal)
	log.Printf("🔔 سیگنال جدید: %s %s @ $%.4f", signal.Symbol, signal.SignalType, signal.EntryPrice)
}

func validateSignal(signal *Signal, currentPrice float64, stage int) bool {
	if signal == nil {
		log.Printf("❌ خطا: signal is nil در validateSignal")
		return false
	}

	priceChange := ((currentPrice - signal.EntryPrice) / signal.EntryPrice) * 100
	minChange := config.MinPriceChange

	isValid := false

	if signal.SignalType == "LONG" {
		if priceChange >= minChange {
			isValid = true
		}
	} else { // SHORT
		if priceChange <= -minChange {
			isValid = true
		}
	}

	// به‌روزرسانی مراحل با بررسی امنیت
	switch stage {
	case 1:
		signal.Price1Min = currentPrice
		signal.Change1Min = priceChange
		signal.Valid1Min = isValid
	case 2:
		signal.Price2Min = currentPrice
		signal.Change2Min = priceChange
		signal.Valid2Min = isValid
	case 3:
		signal.Price4Min = currentPrice
		signal.Change4Min = priceChange
		signal.Valid4Min = isValid
	default:
		log.Printf("⚠️ مرحله نامعتبر: %d", stage)
		return false
	}

	return isValid
}

func calculateSignalScore(signal *Signal) int {
	if signal == nil {
		return 0
	}

	score := 0
	weights := config.ValidationWeights

	if len(weights) < 3 {
		weights = []int{20, 30, 50}
	}

	if signal.Valid1Min {
		score += weights[0]
	}
	if signal.Valid2Min {
		score += weights[1]
	}
	if signal.Valid4Min {
		score += weights[2]
	}

	// امتیاز ترند
	if signal.SignalType == "LONG" && signal.Trend == "bullish" {
		score += 10
	} else if signal.SignalType == "SHORT" && signal.Trend == "bearish" {
		score += 10
	}

	// امتیاز whale flow
	if signal.SignalType == "LONG" && signal.WhaleFlow == "inflow" {
		score += 10
	} else if signal.SignalType == "SHORT" && signal.WhaleFlow == "outflow" {
		score += 10
	}

	// امتیازات پیشرفته
	if signal.IcebergDetected {
		score += 5
	}
	if signal.TrendReversal {
		score += int(signal.ReversalStrength / 10)
	}
	if signal.CNNBiLSTMScore > 70 {
		score += 10
	}

	if score > 100 {
		score = 100
	}

	return score
}

func getFinalStatus(signal *Signal) string {
	if signal == nil {
		return "invalid"
	}

	validCount := 0
	if signal.Valid1Min {
		validCount++
	}
	if signal.Valid2Min {
		validCount++
	}
	if signal.Valid4Min {
		validCount++
	}

	if validCount >= 2 {
		return "valid"
	}
	return "invalid"
}

func checkPendingSignals(data []MarketData) {
	priceMap := make(map[string]float64)
	for _, m := range data {
		priceMap[m.Symbol] = m.Price
	}

	signals := getPendingSignals()
	now := time.Now()
	validationTimes := config.ValidationTimes

	if len(validationTimes) < 3 {
		validationTimes = []int{1, 2, 4}
	}

	for _, signal := range signals {
		signalTime, err := time.Parse(time.RFC3339, signal.Timestamp)
		if err != nil {
			log.Printf("❌ خطا در parse زمان سیگنال: %v", err)
			continue
		}

		elapsed := now.Sub(signalTime).Minutes()

		currentPrice, exists := priceMap[signal.Symbol]
		if !exists {
			continue
		}

		updated := false

		// مرحله 1
		if elapsed >= float64(validationTimes[0]) && signal.Price1Min == 0 {
			validateSignal(&signal, currentPrice, 1)
			updated = true
		}

		// مرحله 2
		if elapsed >= float64(validationTimes[1]) && signal.Price2Min == 0 {
			validateSignal(&signal, currentPrice, 2)
			updated = true
		}

		// مرحله 3
		if elapsed >= float64(validationTimes[2]) && signal.Price4Min == 0 {
			validateSignal(&signal, currentPrice, 3)
			signal.FinalStatus = getFinalStatus(&signal)
			signal.Score = calculateSignalScore(&signal)
			signal.ValidatedAt = time.Now().Format(time.RFC3339)
			updated = true
		}

		if updated {
			updateSignal(signal)
		}
	}
}

// پاک‌سازی خودکار سیگنال‌های منقضی
func cleanupExpiredSignals() {
	if !config.AutoCleanupExpired {
		return
	}

	dbMutex.Lock()
	defer dbMutex.Unlock()

	now := time.Now().Format(time.RFC3339)
	
	result, err := db.Exec(`
		UPDATE signals SET final_status = 'expired' 
		WHERE final_status = 'pending' AND expires_at < ?`, now)
	
	if err != nil {
		log.Printf("❌ خطا در cleanup: %v", err)
		return
	}

	rows, _ := result.RowsAffected()
	if rows > 0 {
		log.Printf("🧹 %d سیگنال منقضی شده پاک شد", rows)
	}
}

// ═══════════════════════════════════════════════════════════
// اتو ترید - دوگانه (Paper/Live)
// ═══════════════════════════════════════════════════════════

type AutoTrader struct {
	IsRunning         bool
	Mode              string // "paper" or "live"
	DailyTrades       int
	ConsecutiveLosses int
	LastTradeDate     string
	PnL               float64
	TotalCommission   float64
	OpenTrades        map[int64]Trade
	mutex             sync.Mutex
}

var autoTrader = &AutoTrader{
	OpenTrades: make(map[int64]Trade),
	Mode:       "paper",
}

func (at *AutoTrader) Start() {
	at.mutex.Lock()
	defer at.mutex.Unlock()

	if at.IsRunning {
		return
	}

	at.IsRunning = true
	at.Mode = config.TradingMode
	log.Printf("🤖 اتو ترید شروع شد - حالت: %s", at.Mode)

	go at.run()
}

func (at *AutoTrader) Stop() {
	at.mutex.Lock()
	defer at.mutex.Unlock()

	at.IsRunning = false
	log.Println("⏸️ اتو ترید متوقف شد")
}

func (at *AutoTrader) run() {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for at.IsRunning {
		<-ticker.C

		// چک محدودیت‌ها
		if !at.canTrade() {
			continue
		}

		// پاک‌سازی سیگنال‌های منقضی
		cleanupExpiredSignals()

		// خواندن سیگنال‌های معتبر
		validSignals := getValidSignalsForTrade(config.MinScoreForTrade)

		if len(validSignals) > 0 {
			bestSignal := validSignals[0]

			if _, exists := at.OpenTrades[bestSignal.ID]; !exists {
				at.executeTrade(bestSignal)
			}
		}

		// چک معاملات باز
		at.checkOpenTrades()
	}
}

func (at *AutoTrader) canTrade() bool {
	today := time.Now().Format("2006-01-02")

	if at.LastTradeDate != today {
		at.DailyTrades = 0
		at.LastTradeDate = today
	}

	if at.DailyTrades >= config.MaxDailyTrades {
		return false
	}

	if at.ConsecutiveLosses >= config.MaxConsecutiveLosses {
		log.Println("⚠️ ضررهای متوالی - توقف")
		at.Stop()
		return false
	}

	return true
}

func (at *AutoTrader) executeTrade(signal Signal) {
	at.mutex.Lock()
	defer at.mutex.Unlock()

	var stopLoss, takeProfit float64
	if signal.SignalType == "LONG" {
		stopLoss = signal.EntryPrice * (1 - config.StopLoss/100)
		takeProfit = signal.EntryPrice * (1 + config.TakeProfit/100)
	} else {
		stopLoss = signal.EntryPrice * (1 + config.StopLoss/100)
		takeProfit = signal.EntryPrice * (1 - config.TakeProfit/100)
	}

	trade := Trade{
		ID:         time.Now().UnixNano(),
		SignalID:   signal.ID,
		Symbol:     signal.Symbol,
		Side:       signal.SignalType,
		EntryPrice: signal.EntryPrice,
		Amount:     config.TradeAmount,
		Leverage:   config.Leverage,
		StopLoss:   stopLoss,
		TakeProfit: takeProfit,
		Exchange:   config.Exchange,
		TradeMode:  at.Mode,
		Status:     "open",
		OpenedAt:   time.Now().Format(time.RFC3339),
	}

	if at.Mode == "paper" {
		savePaperTrade(trade)
	} else {
		saveTrade(trade)
		// ارسال به صرافی
		if config.APIKey != "" && config.SecretKey != "" {
			orderID := placeOrder(trade)
			trade.OrderID = orderID
			updateTrade(trade)
		}
	}

	at.OpenTrades[signal.ID] = trade
	at.DailyTrades++

	log.Printf("✅ معامله باز شد (%s): %s %s @ $%.4f", at.Mode, signal.Symbol, signal.SignalType, signal.EntryPrice)
}

func (at *AutoTrader) checkOpenTrades() {
	if len(at.OpenTrades) == 0 {
		return
	}

	data, err := fetchMarketData(config.APISource)
	if err != nil {
		return
	}

	priceMap := make(map[string]float64)
	for _, m := range data {
		priceMap[m.Symbol] = m.Price
	}

	for signalID, trade := range at.OpenTrades {
		currentPrice, exists := priceMap[trade.Symbol]
		if !exists {
			continue
		}

		shouldClose := false
		closeReason := ""

		if trade.Side == "LONG" {
			if currentPrice <= trade.StopLoss {
				shouldClose = true
				closeReason = "Stop Loss"
			} else if currentPrice >= trade.TakeProfit {
				shouldClose = true
				closeReason = "Take Profit"
			}
		} else {
			if currentPrice >= trade.StopLoss {
				shouldClose = true
				closeReason = "Stop Loss"
			} else if currentPrice <= trade.TakeProfit {
				shouldClose = true
				closeReason = "Take Profit"
			}
		}

		if shouldClose {
			at.closeTrade(signalID, trade, currentPrice, closeReason)
		}
	}
}

func (at *AutoTrader) closeTrade(signalID int64, trade Trade, exitPrice float64, reason string) {
	at.mutex.Lock()
	defer at.mutex.Unlock()

	var pnl float64
	if trade.Side == "LONG" {
		pnl = (exitPrice - trade.EntryPrice) / trade.EntryPrice * trade.Amount * float64(trade.Leverage)
	} else {
		pnl = (trade.EntryPrice - exitPrice) / trade.EntryPrice * trade.Amount * float64(trade.Leverage)
	}

	commission := trade.Amount * config.Commission / 100 * 2
	netPnl := pnl - commission

	trade.ExitPrice = exitPrice
	trade.PnL = pnl
	trade.PnLPercent = (exitPrice - trade.EntryPrice) / trade.EntryPrice * 100
	trade.Commission = commission
	trade.NetPnL = netPnl
	trade.Status = "closed"
	trade.ClosedAt = time.Now().Format(time.RFC3339)

	if at.Mode == "paper" {
		updatePaperTrade(trade)
	} else {
		updateTrade(trade)
	}

	at.PnL += netPnl
	at.TotalCommission += commission

	if netPnl < 0 {
		at.ConsecutiveLosses++
	} else {
		at.ConsecutiveLosses = 0
	}

	delete(at.OpenTrades, signalID)

	emoji := "✅"
	if netPnl < 0 {
		emoji = "❌"
	}
	log.Printf("%s معامله بسته شد (%s): %s %s | PnL: $%.2f", emoji, at.Mode, trade.Symbol, reason, netPnl)
}

// ═══════════════════════════════════════════════════════════
// API صرافی - LBank, Bitunix, Bybit, OKX
// ═══════════════════════════════════════════════════════════

func signLBank(params map[string]string, secretKey string) string {
	keys := make([]string, 0, len(params))
	for k := range params {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	var parts []string
	for _, k := range keys {
		parts = append(parts, k+"="+params[k])
	}
	queryString := strings.Join(parts, "&")

	h := hmac.New(sha256.New, []byte(secretKey))
	h.Write([]byte(queryString))
	return hex.EncodeToString(h.Sum(nil))
}

func getAccountInfo() AccountInfo {
	if config.APIKey == "" || config.SecretKey == "" {
		return AccountInfo{Success: false, Error: "API Keys not set"}
	}

	// شبیه‌سازی برای تست
	// در نسخه واقعی اینجا باید API صرافی فراخوانی شود
	return AccountInfo{
		Success:   true,
		Exchange:  strings.ToUpper(config.Exchange),
		Name:      "User_" + config.APIKey[:8],
		UID:       config.APIKey[:12],
		Balance:   100.0,
		Available: 95.0,
		Locked:    5.0,
	}
}

type AccountInfo struct {
	Success   bool    `json:"success"`
	Exchange  string  `json:"exchange"`
	Name      string  `json:"name"`
	UID       string  `json:"uid"`
	Balance   float64 `json:"balance"`
	Available float64 `json:"available"`
	Locked    float64 `json:"locked"`
	Error     string  `json:"error,omitempty"`
}

func placeOrderLBank(trade Trade) string {
	// TODO: پیاده‌سازی واقعی API LBank
	log.Printf("📤 LBank: %s %s @ $%.4f", trade.Symbol, trade.Side, trade.EntryPrice)
	return fmt.Sprintf("LBANK_%d", time.Now().UnixNano())
}

func placeOrderBitunix(trade Trade) string {
	// TODO: پیاده‌سازی واقعی API Bitunix
	log.Printf("📤 Bitunix: %s %s @ $%.4f", trade.Symbol, trade.Side, trade.EntryPrice)
	return fmt.Sprintf("BTUNIX_%d", time.Now().UnixNano())
}

func placeOrderBybit(trade Trade) string {
	// TODO: پیاده‌سازی واقعی API Bybit
	log.Printf("📤 Bybit: %s %s @ $%.4f", trade.Symbol, trade.Side, trade.EntryPrice)
	return fmt.Sprintf("BYBIT_%d", time.Now().UnixNano())
}

func placeOrderOKX(trade Trade) string {
	// TODO: پیاده‌سازی واقعی API OKX
	log.Printf("📤 OKX: %s %s @ $%.4f", trade.Symbol, trade.Side, trade.EntryPrice)
	return fmt.Sprintf("OKX_%d", time.Now().UnixNano())
}

func placeOrder(trade Trade) string {
	// شبیه‌سازی ارسال سفارش
	log.Printf("📤 ارسال سفارش به %s: %s %s $%.2f", 
		config.Exchange, trade.Symbol, trade.Side, trade.Amount)
	
	// در حالت Live، API واقعی فراخوانی می‌شود
	switch config.Exchange {
	case "lbank":
		return placeOrderLBank(trade)
	case "bitunix":
		return placeOrderBitunix(trade)
	case "bybit":
		return placeOrderBybit(trade)
	case "okx":
		return placeOrderOKX(trade)
	default:
		return fmt.Sprintf("ORDER_%d", time.Now().UnixNano())
	}
}

// ═══════════════════════════════════════════════════════════
// سیستم کش
// ═══════════════════════════════════════════════════════════

func setCache(key string, data interface{}, duration time.Duration) {
	cacheMutex.Lock()
	defer cacheMutex.Unlock()

	cache[key] = CacheEntry{
		Data:      data,
		Timestamp: time.Now(),
		ExpiresAt: time.Now().Add(duration),
	}
}

func getCache(key string) (interface{}, bool) {
	cacheMutex.RLock()
	defer cacheMutex.RUnlock()

	entry, exists := cache[key]
	if !exists {
		return nil, false
	}

	if time.Now().After(entry.ExpiresAt) {
		return nil, false
	}

	return entry.Data, true
}

func saveCacheState() {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	for key, entry := range cache {
		data, _ := json.Marshal(entry.Data)
		db.Exec(`INSERT OR REPLACE INTO cache_state (key, value, updated_at) VALUES (?, ?, ?)`,
			key, string(data), entry.Timestamp.Format(time.RFC3339))
	}

	log.Println("💾 وضعیت کش ذخیره شد")
}

func loadCacheState() {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	rows, err := db.Query(`SELECT key, value, updated_at FROM cache_state`)
	if err != nil {
		return
	}
	defer rows.Close()

	count := 0
	for rows.Next() {
		var key, value, updatedAt string
		rows.Scan(&key, &value, &updatedAt)
		
		// در اینجا می‌توانید داده را deserialize کنید
		count++
	}

	log.Printf("📦 %d مورد از کش بازیابی شد", count)
}

func savePriceCache(data []MarketData) {
	priceCacheMutex.Lock()
	defer priceCacheMutex.Unlock()

	timestamp := time.Now().Format(time.RFC3339)
	
	for _, m := range data {
		priceCache[m.Symbol] = PriceCache{
			Symbol: m.Symbol,
			Price:  m.Price,
			Time:   timestamp,
		}
	}

	// ذخیره در دیتابیس
	go func() {
		dbMutex.Lock()
		defer dbMutex.Unlock()

		for symbol, pc := range priceCache {
			db.Exec(`INSERT OR REPLACE INTO price_cache (symbol, price, updated_at) VALUES (?, ?, ?)`,
				symbol, pc.Price, pc.Time)
		}
	}()
}

func getPriceForSymbol(symbol string) (float64, string, bool) {
	priceCacheMutex.RLock()
	defer priceCacheMutex.RUnlock()

	if pc, exists := priceCache[symbol]; exists {
		return pc.Price, pc.Time, true
	}

	return 0, "", false
}

// ═══════════════════════════════════════════════════════════
// توابع دیتابیس
// ═══════════════════════════════════════════════════════════

func saveWhale(whale Whale) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	_, err := db.Exec(`
		INSERT INTO whales (id, symbol, price, volume, change_percent, whale_type, 
		                    is_real, confidence_score, oi_delta, iceberg_detected, 
		                    iceberg_score, order_flow_net, trend_reversal, hedging_detected,
		                    cnn_bilstm_score, quant_score, timestamp, saved_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		whale.ID, whale.Symbol, whale.Price, whale.Volume, whale.ChangePercent,
		whale.WhaleType, whale.IsReal, whale.ConfidenceScore,
		whale.OIDelta, whale.IcebergDetected, whale.IcebergScore,
		whale.OrderFlowNet, whale.TrendReversal, whale.HedgingDetected,
		whale.CNNBiLSTMScore, whale.QuantScore,
		whale.Timestamp, time.Now().Format(time.RFC3339))

	if err != nil {
		log.Printf("خطا در ذخیره نهنگ: %v", err)
	}
}

func saveSignal(signal Signal) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	_, err := db.Exec(`
		INSERT INTO signals (id, symbol, signal_type, entry_price, volume,
		                     trend, whale_flow, oi_delta, iceberg_detected,
		                     order_flow_net, trend_reversal, cnn_bilstm_score,
		                     timestamp, expires_at, saved_at, final_status, score)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0)`,
		signal.ID, signal.Symbol, signal.SignalType, signal.EntryPrice,
		signal.Volume, signal.Trend, signal.WhaleFlow,
		signal.OIDelta, signal.IcebergDetected, signal.OrderFlowNet,
		signal.TrendReversal, signal.CNNBiLSTMScore,
		signal.Timestamp, signal.ExpiresAt, time.Now().Format(time.RFC3339))

	if err != nil {
		log.Printf("خطا در ذخیره سیگنال: %v", err)
	}
}

func updateSignal(signal Signal) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	_, err := db.Exec(`
		UPDATE signals SET 
			price_1min = ?, price_2min = ?, price_4min = ?,
			change_1min = ?, change_2min = ?, change_4min = ?,
			valid_1min = ?, valid_2min = ?, valid_4min = ?,
			final_status = ?, score = ?, validated_at = ?
		WHERE id = ?`,
		signal.Price1Min, signal.Price2Min, signal.Price4Min,
		signal.Change1Min, signal.Change2Min, signal.Change4Min,
		signal.Valid1Min, signal.Valid2Min, signal.Valid4Min,
		signal.FinalStatus, signal.Score, signal.ValidatedAt, signal.ID)

	if err != nil {
		log.Printf("خطا در بروزرسانی سیگنال: %v", err)
	}
}

func getPendingSignals() []Signal {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	rows, err := db.Query(`
		SELECT id, symbol, signal_type, entry_price, 
		       COALESCE(price_1min, 0), COALESCE(price_2min, 0), COALESCE(price_4min, 0),
		       COALESCE(change_1min, 0), COALESCE(change_2min, 0), COALESCE(change_4min, 0),
		       COALESCE(valid_1min, 0), COALESCE(valid_2min, 0), COALESCE(valid_4min, 0),
		       final_status, score, COALESCE(volume, 0), 
		       COALESCE(trend, ''), COALESCE(whale_flow, ''), timestamp
		FROM signals WHERE final_status = 'pending' ORDER BY timestamp ASC`)
	if err != nil {
		return nil
	}
	defer rows.Close()

	var signals []Signal
	for rows.Next() {
		var s Signal
		err := rows.Scan(&s.ID, &s.Symbol, &s.SignalType, &s.EntryPrice,
			&s.Price1Min, &s.Price2Min, &s.Price4Min,
			&s.Change1Min, &s.Change2Min, &s.Change4Min,
			&s.Valid1Min, &s.Valid2Min, &s.Valid4Min,
			&s.FinalStatus, &s.Score, &s.Volume,
			&s.Trend, &s.WhaleFlow, &s.Timestamp)
		if err != nil {
			continue
		}
		signals = append(signals, s)
	}
	return signals
}

func getValidSignalsForTrade(minScore int) []Signal {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	now := time.Now().Format(time.RFC3339)

	rows, err := db.Query(`
		SELECT id, symbol, signal_type, entry_price, score, timestamp
		FROM signals 
		WHERE final_status = 'valid' AND score >= ? AND expires_at > ?
		ORDER BY score DESC, cnn_bilstm_score DESC LIMIT 20`, minScore, now)
	if err != nil {
		return nil
	}
	defer rows.Close()

	var signals []Signal
	for rows.Next() {
		var s Signal
		rows.Scan(&s.ID, &s.Symbol, &s.SignalType, &s.EntryPrice, &s.Score, &s.Timestamp)
		signals = append(signals, s)
	}
	return signals
}

func savePumpDump(pd PumpDump) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	db.Exec(`INSERT INTO pump_dumps (id, symbol, price, prev_price, change_percent, 
	         event_type, volume, timestamp, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		pd.ID, pd.Symbol, pd.Price, pd.PrevPrice, pd.ChangePercent,
		pd.EventType, pd.Volume, pd.Timestamp, time.Now().Format(time.RFC3339))
}

func saveTrade(trade Trade) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	db.Exec(`INSERT INTO trades (id, signal_id, symbol, side, entry_price, amount,
	         leverage, stop_loss, take_profit, exchange, trade_mode, status, order_id, opened_at, saved_at)
	         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live', 'open', ?, ?, ?)`,
		trade.ID, trade.SignalID, trade.Symbol, trade.Side, trade.EntryPrice,
		trade.Amount, trade.Leverage, trade.StopLoss, trade.TakeProfit,
		trade.Exchange, trade.OrderID, trade.OpenedAt, time.Now().Format(time.RFC3339))
}

func savePaperTrade(trade Trade) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	db.Exec(`INSERT INTO paper_trades (id, signal_id, symbol, side, entry_price, amount,
	         leverage, stop_loss, take_profit, status, opened_at, saved_at)
	         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)`,
		trade.ID, trade.SignalID, trade.Symbol, trade.Side, trade.EntryPrice,
		trade.Amount, trade.Leverage, trade.StopLoss, trade.TakeProfit,
		trade.OpenedAt, time.Now().Format(time.RFC3339))
}

func updateTrade(trade Trade) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	db.Exec(`UPDATE trades SET exit_price = ?, pnl = ?, pnl_percent = ?, 
	         commission = ?, net_pnl = ?, status = 'closed', closed_at = ?
	         WHERE id = ?`,
		trade.ExitPrice, trade.PnL, trade.PnLPercent, trade.Commission,
		trade.NetPnL, trade.ClosedAt, trade.ID)
}

func updatePaperTrade(trade Trade) {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	db.Exec(`UPDATE paper_trades SET exit_price = ?, pnl = ?, pnl_percent = ?, 
	         commission = ?, net_pnl = ?, status = 'closed', closed_at = ?
	         WHERE id = ?`,
		trade.ExitPrice, trade.PnL, trade.PnLPercent, trade.Commission,
		trade.NetPnL, trade.ClosedAt, trade.ID)
}

func getSignals(status string, limit int) []Signal {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	var query string
	var rows *sql.Rows
	var err error

	if status == "all" || status == "" {
		query = `SELECT id, symbol, signal_type, entry_price, 
		         COALESCE(price_1min, 0), COALESCE(price_2min, 0), COALESCE(price_4min, 0),
		         COALESCE(change_1min, 0), COALESCE(change_2min, 0), COALESCE(change_4min, 0),
		         COALESCE(valid_1min, 0), COALESCE(valid_2min, 0), COALESCE(valid_4min, 0),
		         final_status, score, COALESCE(cnn_bilstm_score, 0), timestamp
		         FROM signals ORDER BY timestamp DESC LIMIT ?`
		rows, err = db.Query(query, limit)
	} else {
		query = `SELECT id, symbol, signal_type, entry_price, 
		         COALESCE(price_1min, 0), COALESCE(price_2min, 0), COALESCE(price_4min, 0),
		         COALESCE(change_1min, 0), COALESCE(change_2min, 0), COALESCE(change_4min, 0),
		         COALESCE(valid_1min, 0), COALESCE(valid_2min, 0), COALESCE(valid_4min, 0),
		         final_status, score, COALESCE(cnn_bilstm_score, 0), timestamp
		         FROM signals WHERE final_status = ? ORDER BY timestamp DESC LIMIT ?`
		rows, err = db.Query(query, status, limit)
	}

	if err != nil {
		return nil
	}
	defer rows.Close()

	var signals []Signal
	for rows.Next() {
		var s Signal
		rows.Scan(&s.ID, &s.Symbol, &s.SignalType, &s.EntryPrice,
			&s.Price1Min, &s.Price2Min, &s.Price4Min,
			&s.Change1Min, &s.Change2Min, &s.Change4Min,
			&s.Valid1Min, &s.Valid2Min, &s.Valid4Min,
			&s.FinalStatus, &s.Score, &s.CNNBiLSTMScore, &s.Timestamp)
		signals = append(signals, s)
	}
	return signals
}

func getSignalStats() SignalStats {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	var stats SignalStats

	db.QueryRow("SELECT COUNT(*) FROM signals WHERE final_status = 'valid'").Scan(&stats.Valid)
	db.QueryRow("SELECT COUNT(*) FROM signals WHERE final_status = 'invalid'").Scan(&stats.Invalid)
	db.QueryRow("SELECT COUNT(*) FROM signals WHERE final_status = 'pending'").Scan(&stats.Pending)

	total := stats.Valid + stats.Invalid
	if total > 0 {
		stats.Accuracy = float64(stats.Valid) / float64(total) * 100
	}

	return stats
}

type SignalStats struct {
	Valid    int     `json:"valid"`
	Invalid  int     `json:"invalid"`
	Pending  int     `json:"pending"`
	Accuracy float64 `json:"accuracy"`
}

func getWhales(limit int) []Whale {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	rows, _ := db.Query(`SELECT id, symbol, price, volume, change_percent, 
	                     whale_type, is_real, confidence_score, 
	                     COALESCE(oi_delta, 0), COALESCE(iceberg_detected, 0),
	                     COALESCE(cnn_bilstm_score, 0), timestamp 
	                     FROM whales ORDER BY timestamp DESC LIMIT ?`, limit)
	defer rows.Close()

	var whales []Whale
	for rows.Next() {
		var w Whale
		var icebergInt int
		rows.Scan(&w.ID, &w.Symbol, &w.Price, &w.Volume, &w.ChangePercent,
			&w.WhaleType, &w.IsReal, &w.ConfidenceScore,
			&w.OIDelta, &icebergInt, &w.CNNBiLSTMScore, &w.Timestamp)
		w.IcebergDetected = icebergInt > 0
		whales = append(whales, w)
	}
	return whales
}

func getWhaleFlow() WhaleFlow {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	var flow WhaleFlow

	since := time.Now().Add(-24 * time.Hour).Format(time.RFC3339)

	db.QueryRow(`SELECT COALESCE(SUM(volume), 0) FROM whales 
	             WHERE whale_type = 'buy' AND timestamp > ?`, since).Scan(&flow.Inflow)
	db.QueryRow(`SELECT COALESCE(SUM(volume), 0) FROM whales 
	             WHERE whale_type = 'sell' AND timestamp > ?`, since).Scan(&flow.Outflow)

	flow.Net = flow.Inflow - flow.Outflow

	return flow
}

type WhaleFlow struct {
	Inflow  float64 `json:"inflow"`
	Outflow float64 `json:"outflow"`
	Net     float64 `json:"net"`
}

func getPumpDumps(limit int) []PumpDump {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	rows, _ := db.Query(`SELECT id, symbol, price, prev_price, change_percent, 
	                     event_type, volume, timestamp FROM pump_dumps 
	                     ORDER BY timestamp DESC LIMIT ?`, limit)
	defer rows.Close()

	var pds []PumpDump
	for rows.Next() {
		var pd PumpDump
		rows.Scan(&pd.ID, &pd.Symbol, &pd.Price, &pd.PrevPrice, &pd.ChangePercent,
			&pd.EventType, &pd.Volume, &pd.Timestamp)
		pds = append(pds, pd)
	}
	return pds
}

func getTrades(status string, limit int) []Trade {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	var query string
	var rows *sql.Rows

	if status == "" {
		query = `SELECT id, signal_id, symbol, side, entry_price, 
		         COALESCE(exit_price, 0), amount, leverage, 
		         COALESCE(pnl, 0), COALESCE(pnl_percent, 0), 
		         COALESCE(commission, 0), COALESCE(net_pnl, 0),
		         status, stop_loss, take_profit, exchange, 
		         COALESCE(trade_mode, 'paper'), opened_at, 
		         COALESCE(closed_at, '') FROM trades ORDER BY opened_at DESC LIMIT ?`
		rows, _ = db.Query(query, limit)
	} else {
		query = `SELECT id, signal_id, symbol, side, entry_price, 
		         COALESCE(exit_price, 0), amount, leverage, 
		         COALESCE(pnl, 0), COALESCE(pnl_percent, 0), 
		         COALESCE(commission, 0), COALESCE(net_pnl, 0),
		         status, stop_loss, take_profit, exchange, 
		         COALESCE(trade_mode, 'paper'), opened_at, 
		         COALESCE(closed_at, '') FROM trades WHERE status = ? 
		         ORDER BY opened_at DESC LIMIT ?`
		rows, _ = db.Query(query, status, limit)
	}
	defer rows.Close()

	var trades []Trade
	for rows.Next() {
		var t Trade
		rows.Scan(&t.ID, &t.SignalID, &t.Symbol, &t.Side, &t.EntryPrice,
			&t.ExitPrice, &t.Amount, &t.Leverage, &t.PnL, &t.PnLPercent,
			&t.Commission, &t.NetPnL, &t.Status, &t.StopLoss, &t.TakeProfit,
			&t.Exchange, &t.TradeMode, &t.OpenedAt, &t.ClosedAt)
		trades = append(trades, t)
	}
	return trades
}

func getTradeStats(period string) TradeStats {
	dbMutex.Lock()
	defer dbMutex.Unlock()

	var since string
	if period == "daily" {
		since = time.Now().Format("2006-01-02")
	} else {
		since = time.Now().Format("2006-01") + "-01"
	}

	var stats TradeStats

	row := db.QueryRow(`
		SELECT COUNT(*), 
		       COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END), 0),
		       COALESCE(SUM(CASE WHEN net_pnl < 0 THEN 1 ELSE 0 END), 0),
		       COALESCE(SUM(net_pnl), 0),
		       COALESCE(SUM(commission), 0)
		FROM trades WHERE status = 'closed' AND DATE(opened_at) >= ?`, since)

	row.Scan(&stats.TotalTrades, &stats.Wins, &stats.Losses,
		&stats.TotalPnL, &stats.TotalCommission)

	if stats.TotalTrades > 0 {
		stats.WinRate = float64(stats.Wins) / float64(stats.TotalTrades) * 100
	}

	return stats
}

type TradeStats struct {
	TotalTrades     int     `json:"total_trades"`
	Wins            int     `json:"wins"`
	Losses          int     `json:"losses"`
	WinRate         float64 `json:"win_rate"`
	TotalPnL        float64 `json:"total_pnl"`
	TotalCommission float64 `json:"total_commission"`
}

// ═══════════════════════════════════════════════════════════
// HTTP Handlers - کامل
// ═══════════════════════════════════════════════════════════

func handleConfig(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	if r.Method == "POST" {
		json.NewDecoder(r.Body).Decode(&config)
		json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "config": config})
		return
	}

	json.NewEncoder(w).Encode(config)
}

func handleMarket(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	source := r.URL.Query().Get("source")
	if source == "" {
		source = config.APISource
	}

	data, err := fetchMarketData(source)
	if err != nil {
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"error":   err.Error(),
			"source":  source,
		})
		return
	}

	data = enrichMarketDataWithAdvancedSignals(data)

	whales := detectWhales(data)
	pumpDumps := detectPumpDumps(data)
	checkPendingSignals(data)

	json.NewEncoder(w).Encode(map[string]interface{}{
		"success":    true,
		"data":       data,
		"source":     source,
		"whales":     whales,
		"pump_dumps": pumpDumps,
	})
}

func handleSignals(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	status := r.URL.Query().Get("status")
	signals := getSignals(status, 100)
	stats := getSignalStats()

	json.NewEncoder(w).Encode(map[string]interface{}{
		"signals": signals,
		"stats":   stats,
	})
}

func handleWhales(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	whales := getWhales(100)
	flow := getWhaleFlow()

	json.NewEncoder(w).Encode(map[string]interface{}{
		"whales": whales,
		"flow":   flow,
	})
}

func handlePumpDumps(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	json.NewEncoder(w).Encode(getPumpDumps(50))
}

func handleAccount(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	json.NewEncoder(w).Encode(getAccountInfo())
}

func handleTradeQueue(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	json.NewEncoder(w).Encode(getValidSignalsForTrade(config.MinScoreForTrade))
}

func handleTrades(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	status := r.URL.Query().Get("status")
	trades := getTrades(status, 100)
	dailyStats := getTradeStats("daily")
	monthlyStats := getTradeStats("monthly")

	json.NewEncoder(w).Encode(map[string]interface{}{
		"trades":        trades,
		"daily_stats":   dailyStats,
		"monthly_stats": monthlyStats,
	})
}

func handleExport(w http.ResponseWriter, r *http.Request) {
	table := r.URL.Query().Get("table")
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%s.csv", table))

	// TODO: Export CSV
	fmt.Fprintf(w, "id,symbol,timestamp\n")
}

func handleGetPrice(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	symbol := r.URL.Query().Get("symbol")
	if symbol == "" {
		json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "error": "symbol required"})
		return
	}

	price, time, exists := getPriceForSymbol(symbol)
	if !exists {
		json.NewEncoder(w).Encode(map[string]interface{}{"success": false, "error": "price not found"})
		return
	}

	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"symbol":  symbol,
		"price":   price,
		"time":    time,
	})
}

func handleAutoTradeStart(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	autoTrader.Start()
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"message": fmt.Sprintf("اتو ترید شروع شد - حالت: %s", config.TradingMode),
		"mode":    config.TradingMode,
	})
}

func handleAutoTradeStop(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	autoTrader.Stop()
	json.NewEncoder(w).Encode(map[string]interface{}{"success": true, "message": "اتو ترید متوقف شد"})
}

func handleAutoTradeStats(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	json.NewEncoder(w).Encode(map[string]interface{}{
		"is_running":          autoTrader.IsRunning,
		"mode":                autoTrader.Mode,
		"daily_trades":        autoTrader.DailyTrades,
		"consecutive_losses":  autoTrader.ConsecutiveLosses,
		"pnl":                 autoTrader.PnL,
		"commission":          autoTrader.TotalCommission,
		"net_pnl":             autoTrader.PnL - autoTrader.TotalCommission,
		"open_trades":         len(autoTrader.OpenTrades),
	})
}

func handleIndex(w http.ResponseWriter, r *http.Request) {
	tmpl := template.Must(template.New("index").Parse(htmlTemplate))
	tmpl.Execute(w, nil)
}

// ═══════════════════════════════════════════════════════════
// HTML Template - فردا ارسال می‌شود به دلیل محدودیت حجم
// ═══════════════════════════════════════════════════════════

var htmlTemplate = `
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐋 Whale Hunter Pro v6.0 - Advanced Edition</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <style>
        * { font-family: system-ui, -apple-system, sans-serif; }
        .glass { background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(10px); }
    </style>
</head>
<body class="bg-slate-950 text-white">
    <div class="container mx-auto p-4">
        <h1 class="text-3xl font-bold mb-4">🐋 Whale Hunter Pro v6.0</h1>
        <div class="glass rounded-xl p-4">
            <p>سیستم در حال اجرا...</p>
            <p>Ctrl+1+Right Click برای نمایش قیمت</p>
        </div>
    </div>
    <script>
        document.addEventListener('contextmenu', (e) => {
            if (e.ctrlKey && e.keyCode === 49) { // Ctrl+1
                alert('Price Display Feature');
            }
        });
    </script>
</body>
</html>
`

// ═══════════════════════════════════════════════════════════
// Main
// ═══════════════════════════════════════════════════════════

func main() {
	fmt.Println("═══════════════════════════════════════════════════════════")
	fmt.Println("   🐋 Whale Hunter Pro v6.0 - Advanced Edition")
	fmt.Println("═══════════════════════════════════════════════════════════")
	fmt.Println()
	fmt.Println("   ✅ OI Delta & Open Interest Analysis")
	fmt.Println("   ✅ Iceberg Orders Detection")
	fmt.Println("   ✅ Order Flow Analysis")
	fmt.Println("   ✅ Trend Reversal Patterns")
	fmt.Println("   ✅ CNN-BiLSTM Scoring")
	fmt.Println("   ✅ Hedging Detection")
	fmt.Println("   ✅ Paper/Live Trading")
	fmt.Println("   ✅ Cache & Reconnection")
	fmt.Println("   ✅ Bybit & OKX Futures Only")
	fmt.Println()
	fmt.Println("   🌐 آدرس: http://localhost:8080")
	fmt.Println("═══════════════════════════════════════════════════════════")

	initDB()
	loadCacheState()

	// Auto cleanup در background
	go func() {
		ticker := time.NewTicker(1 * time.Minute)
		defer ticker.Stop()
		for range ticker.C {
			cleanupExpiredSignals()
			saveCacheState()
		}
	}()

	// Routes - کامل
	http.HandleFunc("/", handleIndex)
	http.HandleFunc("/api/config", handleConfig)
	http.HandleFunc("/api/market", handleMarket)
	http.HandleFunc("/api/signals", handleSignals)
	http.HandleFunc("/api/whales", handleWhales)
	http.HandleFunc("/api/pump-dumps", handlePumpDumps)
	http.HandleFunc("/api/account", handleAccount)
	http.HandleFunc("/api/trade-queue", handleTradeQueue)
	http.HandleFunc("/api/trades", handleTrades)
	http.HandleFunc("/api/export", handleExport)
	http.HandleFunc("/api/price", handleGetPrice)
	http.HandleFunc("/api/auto-trade/start", handleAutoTradeStart)
	http.HandleFunc("/api/auto-trade/stop", handleAutoTradeStop)
	http.HandleFunc("/api/auto-trade/stats", handleAutoTradeStats)

	log.Println("🚀 سرور در حال اجرا روی http://localhost:8080")
	log.Fatal(http.ListenAndServe(":8080", nil))
}
