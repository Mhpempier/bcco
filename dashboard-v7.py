import streamlit as st
import pandas as pd
import plotly.express as px
import base64
import os

# ─── تنظیمات کلان صفحه ───────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="سامانه تحلیل داده‌های پتروشیمی",
    page_icon="🔵"
)

# ─── بارگذاری لوگو ───────────────────────────────────────────────────────────
def get_logo_base64(path="Capture.png"):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo_b64 = get_logo_base64()

# ─── استایل‌های سراسری ───────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;600;700&display=swap');

/* ── فونت سراسری فارسی ── */
html, body, [class*="st-"], .stMarkdown, .stText, button, input, select, label {
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
    direction: rtl;
}

/* ── هدر بنری ── */
/* گرادیانت: چپ فیزیکی = لوگو = روشن‌ترین / راست فیزیکی = متن = تاریک‌ترین */
.report-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(to right, #2563EB 0%, #1E3A8A 45%, #0f2057 100%);
    border-radius: 14px;
    padding: 18px 28px;
    margin-bottom: 10px;
    direction: ltr;   /* چیدمان LTR: لوگو اول (چپ روشن)، متن آخر (راست تاریک) */
    box-shadow: 0 4px 20px rgba(30,58,138,0.28);
}
.header-text { direction: rtl; text-align: right; }
.report-title {
    font-size: 22px !important;
    font-weight: 700;
    color: #ffffff;
    margin: 0;
    line-height: 1.5;
}
.report-subtitle {
    font-size: 12px;
    color: #bfdbfe;
    margin-top: 4px;
    font-weight: 400;
}
.unit-badge {
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.30);
    border-radius: 24px;
    padding: 6px 18px;
    font-size: 12px;
    color: #e0f2fe;
    white-space: nowrap;
    backdrop-filter: blur(6px);
}
/* لوگو در سمت چپ هدر (روشن‌ترین بخش گرادیانت) */
.logo-wrap { flex-shrink: 0; margin-left: 0; }

/* ── تب‌ها ── */
.stTabs [data-baseweb="tab"] {
    font-size: 15px;
    font-weight: 600;
    direction: rtl;
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
}

/* ── multiselect فارسی ── */
div.stMultiSelect { direction: rtl; text-align: right; }
div.stMultiSelect label { direction: rtl; text-align: right; }

/* ── دیتافریم ── */
[data-testid="stDataFrame"] { direction: ltr !important; }

/* ── فوتر ── */
footer { visibility: hidden; }
.footer-custom {
    text-align: center;
    color: #94a3b8;
    font-size: 11px;
    padding: 14px 0 6px 0;
    direction: rtl;
    border-top: 1px solid #e2e8f0;
    margin-top: 24px;
}

/* ── عنوان و تاریخ جدول ── */
/* تغییر ۳: عنوان راست، تاریخ وسط */
.matrix-title-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    direction: rtl;
    margin: 8px 0 4px 0;
    gap: 12px;
}
.matrix-title {
    font-size: 17px;
    font-weight: 700;
    color: #1E3A8A;
    direction: rtl;
    text-align: right;
    flex: 1;
}
.matrix-date-badge {
    font-size: 13px;
    font-weight: 600;
    color: #1e40af;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 20px;
    padding: 5px 16px;
    white-space: nowrap;
    text-align: center;
}
/* تغییر ۵: راهنمای بالای جدول */
.matrix-legend {
    direction: rtl;
    text-align: right;
    font-size: 12px;
    color: #475569;
    background: #f8fafc;
    border-right: 4px solid #1E3A8A;
    border-radius: 6px;
    padding: 8px 14px;
    margin-bottom: 10px;
    line-height: 2;
}
</style>
""", unsafe_allow_html=True)

# ─── هدر صفحه ────────────────────────────────────────────────────────────────
if logo_b64:
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height:68px;border-radius:8px;">'
else:
    logo_html = '<div style="width:68px;height:68px;background:rgba(255,255,255,.18);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:26px;">🔵</div>'

st.markdown(f"""
<div class="report-header">
  <div style="display:flex;align-items:center;gap:14px;flex-shrink:0;">
    <div class="logo-wrap">{logo_html}</div>
    <span class="unit-badge">واحد تحقیق و توسعه بازار</span>
  </div>
  <div class="header-text">
    <p class="report-title">سامانه تحلیلی و مدیریت قیمت‌های جهانی پتروشیمی (ICIS)</p>
    <p class="report-subtitle">داده‌های به‌روز هفتگی &nbsp;·&nbsp; نرخ‌های جهانی &nbsp;·&nbsp; تحلیل منطقه‌ای</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ─── اعتبارسنجی قیمت ────────────────────────────────────────────────────────
def is_valid_price(val):
    if pd.isna(val): return True
    s = str(val).strip()
    if s in ['', '-']: return True
    try:
        float(s)
        return True
    except ValueError:
        return False

# ─── بارگذاری سری زمانی ─────────────────────────────────────────────────────
@st.cache_data
def load_time_series_data():
    file_name = "ICIS Weekly Reports5-Jun.xls"
    df = pd.read_excel(file_name, sheet_name="Data", skiprows=2)
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    df = df.dropna(subset=['Date'])
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df[df['Date'].dt.year >= 2021]
    df = df.dropna(subset=['Date']).sort_values('Date')

    products = [
        'LDPE CFR China',
        'LLDPE CFR China',
        'HDPE Film CFR China',
        'HDPE BM CFR China',
        'HDPE Inj CFR China',
        'HDPE Inj>10 ',
        'HDPE Inj<10 CFR China',
        'Ethylene',
        'MEG CMP',
        'DEG CMP',
        'Methanol',
    ]
    products = [p for p in products if p in df.columns]
    for col in products:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df, products

# ─── بارگذاری گزارش هفتگی ────────────────────────────────────────────────────
@st.cache_data
def load_weekly_report_sheet_clean():
    file_name = "ICIS Weekly Reports5-Jun.xls"
    df_raw = pd.read_excel(file_name, sheet_name="GLOBAL PE PRICES ", header=None)

    import re as _re
    _raw_cell = df_raw.iloc[1, 0] if pd.notna(df_raw.iloc[1, 0]) else None

    def _format_date(dt):
        return f"{dt.day} {dt.strftime('%b')}, {dt.year}"

    if _raw_cell is None:
        report_date = "تاریخ نامشخص"
    elif isinstance(_raw_cell, pd.Timestamp):
        # سلول اکسل به صورت date object خوانده شده
        report_date = _format_date(_raw_cell)
    else:
        s = str(_raw_cell).replace("(", "").replace(")", "").strip()
        s = _re.sub(r'^Date[:\s]+', '', s, flags=_re.IGNORECASE).strip()

        # فرمت "Month, YYYY DD"  مثلاً "May, 2026 31" یا "Jun, 2026 5"
        m = _re.match(r'([A-Za-z]+),?\s+(\d{4})\s+(\d{1,2})', s)
        if m:
            try:
                _dt = pd.to_datetime(f"{m.group(3)} {m.group(1)} {m.group(2)}", dayfirst=True)
                report_date = _format_date(_dt)
            except Exception:
                report_date = s
        else:
            # تلاش عمومی برای فرمت‌های دیگر مانند "5-Jun, 2026" یا "31-May-2026"
            try:
                _dt = pd.to_datetime(s, dayfirst=True)
                report_date = _format_date(_dt)
            except Exception:
                report_date = s

    row3 = df_raw.iloc[3].ffill().fillna("")
    row4 = df_raw.iloc[4].fillna("")

    DISPLAY_NAMES = {
        'CHINA (CFR)':           'CHINA',
        'S.E.A. Du. (CFR)':      'S.E.A. Du.',
        'TURKEY':                'TURKEY (Mid.East)',
        'GCC (CFR)':             'GCC',
        'Emed (CFR)':            'Emed',
        'Pakistan (CFR)':        'Pakistan',
        'India Main Port (CFR)': 'India',
        'N.W.E. (FD)':           'N.W.E.',
        'NE Africa (CFR)':       'NE Africa',
        'Russia (CPT)':          'Russia',
    }

    regions_extracted = []
    seen_names = {}
    for i in range(3, df_raw.shape[1], 5):
        r3 = str(row3[i]).replace('\n', ' ').strip()
        r4 = str(row4[i]).replace('\n', ' ').strip()
        if r4 and r4 not in r3:
            reg_name = r3 + " - " + r4 if r3 else r4
        else:
            reg_name = r3
        if not reg_name or reg_name == "nan":
            continue
        base = reg_name
        if base in seen_names:
            seen_names[base] += 1
            reg_name = f"{base} ({seen_names[base]})"
        else:
            seen_names[base] = 1
        regions_extracted.append((i, reg_name))

    data = []
    cat, prod, grade = "", "", ""

    for i in range(7, df_raw.shape[0] - 1, 2):
        r1 = df_raw.iloc[i]
        r2 = df_raw.iloc[i + 1]

        r1_0 = str(r1[0]).strip() if pd.notna(r1[0]) else ""
        r1_1 = str(r1[1]).strip() if pd.notna(r1[1]) else ""
        r1_2 = str(r1[2]).strip() if pd.notna(r1[2]) else ""

        if r1_0:  cat = r1_0; prod = ""; grade = ""
        if r1_1:  prod = r1_1; grade = ""
        if r1_2:  grade = r1_2

        if not cat and not prod:
            continue

        for start_col, reg_name in regions_extracted:
            sc = start_col
            min_p     = r1[sc]     if sc < len(r1)   and pd.notna(r1[sc])   else None
            max_p     = r1[sc+3]   if sc+3 < len(r1) and pd.notna(r1[sc+3]) else None
            mid_p     = r2[sc+1]   if sc+1 < len(r2) and pd.notna(r2[sc+1]) else None
            delta_min = r2[sc]     if sc < len(r2)   and pd.notna(r2[sc])   else None
            # تغییر ۴: خواندن delta_MAX از offset+4 ردیف delta
            delta_max = r2[sc+4]   if sc+4 < len(r2) and pd.notna(r2[sc+4]) else None

            # فیلتر فرمول‌های اکسل که به صورت متن خوانده می‌شوند
            if isinstance(mid_p, str) and mid_p.startswith('='):
                mid_p = None

            if all(v is None or str(v).strip() in ['', '-'] for v in [min_p, max_p, mid_p]):
                continue
            if not all(is_valid_price(v) for v in [min_p, max_p, mid_p, delta_min, delta_max]):
                continue

            data.append({
                "دسته‌بندی":    cat,
                "فرآورده":      prod,
                "گرید":         grade if grade and grade != "-" else "",
                "منطقه / مبدأ": reg_name,
                "حداقل قیمت":   min_p,
                "میانگین قیمت": mid_p,
                "حداکثر قیمت":  max_p,
                "نوسان حداقل":  delta_min,
                "نوسان حداکثر": delta_max,
            })

    df_clean = pd.DataFrame(data).fillna("")
    col_order = ["دسته‌بندی", "فرآورده", "گرید", "منطقه / مبدأ",
                 "حداقل قیمت", "میانگین قیمت", "حداکثر قیمت",
                 "نوسان حداقل", "نوسان حداکثر"]
    df_clean = df_clean[col_order]
    return df_clean, report_date, DISPLAY_NAMES


# ─── ساخت ماتریس قیمت ───────────────────────────────────────────────────────
@st.cache_data
def build_price_matrix(df_sheet1):
    df = df_sheet1.copy()
    for col in ["حداقل قیمت", "حداکثر قیمت", "میانگین قیمت",
                "نوسان حداقل", "نوسان حداکثر"]:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    def make_label(row):
        parts = [row['دسته‌بندی'], row['فرآورده'], row['گرید']]
        return ' › '.join(p for p in parts if p)

    df['محصول'] = df.apply(make_label, axis=1)
    products_order = list(dict.fromkeys(df['محصول'].tolist()))
    regions_order  = list(dict.fromkeys(df['منطقه / مبدأ'].tolist()))

    def pt(col):
        return df.pivot_table(
            index='محصول', columns='منطقه / مبدأ',
            values=col, aggfunc='first'
        ).reindex(index=products_order, columns=regions_order)

    pivot_mid       = pt('میانگین قیمت')
    pivot_min       = pt('حداقل قیمت')
    pivot_max       = pt('حداکثر قیمت')
    pivot_dmin      = pt('نوسان حداقل')
    pivot_dmax      = pt('نوسان حداکثر')

    return pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax, products_order


# ─── رندر ماتریس ─────────────────────────────────────────────────────────────
def render_price_matrix(pivot_mid, pivot_min, pivot_max,
                        pivot_dmin, pivot_dmax, display_names=None):
    regions  = pivot_mid.columns.tolist()
    products = pivot_mid.index.tolist()

    mid_d  = pivot_mid.to_dict()
    mn_d   = pivot_min.to_dict()
    mx_d   = pivot_max.to_dict()
    dmin_d = pivot_dmin.to_dict()
    dmax_d = pivot_dmax.to_dict()

    # تغییر ۴: سلول شامل میانگین + بازه(min-max) + نوسان min + نوسان max
    table_style = """
    <style>
      .price-matrix {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Vazirmatn', Tahoma, sans-serif;
        font-size: 12px;
        table-layout: fixed;
      }
      .price-matrix thead th {
        background: #1E3A8A;
        color: #fff;
        padding: 9px 4px;
        text-align: center;
        white-space: normal;
        word-break: break-word;
        border: 1px solid #2d4fa0;
        font-size: 10.5px;
        line-height: 1.35;
        vertical-align: middle;
      }
      .price-matrix th.prod-header {
        text-align: right;
        direction: rtl;
        width: 175px;
        min-width: 155px;
      }
      .price-matrix th.reg-header {
        width: 108px;
        min-width: 90px;
      }
      .price-matrix tbody td {
        padding: 5px 3px;
        border: 1px solid #e5e7eb;
        text-align: center;
        vertical-align: middle;
        background: #fff;
      }
      .price-matrix tbody td.prod-cell {
        text-align: right;
        direction: rtl;
        font-weight: 600;
        color: #1e293b;
        background: #f8fafc;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        padding-right: 8px;
      }
      .price-matrix tbody tr:hover td { background: #f0f4ff !important; }

      /* ── محتوای هر سلول ── */
      .cell-mid   { font-size: 13px; font-weight: 700; color: #1e293b; display: block; }
      .cell-range { font-size: 10px; color: #64748b; display: block; margin: 1px 0; }
      /* نوسان‌ها: min و max کنار هم */
      .cell-deltas { display: flex; justify-content: center; gap: 4px; flex-wrap: wrap; font-size: 10px; }
      .d-up   { color: #16a34a; font-weight: 700; }
      .d-down { color: #dc2626; font-weight: 700; }
      .d-zero { color: #9ca3af; }
      .d-label { color: #94a3b8; font-size: 9px; }

      /* ── ردیف سرفصل دسته‌بندی ── */
      .section-divider td {
        background: #dbeafe !important;
        font-weight: 700;
        color: #1E3A8A;
        text-align: right;
        direction: rtl;
        padding: 6px 12px;
        font-size: 12px;
        border-top: 2px solid #1E3A8A;
        letter-spacing: 0.3px;
      }
    </style>
    """

    def fmt_delta(val, label):
        """یک نوسان را با برچسب MIN/MAX رندر می‌کند."""
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ''
        if v > 0:
            arrow = f'<span class="d-up">▲&thinsp;+{v:,.0f}</span>'
        elif v < 0:
            arrow = f'<span class="d-down">▼&thinsp;{v:,.0f}</span>'
        else:
            arrow = f'<span class="d-zero">◆&thinsp;0</span>'
        return f'<span class="d-label">{label}:</span>{arrow}'

    html = table_style + '<table class="price-matrix">\n<thead><tr>'
    html += '<th class="prod-header">محصول / گرید</th>'

    for reg in regions:
        short = reg
        if display_names:
            for k, v in display_names.items():
                if reg.startswith(k) or k in reg:
                    sfx = reg.replace(k, '').strip()
                    short = v + (' ' + sfx if sfx and sfx != '(1)' else '')
                    short = short.strip()
                    break
        short = (short.replace(' (CFR)', '').replace(' (FD)', '').replace(' (CPT)', '')
                      .replace('TURKEY - TURKEY', 'TURKEY')
                      .replace('India Main Port', 'India'))
        html += f'<th class="reg-header">{short}</th>'
    html += '</tr></thead>\n<tbody>\n'

    prev_cat = None
    for prod in products:
        cur_cat = prod.split(' › ')[0] if ' › ' in prod else prod
        if cur_cat != prev_cat:
            html += (f'<tr class="section-divider">'
                     f'<td colspan="{len(regions)+1}">{cur_cat}</td></tr>\n')
        prev_cat = cur_cat

        disp = ' › '.join(prod.split(' › ')[1:]) if ' › ' in prod else prod
        html += '<tr>'
        html += f'<td class="prod-cell">{disp}</td>'

        for reg in regions:
            mid  = mid_d.get(reg, {}).get(prod)
            mn   = mn_d.get(reg, {}).get(prod)
            mx   = mx_d.get(reg, {}).get(prod)
            dmin = dmin_d.get(reg, {}).get(prod)
            dmax = dmax_d.get(reg, {}).get(prod)

            def _nan(v):
                return v is None or (isinstance(v, float) and pd.isna(v))

            if _nan(mid):
                html += '<td><span style="color:#d1d5db;">—</span></td>'
                continue

            mid_str   = f"{mid:,.0f}"
            range_str = (f'<span class="cell-range">{mn:,.0f} – {mx:,.0f}</span>'
                         if not _nan(mn) and not _nan(mx) else '')

            d_min_str = fmt_delta(dmin, 'کف') if not _nan(dmin) else ''
            d_max_str = fmt_delta(dmax, 'سقف') if not _nan(dmax) else ''

            deltas_html = ''
            if d_min_str or d_max_str:
                deltas_html = (f'<div class="cell-deltas">'
                               f'{d_min_str}&nbsp;&nbsp;{d_max_str}</div>')

            html += (f'<td>'
                     f'<span class="cell-mid">{mid_str}</span>'
                     f'{range_str}'
                     f'{deltas_html}'
                     f'</td>')
        html += '</tr>\n'

    html += '</tbody></table>'
    return html


# ─── اجرای اصلی ──────────────────────────────────────────────────────────────
try:
    df_time, ts_products = load_time_series_data()
    df_sheet1, report_date, display_names = load_weekly_report_sheet_clean()
    pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax, _ = build_price_matrix(df_sheet1)

    # ── تب‌ها ──────────────────────────────────────────────────────────────────
    tab1, tab2 = st.tabs([
        "📊  روند زمانی قیمت محصولات",
        "📋  دیتابیس کامل گزارش هفتگی"
    ])

    # ════════════════════════════════════════════════════════════════════════════
    with tab1:

        # ── نمودار خطی ─────────────────────────────────────────────────────
        st.markdown(
            '<p style="font-size:17px;font-weight:700;color:#1E3A8A;'
            'direction:rtl;text-align:right;width:100%;margin-bottom:4px;">روند زمانی قیمت محصولات</p>',
            unsafe_allow_html=True
        )

        selected_products = st.multiselect(
            "فرآورده‌های مورد نظر برای نمایش در نمودار را انتخاب کنید:",
            options=ts_products,
            default=ts_products
        )

        if selected_products:
            fig = px.line(df_time, x='Date', y=selected_products, markers=False)
            fig.update_layout(
                template="plotly_white",
                hovermode="x unified",
                xaxis_title="توالی زمانی (هفتگی)",
                yaxis_title="قیمت (دلار / تن)",
                legend_title="",
                height=620,
                font=dict(family="Tahoma", size=13),
                hoverlabel=dict(bgcolor="white", font_size=14, font_family="Tahoma"),
                dragmode=False,
                clickmode="none",
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1),
                margin=dict(t=30, b=40)
            )
            fig.update_traces(
                hovertemplate="<b>%{y:,.1f} USD</b><extra></extra>",
                line=dict(width=2)
            )
            # رنگ اتیلن: مشکی با خط ضخیم
            if 'Ethylene' in selected_products:
                fig.for_each_trace(
                    lambda t: t.update(
                        line=dict(width=4.5, color='#000000'),
                        mode='lines+markers',
                        marker=dict(size=5, color='#000000', symbol='circle'),
                        name='<b>Ethylene ★</b>',
                    ) if t.name == 'Ethylene' else ()
                )
            fig.update_yaxes(tickformat=",.0f", showgrid=True, gridcolor="#f0f0f0")
            fig.update_xaxes(
                range=[df_time['Date'].min(), df_time['Date'].max()],
                rangeslider_visible=True,
                showgrid=True, gridcolor="#f0f0f0"
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── ماتریس قیمت هفتگی ──────────────────────────────────────────────
        st.divider()

        # تغییر ۳: عنوان راست‌چین، تاریخ وسط
        date_str =  "5 Jun, 2026"
        st.markdown(f"""
        <div class="matrix-title-bar">
          <span class="matrix-title">📌 گزارش ICIS از قیمت‌های جهانی محصولات</span>
          {'<span class="matrix-date-badge">📅 &nbsp;' + date_str + '</span>' if date_str else ''}
        </div>
        """, unsafe_allow_html=True)

        # تغییر ۵: راهنمای به‌روزشده
        st.markdown("""
        <div class="matrix-legend">
          هر سلول شامل: &nbsp;
          <b>میانگین قیمت</b> (USD/MT) &nbsp;|&nbsp;
          بازه <b>کف – سقف</b> قیمت &nbsp;|&nbsp;
          نوسان هفتگی <b>کف</b> و <b>سقف</b> نسبت به هفته قبل<br>
          <span style="color:#16a34a;font-weight:700;">▲ افزایش</span>&nbsp;&nbsp;
          <span style="color:#dc2626;font-weight:700;">▼ کاهش</span>&nbsp;&nbsp;
          <span style="color:#9ca3af;">◆ بدون تغییر</span>&nbsp;&nbsp;
          <span style="color:#94a3b8;">—  داده موجود نیست</span>
        </div>
        """, unsafe_allow_html=True)

        matrix_html = render_price_matrix(
            pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax, display_names
        )
        st.html(matrix_html)

    # ════════════════════════════════════════════════════════════════════════════
    with tab2:
        st.markdown(
            '<p style="font-size:17px;font-weight:700;color:#1E3A8A;'
            'direction:rtl;">دیتابیس کامل گزارش هفتگی ICIS</p>',
            unsafe_allow_html=True
        )
        if date_str:
            st.info(f"📅 تاریخ مرجع: {date_str}")

        numeric_cols = ["حداقل قیمت", "میانگین قیمت", "حداکثر قیمت",
                        "نوسان حداقل", "نوسان حداکثر"]
        for col in numeric_cols:
            df_sheet1[col] = pd.to_numeric(df_sheet1[col], errors='coerce')

        def color_delta(val):
            if pd.isna(val): return ''
            if val < 0:  return 'color: #dc2626; font-weight: bold;'
            if val > 0:  return 'color: #16a34a; font-weight: bold;'
            return 'color: #888888;'

        fmt_map = {
            "حداقل قیمت":   "{:,.1f}",
            "میانگین قیمت": "{:,.1f}",
            "حداکثر قیمت":  "{:,.1f}",
            "نوسان حداقل":  "{:+,.1f}",
            "نوسان حداکثر": "{:+,.1f}",
        }
        styled_df = (
            df_sheet1.style
            .hide(axis="index")
            .format(fmt_map, na_rep="—")
            .map(color_delta, subset=["نوسان حداقل", "نوسان حداکثر"])
        )
        st.dataframe(styled_df, use_container_width=True, height=700)

    # ── فوتر ─────────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="footer-custom">'
        '📊 سامانه تحلیلی قیمت‌های جهانی پتروشیمی &nbsp;|&nbsp;'
        ' تهیه‌شده توسط <b>واحد تحقیق و توسعه بازار</b> &nbsp;|&nbsp; B.C.Co'
        '</div>',
        unsafe_allow_html=True
    )

except Exception as e:
    st.error(f"خطا در پردازش اطلاعات: {e}")
