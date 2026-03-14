import streamlit as st
import sqlite3
import hashlib
import re
import io
import os
import json
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Voltiq – Smart Electricity Analyzer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Syne:wght@400;600;700;800&display=swap');
:root {
    --bg:#0A0E1A; --bg2:#0F1628; --card:#141C30; --card2:#1A2340;
    --accent:#00D4FF; --accent2:#7B61FF; --green:#00E89A;
    --orange:#FF6B35; --red:#FF4757; --yellow:#FFD700;
    --text:#E8EDF5; --muted:#8B96B0; --border:rgba(0,212,255,0.15);
}
html,body,[class*="css"]{font-family:'Space Grotesk',sans-serif!important;background-color:var(--bg)!important;color:var(--text)!important;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:1rem 2rem 2rem 2rem!important;max-width:1400px;}
[data-testid="stSidebar"]{background:var(--bg2)!important;border-right:1px solid var(--border);}
[data-testid="stSidebar"] *{color:var(--text)!important;}
.stButton>button{background:linear-gradient(135deg,var(--accent2),var(--accent))!important;color:#fff!important;border:none!important;border-radius:12px!important;font-family:'Space Grotesk',sans-serif!important;font-weight:600!important;font-size:0.95rem!important;padding:0.6rem 1.4rem!important;transition:all 0.3s ease!important;box-shadow:0 4px 15px rgba(123,97,255,0.3)!important;}
.stButton>button:hover{transform:translateY(-2px)!important;box-shadow:0 6px 25px rgba(0,212,255,0.4)!important;}
.stTextInput>div>div>input,.stSelectbox>div>div,.stNumberInput>div>div>input{background:var(--card2)!important;border:1px solid var(--border)!important;border-radius:10px!important;color:var(--text)!important;font-family:'Space Grotesk',sans-serif!important;}
.stTabs [data-baseweb="tab-list"]{background:var(--card)!important;border-radius:12px!important;padding:4px!important;gap:4px!important;}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:var(--muted)!important;border-radius:8px!important;font-weight:500!important;}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,var(--accent2),var(--accent))!important;color:white!important;}
[data-testid="stMetric"]{background:var(--card)!important;border:1px solid var(--border)!important;border-radius:16px!important;padding:1rem 1.2rem!important;}
[data-testid="stMetricLabel"]{color:var(--muted)!important;font-size:0.85rem!important;}
[data-testid="stMetricValue"]{color:var(--accent)!important;font-family:'Syne',sans-serif!important;}
.streamlit-expanderHeader{background:var(--card)!important;border:1px solid var(--border)!important;border-radius:10px!important;color:var(--text)!important;}
[data-testid="stFileUploader"]{background:var(--card)!important;border:2px dashed var(--border)!important;border-radius:16px!important;}
.stProgress>div>div>div>div{background:linear-gradient(90deg,var(--accent2),var(--accent))!important;}
::-webkit-scrollbar{width:6px;}
::-webkit-scrollbar-track{background:var(--bg);}
::-webkit-scrollbar-thumb{background:var(--accent2);border-radius:4px;}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════
DB_PATH = "voltiq.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT,
        security_question TEXT,
        security_answer_hash TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        provider TEXT, month TEXT, year INTEGER,
        units REAL, amount REAL, rate REAL,
        bill_date TEXT, image_path TEXT,
        carbon_footprint REAL, notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id))""")
    conn.commit()
    conn.close()

init_db()

# ══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def hash_val(v): return hashlib.sha256(v.strip().lower().encode()).hexdigest()

def register_user(username, password, email, sq, sa):
    conn = get_conn(); c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username,password_hash,email,security_question,security_answer_hash) VALUES(?,?,?,?,?)",
                  (username.strip(), hash_val(password), email.strip(), sq, hash_val(sa)))
        conn.commit(); return True, "Account created!"
    except Exception as e:
        return False, "Username already exists." if "UNIQUE" in str(e) else str(e)
    finally: conn.close()

def login_user(username, password):
    conn = get_conn(); c = conn.cursor()
    row = c.execute("SELECT id,username FROM users WHERE username=? AND password_hash=?",
                    (username.strip(), hash_val(password))).fetchone()
    conn.close(); return row

def get_security_question(username):
    conn = get_conn(); c = conn.cursor()
    row = c.execute("SELECT security_question,security_answer_hash FROM users WHERE username=?",
                    (username.strip(),)).fetchone()
    conn.close(); return row

def reset_password(username, new_password):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET password_hash=? WHERE username=?", (hash_val(new_password), username.strip()))
    conn.commit(); conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# BILL HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def save_bill(user_id, provider, month, year, units, amount, rate, bill_date, image_path, carbon):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO bills (user_id,provider,month,year,units,amount,rate,bill_date,image_path,carbon_footprint) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (user_id, provider, month, year, units, amount, rate, bill_date, image_path, carbon))
    conn.commit(); conn.close()

def get_user_bills(user_id):
    conn = get_conn(); c = conn.cursor()
    rows = c.execute("SELECT * FROM bills WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user_id,)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def delete_bill(bill_id, user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM bills WHERE id=? AND user_id=?", (bill_id, user_id))
    conn.commit(); conn.close()

# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS HELPERS
# ══════════════════════════════════════════════════════════════════════════════
PROVIDERS = ["MSEDCL", "Adani Electricity", "Tata Power", "BEST"]

PROVIDER_PATTERNS = {
    "MSEDCL": [r"Units\s*Consumed[:\s]*([0-9]+(?:\.[0-9]+)?)", r"Net\s*Units[:\s]*([0-9]+(?:\.[0-9]+)?)"],
    "Adani Electricity": [r"Consumption\s*\(?kWh\)?[:\s]*([0-9]+(?:\.[0-9]+)?)", r"([0-9]+(?:\.[0-9]+)?)\s*kWh"],
    "Tata Power": [r"Energy\s*Charges\s*Units[:\s]*([0-9]+(?:\.[0-9]+)?)", r"Units\s*Consumed[:\s]*([0-9]+(?:\.[0-9]+)?)"],
    "BEST": [r"Units\s*Consumed[:\s]*([0-9]+(?:\.[0-9]+)?)", r"Consumption[:\s]*([0-9]+(?:\.[0-9]+)?)\s*Units"],
}

TARIFF = {
    "MSEDCL":           [(0,100,3.46),(100,300,7.05),(300,500,10.82),(500,1e9,13.24)],
    "Adani Electricity":[(0,100,3.20),(100,300,6.50),(300,1e9,9.80)],
    "Tata Power":       [(0,100,3.25),(100,300,6.75),(300,1e9,10.10)],
    "BEST":             [(0,100,3.10),(100,300,6.20),(300,1e9,9.50)],
}

APPLIANCES = {
    "AC (1.5 ton)":1500, "Refrigerator":150, "Washing Machine":500,
    'TV (LED 43")':80, "Geyser/Water Heater":2000, "Ceiling Fan":75,
    "LED Bulb (per)":9, "Microwave":1200, "Computer/Laptop":65,
    "Water Pump":750, "Desert Cooler":200, "Electric Kettle":1500,
}

SECURITY_QUESTIONS = [
    "What was the name of your first pet?",
    "What is your mother's maiden name?",
    "What city were you born in?",
    "What was the name of your first school?",
    "What is your favourite movie?",
]

def extract_text(image_bytes):
    try:
        import pytesseract
        from PIL import Image
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("L")
            return pytesseract.image_to_string(img), True
        except Exception:
            pass
        try:
            from pdf2image import convert_from_bytes
            pages = convert_from_bytes(image_bytes)
            if pages:
                text = " ".join(pytesseract.image_to_string(p.convert("L")) for p in pages)
                return text, True
        except Exception:
            pass
        return "", False
    except Exception:
        return "", False

def parse_bill(text, provider):
    result = {"units":None,"amount":None,"month":None,"date":None,"rate":None}
    for pat in PROVIDER_PATTERNS.get(provider, PROVIDER_PATTERNS["MSEDCL"]):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try: result["units"] = float(m.group(1).replace(",","")); break
            except: pass
    for pat in [r"(?:Total\s*Amount|Net\s*Payable|Bill\s*Amount)[:\s₹Rs.]*([0-9,]+(?:\.[0-9]+)?)",
                r"₹\s*([0-9,]+(?:\.[0-9]+)?)", r"Rs\.?\s*([0-9,]+(?:\.[0-9]+)?)"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try: result["amount"] = float(m.group(1).replace(",","")); break
            except: pass
    for pat in [r"(January|February|March|April|May|June|July|August|September|October|November|December)\s*['\-]?\s*(\d{2,4})",
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[^\w]*(\d{2,4})"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m: result["month"] = m.group(0).strip(); break
    for pat in [r"(?:Bill\s*Date|Due\s*Date)[:\s]*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
                r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m: result["date"] = m.group(1).strip(); break
    if result["units"] and result["amount"] and result["units"] > 0:
        result["rate"] = round(result["amount"]/result["units"], 2)
    return result

def calculate_bill(units, provider):
    slabs = TARIFF.get(provider, TARIFF["MSEDCL"])
    total = 150.0; remaining = units
    for low, high, rate in slabs:
        chunk = min(remaining, high-low)
        if chunk <= 0: break
        total += chunk * rate; remaining -= chunk
        if remaining <= 0: break
    return round(total, 2)

def calculate_carbon(units): return round(units * 0.82, 2)
def trees_equivalent(co2): return round(co2 / 22, 1)

def get_suggestions(units, provider):
    s = []
    if units > 500:
        s += ["🔴 Very high consumption! Consider an energy audit immediately.",
              "❄️ Check if AC runs unnecessarily at night.",
              "💡 Replace all incandescent bulbs with LEDs (saves 75% on lighting)."]
    elif units > 300:
        s += ["🟡 Above average. Small changes can save ₹500+/month.",
              "🌡️ Set AC to 24°C instead of 18°C — saves ~6% per degree.",
              "🫧 Run washing machine with full load only."]
    elif units > 100:
        s += ["🟢 Moderate consumption. Keep it up!",
              "🔌 Unplug chargers and standby devices when not in use.",
              "☀️ Consider a solar water heater to cut geyser load."]
    else:
        s += ["🌟 Excellent! You're in the lowest consumption tier.",
              "♻️ Consider sharing your tips with neighbours!"]
    s += ["⏰ Run heavy appliances in off-peak hours (10pm–6am).",
          "🪟 Use natural ventilation in evenings instead of AC/fans."]
    return s

# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
for k, v in [("logged_in",False),("username",None),("user_id",None),("page","home"),
             ("upload_type","single"),("fp_question",None),("fp_verified",False),("fp_username","")]:
    if k not in st.session_state: st.session_state[k] = v

# ══════════════════════════════════════════════════════════════════════════════
# CHART THEME HELPER
# ══════════════════════════════════════════════════════════════════════════════
def dark_layout(fig, **kwargs):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Space Grotesk", color="#E8EDF5"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        margin=dict(t=30,b=20,l=10,r=10), **kwargs)
    return fig

def suggestion_box(s):
    st.markdown(f"""<div style='background:rgba(20,28,48,0.8);border-left:3px solid #7B61FF;
        border-radius:8px;padding:0.7rem 1rem;margin-bottom:0.5rem;color:#C5CDE0;'>{s}</div>""",
        unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████  AUTH PAGE  ██████████████████
# ══════════════════════════════════════════════════════════════════════════════
def show_auth():
    st.markdown("""
    <div style='text-align:center;padding:2rem 1rem 1rem;'>
        <div style='font-family:Syne,sans-serif;font-size:3.5rem;font-weight:800;
            background:linear-gradient(135deg,#00D4FF 0%,#7B61FF 50%,#00E89A 100%);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:0.5rem;'>
            ⚡ VOLTIQ</div>
        <div style='color:#8B96B0;font-size:1rem;letter-spacing:3px;margin-bottom:1rem;'>
            SMART ELECTRICITY ANALYZER</div>
        <div style='max-width:580px;margin:0 auto;color:#C5CDE0;font-size:1.05rem;line-height:1.7;
            background:rgba(20,28,48,0.7);border:1px solid rgba(0,212,255,0.15);
            border-radius:16px;padding:1.2rem 1.5rem;'>
            📊 Upload electricity bills · Track usage trends · Calculate carbon footprint ·
            Get personalized saving tips — all in one place. Built for Maharashtra's top providers.
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("""<div style='display:flex;justify-content:center;gap:2rem;margin:1.5rem 0 2rem;flex-wrap:wrap;'>
        <div style='text-align:center;'><div style='font-family:Syne,sans-serif;font-size:1.6rem;font-weight:800;color:#00D4FF;'>4</div><div style='color:#8B96B0;font-size:0.8rem;'>Providers</div></div>
        <div style='text-align:center;'><div style='font-family:Syne,sans-serif;font-size:1.6rem;font-weight:800;color:#7B61FF;'>OCR</div><div style='color:#8B96B0;font-size:0.8rem;'>Bill Scanning</div></div>
        <div style='text-align:center;'><div style='font-family:Syne,sans-serif;font-size:1.6rem;font-weight:800;color:#00E89A;'>CO₂</div><div style='color:#8B96B0;font-size:0.8rem;'>Carbon Tracking</div></div>
        <div style='text-align:center;'><div style='font-family:Syne,sans-serif;font-size:1.6rem;font-weight:800;color:#FF6B35;'>AI</div><div style='color:#8B96B0;font-size:0.8rem;'>Predictions</div></div>
    </div>""", unsafe_allow_html=True)

    _, col, _ = st.columns([1,1.5,1])
    with col:
        t1, t2, t3 = st.tabs(["🔑 Login","✨ Register","🔓 Forgot Password"])

        with t1:
            st.markdown("<br>", unsafe_allow_html=True)
            u = st.text_input("Username", key="li_u", placeholder="Your username")
            p = st.text_input("Password", type="password", key="li_p", placeholder="Your password")
            if st.button("Login →", key="li_btn", use_container_width=True):
                if not u or not p: st.error("Fill in all fields.")
                else:
                    row = login_user(u, p)
                    if row:
                        st.session_state.update(logged_in=True, username=row["username"],
                                                user_id=row["id"], page="home")
                        st.rerun()
                    else: st.error("Invalid username or password.")

        with t2:
            st.markdown("<br>", unsafe_allow_html=True)
            ru = st.text_input("Username", key="ru_u", placeholder="Choose a username")
            re_ = st.text_input("Email (optional)", key="ru_e", placeholder="your@email.com")
            rp = st.text_input("Password", type="password", key="ru_p", placeholder="Min 6 characters")
            rp2 = st.text_input("Confirm Password", type="password", key="ru_p2", placeholder="Repeat password")
            rsq = st.selectbox("Security Question", SECURITY_QUESTIONS, key="ru_sq")
            rsa = st.text_input("Your Answer", key="ru_sa", placeholder="Answer to security question")
            if st.button("Create Account →", key="ru_btn", use_container_width=True):
                if not ru or not rp or not rsa: st.error("Fill in all required fields.")
                elif rp != rp2: st.error("Passwords do not match.")
                elif len(rp) < 6: st.error("Password must be at least 6 characters.")
                else:
                    ok, msg = register_user(ru, rp, re_, rsq, rsa)
                    st.success(msg + " Please login.") if ok else st.error(msg)

        with t3:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div style='color:#8B96B0;font-size:0.9rem;margin-bottom:1rem;'>Answer your security question to reset your password.</div>", unsafe_allow_html=True)
            fp_u = st.text_input("Username", key="fp_u", placeholder="Enter your username")
            if st.button("Fetch Security Question", key="fp_fetch"):
                if not fp_u: st.error("Enter username first.")
                else:
                    row = get_security_question(fp_u)
                    if row:
                        st.session_state.fp_question = dict(row)
                        st.session_state.fp_username = fp_u
                    else: st.error("Username not found.")
            if st.session_state.fp_question:
                st.info(f"❓ {st.session_state.fp_question['security_question']}")
                ans = st.text_input("Your Answer", key="fp_ans")
                if st.button("Verify Answer", key="fp_verify"):
                    if hash_val(ans) == st.session_state.fp_question["security_answer_hash"]:
                        st.session_state.fp_verified = True
                        st.success("✅ Correct! Set your new password.")
                    else: st.error("❌ Incorrect answer.")
            if st.session_state.fp_verified:
                np1 = st.text_input("New Password", type="password", key="fp_np1")
                np2 = st.text_input("Confirm New Password", type="password", key="fp_np2")
                if st.button("Reset Password →", key="fp_reset"):
                    if np1 != np2: st.error("Passwords don't match.")
                    elif len(np1) < 6: st.error("Too short.")
                    else:
                        reset_password(st.session_state.fp_username, np1)
                        st.success("✅ Password reset! Please login.")
                        st.session_state.fp_question = None
                        st.session_state.fp_verified = False

# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████  HOME PAGE  ██████████████████
# ══════════════════════════════════════════════════════════════════════════════
def show_home():
    bills = get_user_bills(st.session_state.user_id)
    st.markdown(f"""<div style='margin-bottom:2rem;'>
        <h1 style='font-family:Syne,sans-serif;font-size:2.2rem;font-weight:800;margin:0;'>
        Good day, <span style='background:linear-gradient(135deg,#00D4FF,#7B61FF);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>
        {st.session_state.username}</span> ⚡</h1>
        <p style='color:#8B96B0;margin-top:0.3rem;'>Your electricity intelligence dashboard.</p>
    </div>""", unsafe_allow_html=True)

    st.markdown("### 🚀 What would you like to do?")
    c1, c2, c3 = st.columns(3)
    for col, pg, icon, title, desc, ca, cb in [
        (c1,"upload","📤","Upload Bill","Scan your bill with OCR — single or multiple","#00D4FF","#7B61FF"),
        (c2,"enter_units","🔢","Enter Units","Manually enter units for instant analysis","#7B61FF","#00E89A"),
        (c3,"quick_estimate","⚡","Quick Estimate","Estimate based on your appliances","#00E89A","#FF6B35"),
    ]:
        with col:
            st.markdown(f"""<div style='background:linear-gradient(135deg,{ca}15,{cb}15);
                border:1px solid {ca}40;border-radius:20px;padding:1.5rem;margin-bottom:1rem;min-height:160px;'>
                <div style='font-size:2.5rem;margin-bottom:0.5rem;'>{icon}</div>
                <div style='font-family:Syne,sans-serif;font-weight:700;font-size:1.15rem;color:{ca};margin-bottom:0.4rem;'>{title}</div>
                <div style='color:#8B96B0;font-size:0.85rem;line-height:1.5;'>{desc}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Go to {title} →", key=f"hn_{pg}", use_container_width=True):
                st.session_state.page = pg; st.rerun()

    st.markdown("---")
    if bills:
        df = pd.DataFrame(bills)
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total Bills", len(bills))
        m2.metric("Total Units", f"{df['units'].sum():,.0f} kWh")
        m3.metric("Total Spent", f"₹{df['amount'].sum():,.0f}")
        m4.metric("CO₂ Footprint", f"{df['carbon_footprint'].sum():,.1f} kg")
        st.markdown("---")
        st.markdown("### 🗂️ Recent Bills")
        for b in bills[:5]:
            with st.expander(f"📋 {b['provider']} · {b['month']} · {b['units']} kWh · ₹{b['amount']}"):
                cc1,cc2,cc3 = st.columns(3)
                cc1.markdown(f"**Units:** {b['units']} kWh  \n**Provider:** {b['provider']}")
                cc2.markdown(f"**Amount:** ₹{b['amount']}  \n**Carbon:** {b['carbon_footprint']} kg CO₂")
                cc3.markdown(f"**Rate:** ₹{b['rate']}/kWh  \n**Trees:** {trees_equivalent(b['carbon_footprint'] or 0)} 🌳")
        if len(bills) > 5:
            if st.button("View All Bills →", key="h_hist"): st.session_state.page="history"; st.rerun()
    else:
        st.markdown("""<div style='text-align:center;padding:3rem;background:rgba(20,28,48,0.6);
            border:1px dashed rgba(0,212,255,0.2);border-radius:20px;margin-top:1rem;'>
            <div style='font-size:4rem;margin-bottom:1rem;'>📂</div>
            <div style='font-family:Syne,sans-serif;font-size:1.3rem;font-weight:700;color:#00D4FF;margin-bottom:0.5rem;'>No bills yet!</div>
            <div style='color:#8B96B0;'>Upload your first electricity bill to get started.</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🏢 Supported Maharashtra Providers")
    p1,p2,p3,p4 = st.columns(4)
    for col,(name,color,area) in zip([p1,p2,p3,p4],[
        ("MSEDCL","#FF6B35","Rural & semi-urban MH"),
        ("Adani Electricity","#00D4FF","Mumbai Western Suburbs"),
        ("Tata Power","#7B61FF","Urban Mumbai"),
        ("BEST","#00E89A","BMC Area Mumbai")]):
        col.markdown(f"""<div style='background:rgba(20,28,48,0.8);border:1px solid {color}40;
            border-radius:14px;padding:1rem;text-align:center;'>
            <div style='color:{color};font-weight:700;font-size:0.95rem;'>{name}</div>
            <div style='color:#8B96B0;font-size:0.75rem;margin-top:4px;'>{area}</div>
        </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████  UPLOAD PAGE  ██████████████████
# ══════════════════════════════════════════════════════════════════════════════
def show_upload():
    st.markdown("""<h1 style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;margin-bottom:0.3rem;'>
        📤 Upload Your <span style='background:linear-gradient(135deg,#00D4FF,#7B61FF);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>Electricity Bill</span></h1>
        <p style='color:#8B96B0;margin-bottom:1.5rem;'>OCR reads your bill automatically. Choose single or multiple bills.</p>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        active = st.session_state.upload_type == "single"
        st.markdown(f"""<div style='background:{"rgba(0,212,255,0.1)" if active else "rgba(20,28,48,0.6)"};
            border:{"2px solid #00D4FF" if active else "1px solid rgba(0,212,255,0.2)"};
            border-radius:16px;padding:1.2rem;text-align:center;'>
            <div style='font-size:2rem;'>📄</div>
            <div style='font-weight:700;color:#00D4FF;'>Single Bill</div>
            <div style='color:#8B96B0;font-size:0.8rem;'>Appliance survey + carbon footprint</div>
        </div>""", unsafe_allow_html=True)
        if st.button("Select Single", key="sel_s", use_container_width=True):
            st.session_state.upload_type = "single"; st.rerun()
    with c2:
        active2 = st.session_state.upload_type == "multiple"
        st.markdown(f"""<div style='background:{"rgba(123,97,255,0.1)" if active2 else "rgba(20,28,48,0.6)"};
            border:{"2px solid #7B61FF" if active2 else "1px solid rgba(123,97,255,0.2)"};
            border-radius:16px;padding:1.2rem;text-align:center;'>
            <div style='font-size:2rem;'>📚</div>
            <div style='font-weight:700;color:#7B61FF;'>Multiple Bills</div>
            <div style='color:#8B96B0;font-size:0.8rem;'>Compare months + predict next bill</div>
        </div>""", unsafe_allow_html=True)
        if st.button("Select Multiple", key="sel_m", use_container_width=True):
            st.session_state.upload_type = "multiple"; st.rerun()

    st.markdown("---")
    if st.session_state.upload_type == "single": _single_flow()
    else: _multi_flow()

def _try_ocr(img_bytes, provider):
    with st.spinner("🔍 Reading bill with OCR..."):
        text, ok = extract_text(img_bytes)
    if ok and text.strip():
        result = parse_bill(text, provider)
        if result["units"]:
            st.success("✅ Bill scanned successfully!")
            return result
        else:
            st.warning("⚠️ We could not detect the electricity units automatically. Please enter the units from your bill.")
    else:
        st.warning("⚠️ We could not detect the electricity units automatically. Please enter the units from your bill.")
    return None

def _manual_fields(prefix):
    c1,c2 = st.columns(2)
    units = c1.number_input("Units Consumed (kWh)", min_value=0.0, step=1.0, key=f"{prefix}_u")
    amount = c2.number_input("Total Bill Amount (₹)", min_value=0.0, step=10.0, key=f"{prefix}_a")
    c3,c4 = st.columns(2)
    month = c3.text_input("Billing Month", placeholder="e.g. January 2025", key=f"{prefix}_m")
    bdate = c4.text_input("Bill Date", placeholder="e.g. 15/01/2025", key=f"{prefix}_d")
    return {"units":units or None, "amount":amount or None, "month":month, "date":bdate,
            "rate": round(amount/units,2) if units>0 and amount>0 else None}

def _single_flow():
    st.markdown("## 📄 Single Bill Analysis")
    provider = st.selectbox("⚡ Electricity Provider", PROVIDERS, key="sp_prov")
    uploaded = st.file_uploader("Upload bill (JPG, PNG, PDF)", type=["jpg","jpeg","png","pdf"], key="sp_up")

    bill_data = None; image_path = ""
    if uploaded:
        img_bytes = uploaded.read()
        st.image(img_bytes, caption="Uploaded Bill", width=380)
        os.makedirs("uploads", exist_ok=True)
        image_path = f"uploads/{st.session_state.user_id}_{uploaded.name}"
        with open(image_path,"wb") as f: f.write(img_bytes)
        result = _try_ocr(img_bytes, provider)
        if result:
            bill_data = result
            r1,r2,r3,r4 = st.columns(4)
            r1.metric("Units", f"{result['units']} kWh")
            r2.metric("Amount", f"₹{result['amount']}" if result['amount'] else "Not detected")
            r3.metric("Rate", f"₹{result['rate']}/kWh" if result['rate'] else "N/A")
            r4.metric("Month", result['month'] or "Not detected")
        else:
            st.markdown("#### ✏️ Enter Bill Details Manually")
            bill_data = _manual_fields("sp_man")
    else:
        st.markdown("**Or enter details manually:**")
        bill_data = _manual_fields("sp_noimg")

    if bill_data and bill_data.get("units") and bill_data["units"] > 0:
        units = bill_data["units"]
        st.markdown("---")
        st.markdown("### 🏠 Appliance Survey")
        st.markdown("<div style='color:#8B96B0;font-size:0.9rem;margin-bottom:1rem;'>Tell us your appliances to see how electricity is distributed.</div>", unsafe_allow_html=True)
        survey = {}
        cols = st.columns(2)
        for i,(name,watt) in enumerate(APPLIANCES.items()):
            with cols[i%2]:
                hrs = st.number_input(f"{name} ({watt}W) — hrs/day", 0.0, 24.0, step=0.5, key=f"sv_{name}")
                survey[name] = {"wattage":watt, "hours":hrs}

        if st.button("🔬 Analyse My Bill", key="sp_analyse", use_container_width=True):
            amount = bill_data.get("amount") or calculate_bill(units, provider)
            carbon = calculate_carbon(units)
            trees = trees_equivalent(carbon)
            _show_single_result(provider, units, amount, carbon, trees, survey, bill_data, image_path)

def _show_single_result(provider, units, amount, carbon, trees, survey, bill_data, image_path):
    st.markdown("---")
    st.markdown("## 📊 Your Bill Analysis")
    m1,m2,m3,m4 = st.columns(4)
    m1.metric("⚡ Units", f"{units} kWh")
    m2.metric("💰 Bill", f"₹{amount:,.0f}")
    m3.metric("🌿 CO₂", f"{carbon} kg")
    m4.metric("🌳 Trees", str(trees))

    st.markdown(f"""<div style='background:rgba(0,232,154,0.08);border:1px solid rgba(0,232,154,0.3);
        border-radius:12px;padding:1rem;margin:1rem 0;'>
        <b style='color:#00E89A;'>🌿 Carbon Insight:</b>
        <span style='color:#C5CDE0;'> Your usage generates <b>{carbon} kg CO₂</b> — equivalent to planting <b>{trees} trees</b> to offset it.
        {"Above average — take action!" if carbon>100 else "You're doing well!"}</span>
    </div>""", unsafe_allow_html=True)

    # Appliance pie
    app_kwh = {k: round((v["wattage"]*v["hours"]*30)/1000, 1) for k,v in survey.items() if v["hours"]>0}
    if app_kwh:
        st.markdown("### 🥧 Consumption by Appliance")
        fig = px.pie(names=list(app_kwh.keys()), values=list(app_kwh.values()),
                     hole=0.4, color_discrete_sequence=px.colors.qualitative.Bold)
        fig.update_traces(textposition='inside', textinfo='percent+label', textfont_color='white')
        dark_layout(fig); st.plotly_chart(fig, use_container_width=True)
        df_app = pd.DataFrame([{"Appliance":k,"Monthly kWh":v,"Est. Cost (₹)":round(v*(amount/units),0)}
                                for k,v in sorted(app_kwh.items(),key=lambda x:-x[1])])
        st.dataframe(df_app, use_container_width=True, hide_index=True)

    # Slab breakdown
    st.markdown("### 📈 Tariff Slab Breakdown")
    _slab_chart(units, provider)

    # Suggestions
    st.markdown("### 💡 Personalized Suggestions")
    for s in get_suggestions(units, provider): suggestion_box(s)

    # Alert
    if units > 500: st.error("🚨 ALERT: Very high consumption (>500 units)! You're in the most expensive tariff slab.")
    elif units > 300: st.warning("⚠️ ALERT: Above 300 units — higher tariff slabs apply. Consider reducing usage.")
    else: st.success("✅ Your consumption looks healthy this month!")

    # Save
    month_val = bill_data.get("month") or datetime.now().strftime("%B %Y")
    rate_val = bill_data.get("rate") or round(amount/units, 2)
    save_bill(st.session_state.user_id, provider, month_val, datetime.now().year,
              units, amount, rate_val, bill_data.get("date",""), image_path, carbon)
    st.success("💾 Bill saved to your history!")

def _slab_chart(units, provider):
    slabs = TARIFF.get(provider, TARIFF["MSEDCL"])
    labels, vals, remaining = [], [], units
    for low, high, rate in slabs:
        chunk = min(remaining, high-low)
        if chunk <= 0: break
        labels.append(f"{int(low)}–{int(high) if high<1e8 else '∞'}")
        vals.append(round(chunk*rate, 0)); remaining -= chunk
    if vals:
        fig = go.Figure(go.Bar(x=labels, y=vals,
            marker_color=["#00D4FF","#7B61FF","#FF6B35","#FF4757"][:len(vals)],
            text=[f"₹{v:,.0f}" for v in vals], textposition="outside"))
        dark_layout(fig); st.plotly_chart(fig, use_container_width=True)

def _multi_flow():
    st.markdown("## 📚 Multiple Bills — Compare & Predict")
    provider = st.selectbox("⚡ Provider", PROVIDERS, key="mp_prov")
    num = st.slider("How many bills?", 2, 6, 2, key="mp_num")
    bills_data = []
    for i in range(num):
        st.markdown(f"#### 📋 Bill {i+1}")
        col1, col2 = st.columns([2,1])
        with col1:
            up = st.file_uploader(f"Bill {i+1}", type=["jpg","jpeg","png","pdf"], key=f"mu_{i}")
        with col2:
            ml = st.text_input(f"Month Label", placeholder="e.g. Jan 2025", key=f"ml_{i}")
        info = {"month":ml, "units":None, "amount":None}
        if up:
            img_bytes = up.read()
            result = _try_ocr(img_bytes, provider)
            if result and result["units"]:
                info.update(result)
                st.success(f"✅ Bill {i+1}: {result['units']} kWh")
            else:
                u2 = st.number_input(f"Units for Bill {i+1}", 0.0, key=f"mu_u_{i}")
                a2 = st.number_input(f"Amount for Bill {i+1} (₹)", 0.0, key=f"mu_a_{i}")
                info["units"] = u2 or None; info["amount"] = a2 or None
        else:
            u2 = st.number_input(f"Units for Bill {i+1} (kWh)", 0.0, key=f"mu_un_{i}")
            a2 = st.number_input(f"Amount for Bill {i+1} (₹)", 0.0, key=f"mu_am_{i}")
            info["units"] = u2 or None; info["amount"] = a2 or None
        if info["units"]:
            info["amount"] = info["amount"] or calculate_bill(info["units"], provider)
            info["carbon"] = calculate_carbon(info["units"])
        bills_data.append(info)

    valid = [b for b in bills_data if b.get("units")]
    if len(valid) >= 2 and st.button("📊 Compare & Analyse", key="mp_go", use_container_width=True):
        _show_multi_result(valid, provider)

def _show_multi_result(bills, provider):
    st.markdown("---")
    st.markdown("## 📊 Multi-Bill Comparison")
    months = [b.get("month") or f"Bill {i+1}" for i,b in enumerate(bills)]
    units_list = [b["units"] for b in bills]
    amounts_list = [b["amount"] for b in bills]
    carbon_list = [b.get("carbon", calculate_carbon(b["units"])) for b in bills]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Units (kWh)", x=months, y=units_list,
                         marker_color="#00D4FF", opacity=0.85, yaxis="y1"))
    fig.add_trace(go.Scatter(name="Amount (₹)", x=months, y=amounts_list,
                             mode="lines+markers", line=dict(color="#FF6B35",width=3),
                             marker=dict(size=10), yaxis="y2"))
    dark_layout(fig, yaxis=dict(title="Units (kWh)", gridcolor="rgba(255,255,255,0.05)"),
                yaxis2=dict(title="Amount (₹)", overlaying="y", side="right"))
    st.plotly_chart(fig, use_container_width=True)

    fig2 = px.area(x=months, y=carbon_list, labels={"x":"Month","y":"CO₂ (kg)"},
                   color_discrete_sequence=["#00E89A"], title="CO₂ Footprint")
    fig2.update_traces(fillcolor="rgba(0,232,154,0.1)", line=dict(width=2))
    dark_layout(fig2); st.plotly_chart(fig2, use_container_width=True)

    max_i = units_list.index(max(units_list))
    min_i = units_list.index(min(units_list))
    diff_pct = round(((max(units_list)-min(units_list))/min(units_list))*100, 1)
    cc1, cc2 = st.columns(2)
    cc1.markdown(f"""<div style='background:rgba(255,71,87,0.1);border:1px solid #FF475740;
        border-radius:14px;padding:1.2rem;text-align:center;'>
        <div style='font-size:1.5rem;'>📈</div>
        <div style='color:#FF4757;font-weight:700;'>Highest Consumption</div>
        <div style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;color:#FF4757;'>{max(units_list)} kWh</div>
        <div style='color:#8B96B0;'>{months[max_i]}</div>
    </div>""", unsafe_allow_html=True)
    cc2.markdown(f"""<div style='background:rgba(0,232,154,0.1);border:1px solid #00E89A40;
        border-radius:14px;padding:1.2rem;text-align:center;'>
        <div style='font-size:1.5rem;'>📉</div>
        <div style='color:#00E89A;font-weight:700;'>Lowest Consumption</div>
        <div style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;color:#00E89A;'>{min(units_list)} kWh</div>
        <div style='color:#8B96B0;'>{months[min_i]}</div>
    </div>""", unsafe_allow_html=True)
    st.markdown(f"""<div style='background:rgba(123,97,255,0.1);border:1px solid #7B61FF40;
        border-radius:12px;padding:1rem;margin:1rem 0;text-align:center;'>
        <b style='color:#7B61FF;'>📊 Variation:</b>
        <span style='color:#C5CDE0;'> Consumption varied by <b>{diff_pct}%</b> across the selected months.</span>
    </div>""", unsafe_allow_html=True)

    # Prediction
    st.markdown("### 🔮 Next Month Prediction")
    z = np.polyfit(range(len(units_list)), units_list, 1)
    pred_units = max(0, round(np.poly1d(z)(len(units_list)), 1))
    pred_amount = calculate_bill(pred_units, provider)
    pred_carbon = calculate_carbon(pred_units)
    p1,p2,p3 = st.columns(3)
    p1.metric("Predicted Units", f"{pred_units} kWh", delta=f"{round(pred_units-units_list[-1],1)} from last")
    p2.metric("Predicted Bill", f"₹{pred_amount:,.0f}")
    p3.metric("Predicted CO₂", f"{pred_carbon} kg")
    trend = "📈 Increasing" if z[0]>0 else "📉 Decreasing"
    st.info(f"**Trend:** {trend} — Avg monthly change: {abs(round(z[0],1))} kWh/month.")

    st.markdown("### 💡 Suggestions Based on Trends")
    if z[0] > 20: suggestion_box("🚨 **Rising trend!** Your consumption is increasing month-over-month. Act now!")
    for s in get_suggestions(max(units_list), provider): suggestion_box(s)

    if pred_units > max(units_list): st.error(f"🚨 ALERT: Next month may be your highest ever ({pred_units} kWh predicted)!")
    elif pred_units > 300: st.warning(f"⚠️ Next month ({pred_units} kWh) is in high tariff territory.")
    else: st.success(f"✅ Next month prediction looks manageable at {pred_units} kWh.")

    for b in bills:
        if b.get("units"):
            save_bill(st.session_state.user_id, provider, b.get("month",""), datetime.now().year,
                      b["units"], b["amount"], round(b["amount"]/b["units"],2), "", "", b.get("carbon",0))
    st.success("💾 All bills saved to your history!")

# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████  ENTER UNITS PAGE  ██████████████████
# ══════════════════════════════════════════════════════════════════════════════
def show_enter_units():
    st.markdown("""<h1 style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;margin-bottom:0.3rem;'>
        🔢 Enter <span style='background:linear-gradient(135deg,#7B61FF,#00E89A);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>Units Manually</span></h1>
        <p style='color:#8B96B0;margin-bottom:1.5rem;'>Know your units? Enter directly for instant analysis.</p>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1,1])
    with col1:
        provider = st.selectbox("⚡ Provider", PROVIDERS, key="eu_prov")
        units = st.number_input("📊 Units Consumed (kWh)", min_value=0.0, step=1.0, key="eu_u")
        month = st.text_input("📅 Billing Month", placeholder="e.g. January 2025", key="eu_m")
        actual = st.number_input("💰 Actual Bill Amount (₹) — optional", min_value=0.0, step=10.0, key="eu_a")
    with col2:
        st.markdown("""<div style='background:rgba(123,97,255,0.08);border:1px solid rgba(123,97,255,0.25);
            border-radius:16px;padding:1.5rem;margin-top:1.8rem;'>
            <div style='color:#7B61FF;font-weight:700;margin-bottom:0.8rem;'>💡 Where to find units?</div>
            <div style='color:#8B96B0;font-size:0.9rem;line-height:1.8;'>
                <b style='color:#C5CDE0;'>MSEDCL:</b> "Units Consumed"<br>
                <b style='color:#C5CDE0;'>Adani:</b> "Consumption (kWh)"<br>
                <b style='color:#C5CDE0;'>Tata Power:</b> "Energy Charges Units"<br>
                <b style='color:#C5CDE0;'>BEST:</b> "Units Consumed"
            </div></div>""", unsafe_allow_html=True)

    if st.button("⚡ Analyse My Usage", key="eu_go", use_container_width=True):
        if not units or units <= 0: st.error("Please enter a valid number of units."); return
        estimated = calculate_bill(units, provider)
        final = actual if actual > 0 else estimated
        carbon = calculate_carbon(units); trees = trees_equivalent(carbon)

        st.markdown("---"); st.markdown("## 📊 Analysis Results")
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("⚡ Units", f"{units} kWh")
        m2.metric("💰 Estimated", f"₹{estimated:,.0f}")
        if actual > 0: m3.metric("📋 Actual", f"₹{actual:,.0f}", delta=f"₹{actual-estimated:+.0f} vs est.")
        else: m3.metric("🌿 CO₂", f"{carbon} kg")
        m4.metric("🌳 Trees", str(trees))

        st.markdown("### 📈 Tariff Slab Breakdown")
        _slab_chart(units, provider)

        slabs = TARIFF.get(provider, TARIFF["MSEDCL"])
        rows = []; rem = units
        for low,high,rate in slabs:
            chunk = min(rem, high-low)
            if chunk<=0: break
            rows.append({"Slab":f"{int(low)}–{int(high) if high<1e8 else '∞'}","Units":round(chunk,1),"Rate (₹/kWh)":rate,"Cost (₹)":round(chunk*rate,0)})
            rem -= chunk
        if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("### 🏢 Provider Bill Comparison")
        cmp = {p: calculate_bill(units, p) for p in PROVIDERS}
        fig = go.Figure(go.Bar(x=list(cmp.keys()), y=list(cmp.values()),
            marker_color=["#FF6B35" if k==provider else "#7B61FF40" for k in cmp],
            text=[f"₹{v:,.0f}" for v in cmp.values()], textposition="outside"))
        dark_layout(fig); st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 🌿 Carbon Footprint Gauge")
        fig2 = go.Figure(go.Indicator(mode="gauge+number+delta", value=carbon,
            number=dict(suffix=" kg CO₂", font=dict(color="#00E89A",family="Syne")),
            delta=dict(reference=82, suffix=" vs avg"),
            gauge=dict(axis=dict(range=[0,500]),bar=dict(color="#00E89A"),bgcolor="rgba(0,0,0,0)",borderwidth=0,
                steps=[dict(range=[0,100],color="rgba(0,232,154,0.15)"),
                       dict(range=[100,250],color="rgba(255,215,0,0.15)"),
                       dict(range=[250,500],color="rgba(255,71,87,0.15)")],
                threshold=dict(line=dict(color="#FF4757",width=2),value=250))))
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)",font=dict(family="Space Grotesk",color="#E8EDF5"),height=250,margin=dict(t=20,b=10))
        st.plotly_chart(fig2, use_container_width=True)

        st.markdown("### 💡 Tips to Save")
        for s in get_suggestions(units, provider): suggestion_box(s)

        if units > 500: st.error("🚨 CRITICAL: 500+ units — most expensive slab!")
        elif units > 300: st.warning("⚠️ Above 300 units — premium tariff rates apply.")
        else: st.success("✅ Healthy usage range!")

        save_bill(st.session_state.user_id, provider, month or datetime.now().strftime("%B %Y"),
                  datetime.now().year, units, final, round(final/units,2), "", "", carbon)
        st.success("💾 Saved to your history!")

# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████  QUICK ESTIMATE PAGE  ██████████████████
# ══════════════════════════════════════════════════════════════════════════════
def show_quick_estimate():
    st.markdown("""<h1 style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;margin-bottom:0.3rem;'>
        ⚡ Quick <span style='background:linear-gradient(135deg,#00E89A,#00D4FF);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>Estimate</span></h1>
        <p style='color:#8B96B0;margin-bottom:1.5rem;'>No bill? Tell us your appliances — we'll estimate your monthly bill instantly.</p>
    """, unsafe_allow_html=True)

    FULL_APPLIANCES = [
        ("🌬️ AC (1.5 ton)",1500),("❄️ Refrigerator",150),("🫧 Washing Machine",500),
        ('📺 LED TV (43")',80),("🚿 Geyser / Water Heater",2000),("💨 Ceiling Fan",75),
        ("💡 LED Bulb (per)",9),("🍳 Microwave",1200),("💻 Computer/Laptop",65),
        ("🔧 Water Pump",750),("🌀 Desert Cooler",200),("☕ Electric Kettle",1500),
        ("📡 Set-Top Box+Router",30),("🍚 Rice Cooker",700),("🔌 Phone Chargers ×4",20),
    ]
    col_l, col_r = st.columns([2,1])
    total_kwh = 0.0; breakdown = {}
    with col_l:
        provider = st.selectbox("⚡ Your Provider", PROVIDERS, key="qe_prov")
        st.markdown("### 🏠 Appliances & Daily Usage")
        st.markdown("<div style='color:#8B96B0;font-size:0.8rem;margin-bottom:0.5rem;'>Qty = number of units &nbsp;·&nbsp; Hrs = daily hours used</div>", unsafe_allow_html=True)
        for name, watt in FULL_APPLIANCES:
            c1,c2,c3 = st.columns([3,1,1])
            c1.markdown(f"<span style='font-size:0.95rem;color:#C5CDE0;'>{name}</span>", unsafe_allow_html=True)
            qty = c2.number_input("Qty", 0, 20, step=1, key=f"qe_q_{name}", label_visibility="collapsed")
            hrs = c3.number_input("Hrs", 0.0, 24.0, step=0.5, key=f"qe_h_{name}", label_visibility="collapsed")
            if qty>0 and hrs>0:
                kwh = (watt*qty*hrs*30)/1000; total_kwh += kwh; breakdown[name] = kwh
        st.markdown(f"""<div style='background:rgba(0,212,255,0.08);border:1px solid rgba(0,212,255,0.3);
            border-radius:12px;padding:1rem;margin-top:1rem;text-align:center;'>
            <div style='color:#8B96B0;font-size:0.85rem;'>Estimated Monthly Consumption</div>
            <div style='font-family:Syne,sans-serif;font-size:2.5rem;font-weight:800;color:#00D4FF;'>{total_kwh:.1f} kWh</div>
        </div>""", unsafe_allow_html=True)
    with col_r:
        if total_kwh > 0:
            est = calculate_bill(total_kwh, provider)
            st.markdown(f"""<div style='background:rgba(123,97,255,0.08);border:1px solid rgba(123,97,255,0.3);
                border-radius:16px;padding:1.2rem;margin-top:4.5rem;text-align:center;'>
                <div style='color:#8B96B0;font-size:0.85rem;'>Est. Monthly Bill</div>
                <div style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;color:#7B61FF;'>₹{est:,.0f}</div>
                <div style='color:#8B96B0;font-size:0.75rem;margin-top:4px;'>~₹{est//30:,}/day</div>
            </div>""", unsafe_allow_html=True)

    if total_kwh > 0 and st.button("🔬 Generate Full Report", key="qe_go", use_container_width=True):
        est = calculate_bill(total_kwh, provider)
        carbon = calculate_carbon(total_kwh); trees = trees_equivalent(carbon)
        st.markdown("---"); st.markdown("## 📊 Estimate Report")
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("⚡ Est. Units", f"{total_kwh:.1f} kWh")
        m2.metric("💰 Est. Bill", f"₹{est:,.0f}")
        m3.metric("🌿 CO₂", f"{carbon} kg")
        m4.metric("🌳 Trees", str(trees))

        st.markdown(f"""<div style='display:flex;gap:1rem;margin:1rem 0;flex-wrap:wrap;'>
            <div style='background:rgba(20,28,48,0.8);border:1px solid rgba(0,212,255,0.2);border-radius:12px;padding:0.8rem 1.2rem;flex:1;text-align:center;'>
                <div style='color:#8B96B0;font-size:0.8rem;'>Daily Cost</div><div style='color:#00D4FF;font-size:1.3rem;font-weight:700;'>₹{est/30:.1f}</div></div>
            <div style='background:rgba(20,28,48,0.8);border:1px solid rgba(123,97,255,0.2);border-radius:12px;padding:0.8rem 1.2rem;flex:1;text-align:center;'>
                <div style='color:#8B96B0;font-size:0.8rem;'>Weekly Cost</div><div style='color:#7B61FF;font-size:1.3rem;font-weight:700;'>₹{est/4.33:.1f}</div></div>
            <div style='background:rgba(20,28,48,0.8);border:1px solid rgba(0,232,154,0.2);border-radius:12px;padding:0.8rem 1.2rem;flex:1;text-align:center;'>
                <div style='color:#8B96B0;font-size:0.8rem;'>Annual Cost</div><div style='color:#00E89A;font-size:1.3rem;font-weight:700;'>₹{est*12:,.0f}</div></div>
        </div>""", unsafe_allow_html=True)

        if breakdown:
            st.markdown("### 🥧 Appliance Breakdown")
            fig = px.pie(names=list(breakdown.keys()), values=[round(v,2) for v in breakdown.values()],
                         hole=0.45, color_discrete_sequence=px.colors.qualitative.Bold)
            fig.update_traces(textposition='inside', textinfo='percent+label', textfont_size=11)
            dark_layout(fig); st.plotly_chart(fig, use_container_width=True)

            st.markdown("### 🔥 Top Energy Consumers")
            df = pd.DataFrame([{"Appliance":k,"Monthly kWh":round(v,1),"Share (%)":round((v/total_kwh)*100,1),"Cost (₹)":round((v/total_kwh)*est,0)}
                                for k,v in sorted(breakdown.items(),key=lambda x:-x[1])]).head(8)
            st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("### 💡 How to Reduce Your Bill")
        for s in get_suggestions(total_kwh, provider): suggestion_box(s)
        if total_kwh > 400: st.error("🚨 Very high estimated usage! Consider energy-efficient appliances.")
        elif total_kwh > 250: st.warning("⚠️ Reducing AC by 1-2 hrs/day can save ₹300-500/month.")
        else: st.success("✅ Estimated usage looks reasonable!")

# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████  HISTORY PAGE  ██████████████████
# ══════════════════════════════════════════════════════════════════════════════
def show_history():
    st.markdown("""<h1 style='font-family:Syne,sans-serif;font-size:2rem;font-weight:800;margin-bottom:0.3rem;'>
        📊 Bill <span style='background:linear-gradient(135deg,#FFD700,#FF6B35);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>History</span></h1>
        <p style='color:#8B96B0;margin-bottom:1.5rem;'>All your electricity data — trends, comparisons, and carbon impact.</p>
    """, unsafe_allow_html=True)

    bills = get_user_bills(st.session_state.user_id)
    if not bills:
        st.markdown("""<div style='text-align:center;padding:4rem;background:rgba(20,28,48,0.6);
            border:1px dashed rgba(0,212,255,0.2);border-radius:20px;'>
            <div style='font-size:4rem;'>📂</div>
            <div style='font-family:Syne,sans-serif;color:#00D4FF;font-size:1.4rem;margin:0.5rem 0;'>No history yet</div>
            <div style='color:#8B96B0;'>Upload or enter your first bill to start tracking!</div>
        </div>""", unsafe_allow_html=True); return

    df = pd.DataFrame(bills)
    m1,m2,m3,m4,m5 = st.columns(5)
    m1.metric("📋 Bills", len(bills))
    m2.metric("⚡ Total kWh", f"{df['units'].sum():,.0f}")
    m3.metric("💰 Total Spent", f"₹{df['amount'].sum():,.0f}")
    m4.metric("🌿 CO₂", f"{df['carbon_footprint'].sum():,.0f} kg")
    m5.metric("📊 Avg/Month", f"{df['units'].mean():,.0f} kWh")
    st.markdown("---")

    c1,c2 = st.columns(2)
    with c1:
        provs = ["All"] + sorted(df["provider"].dropna().unique().tolist())
        fp = st.selectbox("Filter by Provider", provs, key="h_fp")
    with c2:
        sb = st.selectbox("Sort by", ["Newest first","Oldest first","Highest units","Lowest units"], key="h_sb")

    filtered = df.copy()
    if fp != "All": filtered = filtered[filtered["provider"]==fp]
    filtered = filtered.sort_values({"Newest first":"created_at","Oldest first":"created_at",
                                     "Highest units":"units","Lowest units":"units"}[sb],
                                    ascending=sb in ["Oldest first","Lowest units"])
    st.markdown(f"<div style='color:#8B96B0;font-size:0.85rem;margin-bottom:0.5rem;'>Showing {len(filtered)} records</div>", unsafe_allow_html=True)

    if len(filtered) >= 2:
        st.markdown("### 📈 Usage Trend")
        chart = filtered.sort_values("created_at").tail(12)
        labels = [str(r["month"] or r["created_at"][:7]) for _,r in chart.iterrows()]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=labels, y=chart["units"].tolist(), mode="lines+markers",
            name="Units (kWh)", line=dict(color="#00D4FF",width=2.5), marker=dict(size=8),
            fill="tozeroy", fillcolor="rgba(0,212,255,0.08)"))
        fig.add_trace(go.Scatter(x=labels, y=chart["amount"].tolist(), mode="lines+markers",
            name="Amount (₹)", line=dict(color="#FF6B35",width=2,dash="dot"), marker=dict(size=7), yaxis="y2"))
        dark_layout(fig, yaxis=dict(title="Units (kWh)",gridcolor="rgba(255,255,255,0.04)"),
                    yaxis2=dict(title="Amount (₹)",overlaying="y",side="right"))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### 🌿 Carbon Footprint Over Time")
        fig2 = px.area(x=labels, y=chart["carbon_footprint"].tolist(), color_discrete_sequence=["#00E89A"])
        fig2.update_traces(fillcolor="rgba(0,232,154,0.1)", line=dict(width=2))
        dark_layout(fig2); fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("### 📋 All Bills")
    for _,b in filtered.iterrows():
        units = b["units"] or 0; amount = b["amount"] or 0; carbon = b["carbon_footprint"] or 0
        with st.expander(f"⚡ {b['month'] or 'N/A'}  ·  {b['provider']}  ·  {units} kWh  ·  ₹{amount:,.0f}"):
            r1,r2,r3,r4 = st.columns(4)
            r1.metric("Units", f"{units} kWh"); r2.metric("Amount", f"₹{amount:,.0f}")
            r3.metric("Rate", f"₹{b['rate'] or 'N/A'}/kWh"); r4.metric("CO₂", f"{carbon} kg")
            st.markdown(f"**Trees to offset:** {trees_equivalent(carbon)} 🌳")
            if st.button("🗑️ Delete", key=f"del_{b['id']}"):
                delete_bill(b["id"], st.session_state.user_id); st.rerun()

    st.markdown("---")
    st.markdown("### 📥 Export Data")
    export = filtered[["month","provider","units","amount","rate","carbon_footprint","bill_date","created_at"]].copy()
    export.columns = ["Month","Provider","Units (kWh)","Amount (₹)","Rate (₹/kWh)","CO₂ (kg)","Bill Date","Saved On"]
    st.download_button("⬇️ Download as CSV", data=export.to_csv(index=False),
                       file_name="voltiq_history.csv", mime="text/csv", use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████  MAIN ROUTER  ██████████████████
# ══════════════════════════════════════════════════════════════════════════════
if not st.session_state.logged_in:
    show_auth()
else:
    with st.sidebar:
        st.markdown("""<div style='text-align:center;padding:1rem 0 1.5rem;'>
            <div style='font-family:Syne,sans-serif;font-size:1.8rem;font-weight:800;
                background:linear-gradient(135deg,#00D4FF,#7B61FF);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;'>⚡ VOLTIQ</div>
            <div style='color:#8B96B0;font-size:0.75rem;margin-top:2px;letter-spacing:2px;'>SMART ELECTRICITY ANALYZER</div>
        </div>""", unsafe_allow_html=True)
        st.markdown(f"<div style='color:#00E89A;font-size:0.85rem;margin-bottom:1rem;text-align:center;'>👤 {st.session_state.username}</div>", unsafe_allow_html=True)
        st.markdown("---")
        for icon, label, key in [("🏠","Home","home"),("📤","Upload Bill","upload"),
                                   ("🔢","Enter Units","enter_units"),("⚡","Quick Estimate","quick_estimate"),
                                   ("📊","History","history")]:
            if st.button(f"{icon}  {label}", key=f"nav_{key}", use_container_width=True):
                st.session_state.page = key; st.rerun()
        st.markdown("---")
        if st.button("🚪  Logout", use_container_width=True):
            for k in ["logged_in","username","user_id","page"]: st.session_state.pop(k, None)
            st.session_state.logged_in = False; st.rerun()
        st.markdown("<div style='text-align:center;color:#3a4560;font-size:0.7rem;margin-top:2rem;'>Voltiq v1.0 · Maharashtra</div>", unsafe_allow_html=True)

    page = st.session_state.page
    if page == "home": show_home()
    elif page == "upload": show_upload()
    elif page == "enter_units": show_enter_units()
    elif page == "quick_estimate": show_quick_estimate()
    elif page == "history": show_history()
