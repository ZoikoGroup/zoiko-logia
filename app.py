import os
import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from prompts import SYSTEM_PROMPT

load_dotenv()

st.set_page_config(
    page_title="ZoikoLogia | Kriton",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
PAGES = [
    "Landing", "Login", "Register", "Dashboard", "Learning Center",
    "Standards Library", "Worked Examples", "Practice Questions",
    "Workflow Assistant", "Jurisdiction Center", "Source Explorer",
    "Saved Chats", "Reports", "Notifications", "Profile", "Settings",
    "Admin Panel", "Bot",
]

PROFESSIONAL_BODIES = ["ACCA","ICAI","ICAEW","CPA","AICPA","CIMA","AAT","CA ANZ","SAICA"]
STANDARDS = ["IFRS","IAS","US GAAP","ISA","ISQM","OECD","HMRC","IRS","IESBA","IFAC","IPSAS","ESRS","GRI"]
COUNTRIES  = ["India","UK","USA","Canada","Australia","Germany","France"]

WORKED_EXAMPLES = [
    {
        "topic": "Revenue Recognition",
        "question": "When should revenue from a service contract be recognised under IFRS 15?",
        "solution": "When the performance obligation is satisfied, usually over time or at a point in time depending on contract terms.",
        "journal": "Dr Contract Asset / Cr Revenue",
    },
    {
        "topic": "Deferred Revenue",
        "question": "How is customer advance payment recorded before performance obligation is satisfied?",
        "solution": "As a contract liability until the goods or services are delivered.",
        "journal": "Dr Cash / Cr Deferred Revenue",
    },
    {
        "topic": "Inventory",
        "question": "How is inventory valued under IAS 2?",
        "solution": "At the lower of cost and net realisable value.",
        "journal": "Dr Cost of Sales / Cr Inventory",
    },
]

PRACTICE_QUESTIONS = [
    {"question": "Which standard covers lease accounting for lessees and lessors?",
     "options": ["IFRS 15","IFRS 16","IAS 19","IAS 2"], "answer": 1},
    {"question": "What does ISQM 1 address?",
     "options": ["Financial reporting","Quality management","Audit evidence","Tax compliance"], "answer": 1},
    {"question": "Under IFRS, goodwill is tested for impairment at least:",
     "options": ["Annually","Every 3 years","Only on disposal","Only when impairment indicators exist"], "answer": 0},
]

NOTIFICATIONS = [
    "New IFRS release available",
    "ACCA syllabus update published",
    "IAS implementation note refreshed",
    "Practice reminder: complete your Audit module",
    "System update scheduled for tonight",
]

ADMIN_SECTIONS = [
    "Dashboard","Users","AI Models","Knowledge Sources","Standards","Syllabus Management",
    "Content Approval","Practice Questions","Worked Examples","Jurisdictions","Analytics",
    "Feedback","Audit Logs","Roles & Permissions","System Settings",
]

BOT_MODES = [
    " Learning — Students & Trainees",
    " Practice — Accountants & Bookkeepers",
    " Workflow — ZoikoSuite Users",
    " Review — Managers & Partners",
]
BOT_RISKS = [
    " Low — Basic definitions & journal entries",
    " Medium — Complex estimates & consolidation",
    " High — Tax, audit judgment, going concern",
    " Restricted — Legal opinions & audit sign-off",
]
BOT_JURISDICTIONS = [
    "Not specified","International (IFRS/OECD)","United Kingdom",
    "United States","India","Canada","Australia","European Union",
    "Africa","Caribbean","Other",
]

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
def init_session():
    defaults = {
        "authenticated": False,
        "user_name": "Guest",
        "user_email": "",
        "page": "Landing",
        "is_admin": False,
        "messages": [],
        "bot_messages": [],
        "practice_answers": {},
        "practice_submitted": False,
        "selected_body": "ACCA",
        "selected_standard": "IFRS",
        "selected_country": "India",
        "dark_mode": True,
        "notifications": NOTIFICATIONS.copy(),
        "bot_operating_mode": BOT_MODES[0],
        "bot_risk_level": BOT_RISKS[0],
        "bot_jurisdiction": BOT_JURISDICTIONS[0],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

# ─────────────────────────────────────────────────────────────────────────────
# GROQ CLIENT
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)

# ─────────────────────────────────────────────────────────────────────────────
# STYLES  — two separate style blocks
# ─────────────────────────────────────────────────────────────────────────────
# Styles used on ALL pages EXCEPT Bot
MAIN_APP_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp { background: #0A0E1A; color: #FFFFFF !important; }
.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp h5,.stApp h6,
.stApp p,.stApp div,.stApp span,.stApp label,.stApp li,
.stApp a,.stApp strong,.stApp em { color: #FFFFFF !important; }

/* hide sidebar on all non-bot pages */
[data-testid="stSidebar"] { display: none !important; }

#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }

.top-nav {
    display: flex; flex-wrap: wrap; gap: 10px;
    align-items: center; justify-content: space-between;
    background: #0B1224;
    border: 1px solid rgba(148,163,184,0.12);
    padding: 12px 20px; margin-bottom: 18px;
    border-radius: 0 0 18px 18px;
}
.nav-links { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.nav-link {
    color: #CBD5E1; text-decoration: none;
    padding: 10px 14px; border-radius: 12px;
    background: rgba(148,163,184,0.08);
    transition: background 0.2s ease, color 0.2s ease;
    font-size: 0.95rem;
}
.nav-link:hover, .nav-link.active {
    color: #FFFFFF; background: rgba(56,189,248,0.18);
}
.nav-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

.stTextInput > div > div,
.stNumberInput > div > div,
.stTextArea > div > div,
.stSelectbox > div > div {
    background: #0D1220 !important;
    border: 1px solid rgba(148,163,184,0.16) !important;
    border-radius: 14px !important;
}
.stTextInput input, .stTextInput > div > div > input,
.stTextArea > div > div > textarea, .stNumberInput input {
    background: #0D1220 !important; color: #FFFFFF !important; border: none !important;
}
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button {
    background: #0F172A !important; color: #E2E8F0 !important;
    border: 1px solid rgba(56,189,248,0.16) !important;
    border-radius: 14px !important; padding: 10px 18px !important;
}
[data-testid="stButton"] button:hover { background: #11203d !important; color: #FFFFFF !important; }

.hero-box {
    background: linear-gradient(180deg, rgba(15,23,42,0.95), rgba(16,185,129,0.08));
    border: 1px solid rgba(56,189,248,0.14); border-radius: 26px;
    padding: 30px; margin-bottom: 24px;
}
.pill {
    display: inline-block; background: rgba(56,189,248,0.14);
    color: #7DD3FC; padding: 6px 14px; border-radius: 999px;
    font-size: 0.82rem; margin-bottom: 1rem;
}
.hero-title { font-size: 3rem; line-height: 1.05; letter-spacing: -0.03em; margin: 0; color: #FFFFFF; }
.hero-subtitle { color: #FFFFFF; font-size: 1.05rem; margin-top: 0.6rem; }

/* Floating bot button */
.bot-floating { position: fixed; right: 24px; bottom: 24px; z-index: 9999; }
.bot-floating a {
    display: inline-flex; align-items: center; justify-content: center;
    width: 64px; height: 64px; border-radius: 50%;
    background: linear-gradient(135deg, #0EA5E9, #6366F1);
    color: white; font-size: 30px; text-decoration: none;
    box-shadow: 0 16px 30px rgba(14,165,233,0.28);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.bot-floating a:hover {
    transform: scale(1.1); box-shadow: 0 20px 40px rgba(14,165,233,0.45);
}

hr { border-color: #1E2D4A !important; margin: 0.8rem 0 !important; }
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #0A0E1A; }
::-webkit-scrollbar-thumb { background: #1E3A5F; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #38BDF8; }
</style>
"""

# Styles used ONLY on the Bot page — matches Image 3 exactly
BOT_PAGE_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp { background: #0A0E1A; color: #E2E8F0; }

/* Hide top streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }

/* Show and style sidebar */
[data-testid="stSidebar"] {
    display: flex !important;
    background: #0D1220 !important;
    border-right: 1px solid #1E2D4A !important;
    min-width: 240px !important;
}
[data-testid="stSidebar"] > div:first-child { background: #0D1220 !important; }
[data-testid="stSidebar"] * { color: #CBD5E1 !important; }

[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div {
    background: #131929 !important;
    border: 1px solid #1E3A5F !important;
    border-radius: 8px !important;
    color: #94A3B8 !important;
    font-size: 0.82rem !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] > div > div:hover {
    border-color: #38BDF8 !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] label {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
    color: #64748B !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button {
    background: linear-gradient(135deg, #1E293B, #0F172A) !important;
    color: #94A3B8 !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
    width: 100% !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover {
    border-color: #EF4444 !important;
    color: #EF4444 !important;
    background: #1A0A0A !important;
}

/* Main area background */
.stApp { background: #0A0E1A !important; }
section.main > div { background: #0A0E1A !important; }

/* Chat messages */
[data-testid="stChatMessage"] {
    background: #0D1220 !important;
    border: 1px solid #1E2D4A !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    margin-bottom: 0.75rem !important;
    color: #F1F5F9 !important;
}
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] li,
[data-testid="stChatMessage"] span,
[data-testid="stChatMessage"] div,
[data-testid="stChatMessage"] strong,
[data-testid="stChatMessage"] em,
[data-testid="stChatMessage"] code,
[data-testid="stChatMessage"] h1,
[data-testid="stChatMessage"] h2,
[data-testid="stChatMessage"] h3,
[data-testid="stChatMessage"] h4 { color: #F1F5F9 !important; }

[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background: #0F1E38 !important;
    border-color: #1E3A6A !important;
    border-left: 3px solid #2563EB !important;
}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
    background: #0A1628 !important;
    border-color: #1E2D4A !important;
    border-left: 3px solid #38BDF8 !important;
}
[data-testid="chatAvatarIcon-user"] {
    background: linear-gradient(135deg, #2563EB, #7C3AED) !important;
    border-radius: 8px !important;
}
[data-testid="chatAvatarIcon-assistant"] {
    background: linear-gradient(135deg, #0EA5E9, #6366F1) !important;
    border-radius: 8px !important;
}

/* Chat input */
[data-testid="stChatInput"] {
    background: #0D1220 !important;
    border: 1px solid #1E3A5F !important;
    border-radius: 12px !important;
    box-shadow: 0 0 30px #38BDF808 !important;
}
[data-testid="stChatInput"]:focus-within {
    border-color: #38BDF8 !important;
    box-shadow: 0 0 0 2px #38BDF820 !important;
}
[data-testid="stChatInput"] textarea {
    background: #0D1220 !important;
    color: #F1F5F9 !important;
    font-size: 0.9rem !important;
    caret-color: #38BDF8 !important;
    border-radius: 8px !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: #475569 !important; }
[data-testid="stChatInput"] > div { background: #0D1220 !important; border-radius: 12px !important; }
[data-testid="stChatInput"] button {
    background: linear-gradient(135deg, #0EA5E9, #6366F1) !important;
    border-radius: 8px !important;
    border: none !important;
}

/* Bottom bar */
.stBottom, .stBottom > div,
[data-testid="stBottom"], [data-testid="stBottom"] > div {
    background: #0A0E1A !important;
    border-top: 1px solid #1E2D4A !important;
    box-shadow: none !important;
}

/* Spinner */
[data-testid="stSpinner"] { color: #38BDF8 !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #0A0E1A; }
::-webkit-scrollbar-thumb { background: #1E3A5F; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #38BDF8; }

hr { border-color: #1E2D4A !important; margin: 0.8rem 0 !important; }

/* Bot header title */
.bot-main-title {
    font-family: 'Playfair Display', serif;
    font-size: 2rem;
    font-weight: 700;
    background: linear-gradient(135deg, #38BDF8 0%, #818CF8 50%, #C084FC 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0;
    line-height: 1.2;
}
.bot-caption {
    font-size: 0.78rem;
    color: #475569;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-top: 0.35rem;
}
.status-dot {
    display: inline-block;
    width: 7px; height: 7px;
    background: #22C55E;
    border-radius: 50%;
    margin-right: 6px;
    box-shadow: 0 0 6px #22C55E;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def set_page(page_name):
    st.session_state.page = page_name
    st.query_params["page"] = page_name


def render_nav():
    links = [
        p for p in PAGES
        if p != "Bot"
        and not (p == "Admin Panel" and not st.session_state.is_admin)
    ]
    nav_items = "".join([
        f'<a class="nav-link {"active" if st.session_state.page == item else ""}" '
        f'href="?page={item}">{item}</a>'
        for item in links
    ])
    auth_html = ""
    if st.session_state.authenticated:
        auth_html = (
            f'<span style="color:#94A3B8;">Signed in as {st.session_state.user_name}</span>'
            f' <a class="nav-link" href="?page=Landing">Logout</a>'
        )
    st.markdown(
        f"""
        <div class='top-nav'>
            <div style='display:flex;align-items:center;gap:14px;'>
                <span style='font-size:1.3rem;font-weight:700;color:#38BDF8;'>ZoikoLogia</span>
                <span style='color:#94A3B8;'>Kriton Professional Intelligence</span>
            </div>
            <div class='nav-links'>{nav_items}</div>
            <div class='nav-actions'>{auth_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_bot_icon():
    """Floating 💬 button — only shown on non-Bot pages."""
    st.markdown(
        """
        <div class="bot-floating">
            <a href="?page=Bot" target="_self" title="Open Kriton Bot">💬</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer():
    st.markdown("---")
    st.markdown(
        "<div style='text-align:center;color:#94A3B8;font-size:0.9rem;'>"
        "© 2026 ZoikoLogia. Powered by Kriton™. Not a substitute for professional advice."
        "</div>",
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
# MAIN APP PAGES
# ─────────────────────────────────────────────────────────────────────────────
def hero_section():
    st.markdown("<div class='hero-box'>", unsafe_allow_html=True)
    st.markdown("""
        <div style='display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap;'>
            <div style='max-width:640px;'>
                <div class='pill'>Professional Accounting Intelligence</div>
                <h1 class='hero-title'>Ask accounting, audit, tax, and compliance questions with source-backed answers.</h1>
                <p class='hero-subtitle'>ZoikoLogia combines Kriton AI with rich standards, exam-style support, and workflow guidance for accounting teams.</p>
                <div style='margin-top:24px;'>
                    <a href='?page=Register' style='margin-right:12px;padding:12px 24px;background:#0EA5E9;color:#fff;border-radius:999px;text-decoration:none;'>Start Free</a>
                    <a href='?page=Bot' style='padding:12px 24px;border:1px solid #38BDF8;color:#38BDF8;border-radius:999px;text-decoration:none;'>Try Kriton Bot</a>
                </div>
            </div>
            <div style='min-width:280px;padding:24px;background:rgba(255,255,255,0.04);border:1px solid rgba(148,163,184,0.1);border-radius:24px;'>
                <h3 style='margin-bottom:12px;color:#fff;'>Meet Kriton AI</h3>
                <p style='color:#CBD5E1;'>Kriton delivers guided answers in Learning, Practice, Workflow and Review modes, with source-quality traceability for accounting professionals.</p>
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def landing_page():
    st.markdown("# Welcome to ZoikoLogia")
    hero_section()
    st.write("---")
    col1, _ = st.columns([2, 1])
    with col1:
        st.subheader("What is ZoikoLogia?")
        st.write("ZoikoLogia is an accounting intelligence platform for professionals, students and firms. Use Kriton to ask source-backed questions, study for exams, manage workflow tasks and follow standards review guidance.")
        st.subheader("Features")
        st.write("- AI-guided accounting and tax answers\n- Standards and syllabus knowledge base\n- Practice questions and worked examples\n- Workflow tools for payroll, bank reconciliation and close")
        st.write("---")
        st.subheader("Professional Bodies Supported")
        st.write(", ".join(PROFESSIONAL_BODIES))
        st.write("---")
        st.subheader("Standards Supported")
        st.write(", ".join(STANDARDS))
    st.write("---")
    st.subheader("Testimonials")
    st.write("**Aditi M.** – 'Kriton makes exam revision and compliance research faster.'\n\n**Michael R.** – 'The workflow cards help my team close month-end with fewer errors.'")
    st.write("---")
    st.subheader("Pricing")
    st.write("Free access for learners and a premium plan for teams with admin controls and source explorer.")
    st.write("---")
    st.subheader("Contact")
    st.write("Email: support@zoikologia.com\nPhone: +44 20 7946 0000")
    render_footer()


def login_page():
    st.markdown("# Login")
    email    = st.text_input("Email")
    password = st.text_input("Password", type="password")
    st.checkbox("Remember Me")
    if st.button("Login"):
        if email and password:
            st.session_state.authenticated = True
            st.session_state.user_name  = email.split("@")[0].title()
            st.session_state.user_email = email
            st.success("Logged in successfully.")
            set_page("Dashboard")
        else:
            st.error("Please enter an email and password.")
    st.write("---")
    st.markdown("[Forgot Password](#)")
    st.write("---")
    st.markdown("**Continue with**")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Continue with Google"):
            st.info("Google sign-in is not configured in this demo.")
    with c2:
        if st.button("Continue with Microsoft"):
            st.info("Microsoft sign-in is not configured in this demo.")


def register_page():
    st.markdown("# Register")
    full_name        = st.text_input("Full Name")
    email            = st.text_input("Email")
    password         = st.text_input("Password", type="password")
    confirm_password = st.text_input("Confirm Password", type="password")
    st.text_input("Profession")
    st.selectbox("Country", COUNTRIES)
    st.text_input("Qualification")
    st.text_input("Organization")
    if st.button("Create Account"):
        if not full_name or not email or not password or not confirm_password:
            st.error("Please complete all required fields.")
        elif password != confirm_password:
            st.error("Passwords do not match.")
        else:
            st.session_state.authenticated = True
            st.session_state.user_name  = full_name
            st.session_state.user_email = email
            st.success("Account created successfully.")
            set_page("Dashboard")


def dashboard_page():
    st.markdown(f"# Hello {st.session_state.user_name} 👋")
    st.write("Welcome back to ZoikoLogia.")
    st.write("---")
    st.text_input("Search Anything...", placeholder="Search accounting standards, topics or workflows")
    st.markdown("### Quick Actions")
    c1, c2, c3, c4 = st.columns(4)
    c1.button("Ask Kriton", key="qa", on_click=lambda: set_page("Bot"))
    c2.button("Learn",      key="ql", on_click=lambda: set_page("Learning Center"))
    c3.button("Practice",   key="qp", on_click=lambda: set_page("Practice Questions"))
    c4.button("Workflow",   key="qw", on_click=lambda: set_page("Workflow Assistant"))
    st.write("---")
    st.markdown("### Recent Chats")
    st.write("- Deferred Revenue\n- Lease Accounting\n- Inventory")
    st.markdown("### Recent Documents")
    st.write("- IFRS 15 summary\n- Audit planning checklist\n- Payroll compliance note")
    st.markdown("### Recent Examples")
    st.write("- Revenue recognition example\n- Depreciation journal entry\n- Tax provision walkthrough")
    st.write("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("Progress", "72%", "+8% this week")
    c2.metric("Notifications", len(st.session_state.notifications))
    c3.metric("Bookmarks", "14")


def learning_center_page():
    st.markdown("# Learning Center")
    categories = ["Accounting","Tax","Audit","Payroll","Compliance","Ethics",
                  "Financial Reporting","Governance","Internal Controls","ESG"]
    st.write("### Topics")
    cols = st.columns(5)
    for i, t in enumerate(categories):
        cols[i % 5].button(t, key=f"topic_{t}")
    st.write("---")
    st.subheader("Professional Bodies")
    sel = st.selectbox("Choose a body", PROFESSIONAL_BODIES,
                       index=PROFESSIONAL_BODIES.index(st.session_state.selected_body))
    st.session_state.selected_body = sel
    st.write(f"### {sel}")
    st.write("**Subjects**: Financial Reporting, Audit & Assurance, Taxation, Management Accounting")
    st.write("**Exam Pattern**: Multiple choice and long-form scenario questions")
    st.write("**Learning Outcomes**: Apply standards, prepare journal entries, assess risks")
    st.write("**Worked Examples**: Revenue recognition, lease accounting, payroll entries")
    st.write("**Practice Questions**: Scenario-based MCQs and case studies")
    st.write("**Exam Traps**: Timing differences, estimates, classification errors")


def standards_library_page():
    st.markdown("# Standards Library")
    search_term = st.text_input("Search standards, authorities or topics")
    filtered = [s for s in STANDARDS if search_term.lower() in s.lower()] if search_term else STANDARDS
    if not filtered:
        st.warning("No standards found.")
        filtered = STANDARDS
    idx = filtered.index(st.session_state.selected_standard) if st.session_state.selected_standard in filtered else 0
    sel = st.selectbox("Select standard", filtered, index=idx)
    st.session_state.selected_standard = sel
    st.write(f"## {sel}")
    st.write("**Overview**: Core guidance for accounting, auditing or reporting.")
    st.write("**Requirements**: Follow published principles, apply disclosures, support judgments.")
    st.write("**Examples**: Revenue contracts, impairment tests, audit evidence.")
    st.write("**Effective Date**: 2024-01-01 | **Jurisdiction**: International / Local.")
    st.write("**Related Topics**: Governance, control environment, disclosures.")


def worked_examples_page():
    st.markdown("# Worked Examples")
    for ex in WORKED_EXAMPLES:
        st.markdown(f"### {ex['topic']}")
        st.write(f"**Question:** {ex['question']}")
        st.write(f"**Solution:** {ex['solution']}")
        st.write(f"**Journal Entry:** {ex['journal']}")
        st.write("**Calculation:** Use contract terms or cost formulas to compute values.")
        st.write("**Explanation:** Apply the relevant standard and recognise timing.")
        st.write("---")


def practice_questions_page():
    st.markdown("# Practice Questions")
    for i, item in enumerate(PRACTICE_QUESTIONS):
        st.write(f"**{i+1}. {item['question']}**")
        st.session_state.practice_answers[i] = st.radio(
            "Choose an option", item['options'], key=f"practice_{i}")
    if st.button("Submit Answers"):
        st.session_state.practice_submitted = True
    if st.session_state.practice_submitted:
        score, mistakes = 0, []
        for i, item in enumerate(PRACTICE_QUESTIONS):
            ans = st.session_state.practice_answers.get(i)
            if ans == item['options'][item['answer']]:
                score += 1
            else:
                mistakes.append((item['question'], ans, item['options'][item['answer']]))
        st.success(f"Score: {score}/{len(PRACTICE_QUESTIONS)}")
        if mistakes:
            st.warning("Review the following mistakes:")
            for q, a, c in mistakes:
                st.write(f"- {q} | Your answer: {a} | Correct: {c}")
        st.info("Improvement Tips: Review standard guidance, apply examples, and check terminology.")


def workflow_assistant_page():
    st.markdown("# Workflow Assistant")
    st.write("Choose a workflow to view checklists, errors, documents, and AI suggestions.")
    for item in ["Payroll","Tax Filing","Month End Close","Bank Reconciliation","Working Papers","Financial Reporting","Audit Trail"]:
        if st.button(item, key=f"wf_{item}"):
            st.session_state.selected_workflow = item
    if "selected_workflow" in st.session_state:
        st.markdown(f"## {st.session_state.selected_workflow} Checklist")
        st.write("- Confirm data completeness\n- Validate calculations\n- Attach supporting documents\n- Document approvals")
        st.write("**Common Errors**: missing entries, incorrect classifications, timing issues")
        st.write("**Required Documents**: invoices, bank statements, payroll registers")
        st.write("**AI Suggestions**: Use Kriton for journal entry support and standards references.")


def jurisdiction_center_page():
    st.markdown("# Jurisdiction Center")
    country = st.selectbox("Choose Country", COUNTRIES,
                           index=COUNTRIES.index(st.session_state.selected_country))
    st.session_state.selected_country = country
    st.write(f"## {country}")
    st.write("**Accounting Standards**: IFRS / Local GAAP")
    st.write("**Tax Rules**: Local corporate and indirect tax guidance")
    st.write("**Compliance**: Filing deadlines, reporting requirements")
    st.write("**Payroll**: Statutory deductions and reporting")
    st.write("**Local Regulations**: Entity and registration requirements")


def source_explorer_page():
    st.markdown("# Source Explorer")
    source = st.selectbox("Select source", STANDARDS)
    st.write(f"## {source}")
    st.write("**Version**: 2025.1 | **Effective Date**: 2025-01-01")
    st.write("**Authority**: Official standard setter | **Confidence**: High")
    st.write("**Reference**: Source section or paragraph number")


def saved_chats_page():
    st.markdown("# Saved Chats")
    st.write("- Deferred Revenue\n- Lease Accounting\n- Inventory\n- Audit Planning\n- Transfer Pricing\n- GST Questions")


def reports_page():
    st.markdown("# Reports")
    st.metric("Learning Progress", "72%")
    st.metric("Accuracy", "85%")
    st.metric("Practice Score", "78%")
    st.write("### Weekly Progress")
    st.line_chart({"Progress": [60,65,68,72,72]})
    st.write("### Monthly Progress")
    st.bar_chart({"Score": [68,72,75,78,82]})


def notifications_page():
    st.markdown("# Notifications")
    for note in st.session_state.notifications:
        st.info(note)


def profile_page():
    st.markdown("# Profile")
    st.text_input("Name",  value=st.session_state.user_name)
    st.text_input("Email", value=st.session_state.user_email)
    st.text_input("Qualification", value="CA / ACCA")
    st.text_input("Organization",  value="ZoikoCorp")
    st.selectbox("Country", COUNTRIES,
                 index=COUNTRIES.index(st.session_state.selected_country))
    st.slider("Experience (years)", 0, 30, 5)
    st.selectbox("Subscription", ["Free","Premium"], index=1)
    st.text_area("Achievements", value="Kriton Super User")
    if st.button("Save Profile"):
        st.success("Profile updated.")


def settings_page():
    st.markdown("# Settings")
    st.selectbox("Theme", ["Dark","Light"], index=0 if st.session_state.dark_mode else 1)
    st.selectbox("Language", ["English","Spanish","French","Hindi"], index=0)
    st.checkbox("Enable notifications", value=True)
    dark_mode = st.checkbox("Dark mode", value=st.session_state.dark_mode)
    if st.button("Save Settings"):
        st.session_state.dark_mode = dark_mode
        st.success("Settings saved.")
    st.write("**Security**")
    st.checkbox("Enable 2FA")
    st.button("Change Password")
    st.button("Delete Account")


def admin_panel_page():
    st.markdown("# Admin Panel")
    st.write("Only visible to admin users.")
    for s in ADMIN_SECTIONS:
        st.write(f"- {s}")


# ─────────────────────────────────────────────────────────────────────────────
# BOT PAGE  — identical look to Image 3 (no top nav, sidebar + clean chat)
# ─────────────────────────────────────────────────────────────────────────────
def bot_page():
    client = get_client()

    if client is None:
        st.error("GROQ_API_KEY not found. Add it to your .env file and restart.")
        st.code("GROQ_API_KEY=gsk_your_key_here", language="bash")
        return

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        # Brand
        st.markdown("""
        <div style="padding:1.2rem 0 0.6rem 0; text-align:center;">
            <span style="font-family:'Playfair Display',serif; font-size:1.5rem; font-weight:700;
                background:linear-gradient(135deg,#38BDF8,#818CF8);
                -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                background-clip:text; display:block;">ZoikoLogia</span>
            <span style="font-size:0.65rem; color:#64748B; letter-spacing:0.08em;
                text-transform:uppercase; display:block; margin-top:3px;">
                Kriton · Professional Judgment Advisor
            </span>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown(
            '<span style="font-size:0.65rem;font-weight:600;letter-spacing:0.12em;'
            'text-transform:uppercase;color:#475569;">Configuration</span>',
            unsafe_allow_html=True,
        )

        # Operating Mode
        mode_idx = BOT_MODES.index(st.session_state.bot_operating_mode) \
            if st.session_state.bot_operating_mode in BOT_MODES else 0
        operating_mode = st.selectbox(
            "Operating Mode", options=BOT_MODES, index=mode_idx,
            help="Controls the depth and style of Kriton™'s answers.",
        )
        st.session_state.bot_operating_mode = operating_mode

        # Risk Level
        risk_idx = BOT_RISKS.index(st.session_state.bot_risk_level) \
            if st.session_state.bot_risk_level in BOT_RISKS else 0
        risk_level = st.selectbox(
            "Risk Level", options=BOT_RISKS, index=risk_idx,
            help="Force a specific risk level for your question.",
        )
        st.session_state.bot_risk_level = risk_level

        # Jurisdiction
        jur_idx = BOT_JURISDICTIONS.index(st.session_state.bot_jurisdiction) \
            if st.session_state.bot_jurisdiction in BOT_JURISDICTIONS else 0
        jurisdiction = st.selectbox(
            "Jurisdiction", options=BOT_JURISDICTIONS, index=jur_idx,
            help="Set jurisdiction for tax, payroll, and local compliance questions.",
        )
        st.session_state.bot_jurisdiction = jurisdiction

        st.markdown("---")

        # Config badge
        mode_label = operating_mode.split("—")[0].strip()
        risk_label = risk_level.split("—")[0].strip()
        st.markdown(f"""
        <div style="background:#0A1628;border:1px solid #1E2D4A;border-radius:10px;
            padding:10px 14px;margin:4px 0;">
            <div style="display:flex;justify-content:space-between;padding:3px 0;">
                <span style="font-size:0.68rem;color:#475569;text-transform:uppercase;letter-spacing:0.06em;">Mode</span>
                <span style="font-size:0.7rem;font-weight:600;color:#38BDF8;">{mode_label}</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:3px 0;">
                <span style="font-size:0.68rem;color:#475569;text-transform:uppercase;letter-spacing:0.06em;">Risk</span>
                <span style="font-size:0.7rem;font-weight:600;color:#38BDF8;">{risk_label}</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:3px 0;">
                <span style="font-size:0.68rem;color:#475569;text-transform:uppercase;letter-spacing:0.06em;">Jurisdiction</span>
                <span style="font-size:0.7rem;font-weight:600;color:#38BDF8;">{jurisdiction}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        if st.button("Clear Conversation", use_container_width=True):
            st.session_state.bot_messages = []
            st.rerun()

        # Back link
        st.markdown(
            '<div style="text-align:center;margin-top:10px;">'
            '<a href="?page=Landing" style="font-size:0.75rem;color:#475569;'
            'text-decoration:none;">← Back to ZoikoLogia</a></div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div style="font-size:0.65rem;color:#374151;text-align:center;'
            'margin-top:12px;border-top:1px solid #1E2D4A;padding-top:10px;">'
            'Not a substitute for a licensed accountant, tax adviser, or auditor.</div>',
            unsafe_allow_html=True,
        )

    # ── Main chat area ───────────────────────────────────────────────────────
    st.markdown("""
    <div style="padding:1.5rem 0 1rem 0; border-bottom:1px solid #1E2D4A; margin-bottom:1.2rem;">
        <h1 class="bot-main-title">ZoikoLogia | Kriton</h1>
        <div class="bot-caption">
            <span class="status-dot"></span>
            Governed Accounting Intelligence · Professional Judgment Advisor
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Chat history
    for msg in st.session_state.bot_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Ask Kriton™ an accounting, audit, tax or compliance question..."):

        context_injection = (
            "\n[USER CONTEXT]\n"
            f"- Operating Mode: {operating_mode}\n"
            f"- Risk Level Override: {risk_level}\n"
            f"- Jurisdiction: {jurisdiction}\n\n"
            "Apply the above mode and risk level strictly when composing your answer.\n"
            'If jurisdiction is "Not specified" and the question is jurisdiction-sensitive, ask for it.'
        )

        st.session_state.bot_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        api_messages = (
            [{"role": "system", "content": SYSTEM_PROMPT + context_injection}]
            + st.session_state.bot_messages
        )

        with st.chat_message("assistant"):
            with st.spinner("Kriton™ is thinking..."):
                try:
                    stream = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=api_messages,
                        temperature=0.3,
                        max_tokens=2048,
                        stream=True,
                    )
                    response = st.write_stream(
                        chunk.choices[0].delta.content or ""
                        for chunk in stream
                        if chunk.choices[0].delta.content
                    )
                    st.session_state.bot_messages.append(
                        {"role": "assistant", "content": response}
                    )
                except Exception as exc:
                    st.error(f"Groq error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    init_session()

    # Resolve page from URL
    page_query = st.query_params.get("page", st.session_state.page)
    if isinstance(page_query, list):
        page_query = page_query[0]
    if page_query in PAGES:
        st.session_state.page = page_query

    page = st.session_state.page

    # ── Inject page-specific styles FIRST, before any other rendering ────────
    if page == "Bot":
        st.markdown(BOT_PAGE_STYLES, unsafe_allow_html=True)
        # Bot page: no top nav, no floating icon, no footer — pure chat UI
        bot_page()
        return

    # All other pages
    st.markdown(MAIN_APP_STYLES, unsafe_allow_html=True)
    render_bot_icon()   # floating 💬 button
    render_nav()        # top navigation bar
    st.write("")

    if page == "Landing":
        landing_page()
    elif page == "Login":
        login_page()
    elif page == "Register":
        register_page()
    elif page == "Dashboard":
        if st.session_state.authenticated:
            dashboard_page()
        else:
            st.warning("Please log in to access the dashboard.")
            login_page()
    elif page == "Learning Center":
        learning_center_page()
    elif page == "Standards Library":
        standards_library_page()
    elif page == "Worked Examples":
        worked_examples_page()
    elif page == "Practice Questions":
        practice_questions_page()
    elif page == "Workflow Assistant":
        workflow_assistant_page()
    elif page == "Jurisdiction Center":
        jurisdiction_center_page()
    elif page == "Source Explorer":
        source_explorer_page()
    elif page == "Saved Chats":
        if st.session_state.authenticated:
            saved_chats_page()
        else:
            st.warning("Please log in.")
            login_page()
    elif page == "Reports":
        if st.session_state.authenticated:
            reports_page()
        else:
            st.warning("Please log in.")
            login_page()
    elif page == "Notifications":
        if st.session_state.authenticated:
            notifications_page()
        else:
            st.warning("Please log in.")
            login_page()
    elif page == "Profile":
        if st.session_state.authenticated:
            profile_page()
        else:
            st.warning("Please log in.")
            login_page()
    elif page == "Settings":
        if st.session_state.authenticated:
            settings_page()
        else:
            st.warning("Please log in.")
            login_page()
    elif page == "Admin Panel":
        if st.session_state.authenticated and st.session_state.is_admin:
            admin_panel_page()
        else:
            st.warning("Admin access required.")
            login_page()

    render_footer()


if __name__ == "__main__":
    main()
