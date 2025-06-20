import streamlit as st
import sqlite3
import datetime
import base64
from openai import OpenAI
from os.path import abspath

DB_FILE = "zenith.db"
openai_api_key = st.secrets["OPENAI_API_KEY"]
#GUIDE = ""
#with open(abspath("AI_Dev\Zenith\guide.txt"), 'r', encoding='UTF-8') as text:
    #GUIDE += text.read()

# ----------- DB 관련 ----------- #
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                role TEXT,
                content TEXT,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id))
        """)

def get_conversations():
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT id, name FROM conversations ORDER BY created_at DESC").fetchall()
        return rows

def create_conversation(name=None):
    with sqlite3.connect(DB_FILE) as conn:
        if name is None:
            name = "New Chat " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        cur = conn.execute("INSERT INTO conversations (name) VALUES (?)", (name,))
        return cur.lastrowid

def get_messages(conversation_id):
    # 기존 DB에서 메시지 불러오기
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC", 
            (conversation_id,)
        ).fetchall()
        messages = [{"role": role, "content": content} for role, content in rows]

    # system 프롬프트 추가 (맨 앞!)
    #system_prompt = {
        #"role": "system",
        #"content": f"너는 이런 말투로 대화하는 AI야. 아래 말투들을 반드시 따라야 해:\n{GUIDE}"
    #} [system_prompt] + messages
    return messages

def save_message(conversation_id, role, content):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content)
        )

def update_conversation_name(conversation_id, new_name):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE conversations SET name = ? WHERE id = ?", (new_name, conversation_id))

def delete_conversation(conversation_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

# ------------- 초기 세팅 ------------- #
init_db()
client = OpenAI(api_key=openai_api_key)
st.title("Zenith")

#AI_img = abspath("AI_Dev\Zenith\image.png")

# ------------- 세션 상태 ------------- #
if "conversation_id" not in st.session_state:
    convs = get_conversations()
    if convs:
        st.session_state.conversation_id = convs[0][0]
    else:
        st.session_state.conversation_id = create_conversation()

if "conversation_name" not in st.session_state:
    convs = get_conversations()
    if convs:
        st.session_state.conversation_name = [name for (_id, name) in convs if _id == st.session_state.conversation_id][0]
    else:
        st.session_state.conversation_name = "New Chat"

# ------------- 사이드바 ------------- #
with st.sidebar:
    st.header("💬 대화 목록")
    conversations = get_conversations()
    conv_names = [name for (_id, name) in conversations]
    conv_ids = [_id for (_id, name) in conversations]

    if st.button("➕ 새 대화"):
        new_id = create_conversation()
        st.session_state.conversation_id = new_id
        st.rerun()

    if conversations:
        selected_idx = conv_ids.index(st.session_state.conversation_id)
        selected_conv = st.radio(
            "대화 선택", conv_names, index=selected_idx, key="conv_radio"
        )
        st.session_state.conversation_id = conv_ids[conv_names.index(selected_conv)]
        st.session_state.conversation_name = selected_conv

        st.write("---")
        # 👉 대화명 변경 with 저장 버튼
        def save_conv_name():
            new_name = st.session_state["name_text_input"]
            if new_name.strip() == "":
                st.warning("대화명은 비워둘 수 없습니다.")
            else:
                st.session_state.conversation_name = new_name
                update_conversation_name(st.session_state.conversation_id, new_name)
                st.success("이름이 변경되었습니다.")
                st.rerun()

        st.text_input(
            "현재 대화명",
            st.session_state.conversation_name,
            key="name_text_input",
            on_change=save_conv_name,
        )
                    
        # 대화 삭제 버튼
        if st.button("🗑️ 현재 대화 삭제"):
            delete_conversation(st.session_state.conversation_id)
            convs = get_conversations()
            if convs:
                st.session_state.conversation_id = convs[0][0]
            else:
                st.session_state.conversation_id = create_conversation()
            st.rerun()

# ------------- 메인: 채팅 히스토리 ------------- #
messages = get_messages(st.session_state.conversation_id)
if "messages" not in st.session_state:
    st.session_state.messages = messages
else:
    st.session_state.messages = messages  # always reload from DB in this code

for message in st.session_state.messages:
    with st.chat_message(message["role"], avatar=None): # avatar=AI_img if message["role"] == "assistant" else None
        st.markdown(message["content"])
    

st.markdown("---")

uploaded_img = st.file_uploader("Image", type=["jpg", "jpeg", "png", "pdf"], key="zenith_img_upload")
if uploaded_img is not None:
    st.image(uploaded_img, width=150)
    st.info(f"파일명: {uploaded_img.name} / 파일크기: {uploaded_img.size // 1024}KB")

    # base64 encode and data URI
    bytes_data = uploaded_img.getvalue()
    mime = uploaded_img.type  # 예: "image/png", "image/jpeg"
    b64 = base64.b64encode(bytes_data).decode('utf-8')
    data_url = f"data:{mime};base64,{b64}"

    user_prompt = st.text_input("이 사진에 대해 궁금한 점을 입력하세요", value="이 사진의 내용을 설명해줘", key="image_prompt")
    if st.button("사진 분석"):
        with st.spinner("AI가 사진을 분석 중입니다..."):
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                max_tokens=512,
            )
            st.success("분석 완료!")
            st.write(response.choices[0].message.content)

# ------------- 채팅 입력 및 답변 생성 ------------- #
if prompt := st.chat_input("메시지를 입력하세요"):
    save_message(st.session_state.conversation_id, "user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)

    # OpenAI 답변 생성
    with st.chat_message("assistant", avatar=None): #avatar=AI_img 
        stream = client.chat.completions.create(
            model="gpt-4.1",
            messages=get_messages(st.session_state.conversation_id),
            stream=True,
        )
        response = st.write_stream(stream)
    save_message(st.session_state.conversation_id, "assistant", response)

    st.rerun()