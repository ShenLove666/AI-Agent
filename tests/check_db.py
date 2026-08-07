from db.database import get_db
from db.models import ChatHistory
import json

db = next(get_db())
try:
    msgs = db.query(ChatHistory).order_by(ChatHistory.id.desc()).limit(20).all()
    for m in msgs:
        print(f"ID: {m.id} | Role: {m.role} | Content: {m.content}")
finally:
    db.close()
