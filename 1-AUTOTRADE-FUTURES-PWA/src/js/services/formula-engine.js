/**
 * موتور فرمول پارامتریک — محاسبهٔ امن فرمول سفارشی کاربر بدون eval/Function
 * ---------------------------------------------------------------------------
 * فرمول به‌صورت یک عبارت ریاضی/منطقی نوشته می‌شود و در لحظهٔ هر اسکن، با
 * مقادیر واقعی اندیکاتورها ارزیابی می‌شود. نتیجه در «الگویابی» سیستم لحاظ
 * می‌شود (حالت filter: شرط ورود + پاداش امتیاز).
 *
 * گرامر (از کم‌اهمیت به مهم‌ترین):
 *   ? :        سه‌تایی        cond ? a : b
 *   ||         یا منطقی
 *   &&         و منطقی
 *   == !=      تساوی / عدم تساوی
 *   < <= > >=  مقایسه
 *   + -        جمع و تفریق
 *   * / %      ضرب، تقسیم، باقیمانده
 *   ^          توان
 *   - !        منفی یکانی، نقیض
 *   اعداد (100، 1.5)، متغیرها (rsi, volX, ...)، پرانتز، توابع
 *
 * توابع: min(a,b,...) max(a,b,...) abs(x) clamp(x,lo,hi) if(cond,a,b) sign(x) round(x)
 * بولین‌ها به 1/0 تبدیل می‌شوند؛ تقسیم بر صفر یا خروجی بی‌نهایت = خطا.
 *
 * مثال‌ها:
 *   (rsi < 40 && volX > 1.4) || (rsi > 62 && movePct < -0.2)
 *   clamp((volX - 1) * 20 + (40 - rsi), 0, 30)
 *   if(emaFast > emaSlow, min(movePct * 25, 25), 0)
 */

const FUNCS = {
  min: (...args) => Math.min(...args),
  max: (...args) => Math.max(...args),
  abs: x => Math.abs(x),
  sign: x => Math.sign(x),
  round: (x, d = 0) => Number(Math.round(`${x}e${d}`) + `e-${d}`),
  clamp: (x, lo, hi) => Math.max(lo, Math.min(hi, x)),
  if: (cond, a, b) => (truthy(cond) ? a : b)
};

function truthy(v) {
  if (typeof v === 'boolean') return v;
  return Number(v) > 0;
}

// ---------- Tokenizer ----------
function tokenize(code) {
  const tokens = [];
  let i = 0;
  const isDigit = c => c >= '0' && c <= '9';
  const isIdentStart = c => /[A-Za-z_]/.test(c);
  const isIdent = c => /[A-Za-z0-9_]/.test(c);
  while (i < code.length) {
    const c = code[i];
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { i += 1; continue; }
    if (isDigit(c) || (c === '.' && isDigit(code[i + 1]))) {
      let j = i;
      while (j < code.length && (isDigit(code[j]) || code[j] === '.')) j += 1;
      tokens.push({ type: 'num', value: Number(code.slice(i, j)), pos: i });
      i = j;
      continue;
    }
    if (isIdentStart(c)) {
      let j = i;
      while (j < code.length && isIdent(code[j])) j += 1;
      tokens.push({ type: 'ident', value: code.slice(i, j), pos: i });
      i = j;
      continue;
    }
    const two = code.slice(i, i + 2);
    if (['<=', '>=', '==', '!=', '&&', '||'].includes(two)) {
      tokens.push({ type: two, pos: i });
      i += 2;
      continue;
    }
    if ('+-*/%^()<>!?:,'.includes(c)) {
      tokens.push({ type: c, pos: i });
      i += 1;
      continue;
    }
    throw { message: `کاراکتر نامعتبر «${c}» در فرمول`, pos: i };
  }
  return tokens;
}

// ---------- Parser (Recursive Descent) ----------
function parse(tokens) {
  let pos = 0;
  const peek = () => tokens[pos];
  const next = () => tokens[pos++];
  const expect = type => {
    const token = next();
    if (!token || token.type !== type) {
      throw { message: `انتظار «${type}» بود${token ? ` ولی «${token.type}» آمد` : ' ولی فرمول تمام شد'}`, pos: token ? token.pos : '(انتها)' };
    }
    return token;
  };

  const parseTernary = () => {
    const cond = parseOr();
    if (peek() && peek().type === '?') {
      next();
      const a = parseTernary();
      expect(':');
      const b = parseTernary();
      return { type: 'cond', cond, a, b };
    }
    return cond;
  };
  const parseOr = () => {
    let left = parseAnd();
    while (peek() && peek().type === '||') {
      next();
      left = { type: '||', left, right: parseAnd() };
    }
    return left;
  };
  const parseAnd = () => {
    let left = parseEquality();
    while (peek() && peek().type === '&&') {
      next();
      left = { type: '&&', left, right: parseEquality() };
    }
    return left;
  };
  const parseEquality = () => {
    let left = parseCompare();
    while (peek() && (peek().type === '==' || peek().type === '!=')) {
      const op = next().type;
      left = { type: op, left, right: parseCompare() };
    }
    return left;
  };
  const parseCompare = () => {
    let left = parseAdd();
    while (peek() && ['<', '<=', '>', '>='].includes(peek().type)) {
      const op = next().type;
      left = { type: op, left, right: parseAdd() };
    }
    return left;
  };
  const parseAdd = () => {
    let left = parseMul();
    while (peek() && (peek().type === '+' || peek().type === '-')) {
      const op = next().type;
      left = { type: op, left, right: parseMul() };
    }
    return left;
  };
  const parseMul = () => {
    let left = parseUnary();
    while (peek() && ['*', '/', '%'].includes(peek().type)) {
      const op = next().type;
      left = { type: op, left, right: parseUnary() };
    }
    return left;
  };
  const parseUnary = () => {
    if (peek() && peek().type === '-') {
      next();
      return { type: 'neg', arg: parseUnary() };
    }
    if (peek() && peek().type === '!') {
      next();
      return { type: '!', arg: parseUnary() };
    }
    return parsePower();
  };
  const parsePower = () => {
    const base = parsePrimary();
    if (peek() && peek().type === '^') {
      next();
      return { type: '^', left: base, right: parseUnary() };
    }
    return base;
  };
  const parsePrimary = () => {
    const token = next();
    if (!token) throw { message: 'فرمول ناقص است', pos: '(انتها)' };
    if (token.type === 'num') return { type: 'num', value: token.value };
    if (token.type === 'ident') {
      if (peek() && peek().type === '(') {
        next();
        const args = [];
        if (peek() && peek().type !== ')') {
          args.push(parseTernary());
          while (peek() && peek().type === ',') {
            next();
            args.push(parseTernary());
          }
        }
        expect(')');
        return { type: 'call', name: token.value, args };
      }
      return { type: 'var', name: token.value };
    }
    if (token.type === '(') {
      const inner = parseTernary();
      expect(')');
      return inner;
    }
    throw { message: `انتظار عدد/متغیر/پرانتز بود ولی «${token.type}» آمد`, pos: token.pos };
  };

  const ast = parseTernary();
  if (pos < tokens.length) {
    throw { message: `بخش اضافه بعد از پایان فرمول («${tokens[pos].type}»)`, pos: tokens[pos].pos };
  }
  return ast;
}

// ---------- Evaluator ----------
function evalNode(node, vars) {
  const num = n => {
    const v = evalNode(n, vars);
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (!Number.isFinite(v)) throw { message: 'نتیجهٔ میانی بی‌نهایت است (تقسیم بر صفر؟)' };
    return v;
  };
  switch (node.type) {
    case 'num': return node.value;
    case 'var': {
      if (!(node.name in vars)) throw { message: `متغیر ناشناخته: «${node.name}»` };
      const value = vars[node.name];
      if (typeof value === 'boolean') return value ? 1 : 0;
      if (value === undefined || value === null || !Number.isFinite(Number(value))) {
        throw { message: `مقدار متغیر «${node.name}» معتبر نیست` };
      }
      return Number(value);
    }
    case 'call': {
      const fn = FUNCS[node.name];
      if (!fn) throw { message: `تابع ناشناخته: «${node.name}»` };
      const args = node.args.map(arg => {
        const v = evalNode(arg, vars);
        return typeof v === 'boolean' ? (v ? 1 : 0) : v;
      });
      return fn(...args);
    }
    case 'neg': return -num(node.arg);
    case '!': return truthy(num(node.arg)) ? 0 : 1;
    case 'cond': return truthy(num(node.cond)) ? num(node.a) : num(node.b);
    case '||': return truthy(num(node.left)) || truthy(num(node.right)) ? 1 : 0;
    case '&&': return truthy(num(node.left)) && truthy(num(node.right)) ? 1 : 0;
    case '==': return (num(node.left) === num(node.right)) ? 1 : 0;
    case '!=': return (num(node.left) !== num(node.right)) ? 1 : 0;
    case '<': return num(node.left) < num(node.right) ? 1 : 0;
    case '<=': return num(node.left) <= num(node.right) ? 1 : 0;
    case '>': return num(node.left) > num(node.right) ? 1 : 0;
    case '>=': return num(node.left) >= num(node.right) ? 1 : 0;
    case '+': return num(node.left) + num(node.right);
    case '-': return num(node.left) - num(node.right);
    case '*': return num(node.left) * num(node.right);
    case '/': {
      const d = num(node.right);
      if (d === 0) throw { message: 'تقسیم بر صفر در فرمول' };
      return num(node.left) / d;
    }
    case '%': {
      const d = num(node.right);
      if (d === 0) throw { message: 'باقیمانده بر صفر در فرمول' };
      return num(node.left) % d;
    }
    case '^': return Math.pow(num(node.left), num(node.right));
    default: throw { message: 'گرهٔ ناشناخته در فرمول' };
  }
}

// ---------- API عمومی (با کش parse) ----------
const parseCache = new Map();

export function parseFormula(code) {
  const key = String(code || '').trim();
  if (!key) return null;
  if (parseCache.has(key)) return parseCache.get(key);
  const ast = parse(tokenize(key));
  parseCache.set(key, ast);
  return ast;
}

/** ارزیابی فرمول با متغیرهای واقعی؛ خروجی همیشه {ok, value, error} */
export function evaluateFormula(code, vars = {}) {
  try {
    const ast = parseFormula(code);
    if (!ast) return { ok: false, value: null, error: 'فرمول خالی است' };
    const value = evalNode(ast, vars);
    if (!Number.isFinite(value)) return { ok: false, value: null, error: 'نتیجهٔ فرمول عددی/متناهی نیست' };
    return { ok: true, value, error: null };
  } catch (error) {
    return { ok: false, value: null, error: error?.message || 'خطای ناشناخته در فرمول' };
  }
}

/** فقط بررسی صحت نگارشی فرمول (بدون نیاز به متغیرهای واقعی) */
export function validateFormula(code) {
  try {
    parseFormula(code);
    return { ok: String(code || '').trim().length > 0, error: null };
  } catch (error) {
    return { ok: false, error: error?.message || 'خطای ناشناخته' };
  }
}

/** کاتالوگ متغیرها برای نمایش در UI و مستندات */
export const FORMULA_VARIABLES = Object.freeze([
  { name: 'price', desc: 'آخرین قیمت زنده' },
  { name: 'movePct', desc: 'حرکت ٪ طی ۳ کندل آخر' },
  { name: 'oneCandlePct', desc: 'حرکت ٪ کندل آخر' },
  { name: 'volX', desc: 'حجم کندل آخر ÷ میانگین ۲۷ کندل قبل' },
  { name: 'atr', desc: 'ATR(14) قیمتی' },
  { name: 'atrPct', desc: 'ATR به‌درصد قیمت' },
  { name: 'rsi', desc: 'RSI(14) کندل‌های بسته' },
  { name: 'emaFast', desc: 'EMA(9)' },
  { name: 'emaSlow', desc: 'EMA(21)' },
  { name: 'emaRatio', desc: 'EMA9 ÷ EMA21 (بیش از ۱ = روند صعودی)' },
  { name: 'bodyPct', desc: 'اندازه بدنهٔ کندل آخر ٪' },
  { name: 'breakoutUp', desc: '۱ اگر شکست سقف ۲۲ کندل' },
  { name: 'breakoutDown', desc: '۱ اگر شکست کف ۲۲ کندل' },
  { name: 'trendUp', desc: '۱ اگر ۵ از ۷ کندل آخر صعودی' },
  { name: 'trendDown', desc: '۱ اگر ۵ از ۷ کندل آخر نزولی' },
  { name: 'microStreak', desc: 'طول استریک کندل‌های ریز هم‌جهت' },
  { name: 'microLong', desc: '۱ اگر استریک ریز صعودی' },
  { name: 'microShort', desc: '۱ اگر استریک ریز نزولی' },
  { name: 'hourUtc', desc: 'ساعت UTC کندل آخر (۰–۲۳)' },
  { name: 'buyRatio', desc: 'سهم خرید تیکری از حجم (فقط منبع Binance؛ ۰.۵=تعادل)' },
  { name: 'cvdDelta', desc: 'ΔCVD پنجره: خرید تیکری − فروش تیکری (مثبت=فشار خرید واقعی)' },
  { name: 'tradeAccel', desc: 'شتاب تعداد تریدها: کندل آخر ÷ میانگین پنجره' }
]);
