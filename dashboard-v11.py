import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import base64
import os
import io
import hashlib
import urllib.parse
from sqlalchemy import create_engine, text

# ─── تنظیمات کلان صفحه ───────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="سامانه تحلیل قیمت‌های پتروشیمی — v11.0",
    page_icon="🔵"
)

# ══════════════════════════════════════════════════════════════════════════════
# ─── AUTH HELPERS — SHA-256 + salt ───────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
_SALT = "bcco_petrochem_2026_salt"

def _hash_pw(plain: str) -> str:
    return hashlib.sha256(f"{_SALT}{plain}".encode()).hexdigest()

# ══════════════════════════════════════════════════════════════════════════════
# ─── FALLBACK STATIC DATA (used when database is offline) ────────────────────
# ══════════════════════════════════════════════════════════════════════════════
_FALLBACK_USERS = {
    "admin":   {"password_hash": _hash_pw("Admin@1234"),  "role_id": "Admin"},
    "analyst": {"password_hash": _hash_pw("Analyst@2024"), "role_id": "Analyst"},
    "guest":   {"password_hash": _hash_pw("Guest@0000"),  "role_id": "Guest"},
}

_FALLBACK_PERMISSIONS = {
    "Guest":   ["tab1"],
    "Analyst": ["tab1", "tab2", "tab3"],
    "Admin":   ["tab1", "tab2", "tab3", "admin"],
}

# ══════════════════════════════════════════════════════════════════════════════
# ─── DATABASE ENGINE BUILDER ────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def get_engine():
    """
    Build a SQLAlchemy engine from st.secrets or Supabase env vars.
    Handles special characters in passwords via URL encoding.
    """
    try:
        # Try Streamlit secrets first
        if "postgres" in st.secrets:
            cfg = st.secrets["postgres"]
            safe_password = urllib.parse.quote_plus(cfg['password'])
            url = (
                f"postgresql+psycopg2://{cfg['user']}:{safe_password}"
                f"@{cfg['host']}:{cfg.get('port', 5432)}/{cfg['dbname']}"
            )
            return create_engine(url, pool_pre_ping=True)
        elif "sql_server" in st.secrets:
            cfg = st.secrets["sql_server"]
            safe_password = urllib.parse.quote_plus(cfg['password'])
            url = (
                f"mssql+pyodbc://{cfg['user']}:{safe_password}"
                f"@{cfg['host']}/{cfg['dbname']}?driver=ODBC+Driver+17+for+SQL+Server"
            )
            return create_engine(url, pool_pre_ping=True)

        # Try Supabase environment variables
        supabase_url = os.environ.get("SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL")
        supabase_db_url = os.environ.get("SUPABASE_DB_URL")

        if supabase_db_url:
            # Direct connection string available
            return create_engine(supabase_db_url, pool_pre_ping=True)

        if supabase_url:
            # Parse Supabase URL to build connection string
            # Format: https://<project-ref>.supabase.co
            from urllib.parse import urlparse
            parsed = urlparse(supabase_url)
            project_ref = parsed.netloc.split('.')[0]
            # Supabase uses port 5432 direct connection
            # This requires the database password which should be in secrets
            pass

    except Exception as e:
        print(f"Database connection error: {e}")
    return None


def _run_query(engine, sql: str, params: dict | None = None):
    """Execute a parameterized SELECT and return a DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def _execute_sql(engine, sql: str, params: dict | None = None):
    """Execute a SQL statement (INSERT, UPDATE, DELETE) and return success."""
    try:
        with engine.connect() as conn:
            conn.execute(text(sql), params or {})
            conn.commit()
        return True
    except Exception as e:
        print(f"SQL execution error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ─── DATABASE TABLE INITIALIZATION ──────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def init_auth_tables(engine):
    """
    Initialize auth_users and auth_permissions tables if they don't exist.
    Pre-populate with default users and permissions if empty.
    Supports both PostgreSQL and MSSQL dialects.
    """
    if engine is None:
        return

    try:
        # Detect database dialect for cross-database compatibility
        dialect = engine.dialect.name

        # Set dialect-specific timestamp column definition
        if dialect == "mssql":
            timestamp_def = "DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()"
        else:
            # PostgreSQL and others
            timestamp_def = "TIMESTAMPTZ DEFAULT NOW()"

        # Create auth_users table with dialect-aware timestamp
        create_users_sql = f"""
        CREATE TABLE IF NOT EXISTS auth_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role_id TEXT NOT NULL,
            created_at {timestamp_def}
        )
        """
        _execute_sql(engine, create_users_sql)

        # Create auth_permissions table
        create_perms_sql = """
        CREATE TABLE IF NOT EXISTS auth_permissions (
            role_id TEXT PRIMARY KEY,
            allowed_tabs TEXT NOT NULL
        )
        """
        _execute_sql(engine, create_perms_sql)

        # Check if tables have data, if not populate defaults
        check_users = _run_query(engine, "SELECT COUNT(*) as cnt FROM auth_users")
        if check_users.iloc[0]['cnt'] == 0:
            # Insert default users with hashed passwords
            default_users = [
                ('admin', _hash_pw('Admin@1234'), 'Admin'),
                ('analyst', _hash_pw('Analyst@2024'), 'Analyst'),
                ('guest', _hash_pw('Guest@0000'), 'Guest'),
            ]
            for uname, pwhash, role in default_users:
                if dialect == "mssql":
                    # MSSQL uses IF NOT EXISTS pattern
                    insert_sql = """
                    IF NOT EXISTS (SELECT 1 FROM auth_users WHERE username = :username)
                    INSERT INTO auth_users (username, password_hash, role_id)
                    VALUES (:username, :password_hash, :role_id)
                    """
                else:
                    # PostgreSQL uses ON CONFLICT
                    insert_sql = """
                    INSERT INTO auth_users (username, password_hash, role_id)
                    VALUES (:username, :password_hash, :role_id)
                    ON CONFLICT (username) DO NOTHING
                    """
                _execute_sql(engine, insert_sql, {
                    'username': uname,
                    'password_hash': pwhash,
                    'role_id': role
                })

        check_perms = _run_query(engine, "SELECT COUNT(*) as cnt FROM auth_permissions")
        if check_perms.iloc[0]['cnt'] == 0:
            # Insert default permissions
            default_perms = [
                ('Admin', 'tab1,tab2,tab3,admin'),
                ('Analyst', 'tab1,tab2,tab3'),
                ('Guest', 'tab1'),
            ]
            for role, tabs in default_perms:
                if dialect == "mssql":
                    insert_sql = """
                    IF NOT EXISTS (SELECT 1 FROM auth_permissions WHERE role_id = :role_id)
                    INSERT INTO auth_permissions (role_id, allowed_tabs)
                    VALUES (:role_id, :allowed_tabs)
                    """
                else:
                    insert_sql = """
                    INSERT INTO auth_permissions (role_id, allowed_tabs)
                    VALUES (:role_id, :allowed_tabs)
                    ON CONFLICT (role_id) DO NOTHING
                    """
                _execute_sql(engine, insert_sql, {
                    'role_id': role,
                    'allowed_tabs': tabs
                })
    except Exception as e:
        print(f"Table initialization error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ─── DYNAMIC USER & PERMISSION LOADERS ───────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=60)
def load_users_from_db(_engine):
    """Load all users from database. Returns dict like _FALLBACK_USERS."""
    if _engine is None:
        return _FALLBACK_USERS.copy()

    try:
        df = _run_query(_engine, "SELECT username, password_hash, role_id FROM auth_users")
        if df.empty:
            return _FALLBACK_USERS.copy()
        users = {}
        for _, row in df.iterrows():
            users[row['username'].lower()] = {
                'password_hash': row['password_hash'],
                'role_id': row['role_id']
            }
        return users
    except Exception:
        return _FALLBACK_USERS.copy()


@st.cache_data(ttl=60)
def load_permissions_from_db(_engine):
    """Load permissions from database. Returns dict role_id -> list of tabs."""
    if _engine is None:
        return _FALLBACK_PERMISSIONS.copy()

    try:
        df = _run_query(_engine, "SELECT role_id, allowed_tabs FROM auth_permissions")
        if df.empty:
            return _FALLBACK_PERMISSIONS.copy()
        perms = {}
        for _, row in df.iterrows():
            tabs = [t.strip() for t in row['allowed_tabs'].split(',') if t.strip()]
            perms[row['role_id']] = tabs
        return perms
    except Exception:
        return _FALLBACK_PERMISSIONS.copy()


def authenticate(username: str, password: str, engine=None):
    """
    Authenticate user against database or fallback static data.
    Returns role_id if valid, None otherwise.
    """
    users = load_users_from_db(engine)
    user = users.get(username.strip().lower())
    if user and user["password_hash"] == _hash_pw(password):
        return user["role_id"]
    return None


def get_allowed_tabs(role_id: str, engine=None):
    """Get allowed tabs for a role from database."""
    perms = load_permissions_from_db(engine)
    return perms.get(role_id, ["tab1"])


# ══════════════════════════════════════════════════════════════════════════════
# ─── USER MANAGEMENT FUNCTIONS ───────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def add_user_to_db(engine, username: str, password: str, role_id: str):
    """Add a new user to the database. Returns (success, message)."""
    if engine is None:
        return False, "پایگاه داده در دسترس نیست."

    try:
        uname = username.strip().lower()
        pwhash = _hash_pw(password)

        # Check if user already exists
        existing = _run_query(
            engine,
            "SELECT username FROM auth_users WHERE username = :username",
            {'username': uname}
        )
        if not existing.empty:
            return False, "نام کاربری قبلاً وجود دارد."

        insert_sql = """
        INSERT INTO auth_users (username, password_hash, role_id)
        VALUES (:username, :password_hash, :role_id)
        """
        success = _execute_sql(engine, insert_sql, {
            'username': uname,
            'password_hash': pwhash,
            'role_id': role_id
        })

        if success:
            # Clear cache
            load_users_from_db.clear()
            return True, f"کاربر '{uname}' با نقش '{role_id}' با موفقیت افزودن شد."
        return False, "خطا در ذخیره‌سازی داده‌ها."
    except Exception as e:
        return False, f"خطا: {str(e)}"


def delete_user_from_db(engine, username: str, current_user: str):
    """Delete a user from database. Returns (success, message)."""
    if engine is None:
        return False, "پایگاه داده در دسترس نیست."

    uname = username.strip().lower()

    # Prevent self-deletion
    if uname == current_user.strip().lower():
        return False, "نمی‌توانید حساب کاربری خود را حذف کنید."

    try:
        delete_sql = "DELETE FROM auth_users WHERE username = :username"
        success = _execute_sql(engine, delete_sql, {'username': uname})

        if success:
            load_users_from_db.clear()
            return True, f"کاربر '{uname}' با موفقیت حذف شد."
        return False, "خطا در حذف کاربر."
    except Exception as e:
        return False, f"خطا: {str(e)}"


def update_permissions_in_db(engine, role_id: str, allowed_tabs: str):
    """Update permissions for a role. Returns (success, message)."""
    if engine is None:
        return False, "پایگاه داده در دسترس نیست."

    try:
        update_sql = """
        UPDATE auth_permissions
        SET allowed_tabs = :allowed_tabs
        WHERE role_id = :role_id
        """
        success = _execute_sql(engine, update_sql, {
            'role_id': role_id,
            'allowed_tabs': allowed_tabs
        })

        if success:
            load_permissions_from_db.clear()
            return True, f"دسترسی‌های نقش '{role_id}' به‌روز شد."
        return False, "خطا در به‌روزرسانی دسترسی‌ها."
    except Exception as e:
        return False, f"خطا: {str(e)}"


def get_all_users_df(engine):
    """Get all users as a DataFrame for display."""
    if engine is None:
        # Return fallback data
        df = pd.DataFrame([
            {'username': k, 'role_id': v['role_id']}
            for k, v in _FALLBACK_USERS.items()
        ])
        return df

    try:
        df = _run_query(
            engine,
            "SELECT username, role_id, created_at FROM auth_users ORDER BY username"
        )
        return df
    except Exception:
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# ─── INITIALIZE DATABASE & SESSION STATE ─────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

# Get engine and initialize tables
_engine = get_engine()
init_auth_tables(_engine)

# Session state init
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.session_state.role = ""

# ══════════════════════════════════════════════════════════════════════════════
# ─── GLOBAL CSS ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;600;700&display=swap');

html, body, .stMarkdown, .stText, button, input, select, label,
div[data-testid="stMetricValue"],
div[data-testid="stMetricLabel"] {
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
    direction: rtl;
    text-align: right;
}

div[data-testid="stMetricDelta"], div[data-testid="stMetricDelta"] * {
    direction: ltr !important;
    unicode-bidi: bidi-override !important;
    text-align: right !important;
}

/* ── هدر بنری ── */
.report-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 25%, #1d4ed8 65%, #1e3a8a 100%);
    border-radius: 16px;
    padding: 18px 28px;
    margin-bottom: 12px;
    direction: ltr;
    box-shadow: 0 6px 24px rgba(30,58,138,0.30);
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
.v-badge {
    background: rgba(255,255,255,0.20);
    border: 1px solid rgba(255,255,255,0.35);
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 11px;
    color: #e0f2fe;
    font-weight: 700;
    margin-right: 8px;
}

/* ── User Status Bar ── */
.user-status-bar {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 16px;
    direction: rtl;
    padding: 10px 16px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    margin-bottom: 12px;
}
.user-status-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: #334155;
}
.user-status-label {
    color: #64748b;
    font-weight: 500;
}
.user-status-value {
    font-weight: 700;
    color: #1e293b;
}
.role-badge-admin  { background:#dbeafe; color:#1e3a8a; border-radius:6px; padding:2px 10px; font-size:12px; font-weight:700; }
.role-badge-analyst{ background:#dcfce7; color:#166534; border-radius:6px; padding:2px 10px; font-size:12px; font-weight:700; }
.role-badge-guest  { background:#f1f5f9; color:#64748b; border-radius:6px; padding:2px 10px; font-size:12px; font-weight:700; }

/* ── کارت‌های متریک ── */
div[data-testid="stMetric"] {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 10px 14px !important;
    box-shadow: 0 1px 6px rgba(0,0,0,0.06);
    text-align: right !important;
    direction: rtl;
}
div[data-testid="stMetricLabel"] {
    font-size: 10px !important;
    color: #94a3b8 !important;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
div[data-testid="stMetricValue"] {
    font-size: 18px !important;
    font-weight: 700 !important;
    color: #1e293b !important;
}
div[data-testid="stMetricDelta"] svg { display: none !important; }

/* ── تب‌ها ── */
.stTabs [data-baseweb="tab"] {
    font-size: 14px;
    font-weight: 600;
    direction: rtl;
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
    padding: 8px 16px !important;
    height: auto !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    line-height: 1.6 !important;
}
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [aria-selected="true"] {
    background: #1e3a8a !important;
    color: white !important;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(30, 58, 138, 0.2);
}

/* ── ماتریس قیمت ── */
.matrix-title-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    direction: rtl;
    margin: 10px 0 6px 0;
    gap: 12px;
}
.matrix-title { font-size: 17px; font-weight: 700; color: #1E3A8A; }
.matrix-date-badge {
    font-size: 13px;
    font-weight: 600;
    color: #1e40af;
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 20px;
    padding: 5px 16px;
}
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

/* ─ـ فیلتر دسته‌بندی ── */
.cat-filter-bar { display: flex; gap: 8px; direction: rtl; margin-bottom: 10px; }
.cat-btn {
    padding: 6px 20px; border-radius: 20px; font-size: 12px; font-weight: 700;
    border: 2px solid #1e3a8a; cursor: pointer;
    font-family: 'Vazirmatn', Tahoma, sans-serif; transition: all 0.15s;
}
.cat-btn-active { background: #1e3a8a; color: #fff; }
.cat-btn-inactive { background: #fff; color: #1e3a8a; }

/* ─ـ multiselect ── */
div.stMultiSelect { direction: rtl; text-align: right; }
div.stMultiSelect label { direction: rtl; text-align: right; }

/* ─ـ دیتافریم ── */
[data-testid="stDataFrame"] th {
    direction: rtl !important;
    text-align: right !important;
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
}
[data-testid="stDataFrame"] td {
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
}

/* ─ـ سکشن عنوان ── */
.section-header {
    font-size: 17px; font-weight: 700; color: #1E3A8A;
    direction: rtl; text-align: right;
    padding: 6px 0 4px 0;
    border-bottom: 2px solid #e2e8f0;
    margin-bottom: 12px;
}

/* ─ـ تحلیل آماری ─ـ */
.stat-card {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 14px 16px; text-align: right; direction: rtl;
    box-shadow: 0 1px 6px rgba(0,0,0,0.05);
}
.stat-card-title { font-size: 11px; color: #94a3b8; font-weight: 500; margin-bottom: 6px; }
.stat-card-value { font-size: 20px; font-weight: 700; color: #1e293b; }
.stat-card-change { font-size: 12px; font-weight: 700; margin-top: 4px; }

/* ─ـ فرم ورود ── */
.login-card {
    max-width: 420px;
    margin: 60px auto 0 auto;
    background: #fff;
    border-radius: 18px;
    padding: 36px 32px 28px 32px;
    box-shadow: 0 8px 32px rgba(30,58,138,0.13);
    border: 1px solid #e2e8f0;
    direction: rtl;
}
.login-title {
    font-size: 22px;
    font-weight: 700;
    color: #1e3a8a;
    text-align: center;
    margin-bottom: 6px;
}
.login-subtitle {
    font-size: 12px;
    color: #94a3b8;
    text-align: center;
    margin-bottom: 22px;
}

/* ─ـ دکمه ورود مهمان (داخل کارت) ── */
.guest-login-btn {
    margin-top: 16px;
    padding: 12px 20px;
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    border: none;
    border-radius: 10px;
    color: white;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    text-align: center;
    transition: all 0.2s;
    box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
}
.guest-login-btn:hover {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
    transform: translateY(-1px);
}

.guest-divider {
    display: flex;
    align-items: center;
    margin: 20px 0 12px 0;
    color: #94a3b8;
    font-size: 12px;
}
.guest-divider::before,
.guest-divider::after {
    content: "";
    flex: 1;
    border-bottom: 1px solid #e2e8f0;
}
.guest-divider::before { margin-left: 12px; }
.guest-divider::after { margin-right: 12px; }

/* ─ـ پنل مدیریت کاربران ─ـ */
.admin-panel-card {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 16px 18px;
    margin-bottom: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
.admin-panel-title {
    font-size: 15px;
    font-weight: 700;
    color: #1e3a8a;
    direction: rtl;
    text-align: right;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid #e2e8f0;
}
.db-status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
}
.db-online { background: #dcfce7; color: #166534; }
.db-offline { background: #fee2e2; color: #dc2626; }

/* ─ـ فوتر ─ـ */
footer { visibility: hidden; }
.footer-custom {
    text-align: center; color: #94a3b8; font-size: 11px;
    padding: 14px 0 6px 0; direction: rtl;
    border-top: 1px solid #e2e8f0; margin-top: 24px;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ─── LOGIN GATE (v11.0: Guest button INSIDE the card) ─────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.authenticated:
    st.markdown("""
    <div class="login-card">
        <div class="login-title">🔵 ورود به سامانه</div>
        <div class="login-subtitle">سامانه تحلیلی قیمت‌های جهانی پتروشیمی (ICIS) — v11.0</div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form", clear_on_submit=False):
        st.markdown("<br>", unsafe_allow_html=True)
        col_l, col_c, col_r = st.columns([1, 2, 1])
        with col_c:
            username = st.text_input("نام کاربری", placeholder="username")
            password = st.text_input("رمز عبور", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("ورود  →", use_container_width=True)

        if submitted:
            role = authenticate(username, password, _engine)
            if role:
                st.session_state.authenticated = True
                st.session_state.username = username.strip().lower()
                st.session_state.role = role
                st.rerun()
            else:
                st.error("نام کاربری یا رمز عبور نادرست است.")

    # ── Guest login button INSIDE the card (below form) ───────────────────────
    st.markdown("""
    <div style="max-width:420px;margin:0 auto;padding:0 32px;">
        <div class="guest-divider">یا</div>
    </div>
    """, unsafe_allow_html=True)

    col_l_g, col_c_g, col_r_g = st.columns([1, 2, 1])
    with col_c_g:
        if st.button("✨ ورود سریع به عنوان مهمان (دسترسی محدود)", use_container_width=True, type="primary"):
            st.session_state.authenticated = True
            st.session_state.username = "guest_user"
            st.session_state.role = "Guest"
            st.rerun()

    st.markdown("""
    <div style="text-align:center;color:#94a3b8;font-size:11px;margin-top:24px;direction:rtl;">
        جهت دریافت اکانت اختصاصی با مدیر سیستم تماس بگیرید.
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# ─── AUTHENTICATED AREA (v11.0: NO SIDEBAR) ───────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

current_role = st.session_state.role
allowed_tabs = get_allowed_tabs(current_role, _engine)

# ─── بارگذاری لوگو ────────────────────────────────────────────────────────────
def get_logo_base64(path="Capture.png"):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo_b64 = get_logo_base64()

if logo_b64:
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="height:64px;border-radius:8px;">'
else:
    logo_html = '<div style="width:56px;height:56px;background:rgba(255,255,255,.18);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;">🔵</div>'

# ─── Banner with User Status (v11.0: Top-right user info in banner area) ─────
role_colors = {"Admin": "role-badge-admin", "Analyst": "role-badge-analyst", "Guest": "role-badge-guest"}
badge_class = role_colors.get(current_role, "role-badge-guest")
db_status = "آنلاین" if _engine is not None else "آفلاین"
db_class = "db-online" if _engine is not None else "db-offline"

st.markdown(f"""
<div class="report-header">
  <div style="display:flex;align-items:center;gap:14px;flex-shrink:0;">
    <div>{logo_html}</div>
    <span class="unit-badge">واحد تحقیق و توسعه بازار</span>
  </div>
  <div class="header-text">
    <div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;">
      <p class="report-title">سامانه تحلیلی و مدیریت قیمت‌های جهانی پتروشیمی (ICIS)</p>
      <span class="v-badge">v11.0</span>
    </div>
    <p class="report-subtitle">داده‌های به‌روز هفتگی &nbsp;·&nbsp; نرخ‌های جهانی &nbsp;·&nbsp; تحلیل منطقه‌ای</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ─── User Status Bar (v11.0: Horizontal layout below banner) ─────────────────
col_status_1, col_status_2, col_status_3, col_status_4, col_status_5 = st.columns([2, 1.5, 1.5, 1, 1])

with col_status_1:
    st.markdown(f"""
    <div class="user-status-item">
        <span class="user-status-label">👤 کاربر:</span>
        <span class="user-status-value">{st.session_state.username}</span>
        <span class="{badge_class}">{current_role}</span>
    </div>
    """, unsafe_allow_html=True)

with col_status_2:
    st.markdown(f"""
    <div class="user-status-item">
        <span class="user-status-label">پایگاه داده:</span>
        <span class="db-status-badge {db_class}">{db_status}</span>
    </div>
    """, unsafe_allow_html=True)

with col_status_3:
    st.empty()

with col_status_4:
    st.empty()

with col_status_5:
    if st.button("خروج از سیستم", use_container_width=True, type="secondary"):
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.session_state.role = ""
        st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# ─── DATA LOADING ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600)
def load_time_series_data():
    engine = get_engine()
    if engine is not None:
        try:
            sql = """
                SELECT
                    "Date",
                    "LDPE CFR China",
                    "LLDPE CFR China",
                    "HDPE Film CFR China",
                    "HDPE BM CFR China",
                    "HDPE Inj CFR China",
                    "HDPE Inj>10 ",
                    "HDPE Inj<10 CFR China",
                    "Ethylene",
                    "MEG CMP",
                    "DEG CMP",
                    "Methanol"
                FROM time_series_data
                WHERE "Date" >= :since
                ORDER BY "Date"
            """
            df = _run_query(engine, sql, {"since": "2021-01-01"})
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"]).sort_values("Date")
            products = [
                c for c in [
                    "LDPE CFR China", "LLDPE CFR China",
                    "HDPE Film CFR China", "HDPE BM CFR China", "HDPE Inj CFR China",
                    "HDPE Inj>10 ", "HDPE Inj<10 CFR China",
                    "Ethylene", "MEG CMP", "DEG CMP", "Methanol",
                ] if c in df.columns
            ]
            for col in products:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df, products
        except Exception:
            pass

    # ── demo fallback ─────────────────────────────────────────────────────────
    dates = pd.date_range("2021-01-01", periods=270, freq="W")
    rng = np.random.default_rng(42)
    products = [
        "LDPE CFR China", "LLDPE CFR China",
        "HDPE Film CFR China", "HDPE BM CFR China", "HDPE Inj CFR China",
        "HDPE Inj>10 ", "HDPE Inj<10 CFR China",
        "Ethylene", "MEG CMP", "DEG CMP", "Methanol",
    ]
    base = {"LDPE CFR China": 950, "LLDPE CFR China": 920,
            "HDPE Film CFR China": 980, "HDPE BM CFR China": 1000,
            "HDPE Inj CFR China": 1050, "HDPE Inj>10 ": 1080,
            "HDPE Inj<10 CFR China": 1020,
            "Ethylene": 700, "MEG CMP": 550, "DEG CMP": 620, "Methanol": 320}
    data = {"Date": dates}
    for p in products:
        walk = rng.normal(0, 12, len(dates)).cumsum()
        data[p] = np.clip(base[p] + walk, 200, 2500)
    df = pd.DataFrame(data)
    return df, products


@st.cache_data(ttl=600)
def load_weekly_report_sheet_clean():
    engine = get_engine()
    DISPLAY_NAMES = {
        "CHINA (CFR)":           "CHINA",
        "S.E.A. Du. (CFR)":      "S.E.A. Du.",
        "TURKEY":                "TURKEY (Mid.East)",
        "GCC (CFR)":             "GCC",
        "Emed (CFR)":            "Emed",
        "Pakistan (CFR)":        "Pakistan",
        "India Main Port (CFR)": "India",
        "N.W.E. (FD)":           "N.W.E.",
        "NE Africa (CFR)":       "NE Africa",
        "Russia (CPT)":          "Russia",
        "N.W.E. - N.W.E. (FD)":  "N.W.E. (FD)",
        "N.W.E. - N.W.E. (CIF)": "N.W.E. (CIF)",
        "R'dam (FOB)":           "R'dam (FOB)",
    }

    if engine is not None:
        try:
            sql = """
                SELECT
                    category         AS "دسته‌بندی",
                    product          AS "فرآورده",
                    grade            AS "گرید",
                    region           AS "منطقه / مبدأ",
                    price_min        AS "حداقل قیمت",
                    price_mid        AS "میانگین قیمت",
                    price_max        AS "حداکثر قیمت",
                    delta_min        AS "نوسان حداقل",
                    delta_max        AS "نوسان حداکثر",
                    report_date
                FROM weekly_report_data
                WHERE report_date = (SELECT MAX(report_date) FROM weekly_report_data)
                ORDER BY category, product, grade, region
            """
            df = _run_query(engine, sql)
            report_date = "—"
            if "report_date" in df.columns and len(df) > 0:
                rd = df["report_date"].iloc[0]
                try:
                    report_date = pd.Timestamp(rd).strftime("%-d %b, %Y")
                except Exception:
                    report_date = str(rd)
            df = df.drop(columns=["report_date"], errors="ignore")
            col_order = ["دسته‌بندی", "فرآورده", "گرید", "منطقه / مبدأ",
                         "حداقل قیمت", "میانگین قیمت", "حداکثر قیمت",
                         "نوسان حداقل", "نوسان حداکثر"]
            for c in col_order:
                if c not in df.columns:
                    df[c] = None
            return df[col_order].fillna(""), report_date, DISPLAY_NAMES
        except Exception:
            pass

    # ── demo fallback ─────────────────────────────────────────────────────────
    rng = np.random.default_rng(7)
    regions = ["CHINA (CFR)", "GCC (CFR)", "TURKEY", "N.W.E. (FD)", "S.E.A. Du. (CFR)"]
    rows = []
    for cat, prod, grade in [
        ("POLYMERS", "LDPE", "Film"), ("POLYMERS", "LLDPE", "Film"),
        ("POLYMERS", "HDPE", "BM"), ("POLYMERS", "HDPE", "INJ"),
        ("CHEMICALS", "MEG", ""), ("CHEMICALS", "DEG", ""), ("CHEMICALS", "Methanol", ""),
    ]:
        for reg in regions:
            mid = rng.uniform(600, 1400)
            delta = rng.uniform(-30, 30)
            rows.append({
                "دسته‌بندی": cat, "فرآورده": prod, "گرید": grade,
                "منطقه / مبدأ": reg,
                "حداقل قیمت": round(mid - 20, 1),
                "میانگین قیمت": round(mid, 1),
                "حداکثر قیمت": round(mid + 20, 1),
                "نوسان حداقل": round(delta - 5, 1),
                "نوسان حداکثر": round(delta + 5, 1),
            })
    df = pd.DataFrame(rows)
    return df, "20 Jun, 2026", DISPLAY_NAMES


# ══════════════════════════════════════════════════════════════════════════════
# ─── PRICE MATRIX ────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def build_price_matrix(df_sheet1):
    df = df_sheet1.copy()
    for col in ["حداقل قیمت", "حداکثر قیمت", "میانگین قیمت",
                "نوسان حداقل", "نوسان حداکثر"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def make_label(row):
        parts = [row["دسته‌بندی"], row["فرآورده"], row["گرید"]]
        return " › ".join(p for p in parts if p)

    df["محصول"] = df.apply(make_label, axis=1)
    products_order = list(dict.fromkeys(df["محصول"].tolist()))
    regions_order  = list(dict.fromkeys(df["منطقه / مبدأ"].tolist()))

    def pt(col):
        return df.pivot_table(
            index="محصول", columns="منطقه / مبدأ",
            values=col, aggfunc="first"
        ).reindex(index=products_order, columns=regions_order)

    pivot_mid  = pt("میانگین قیمت")
    pivot_min  = pt("حداقل قیمت")
    pivot_max  = pt("حداکثر قیمت")
    pivot_dmin = pt("نوسان حداقل")
    pivot_dmax = pt("نوسان حداکثر")
    cat_map = df.drop_duplicates("محصول").set_index("محصول")["دسته‌بندی"].to_dict()
    return pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax, products_order, cat_map


# ══════════════════════════════════════════════════════════════════════════════
# ─── PRICE MATRIX HTML RENDERER ──────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def render_price_matrix(pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax,
                        cat_map=None, display_names=None, cat_target=None):
    regions  = pivot_mid.columns.tolist()
    products = pivot_mid.index.tolist()

    if cat_target and cat_map:
        products = [p for p in products if cat_map.get(p, "") == cat_target]
    if products:
        regions = [r for r in regions if pivot_mid.loc[products, r].notna().any()]

    mid_d  = pivot_mid.to_dict()
    mn_d   = pivot_min.to_dict()
    mx_d   = pivot_max.to_dict()
    dmin_d = pivot_dmin.to_dict()
    dmax_d = pivot_dmax.to_dict()

    table_style = """
    <style>
      .price-matrix {
        width: 100%; border-collapse: collapse;
        font-family: 'Vazirmatn', Tahoma, sans-serif;
        font-size: 12px; table-layout: fixed;
      }
      .price-matrix thead th {
        position: sticky; top: 0; z-index: 10;
        background: #1e3a8a; color: #fff;
        padding: 10px 4px; text-align: center;
        white-space: normal; word-break: break-word;
        border: 1px solid #2d4fa0; font-size: 10.5px;
        line-height: 1.4; vertical-align: middle;
      }
      .price-matrix th.prod-header {
        text-align: right; direction: rtl;
        width: 200px; min-width: 175px;
      }
      .price-matrix th.reg-header { width: 130px; min-width: 110px; }
      .price-matrix tbody td {
        padding: 5px 3px; border: 1px solid #e5e7eb;
        text-align: center; vertical-align: middle; transition: background 0.15s;
      }
      .price-matrix tbody td.prod-cell {
        text-align: right; direction: rtl; font-weight: 600;
        color: #1e293b; background: #f8fafc !important;
        white-space: nowrap; overflow: hidden;
        text-overflow: ellipsis; padding-right: 8px;
      }
      .price-matrix tbody tr:hover td { filter: brightness(0.96); }
      .cell-mid   { font-size: 13px; font-weight: 700; color: #1e293b; display: block; }
      .cell-range { font-size: 10px; color: #64748b; display: block; margin: 1px 0; }
      .cell-deltas { display: flex; justify-content: center; gap: 4px; flex-wrap: wrap; font-size: 10px; line-height: 1.6; }
      .d-up   { color: #16a34a; font-weight: 700; direction: ltr; display: inline-block; }
      .d-down { color: #dc2626; font-weight: 700; direction: ltr; display: inline-block; }
      .d-zero { color: #9ca3af; direction: ltr; display: inline-block; }
      .d-label { color: #94a3b8; font-size: 9px; margin-left: 1px; }
      .cell-bg-up   { background: rgba(16,185,129,0.06) !important; }
      .cell-bg-down { background: rgba(220,38,38,0.06) !important; }
      .cell-bg-zero { background: #fff !important; }
    </style>
    """

    def fmt_delta(val, label):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ""
        if v > 0:
            arrow = f'<span class="d-up">▲&thinsp;+{v:,.0f}</span>'
        elif v < 0:
            arrow = f'<span class="d-down">▼&thinsp;-{abs(v):,.0f}</span>'
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
                    sfx = reg.replace(k, "").strip()
                    short = v + (" " + sfx if sfx and sfx not in ["(1)", ""] else "")
                    short = short.strip()
                    break
        short = (short.replace(" (CFR)", "").replace(" (FD)", "").replace(" (CPT)", "")
                      .replace("TURKEY - TURKEY", "TURKEY")
                      .replace("India Main Port", "India"))
        # Apply dir="ltr" for region names ending with dots
        if short.endswith(".") or (reg and reg.endswith(".")):
            html += f'<th class="reg-header" dir="ltr">{short}</th>'
        else:
            html += f'<th class="reg-header">{short}</th>'
    html += "</tr></thead>\n<tbody>\n"

    def _nan(v):
        return v is None or (isinstance(v, float) and pd.isna(v))

    for prod in products:
        disp = " › ".join(prod.split(" › ")[1:]) if " › " in prod else prod
        html += "<tr>"
        html += f'<td class="prod-cell">{disp}</td>'
        for reg in regions:
            mid  = mid_d.get(reg, {}).get(prod)
            mn   = mn_d.get(reg, {}).get(prod)
            mx   = mx_d.get(reg, {}).get(prod)
            dmin = dmin_d.get(reg, {}).get(prod)
            dmax = dmax_d.get(reg, {}).get(prod)
            if _nan(mid):
                html += '<td class="cell-bg-zero"><span style="color:#d1d5db;">—</span></td>'
                continue
            try:
                avg_delta = (float(dmin if not _nan(dmin) else 0) +
                             float(dmax if not _nan(dmax) else 0)) / 2
                bg_class = ("cell-bg-up" if avg_delta > 0
                            else "cell-bg-down" if avg_delta < 0 else "cell-bg-zero")
            except Exception:
                bg_class = "cell-bg-zero"
            mid_str   = f"{mid:,.0f}"
            range_str = (f'<span class="cell-range">{mn:,.0f} – {mx:,.0f}</span>'
                         if not _nan(mn) and not _nan(mx) else "")
            d_min_str = fmt_delta(dmin, "کف") if not _nan(dmin) else ""
            d_max_str = fmt_delta(dmax, "سقف") if not _nan(dmax) else ""
            deltas_html = ""
            if d_min_str or d_max_str:
                deltas_html = (f'<div class="cell-deltas">'
                               f"{d_min_str}&nbsp;&nbsp;{d_max_str}</div>")
            html += (f'<td class="{bg_class}">'
                     f'<span class="cell-mid">{mid_str}</span>'
                     f"{range_str}{deltas_html}</td>")
        html += "</tr>\n"
    html += "</tbody></table>"
    return html


# ══════════════════════════════════════════════════════════════════════════════
# ─── CHART BUILDERS ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def build_timeseries_chart(df_time, selected_products):
    PRODUCT_COLORS = {
        "LDPE CFR China":        "#2563EB",
        "LLDPE CFR China":       "#7C3AED",
        "HDPE Film CFR China":   "#D97706",
        "HDPE BM CFR China":     "#059669",
        "HDPE Inj CFR China":    "#DC2626",
        "HDPE Inj>10 ":          "#0891B2",
        "HDPE Inj<10 CFR China": "#DB2777",
        "Ethylene":              "#000000",
        "MEG CMP":               "#6B7280",
        "DEG CMP":               "#92400E",
        "Methanol":              "#9333EA",
    }
    fig = go.Figure()
    for p in selected_products:
        color = PRODUCT_COLORS.get(p, "#64748b")
        is_eth = p == "Ethylene"
        display_name = "<b>Ethylene ★</b>" if is_eth else p.replace(" CFR China", "").replace(" CMP", "").strip()
        diff_series = df_time[p].diff().fillna(0)
        custom_labels = []
        for d in diff_series:
            if d > 0:   custom_labels.append(f"▲ +{d:,.0f}")
            elif d < 0: custom_labels.append(f"▼ {d:,.0f}")
            else:        custom_labels.append("◆ 0")
        fig.add_trace(go.Scatter(
            x=df_time["Date"], y=df_time[p],
            mode="lines", name=display_name,
            line=dict(color=color, width=4.5 if is_eth else 1.8, dash="solid"),
            customdata=custom_labels,
            hovertemplate=f"<b>{display_name}</b>: %{{y:,.0f}} USD/MT &nbsp;&nbsp;(%{{customdata}})<extra></extra>",
        ))
    fig.add_hline(y=1000, line_dash="dot", line_color="#cbd5e1", line_width=1)
    fig.update_layout(
        template="plotly_white", hovermode="x unified",
        xaxis_title="توالی زمانی (هفتگی)", yaxis_title="قیمت (دلار / تن)",
        legend_title="", height=540,
        font=dict(family="Vazirmatn, Tahoma", size=12),
        hoverlabel=dict(bgcolor="rgba(255,255,255,0.98)", bordercolor="#e2e8f0",
                        font_size=12, font_family="Vazirmatn, Tahoma", align="left"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
        margin=dict(t=30, b=70, l=80, r=10),
        yaxis=dict(title=dict(text="قیمت (دلار / تن)", standoff=35),
                   tickformat=",.0f", showgrid=True, gridcolor="#f1f5f9",
                   tickfont=dict(size=11), zeroline=False),
        plot_bgcolor="#ffffff",
        xaxis=dict(range=[df_time["Date"].min(), df_time["Date"].max()],
                   rangeslider=dict(visible=True, thickness=0.05, bgcolor="#f8fafc"),
                   showgrid=True, gridcolor="#f1f5f9",
                   tickfont=dict(size=11), hoverformat="%Y-%m-%d"),
    )
    return fig


def build_correlation_heatmap(df_time, products):
    corr  = df_time[products].corr()
    short = [p.replace(" CFR China", "").replace(" CMP", "").strip() for p in products]
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=short, y=short,
        colorscale=[[0.0, "#dc2626"], [0.5, "#f9fafb"], [1.0, "#16a34a"]],
        zmin=-1, zmax=1,
        text=[[f"{v:.2f}" for v in row] for row in corr.values],
        texttemplate="%{text}", textfont=dict(size=10),
        hovertemplate="%{x} & %{y}: <b>%{z:.3f}</b><extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="ماتریس همبستگی قیمت‌ها", x=1, xanchor="right",
                   font=dict(size=14, family="Vazirmatn,Tahoma")),
        height=460, font=dict(family="Vazirmatn, Tahoma", size=11),
        margin=dict(t=50, b=80, l=80, r=20),
        xaxis=dict(tickangle=45, tickfont=dict(size=10), automargin=True),
        yaxis=dict(tickfont=dict(size=10), automargin=True),
    )
    return fig


def build_yoy_chart(df_time, products):
    df   = df_time.set_index("Date")
    rows = []
    for p in products:
        series = df[p].dropna()
        if len(series) < 53:
            continue
        current = series.iloc[-1]
        yoy_val = series.iloc[-53]
        change  = current - yoy_val
        pct     = (change / yoy_val * 100) if yoy_val else 0
        rows.append({
            "محصول": p.replace(" CFR China", "").replace(" CMP", "").strip(),
            "قیمت فعلی": current, "قیمت سال قبل": yoy_val,
            "تغییر (USD)": change, "تغییر (%)": pct,
        })
    if not rows:
        return None
    df_yoy   = pd.DataFrame(rows).sort_values("تغییر (%)", ascending=True)
    colors   = ["#16a34a" if v >= 0 else "#dc2626" for v in df_yoy["تغییر (%)"]]
    fig = go.Figure(go.Bar(
        x=df_yoy["تغییر (%)"], y=df_yoy["محصول"],
        orientation="h", marker_color=colors,
        text=[f"{v:+.1f}%" for v in df_yoy["تغییر (%)"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>تغییر: <b>%{x:+.1f}%</b><extra></extra>",
    ))
    fig.add_vline(x=0, line_width=1.5, line_color="#475569")
    fig.update_layout(
        title=dict(text="تغییر قیمت سالانه (YoY)", x=1, xanchor="right",
                   font=dict(size=14, family="Vazirmatn,Tahoma")),
        height=400, font=dict(family="Vazirmatn, Tahoma", size=11),
        xaxis=dict(title="تغییر (%)", tickformat="+.0f", ticksuffix="%", zeroline=False),
        yaxis=dict(tickfont=dict(size=11)),
        margin=dict(t=50, b=20, l=150, r=40),
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", bargap=0.3,
    )
    fig.update_yaxes(automargin=True)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# ─── MAIN DASHBOARD ──────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

try:
    df_time, ts_products         = load_time_series_data()
    df_sheet1, report_date, display_names = load_weekly_report_sheet_clean()
    pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax, _, cat_map = build_price_matrix(df_sheet1)

    # ── Build tab list based on role permissions from database ─────────────
    # v11.0: Conditional admin tab ONLY for Admin role
    tab_labels = []
    if "tab1" in allowed_tabs: tab_labels.append("📊  روند زمانی قیمت محصولات")
    if "tab2" in allowed_tabs: tab_labels.append("📋  دیتابیس کامل گزارش هفتگی")
    if "tab3" in allowed_tabs: tab_labels.append("📈  تحلیل آماری")
    # Admin-only tab - ONLY visible for Admin role
    if "admin" in allowed_tabs and current_role == "Admin":
        tab_labels.append("⚙️  مدیریت سامانه")

    if not tab_labels:
        st.warning("دسترسی شما به هیچ تبی مجاز نیست. با مدیر سیستم تماس بگیرید.")
        st.stop()

    tabs = st.tabs(tab_labels)
    tab_index = {name: i for i, name in enumerate(tab_labels)}

    # ════════════════════════════════════════════════════════════════════════
    # تب ۱ — روند زمانی + ماتریس قیمت  (همه نقش‌ها)
    # ════════════════════════════════════════════════════════════════════════
    if "tab1" in allowed_tabs:
        with tabs[tab_index["📊  روند زمانی قیمت محصولات"]]:
            st.markdown('<div class="section-header">روند زمانی قیمت محصولات</div>',
                        unsafe_allow_html=True)
            selected_products = st.multiselect(
                "فرآورده‌های مورد نظر برای نمایش در نمودار را انتخاب کنید:",
                options=ts_products, default=ts_products,
            )
            if selected_products and len(df_time) >= 2:
                st.markdown('<p style="font-size:12px;color:#94a3b8;text-align:right;direction:rtl;margin-bottom:6px;">آخرین قیمت‌ها (USD/MT) — تغییر واقعی نسبت به ۷ روز قبل</p>', unsafe_allow_html=True)
                cols     = st.columns(len(selected_products))
                last_row = df_time.iloc[-1]

                # محاسبه هوشمند بازه زمانی هفته قبل برای فرار از ردیف‌های تکراری اکسل
                last_date = last_row['Date']
                target_date = last_date - pd.Timedelta(days=7)
                past_rows = df_time[df_time['Date'] <= target_date]

                if not past_rows.empty:
                    prev_row = past_rows.iloc[-1]
                else:
                    prev_row = df_time.iloc[-2]
                for i, p in enumerate(selected_products):
                    last_val  = last_row[p]
                    prev_val  = prev_row[p]
                    delta_val = last_val - prev_val if pd.notna(last_val) and pd.notna(prev_val) else None
                    short     = p.replace(" CFR China", "").replace(" CMP", "").strip()
                    if pd.notna(last_val):
                        cols[i].metric(
                            label=short, value=f"{last_val:,.0f}",
                            delta=f"{delta_val:+,.0f}" if delta_val is not None else None,
                        )
            if selected_products:
                fig = build_timeseries_chart(df_time, selected_products)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("لطفاً حداقل یک فرآورده انتخاب کنید.")

            st.divider()
            date_display = report_date if report_date else "—"
            st.markdown(f"""
            <div class="matrix-title-bar">
              <span class="matrix-title">📌 گزارش ICIS از قیمت‌های جهانی محصولات</span>
              <span class="matrix-date-badge">📅 &nbsp;{date_display}</span>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("""
            <div class="matrix-legend">
              هر سلول: <b>میانگین قیمت</b> (USD/MT) &nbsp;|&nbsp;
              بازه <b>کف – سقف</b> &nbsp;|&nbsp;
              نوسان هفتگی <b>کف</b> و <b>سقف</b><br>
              <span style="color:#16a34a;font-weight:700;">▲ افزایش</span>&nbsp;&nbsp;
              <span style="color:#dc2626;font-weight:700;">▼ کاهش</span>&nbsp;&nbsp;
              <span style="color:#9ca3af;">◆ بدون تغییر</span>&nbsp;&nbsp;
              <span style="color:#94a3b8;">— داده موجود نیست</span>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("### 🛢️ گزارش قیمت محصولات پلیمری (POLYMERS)")
            poly_html = render_price_matrix(
                pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax,
                cat_map=cat_map, display_names=display_names, cat_target="POLYMERS",
            )
            st.html(poly_html)
            st.markdown("")
            st.markdown("### 🧪 گزارش قیمت محصولات شیمیایی (CHEMICALS)")
            chem_html = render_price_matrix(
                pivot_mid, pivot_min, pivot_max, pivot_dmin, pivot_dmax,
                cat_map=cat_map, display_names=display_names, cat_target="CHEMICALS",
            )
            st.html(chem_html)

    # ════════════════════════════════════════════════════════════════════════
    # تب ۲ — دیتابیس کامل  (Analyst + Admin)
    # ════════════════════════════════════════════════════════════════════════
    if "tab2" in allowed_tabs:
        with tabs[tab_index["📋  دیتابیس کامل گزارش هفتگی"]]:
            st.markdown('<div class="section-header">دیتابیس کامل گزارش هفتگی ICIS</div>',
                        unsafe_allow_html=True)
            if report_date:
                st.info(f"📅 تاریخ مرجع: {report_date}")
            numeric_cols = ["حداقل قیمت", "میانگین قیمت", "حداکثر قیمت",
                            "نوسان حداقل", "نوسان حداکثر"]
            for col in numeric_cols:
                df_sheet1[col] = pd.to_numeric(df_sheet1[col], errors="coerce")

            col_search, col_cat, col_sort, col_dir = st.columns([3, 2, 2, 1])
            with col_search:
                search_q = st.text_input("جستجو:", placeholder="نام محصول، گرید یا منطقه...",
                                         label_visibility="collapsed")
            with col_cat:
                all_cats = ["همه"] + sorted(df_sheet1["دسته‌بندی"].dropna().unique().tolist())
                cat_sel  = st.selectbox("دسته:", all_cats, label_visibility="collapsed")
            with col_sort:
                sort_col = st.selectbox(
                    "مرتب بر اساس:",
                    ["میانگین قیمت", "حداقل قیمت", "حداکثر قیمت",
                     "نوسان حداقل", "نوسان حداکثر", "فرآورده", "منطقه / مبدأ"],
                    label_visibility="collapsed",
                )
            with col_dir:
                sort_asc = st.toggle("صعودی", value=False)

            df_filtered = df_sheet1.copy()
            if cat_sel != "همه":
                df_filtered = df_filtered[df_filtered["دسته‌بندی"] == cat_sel]
            if search_q.strip():
                q    = search_q.strip().lower()
                mask = (
                    df_filtered["فرآورده"].astype(str).str.lower().str.contains(q, na=False) |
                    df_filtered["گرید"].astype(str).str.lower().str.contains(q, na=False) |
                    df_filtered["منطقه / مبدأ"].astype(str).str.lower().str.contains(q, na=False)
                )
                df_filtered = df_filtered[mask]
            if sort_col in df_filtered.columns:
                df_filtered = df_filtered.sort_values(sort_col, ascending=sort_asc, na_position="last")

            st.caption(f"نمایش {len(df_filtered):,} ردیف")
            csv_buf = io.BytesIO()
            df_filtered.to_csv(csv_buf, index=False, encoding="utf-8-sig")
            st.download_button(
                label="⬇️  دانلود CSV", data=csv_buf.getvalue(),
                file_name=f"ICIS_prices_{report_date.replace(' ', '_').replace(',', '')}.csv",
                mime="text/csv", use_container_width=False,
            )

            def color_delta(val):
                if pd.isna(val): return ""
                if val < 0: return "color: #dc2626; font-weight: bold;"
                if val > 0: return "color: #16a34a; font-weight: bold;"
                return "color: #888888;"

            fmt_map = {
                "حداقل قیمت":   "{:,.1f}",
                "میانگین قیمت": "{:,.1f}",
                "حداکثر قیمت":  "{:,.1f}",
                "نوسان حداقل":  "{:+,.1f}",
                "نوسان حداکثر": "{:+,.1f}",
            }
            styled_df = (
                df_filtered.style
                .hide(axis="index")
                .format(fmt_map, na_rep="—")
                .map(color_delta, subset=["نوسان حداقل", "نوسان حداکثر"])
            )
            st.dataframe(
                styled_df, use_container_width=True, height=680,
                column_config={
                    "دسته‌بندی":    st.column_config.TextColumn("دسته‌بندی",    width="small"),
                    "فرآورده":      st.column_config.TextColumn("فرآورده",      width="small"),
                    "گرید":         st.column_config.TextColumn("گرید",         width="small"),
                    "منطقه / مبدأ": st.column_config.TextColumn("منطقه / مبدع", width="medium"),
                    "حداقل قیمت":   st.column_config.NumberColumn("حداقل قیمت",   format="%.1f", width="small"),
                    "میانگین قیمت": st.column_config.NumberColumn("میانگین قیمت", format="%.1f", width="small"),
                    "حداکثر قیمت":  st.column_config.NumberColumn("حداکثر قیمت",  format="%.1f", width="small"),
                    "نوسان حداقل":  st.column_config.NumberColumn("نوسان حداقل",  format="%+.1f", width="small"),
                    "نوسان حداکثر": st.column_config.NumberColumn("نوسان حداکثر", format="%+.1f", width="small"),
                },
            )

    # ════════════════════════════════════════════════════════════════════════
    # تب ۳ — تحلیل آماری  (Analyst + Admin)
    # ════════════════════════════════════════════════════════════════════════
    if "tab3" in allowed_tabs:
        with tabs[tab_index["📈  تحلیل آماری"]]:
            st.markdown('<div class="section-header">تحلیل آماری قیمت‌ها</div>',
                        unsafe_allow_html=True)
            st.markdown('<p style="font-size:13px;font-weight:700;color:#374151;direction:rtl;text-align:right;">آمار توصیفی — کل دوره (۲۰۲۱ تا کنون)</p>',
                        unsafe_allow_html=True)
            stat_data = []
            for p in ts_products:
                series = df_time[p].dropna()
                if len(series) < 2:
                    continue
                current  = series.iloc[-1]
                mean_val = series.mean()
                std_val  = series.std()
                min_val  = series.min()
                max_val  = series.max()
                yoy_chg  = ((current - series.iloc[-53]) / series.iloc[-53] * 100
                            if len(series) >= 53 else None)
                stat_data.append({
                    "فرآورده": p.replace(" CFR China", "").replace(" CMP", "").strip(),
                    "قیمت فعلی": current, "میانگین": mean_val,
                    "انحراف معیار": std_val, "حداقل": min_val, "حداکثر": max_val,
                    "تغییر سالانه (%)": yoy_chg,
                })
            if stat_data:
                df_stats = pd.DataFrame(stat_data)
                def color_yoy(val):
                    if pd.isna(val): return ""
                    if val > 0: return "color: #16a34a; font-weight: bold;"
                    if val < 0: return "color: #dc2626; font-weight: bold;"
                    return ""
                styled_stats = (
                    df_stats.style
                    .hide(axis="index")
                    .format({
                        "قیمت فعلی":          "{:,.0f}",
                        "میانگین":            "{:,.0f}",
                        "انحراف معیار":       "{:,.0f}",
                        "حداقل":              "{:,.0f}",
                        "حداکثر":             "{:,.0f}",
                        "تغییر سالانه (%)":   "{:+.1f}%",
                    }, na_rep="—")
                    .map(color_yoy, subset=["تغییر سالانه (%)"])
                )
                st.dataframe(
                    styled_stats, use_container_width=True, height=380,
                    column_config={
                        "فرآورده":          st.column_config.TextColumn("فرآورده",         width="medium"),
                        "قیمت فعلی":        st.column_config.NumberColumn("قیمت فعلی",        format="%.0f", width="small"),
                        "میانگین":          st.column_config.NumberColumn("میانگین",          format="%.0f", width="small"),
                        "انحراف معیار":     st.column_config.NumberColumn("انحراف معیار",     format="%.0f", width="small"),
                        "حداقل":            st.column_config.NumberColumn("حداقل",            format="%.0f", width="small"),
                        "حداکثر":           st.column_config.NumberColumn("حداکثر",           format="%.0f", width="small"),
                        "تغییر سالانه (%)": st.column_config.NumberColumn("تغییر سالانه (%)", format="%+.1f%%", width="small"),
                    },
                )

            st.divider()
            col_yoy, col_corr = st.columns([1, 1], gap="medium")
            with col_yoy:
                st.markdown('<p style="font-size:13px;font-weight:700;color:#374151;direction:rtl;text-align:right;">مقایسه قیمت فعلی با یک سال قبل (YoY)</p>',
                            unsafe_allow_html=True)
                fig_yoy = build_yoy_chart(df_time, ts_products)
                if fig_yoy:
                    st.plotly_chart(fig_yoy, use_container_width=True)
            with col_corr:
                st.markdown('<p style="font-size:13px;font-weight:700;color:#374151;direction:rtl;text-align:right;">ماتریس همبستگی بین محصولات</p>',
                            unsafe_allow_html=True)
                fig_corr = build_correlation_heatmap(df_time, ts_products)
                st.plotly_chart(fig_corr, use_container_width=True)

            st.divider()
            st.markdown('<p style="font-size:13px;font-weight:700;color:#374151;direction:rtl;text-align:right;">توزیع تغییرات هفتگی قیمت (USD/MT)</p>',
                        unsafe_allow_html=True)
            sel_hist = st.selectbox(
                "انتخاب فرآورده:",
                options=ts_products,
                index=ts_products.index("Ethylene") if "Ethylene" in ts_products else 0,
                label_visibility="collapsed",
            )
            weekly_changes = df_time[sel_hist].diff().dropna()
            fig_hist = px.histogram(
                weekly_changes, nbins=60,
                color_discrete_sequence=["#2563eb"],
                labels={"value": "تغییر هفتگی (USD/MT)", "count": "تعداد هفته"},
            )
            fig_hist.add_vline(x=0, line_width=2, line_color="#1e3a8a")
            fig_hist.add_vline(
                x=weekly_changes.mean(), line_width=1.5, line_color="#16a34a",
                line_dash="dash",
                annotation_text=f"میانگین: {weekly_changes.mean():+.1f}",
                annotation_position="top right",
                annotation_font_color="#16a34a",
                annotation_font_size=11,
            )
            fig_hist.update_layout(
                height=320, font=dict(family="Vazirmatn, Tahoma", size=11),
                margin=dict(t=40, b=50, l=80, r=30),
                plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                showlegend=False, bargap=0.05,
            )
            st.plotly_chart(fig_hist, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # تب ۴ — مدیریت سامانه (Admin ONLY - v11.0)
    # ════════════════════════════════════════════════════════════════════════
    if "admin" in allowed_tabs and current_role == "Admin":
        with tabs[tab_index["⚙️  مدیریت سامانه"]]:
            st.markdown('<div class="section-header">⚙️ مدیریت سامانه</div>',
                        unsafe_allow_html=True)

            # User Management Section
            st.markdown("### 👥 مدیریت کاربران")

            # === افزودن کاربر جدید ===
            st.markdown("**➕ افزودن کاربر جدید**")
            with st.form("add_user_form", clear_on_submit=True):
                new_username = st.text_input("نام کاربری", placeholder="username", key="new_username")
                new_password = st.text_input("رمز عبور", type="password", placeholder="••••••••", key="new_password")
                new_role = st.selectbox("نقش", ["Admin", "Analyst", "Guest"], key="new_role")
                add_submitted = st.form_submit_button("افزودن کاربر", use_container_width=True)

                if add_submitted:
                    if new_username and new_password:
                        success, msg = add_user_to_db(_engine, new_username, new_password, new_role)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)
                    else:
                        st.warning("لطفاً نام کاربری و رمز عبور را وارد کنید.")

            st.markdown("---")

            # === مشاهده و حذف کاربران ===
            st.markdown("**📋 مشاهده و حذف کاربران**")
            users_df = get_all_users_df(_engine)
            if not users_df.empty:
                # Display users table (hide password hash)
                display_df = users_df[['username', 'role_id']].copy()
                if 'created_at' in users_df.columns:
                    display_df['created_at'] = users_df['created_at'].astype(str)
                st.dataframe(display_df, use_container_width=True, hide_index=True)

                # Delete user section
                st.markdown("**🗑️ حذف کاربر**")
                user_to_delete = st.selectbox(
                    "انتخاب کاربر برای حذف:",
                    options=users_df['username'].tolist(),
                    key="delete_user_select"
                )
                if st.button("حذف کاربر", key="delete_user_btn", type="secondary"):
                    if user_to_delete:
                        success, msg = delete_user_from_db(_engine, user_to_delete, st.session_state.username)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
            else:
                st.info("کاربری یافت نشد.")

            st.markdown("---")

            # === مدیریت دسترسی نقش‌ها ===
            st.markdown("### 🔐 مدیریت دسترسی نقش‌ها")
            perms = load_permissions_from_db(_engine)

            for role_id in ["Admin", "Analyst", "Guest"]:
                current_tabs = ",".join(perms.get(role_id, []))
                new_tabs = st.text_input(
                    f"تب‌های مجاز برای '{role_id}':",
                    value=current_tabs,
                    key=f"perms_{role_id}"
                )
                if st.button(f"ذخیره تغییرات {role_id}", key=f"save_perms_{role_id}"):
                    success, msg = update_permissions_in_db(_engine, role_id, new_tabs)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            st.markdown("---")

            # Legacy migrations panel
            st.markdown("### 🗄️ مهاجرت‌های پایگاه داده")
            st.markdown("""
            <div style="direction:rtl;font-size:12px;color:#475569;">
            لیست مهاجرت‌های موجود:
            </div>
            """, unsafe_allow_html=True)
            migrations = [
                {"شماره": "001", "نام": "create_time_series_data",    "وضعیت": "✅ اعمال شده"},
                {"شماره": "002", "نام": "create_weekly_report_data", "وضعیت": "✅ اعمال شده"},
                {"شماره": "003", "نام": "add_indexes_on_date",        "وضعیت": "✅ اعمال شده"},
                {"شماره": "004", "نام": "create_auth_tables",         "وضعیت": "✅ اعمال شده"},
            ]
            st.dataframe(pd.DataFrame(migrations), use_container_width=True, hide_index=True)

            st.markdown("""
            <div style="direction:rtl;font-size:11px;color:#94a3b8;margin-top:16px;">
            دسترسی کامل: تمام تب‌ها فعال هستند.
            </div>
            """, unsafe_allow_html=True)

    # ── فوتر ─────────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="footer-custom">'
        "📊 سامانه تحلیلی قیمت‌های جهانی پتروشیمی &nbsp;|&nbsp;"
        " تهیه‌شده توسط <b>واحد تحقیق و توسعه بازار</b> &nbsp;|&nbsp; B.C.Co"
        '&nbsp;&nbsp;<span style="color:#cbd5e1;">·</span>&nbsp;&nbsp;'
        '<span style="color:#c7d2fe;font-weight:600;">v11.0</span>'
        "</div>",
        unsafe_allow_html=True,
    )

except Exception as e:
    st.error(f"خطا در پردازش اطلاعات: {e}")
    st.exception(e)
