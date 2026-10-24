import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from datetime import datetime
import os

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

# --- DATABASE SETUP ---
Base = declarative_base()
engine = create_engine("sqlite:///chat.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    user = Column(String)
    text = Column(String)
    file = Column(String)
    file_name = Column(String)
    file_type = Column(String)
    time = Column(String)

Base.metadata.create_all(bind=engine)

# --- APP SETUP ---
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
socket_app = socketio.ASGIApp(sio, app)

users = {} 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
async def index():
    file_path = os.path.join(BASE_DIR, "static", "index.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# --- SOCKET EVENTS (CHAT) ---
@sio.event
async def connect(sid, environ):
    print(f"✅ Connected: {sid}")

@sio.event
async def disconnect(sid):
    username = users.pop(sid, None)
    if username:
        await sio.emit('system', {'text': f'{username} left the chat', 'time': datetime.now().strftime('%H:%M')})
        await broadcast_users()

@sio.event
async def join(sid, data):
    username = data.get('username', '').strip()
    if not username: return
    users[sid] = username

    db = SessionLocal()
    old_msgs = db.query(Message).order_by(Message.id.desc()).limit(50).all()
    db.close()
    
    history = [{'user': m.user, 'text': m.text, 'file': m.file, 'name': m.file_name, 'type': m.file_type, 'time': m.time} for m in reversed(old_msgs)]
    await sio.emit('history', history, to=sid)
    await sio.emit('system', {'text': f'{username} joined the chat', 'time': datetime.now().strftime('%H:%M')})
    await broadcast_users()

@sio.event
async def message(sid, data):
    username = users.get(sid)
    if not username: return
    text = data.get('text', '').strip()
    if not text: return

    time_now = datetime.now().strftime('%H:%M')
    db = SessionLocal()
    new_msg = Message(user=username, text=text, time=time_now)
    db.add(new_msg); db.commit(); db.close()

    await sio.emit('message', {'user': username, 'text': text, 'time': time_now, 'sid': sid})

@sio.event
async def file_share(sid, data):
    username = users.get(sid)
    if not username: return
    time_now = datetime.now().strftime('%H:%M')
    file_data, file_name, file_type = data.get('file'), data.get('name'), data.get('type')
    if not file_data: return

    db = SessionLocal()
    new_msg = Message(user=username, text=f"[FILE] {file_name}", file=file_data, file_name=file_name, file_type=file_type, time=time_now)
    db.add(new_msg); db.commit(); db.close()

    await sio.emit('message', {'user': username, 'file': file_data, 'name': file_name, 'type': file_type, 'time': time_now, 'sid': sid})

async def broadcast_users():
    await sio.emit('online_users', list(users.values()))

# ==========================================
# --- SOCKET EVENTS (WEBRTC CALLING) ---
# ==========================================

def get_sid_by_username(username):
    for s, u in users.items():
        if u == username:
            return s
    return None

@sio.event
async def call_offer(sid, data):
    target = data.get('to')
    target_sid = get_sid_by_username(target)
    if target_sid:
        await sio.emit('incoming_call', {
            'from': users[sid],
            'offer': data['offer'],
            'call_type': data['call_type']
        }, to=target_sid)

@sio.event
async def call_answer(sid, data):
    target_sid = get_sid_by_username(data.get('to'))
    if target_sid:
        await sio.emit('call_accepted', {'answer': data['answer']}, to=target_sid)

@sio.event
async def ice_candidate(sid, data):
    target_sid = get_sid_by_username(data.get('to'))
    if target_sid:
        await sio.emit('ice_candidate', {'candidate': data['candidate']}, to=target_sid)

@sio.event
async def call_end(sid, data):
    target_sid = get_sid_by_username(data.get('to'))
    if target_sid:
        await sio.emit('call_ended', {}, to=target_sid)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(socket_app, host="0.0.0.0", port=port)