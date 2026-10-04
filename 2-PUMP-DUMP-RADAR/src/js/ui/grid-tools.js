/**
 * 🗂 ابزار دیتاگرید — فیلتر + سورت روی جدول‌های سیستم
 * ---------------------------------------------------------------------------
 * خواستهٔ داداش هادی: «امکان فیلتر و سورت روی دیتاگریدها مهیا باشه.»
 * این فایل خودکفاست (فقط DOM خالص، بدون وابستگی) و در view برای جدول‌های
 * پوزیشن‌ها و معاملات استفاده می‌شود. نسخهٔ مستقلی از همین فایل در pump-dump-lab
 * هم وجود دارد (هر پروژه کاملاً داخل خودش — قاعدهٔ جدایی پروژه‌ها).
 *
 * ساختار:
 *   new SimpleGrid({ tbodyId, columns, filters, getData, renderRow, emptyHtml, initialSort })
 *     - columns: [{ key, label, type:'text'|'number'|'time', sortable=true, thStyle? }]
 *     - filters: [{ id, key, label, type:'text'|'select', options:[v]|()=>[v], match:(row,val)=>bool }]
 *     - getData(): آرایهٔ ردیف‌های خام (هر رندر تازه خوانده می‌شود)
 *     - renderRow(row): html یک <tr>
 *   grid.render() بعد از هر تغییر داده/فیلتر/سورت صدا زده می‌شود.
 */

/** سورت خالص — قابل تست بدون DOM. dir: 1 صعودی، -1 نزولی */
export function applySort(rows, key, dir, type = 'text') {
  const val = row => {
    const v = row?.[key];
    if (type === 'number' || type === 'time') {
      const n = Number(v);
      return Number.isFinite(n) ? n : Number.NEGATIVE_INFINITY;
    }
    return String(v ?? '').toLowerCase();
  };
  return [...rows].sort((a, b) => {
    const va = val(a);
    const vb = val(b);
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return 0;
  });
}

/** فیلتر متنی خالص — جست‌وجوی بدون حساسیت به حروف در چند کلید */
export function applyTextFilter(rows, query, keys) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return [...rows];
  return rows.filter(row => keys.some(k => String(row?.[k] ?? '').toLowerCase().includes(q)));
}

const cssInjected = Symbol('grid-tools-css');
function injectCss(doc) {
  if (doc[cssInjected]) return;
  const style = doc.createElement('style');
  style.textContent = [
    '.grid-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0 2px}',
    '.grid-toolbar input,.grid-toolbar select{width:auto;min-width:110px;margin:0;padding:7px 10px;font-size:12px}',
    '.grid-toolbar .grid-count{color:var(--muted,#8ca3bd);font-size:11px;margin-inline-start:auto;white-space:nowrap}',
    'th.grid-sortable{cursor:pointer;user-select:none}',
    'th.grid-sortable:hover{color:var(--green,#35e0a1)}',
    'th .grid-arrow{font-size:9px;opacity:.9;margin-inline-start:3px}'
  ].join('\n');
  doc.head.appendChild(style);
  doc[cssInjected] = true;
}

export class SimpleGrid {
  constructor({ tbodyId, columns, filters = [], getData, renderRow, emptyHtml = '<tr><td colspan="1">—</td></tr>', initialSort = null, doc = document }) {
    this.doc = doc;
    this.tbody = doc.getElementById(tbodyId);
    if (!this.tbody) throw new Error(`SimpleGrid: tbody #${tbodyId} پیدا نشد`);
    this.table = this.tbody.closest('table');
    this.columns = columns;
    this.filters = filters;
    this.getData = getData;
    this.renderRow = renderRow;
    this.emptyHtml = emptyHtml;
    this.sortKey = initialSort?.key || null;
    this.sortDir = initialSort?.dir || -1;
    this.filterValues = {};
    injectCss(doc);
    this.buildToolbar();
    this.buildHead();
  }

  buildHead() {
    if (!this.table) return;
    const thead = this.table.querySelector('thead');
    if (!thead) return;
    thead.innerHTML = `<tr>${this.columns.map(col => {
      const style = col.thStyle ? ` style="${col.thStyle}"` : '';
      const sortable = col.sortable === false ? '' : ' grid-sortable';
      return `<th class="grid-th${sortable}" data-key="${col.key}"${style}>${col.label}<span class="grid-arrow" data-arrow></span></th>`;
    }).join('')}</tr>`;
    thead.querySelectorAll('.grid-sortable').forEach(th => {
      th.addEventListener('click', () => {
        const key = th.dataset.key;
        if (this.sortKey === key) this.sortDir = -this.sortDir;
        else { this.sortKey = key; this.sortDir = -1; }
        this.render();
      });
    });
  }

  buildToolbar() {
    const bar = this.doc.createElement('div');
    bar.className = 'grid-toolbar';
    for (const f of this.filters) {
      if (f.type === 'select') {
        const wrap = this.doc.createElement('label');
        wrap.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted,#8ca3bd)';
        const sel = this.doc.createElement('select');
        sel.dataset.filter = f.id;
        const opts = typeof f.options === 'function' ? f.options() : (f.options || []);
        wrap.textContent = f.label + ' ';
        sel.innerHTML = `<option value="">همه</option>` + opts.map(o => `<option value="${String(o).replace(/"/g, '&quot;')}">${String(o)}</option>`).join('');
        sel.onchange = () => { this.filterValues[f.id] = sel.value; this.render(); };
        wrap.appendChild(sel);
        bar.appendChild(wrap);
      } else {
        const input = this.doc.createElement('input');
        input.dataset.filter = f.id;
        input.placeholder = f.label;
        input.type = 'text';
        input.oninput = () => { this.filterValues[f.id] = input.value; this.render(); };
        bar.appendChild(input);
      }
    }
    this.countEl = this.doc.createElement('span');
    this.countEl.className = 'grid-count';
    bar.appendChild(this.countEl);
    // 🛡 ضدگلوله: نردبان هرگز نباید رندر بقیهٔ صفحه را بکشد
    try {
      const mountPoint = this.table?.parentElement || this.tbody;
      if (mountPoint.parentElement) mountPoint.parentElement.insertBefore(bar, mountPoint);
      else if (mountPoint.parentNode) mountPoint.parentNode.insertBefore(bar, mountPoint);
      else this.doc.body?.appendChild?.(bar);
    } catch {
      /* اگر mount نشد، بدون تولبار ادامه بده — سورت/فیلتر از طریق head仍在 کار می‌کند */
    }
  }

  filteredRows() {
    let rows = this.getData() || [];
    for (const f of this.filters) {
      const val = String(this.filterValues[f.id] ?? '').trim();
      if (!val) continue;
      rows = rows.filter(row => (f.match ? f.match(row, val) : String(row?.[f.key] ?? '').toLowerCase().includes(val.toLowerCase())));
    }
    if (this.sortKey) {
      const col = this.columns.find(c => c.key === this.sortKey);
      rows = applySort(rows, this.sortKey, this.sortDir, col?.type || 'text');
    }
    return rows;
  }

  render() {
    let rows = [];
    try {
      rows = this.filteredRows();
    } catch (error) {
      rows = this.getData() || [];
    }
    this.tbody.innerHTML = rows.map(row => this.renderRow(row)).join('') || this.emptyHtml;
    if (this.countEl) {
      const total = (this.getData() || []).length;
      this.countEl.textContent = `${rows.length} از ${total} ردیف`;
    }
    // نشانگر جهت سورت
    this.table?.querySelectorAll('.grid-th').forEach(th => {
      const arrow = th.querySelector('[data-arrow]');
      if (!arrow) return;
      arrow.textContent = th.dataset.key === this.sortKey ? (this.sortDir === 1 ? '▲' : '▼') : '';
    });
  }
}
