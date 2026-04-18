from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from urllib.parse import quote
from email.utils import parsedate_to_datetime
from datetime import datetime
import sqlite3
import os

R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")

app = FastAPI(title="Email Webmail API")

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

def parse_email_date(date_str):
    """Parse RFC 2822 email date string to datetime. Returns None on failure."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(str(date_str).strip())
    except Exception:
        pass
    for fmt in ("%d %b %Y %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(date_str).strip()[:25], fmt)
        except Exception:
            pass
    return None

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

@app.get("/api/dates")
def get_dates(owner: str, folder: str = ""):
    """Return sorted list of unique dates (YYYY-MM-DD) that have emails."""
    if not owner:
        raise HTTPException(status_code=401, detail="Authentication required")

    conn = get_db()
    cursor = conn.cursor()

    query = "SELECT DISTINCT date FROM emails WHERE owner_email = ? AND date IS NOT NULL"
    params = [owner]
    if folder:
        query += " AND folder = ?"
        params.append(folder)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    date_set = set()
    for row in rows:
        d = parse_email_date(row["date"])
        if d:
            date_set.add(d.strftime("%Y-%m-%d"))

    return sorted(list(date_set))

@app.get("/api/emails")
def get_emails(owner: str, page: int = 1, limit: int = 50, folder: str = "", search: str = "", date: str = ""):
    if not owner:
        raise HTTPException(status_code=401, detail="Authentication required")

    conn = get_db()
    cursor = conn.cursor()

    base = "SELECT id, message_id, subject, sender, recipient, date, folder FROM emails WHERE owner_email = ?"
    params = [owner]

    if folder:
        base += " AND folder = ?"
        params.append(folder)

    if search:
        search_term = f"%{search}%"
        base += " AND (subject LIKE ? OR sender LIKE ? OR body_text LIKE ? OR recipient LIKE ?)"
        params.extend([search_term, search_term, search_term, search_term])

    if date:
        # Fetch all matching rows and filter by parsed date in Python
        cursor.execute(base + " ORDER BY id DESC", params)
        all_rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        filtered = [r for r in all_rows if (lambda d: d and d.strftime("%Y-%m-%d") == date)(parse_email_date(r["date"]))]
        return {"total": len(filtered), "page": 1, "limit": len(filtered), "emails": filtered}

    # Normal paginated flow — newest first
    count_query = "SELECT COUNT(*) as total FROM emails WHERE owner_email = ?"
    count_params = [owner]
    if folder:
        count_query += " AND folder = ?"
        count_params.append(folder)
    if search:
        count_query += " AND (subject LIKE ? OR sender LIKE ? OR body_text LIKE ? OR recipient LIKE ?)"
        count_params.extend([search_term, search_term, search_term, search_term])

    cursor.execute(count_query, count_params)
    total_count = cursor.fetchone()["total"]

    offset = (page - 1) * limit
    cursor.execute(base + " ORDER BY id DESC LIMIT ? OFFSET ?", params + [limit, offset])
    emails = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return {"total": total_count, "page": page, "limit": limit, "emails": emails}

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
    attachments = []
    for row in cursor.fetchall():
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
