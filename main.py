from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from urllib.parse import quote
import sqlite3
import os

R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")

app = FastAPI(title="Email Webmail API")

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(os.path.dirname(__file__), "database.sqlite")

def get_db():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not ready yet!")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/login")
def login(creds: LoginRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email, name FROM users WHERE email = ? AND password = ?", (creds.email, creds.password))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    return {"success": True, "email": user["email"], "name": user["name"]}

@app.get("/api/ping")
def ping():
    return {"status": "ok"}

@app.get("/api/emails")
def get_emails(owner: str, page: int = 1, limit: int = 50, folder: str = "", search: str = ""):
    if not owner:
        raise HTTPException(status_code=401, detail="Authentication required")
        
    offset = (page - 1) * limit
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT id, message_id, subject, sender, date, folder FROM emails WHERE owner_email = ?"
    count_query = "SELECT COUNT(*) as total FROM emails WHERE owner_email = ?"
    params = [owner]
    
    if folder:
        query += " AND folder = ?"
        count_query += " AND folder = ?"
        params.append(folder)
        
    if search:
        search_term = f"%{search}%"
        search_snippet = " AND (subject LIKE ? OR sender LIKE ? OR body_text LIKE ? OR recipient LIKE ?)"
        query += search_snippet
        count_query += search_snippet
        params.extend([search_term, search_term, search_term, search_term])
        
    cursor.execute(count_query, params)
    total_count = cursor.fetchone()["total"]
    
    query += " ORDER BY id ASC LIMIT ? OFFSET ?"
    page_params = params + [limit, offset]
    
    cursor.execute(query, page_params)
    emails = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "emails": emails
    }

@app.get("/api/emails/{email_id}")
def get_email(email_id: int, owner: str):
    if not owner:
        raise HTTPException(status_code=401, detail="Authentication required")
        
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM emails WHERE id = ? AND owner_email = ?", (email_id, owner))
    email_row = cursor.fetchone()
    
    if not email_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Email not found or access denied")
        
    email_dict = dict(email_row)
    
    cursor.execute("SELECT id, filename, content_type, content_id, file_path FROM attachments WHERE email_id = ?", (email_id,))
    attachment_rows = cursor.fetchall()
    
    attachments = []
    for row in attachment_rows:
        att = dict(row)
        att["size"] = 0
        attachments.append(att)
    
    body_html = email_dict.get("body_html")
    if body_html:
        for att in attachments:
            cid = att.get("content_id")
            if cid:
                replacement = f"/api/attachments/{att['id']}"
                body_html = body_html.replace(f"cid:{cid}", replacement)
                body_html = body_html.replace(f"CID:{cid}", replacement)
        email_dict["body_html"] = body_html

    email_dict["attachments"] = attachments
    conn.close()
    
    return email_dict

@app.get("/api/attachments/{attachment_id}")
def get_attachment(attachment_id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT filename, file_path, content_type FROM attachments WHERE id = ?", (attachment_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if not R2_PUBLIC_URL:
        raise HTTPException(status_code=503, detail="Storage not configured")

    r2_url = f"{R2_PUBLIC_URL}/{quote(row['file_path'])}"
    return RedirectResponse(url=r2_url)
