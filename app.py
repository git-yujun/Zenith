import streamlit as st
import sqlite3
import datetime
import hashlib
import base64
import fitz
from openai import OpenAI

DB_FILE = "zenith.db"
openai_api_key = st.secrets["OPENAI_API_KEY"]

# ---------- DB 초기화 -------------
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password_hash TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                role TEXT,
                content TEXT,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            )
        """)

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# ---------- 회원가입 / 로그인 UI -------------
def login_ui():
    st.sidebar.subheader("로그인 / 회원가입")
    action = st.sidebar.radio("선택", ["로그인", "회원가입"])
    username = st.sidebar.text_input("아이디")
    password = st.sidebar.text_input("비밀번호", type="password")
    if action == "회원가입" and st.sidebar.button("회원가입"):
        if not username or not password:
            st.sidebar.error("아이디와 비밀번호를 입력해주세요.")
        else:
            pw_hash = hash_password(password)
            try:
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, pw_hash)
                    )
                st.sidebar.success("회원가입이 완료되었습니다.")
            except sqlite3.IntegrityError:
                st.sidebar.error("이미 사용 중인 아이디입니다.")
                
    if action == "로그인" and st.sidebar.button("로그인"):
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row and row[1] == hash_password(password):
            st.session_state.user_id = row[0]
            st.session_state.username = username
            st.sidebar.success(f"{username} 님 환영합니다!")
            st.rerun()
        else:
            st.sidebar.error("아이디 또는 비밀번호가 틀렸습니다.")

# ---------- 대화 관련 DB 함수 -------------
def get_conversations(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT id, name FROM conversations WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return rows

def create_conversation(user_id, name=None):
    if name is None:
        name = "New Chat " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "INSERT INTO conversations (user_id, name) VALUES (?, ?)",
            (user_id, name)
        )
        return cur.lastrowid

def update_conversation_name(conversation_id, new_name):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "UPDATE conversations SET name = ? WHERE id = ?",
            (new_name, conversation_id)
        )

def delete_conversation(conversation_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

def get_messages(conversation_id):
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,)
        ).fetchall()
    return [{"role": r, "content": c} for r, c in rows]

def save_message(conversation_id, role, content):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content)
        )

# ---------- 초기 설정 -------------
init_db()
client = OpenAI(api_key=openai_api_key)
st.title("Zenith")

# 로그인 전용 UI 및 세션 상태 체크
if "user_id" not in st.session_state:
    login_ui()
    st.stop()

# ---------- 사이드바: 모델 선택 & 대화 관리 -------------
with st.sidebar:
    st.header(f"{st.session_state.username}")
    if st.button("로그아웃"):
        for k in ["user_id", "username", "conversation_id", "conversation_name"]:
            if k in st.session_state:
                del st.session_state[k]
        st.success("로그아웃 되었습니다.")
        st.rerun()
        
    st.subheader("모델 선택")
    models = {"o4-mini": "o4-mini", "GPT-4.1": "gpt-4.1"}
    if "selected_model" not in st.session_state:
        st.session_state.selected_model = list(models.values())[0]
    choice = st.selectbox("OpenAI 모델", list(models.keys()),
                          index=list(models.values()).index(st.session_state.selected_model))
    st.session_state.selected_model = models[choice]

    st.write("---")
    st.subheader("대화 목록")
    convs = get_conversations(st.session_state.user_id)
    conv_ids = [c[0] for c in convs]
    conv_names = [c[1] for c in convs]

    if st.button("새 대화"):
        new_id = create_conversation(st.session_state.user_id)
        st.session_state.conversation_id = new_id
        st.rerun()

    if convs:
        idx = conv_ids.index(st.session_state.get("conversation_id", conv_ids[0])) \
              if "conversation_id" in st.session_state and st.session_state["conversation_id"] in conv_ids \
              else 0
        sel = st.radio("대화 선택", conv_names, index=idx)
        sel_id = conv_ids[conv_names.index(sel)]
        st.session_state.conversation_id = sel_id
        st.session_state.conversation_name = sel

        # 대화명 변경
        def _save_name():
            new = st.session_state["name_input"]
            if new.strip():
                update_conversation_name(st.session_state.conversation_id, new)
                st.session_state.conversation_name = new
                st.success("이름 변경 완료")
                st.experimental_rerun()
            else:
                st.warning("이름을 비워둘 수 없습니다.")

        st.text_input("대화명 수정", st.session_state.conversation_name,
                      key="name_input", on_change=_save_name)
        if st.button("대화 삭제"):
            delete_conversation(st.session_state.conversation_id)
            st.rerun()

# 최초 대화 설정
if "conversation_id" not in st.session_state:
    cs = get_conversations(st.session_state.user_id)
    if cs:
        st.session_state.conversation_id = cs[0][0]
        st.session_state.conversation_name = cs[0][1]
    else:
        cid = create_conversation(st.session_state.user_id)
        st.session_state.conversation_id = cid
        st.session_state.conversation_name = "New Chat"

# ---------- 메인: 채팅 히스토리 표시 -------------
msgs = get_messages(st.session_state.conversation_id)
for m in msgs:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

st.markdown("---")

# ---------- 파일 업로드 (PDF / 이미지) -------------
uploaded = st.file_uploader("파일 업로드", type=["pdf", "png", "jpg", "jpeg"])
if st.session_state.selected_model == "gpt-4.1" and uploaded:
    # PDF 처리
    if uploaded.type == "application/pdf":
        doc = fitz.open(stream=uploaded.read(), filetype="pdf")
        text = "".join([p.get_text() for p in doc])
        prompt = st.text_input(" ", value="이 PDF 내용을 요약해줘")
        if st.button("PDF 분석"):
            save_message(st.session_state.conversation_id, "user", prompt)
            with st.spinner("PDF 분석중..."):
                resp = client.chat.completions.create(
                    model=st.session_state.selected_model,
                    messages=[{"role":"user","content":[{"type":"text","text":f"{prompt}\n{text}"}]}],
                    stream=True
                )
                answer = st.write_stream(resp)
            save_message(st.session_state.conversation_id, "assistant", answer)
            st.rerun()
    # 이미지 처리
    elif uploaded.type.startswith("image/"):
        st.image(uploaded, width=200)
        b64 = base64.b64encode(uploaded.getvalue()).decode()
        data_url = f"data:{uploaded.type};base64,{b64}"
        prompt = st.text_input(" ", value="이 이미지 설명해줘")
        if st.button("이미지 분석"):
            save_message(st.session_state.conversation_id, "user", prompt)
            with st.spinner("이미지 분석중..."):
                resp = client.chat.completions.create(
                    model=st.session_state.selected_model,
                    messages=[{
                        "role":"user",
                        "content":[
                            {"type":"text","text":prompt},
                            {"type":"image_url","image_url":{"url":data_url}}
                        ]
                    }],
                    stream=True
                )
                answer = st.write_stream(resp)
            save_message(st.session_state.conversation_id, "assistant", answer)
            st.rerun()
    else:
        st.warning("지원되지 않는 파일 형식입니다.")
elif uploaded:
    st.warning("현재 모델은 파일 입력을 지원하지 않습니다.")

# ---------- 채팅 입력 -------------
if user_input := st.chat_input("메시지를 입력하세요"):
    save_message(st.session_state.conversation_id, "user", user_input)
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        stream = client.chat.completions.create(
            model=st.session_state.selected_model,
            messages=get_messages(st.session_state.conversation_id),
            stream=True
        )
        answer = st.write_stream(stream)

    save_message(st.session_state.conversation_id, "assistant", answer)
    st.rerun()
