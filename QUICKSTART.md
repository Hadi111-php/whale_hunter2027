# 🚀 راهنمای سریع نصب و اجرا

## مرحله 1: نصب Go
```bash
# دانلود Go 1.21+ از https://go.dev/dl/
# یا در لینوکس:
wget https://go.dev/dl/go1.21.6.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go1.21.6.linux-amd64.tar.gz
export PATH=$PATH:/usr/local/go/bin
```

## مرحله 2: آماده‌سازی پروژه
```bash
# ایجاد دایرکتوری
mkdir whale-hunter-v6
cd whale-hunter-v6

# کپی فایل‌ها
# whale_hunter_v6.go را در این دایرکتوری قرار دهید

# ایجاد go.mod
go mod init whale-hunter
```

## مرحله 3: نصب وابستگی‌ها
```bash
# SQLite driver
go get github.com/mattn/go-sqlite3

# اگر خطای CGO داشتید:
# در ویندوز: نصب MinGW
# در لینوکس: sudo apt install build-essential
# در macOS: xcode-select --install
```

## مرحله 4: اجرا
```bash
# اجرای مستقیم
go run whale_hunter_v6.go

# یا ساخت فایل اجرایی
go build -o whale_hunter whale_hunter_v6.go
./whale_hunter
```

## مرحله 5: دسترسی
```
باز کردن مرورگر: http://localhost:8080
```

---

## ⚡ اجرای سریع (بدون نصب Go)

اگر فقط می‌خواهید UI را ببینید:
1. فایل `whale_hunter_ui.html` را باز کنید
2. توجه: بدون backend کار نمی‌کند، فقط نمای کلی UI را می‌بینید

---

## 🐛 عیب‌یابی سریع

### خطا: "gcc not found"
```bash
# ویندوز: نصب MinGW از https://mingw-w64.org/
# لینوکس: sudo apt install gcc
# macOS: xcode-select --install
```

### خطا: "cannot find package"
```bash
go clean -modcache
go get github.com/mattn/go-sqlite3
```

### خطا: "address already in use"
```bash
# پورت 8080 اشغال است
# تغییر پورت در کد: ":8080" → ":8081"
```

---

## 📋 چک‌لیست قبل از اجرا

- [ ] Go نسخه 1.21+ نصب شده
- [ ] GCC نصب شده (برای SQLite)
- [ ] فایل whale_hunter_v6.go در دایرکتوری پروژه
- [ ] دستور `go mod init` اجرا شده
- [ ] وابستگی‌ها نصب شده (`go get`)
- [ ] پورت 8080 آزاد است

---

## ⚙️ تنظیمات اولیه توصیه‌شده

1. ابتدا در **Paper Mode** تست کنید
2. مبلغ معامله را کم شروع کنید (مثلاً 5 USDT)
3. اهرم را زیاد 5x نگه دارید
4. حد ضرر را فعال نگه دارید

---

## 📞 پشتیبانی

در صورت بروز مشکل:
1. فایل `whale_hunter_v6.db` را حذف کنید
2. دوباره اجرا کنید
3. Log های terminal را بررسی کنید

---

**موفق باشید! 🚀**
