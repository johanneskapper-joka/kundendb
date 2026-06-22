from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from supabase import create_client
import anthropic
import os
import re
import json
import httpx
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Optional
import openai

app = FastAPI()

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    if request.method == "OPTIONS":
        response = JSONResponse(content={}, status_code=200)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# Service-Role-Key (nur serverseitig!) für Datei-Uploads in Supabase Storage.
# Fällt auf den normalen Key zurück, falls noch nicht gesetzt – damit der Server nicht abstürzt.
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
supabase_admin = create_client(os.environ["SUPABASE_URL"], SUPABASE_SERVICE_KEY) if SUPABASE_SERVICE_KEY else supabase

claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# E-Mail-Reports über Resend (https://resend.com).
# RESEND_API_KEY: API-Key aus dem Resend-Konto (beginnt mit "re_").
# REPORT_FROM_EMAIL: Absender, muss zu einer in Resend verifizierten Domain gehören.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
REPORT_FROM_EMAIL = os.environ.get("REPORT_FROM_EMAIL", "")

VOICE_IDS = {
    "de": "1J0wWp4zPQIvsK7Xwh34",
    "fr": "E4GQ42zEV1kwul03Bl16",
    "en": "Gfpl8Yo74Is0W6cPUWWT",
}

# ─────────────────────────────────────────
# AUTH – Sessions (in-memory)
# ─────────────────────────────────────────

active_sessions = {}

@app.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    email = body.get("email", "").lower().strip()
    password = body.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="E-Mail und Passwort erforderlich")

    password_hash = hashlib.sha256(password.encode()).hexdigest()

    result = supabase.table("users")\
        .select("*, workspaces(*)")\
        .eq("email", email)\
        .eq("password_hash", password_hash)\
        .eq("is_active", True)\
        .execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="Ungültige Zugangsdaten")

    user = result.data[0]
    token = secrets.token_hex(32)
    active_sessions[token] = {
        "user_id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "workspace_id": user["workspace_id"],
        "workspace": user.get("workspaces"),
        "expires": datetime.now() + timedelta(hours=8)
    }

    return {
        "token": token,
        "role": user["role"],
        "full_name": user["full_name"],
        "workspace_id": user["workspace_id"],
        "workspace": user.get("workspaces")
    }

@app.post("/auth/logout")
async def logout(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    active_sessions.pop(token, None)
    return {"status": "ok"}

@app.get("/auth/me")
async def get_me(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = active_sessions.get(token)
    if not session or session["expires"] < datetime.now():
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    return session

# ─────────────────────────────────────────
# USER MANAGEMENT (nur Admin)
# ─────────────────────────────────────────

def get_session(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = active_sessions.get(token)
    if not session or session["expires"] < datetime.now():
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    return session

@app.get("/users")
async def get_users(request: Request):
    session = get_session(request)
    if session["role"] != "admin":
        raise HTTPException(status_code=403, detail="Kein Zugriff")
    result = supabase.table("users").select("id, email, full_name, role, workspace_id, is_active, created_at").execute()
    return result.data

@app.post("/users")
async def create_user(request: Request):
    session = get_session(request)
    if session["role"] != "admin":
        raise HTTPException(status_code=403, detail="Kein Zugriff")

    body = await request.json()
    email = body.get("email", "").lower().strip()
    password = body.get("password", "")
    full_name = body.get("full_name", "")
    role = body.get("role", "read")
    workspace_id = body.get("workspace_id") or None

    if not email or not password:
        raise HTTPException(status_code=400, detail="E-Mail und Passwort erforderlich")
    if role not in ["admin", "change", "read"]:
        raise HTTPException(status_code=400, detail="Ungültige Rolle")

    password_hash = hashlib.sha256(password.encode()).hexdigest()

    try:
        result = supabase.table("users").insert({
            "email": email,
            "password_hash": password_hash,
            "full_name": full_name,
            "role": role,
            "workspace_id": workspace_id,
            "is_active": True
        }).execute()
        return {"success": True, "user": result.data[0]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fehler: {str(e)}")

@app.put("/users/{user_id}")
async def update_user(user_id: str, request: Request):
    session = get_session(request)
    if session["role"] != "admin":
        raise HTTPException(status_code=403, detail="Kein Zugriff")

    body = await request.json()
    payload = {}

    if "full_name" in body: payload["full_name"] = body["full_name"]
    if "role" in body:
        if body["role"] not in ["admin", "change", "read"]:
            raise HTTPException(status_code=400, detail="Ungültige Rolle")
        payload["role"] = body["role"]
    if "workspace_id" in body: payload["workspace_id"] = body["workspace_id"] or None
    if "is_active" in body: payload["is_active"] = body["is_active"]
    if "password" in body and body["password"]:
        payload["password_hash"] = hashlib.sha256(body["password"].encode()).hexdigest()

    supabase.table("users").update(payload).eq("id", user_id).execute()
    return {"success": True}

@app.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    session = get_session(request)
    if session["role"] != "admin":
        raise HTTPException(status_code=403, detail="Kein Zugriff")
    if session["user_id"] == user_id:
        raise HTTPException(status_code=400, detail="Du kannst dich nicht selbst löschen")
    supabase.table("users").delete().eq("id", user_id).execute()
    return {"success": True}

# ─────────────────────────────────────────
# FUZZY MATCH
# ─────────────────────────────────────────

def fuzzy_match_companies(text: str, contacts: list) -> str:
    if not contacts or not text:
        return text
    company_names = [c.get('company_name', '') for c in contacts if c.get('company_name')]
    if not company_names:
        return text
    words = text.split()
    result_words = []
    i = 0
    while i < len(words):
        matched = False
        for length in range(min(4, len(words) - i), 0, -1):
            phrase = ' '.join(words[i:i+length])
            if len(phrase) < 3:
                continue
            best_match = None
            best_score = 0
            for company in company_names:
                score = similarity_score(phrase.lower(), company.lower())
                if score > best_score:
                    best_score = score
                    best_match = company
            if best_score > 0.75 and best_match:
                result_words.append(best_match)
                i += length
                matched = True
                break
        if not matched:
            result_words.append(words[i])
            i += 1
    return ' '.join(result_words)

def similarity_score(a: str, b: str) -> float:
    if a == b: return 1.0
    if not a or not b: return 0.0
    if a in b or b in a: return 0.85
    longer = a if len(a) >= len(b) else b
    shorter = a if len(a) < len(b) else b
    matches = 0
    used = [False] * len(longer)
    for char in shorter:
        for j, lchar in enumerate(longer):
            if not used[j] and char == lchar:
                matches += 1
                used[j] = True
                break
    if matches == 0: return 0.0
    score = (matches / len(shorter) + matches / len(longer)) / 2
    if a[0] == b[0]: score = min(1.0, score + 0.1)
    return score

# ─────────────────────────────────────────
# DUPLIKAT-PRÜFUNG
# ─────────────────────────────────────────
# Prüft VOR dem Speichern, ob es schon einen ähnlichen Kontakt gibt.
# Vergleicht: (Firmenname + Ansprechpartner identisch) ODER Telefon identisch ODER E-Mail identisch.
# Gelöschte Kontakte (Papierkorb) werden NICHT als Duplikat gewertet.

def _normalize_text(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip().lower())

def _normalize_phone(s: str) -> str:
    return re.sub(r'[^\d+]', '', s or '')

@app.post("/contacts/check-duplicate")
async def check_duplicate(request: Request):
    try:
        body = await request.json()
        company_name = _normalize_text(body.get("company_name", ""))
        contact_name = _normalize_text(body.get("contact_name", ""))
        phone = _normalize_phone(body.get("phone", ""))
        email = _normalize_text(body.get("email", ""))
        workspace_id = body.get("workspace_id")
        exclude_id = body.get("exclude_id")  # beim Bearbeiten: eigenen Kontakt nicht als Duplikat zählen

        if not company_name and not phone and not email:
            return {"duplicates": []}

        query = supabase.table("contacts").select("*").is_("deleted_at", "null")
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        result = query.execute()
        candidates = result.data or []

        matches = []
        for c in candidates:
            if exclude_id and c.get("id") == exclude_id:
                continue
            c_company = _normalize_text(c.get("company_name", ""))
            c_contact = _normalize_text(c.get("contact_name", ""))
            c_phone = _normalize_phone(c.get("phone", ""))
            c_email = _normalize_text(c.get("email", ""))

            is_match = False
            reason = []
            if company_name and contact_name and c_company == company_name and c_contact == contact_name:
                is_match = True
                reason.append("Name + Ansprechpartner identisch")
            if phone and c_phone and phone == c_phone:
                is_match = True
                reason.append("Telefonnummer identisch")
            if email and c_email and email == c_email:
                is_match = True
                reason.append("E-Mail identisch")

            if is_match:
                matches.append({
                    "id": c.get("id"),
                    "company_name": c.get("company_name"),
                    "contact_name": c.get("contact_name"),
                    "phone": c.get("phone"),
                    "email": c.get("email"),
                    "reason": ", ".join(reason)
                })

        return {"duplicates": matches}
    except Exception as e:
        print(f"Duplicate check error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────

BASE_SYSTEM_PROMPT = """Du bist ein intelligenter Assistent für ein kleines Team.
Du führst echte Gespräche – du erinnerst dich an alles was in dieser Unterhaltung gesagt wurde, hakst nach, machst Vorschläge und denkst mit.

Du hast Zugriff auf eine Datenbank und kannst:
- Neue Einträge sofort erstellen
- Bestehende Einträge aktualisieren
- Informationen abrufen und zusammenfassen
- In der Sprache des Nutzers antworten (Deutsch, Französisch, Englisch)

Kern-Felder: company_name (PFLICHT), contact_name, email, phone, language, notes, last_contact, status (aktiv/interessiert/inaktiv), rating (ABC-Klassifizierung: A, B oder C)
{custom_fields_info}

REGEL 1 – IMMER sofort speichern:
Wenn der Nutzer einen neuen Eintrag anlegen will oder neue Infos nennt, sende SOFORT einen db_action Block – NIEMALS erst nach weiteren Infos fragen bevor du speicherst.
Beim Erstellen reicht der Name als company_name. Weitere Felder können danach ergänzt werden.

REGEL 2 – db_action Format:
<db_action>
{{
  "action": "create" oder "update" oder "none",
  "company_name": "Vollständiger Name",
  "contact_name": "falls bekannt",
  "notes_append": "nur wenn Info nicht in custom_fields passt",
  "status": "aktiv/interessiert/inaktiv oder leer lassen",
  "last_contact": "YYYY-MM-DD oder leer lassen",
  "rating": "A, B, C oder leer lassen",
  "custom_fields": {{
    "key": "value"
  }}
}}
</db_action>

REGEL 3 – custom_fields:
- Nutze IMMER die definierten Workspace-Felder wenn die Information passt
- Schreibe NUR in notes_append wenn die Info in kein Workspace-Feld passt
- Sende nur geänderte Felder – bestehende bleiben erhalten

REGEL 4 – Antworten:
- Maximal 2-3 Sätze
- Bestätige was gespeichert wurde, frage dann optional nach weiteren Infos
- Nur was in den Daten steht – niemals spekulieren
- Wenn etwas nicht in den Daten steht: "Dazu habe ich keine Information"
{extra_prompt}"""

def build_system_prompt(workspace: dict = None) -> str:
    custom_fields_info = ""
    extra_prompt = ""
    if workspace:
        schema = workspace.get("field_schema") or []
        if schema:
            field_list = ", ".join([f"{f['key']} ({f['label']})" for f in schema])
            custom_fields_info = f"\nZusatz-Felder dieses Workspace: {field_list}"
        extra = workspace.get("system_prompt_extra", "")
        if extra:
            extra_prompt = f"\n\nWorkspace-Kontext: {extra}"
    return BASE_SYSTEM_PROMPT.format(
        custom_fields_info=custom_fields_info,
        extra_prompt=extra_prompt
    )

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    language: str = "de"
    history: List[Message] = []
    workspace_id: Optional[str] = None


@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    workspace = None
    if req.workspace_id:
        ws_result = supabase.table("workspaces").select("*").eq("id", req.workspace_id).execute()
        if ws_result.data:
            workspace = ws_result.data[0]

    query = supabase.table("contacts").select("*").is_("deleted_at", "null")
    if req.workspace_id:
        query = query.eq("workspace_id", req.workspace_id)
    result = query.execute()
    contacts = result.data

    contacts_text = "\n\n".join([
        f"Firma: {c.get('company_name','')}\n"
        f"Kontakt: {c.get('contact_name','')}\n"
        f"Status: {c.get('status','')}\n"
        f"Letzter Kontakt: {c.get('last_contact','')}\n"
        f"Notizen: {c.get('notes','')}"
        + (f"\nZusatzfelder: {json.dumps(c.get('custom_fields') or {}, ensure_ascii=False)}" if c.get('custom_fields') else "")
        for c in contacts
    ]) if contacts else "Noch keine Einträge."

    system_prompt = build_system_prompt(workspace)
    messages = []
    db_prefix = f"Kundendatenbank:\n{contacts_text}\n\n---\nNachricht ({req.language}): "

    if req.history:
        messages.append({"role": req.history[0].role, "content": db_prefix + req.history[0].content})
        for msg in req.history[1:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": req.message + f"\n\nWICHTIG: Antworte IMMER auf {req.language.upper()} – egal in welcher Sprache die Frage gestellt wurde."})
    else:
        messages.append({"role": "user", "content": db_prefix + req.message + f"\n\nWICHTIG: Antworte IMMER auf {req.language.upper()} – egal in welcher Sprache die Frage gestellt wurde."})

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=system_prompt,
        messages=messages
    )

    response_text = response.content[0].text

    if "<db_action>" in response_text:
        match = re.search(r'<db_action>(.*?)</db_action>', response_text, re.DOTALL)
        if match:
            try:
                action_data = json.loads(match.group(1).strip())
                action = action_data.get("action")
                if action in ["create", "update"] and action_data.get("company_name"):
                    existing = supabase.table("contacts").select("*").eq("company_name", action_data["company_name"]).is_("deleted_at", "null")
                    if req.workspace_id:
                        existing = existing.eq("workspace_id", req.workspace_id)
                    existing = existing.execute()

                    update_payload = {
                        "company_name": action_data.get("company_name"),
                        "status": action_data.get("status"),
                        "last_contact": action_data.get("last_contact", datetime.today().strftime('%Y-%m-%d')),
                        "updated_at": datetime.utcnow().isoformat()
                    }
                    if req.workspace_id:
                        update_payload["workspace_id"] = req.workspace_id
                    if action_data.get("contact_name"):
                        update_payload["contact_name"] = action_data.get("contact_name")

                    if action_data.get("custom_fields"):
                        existing_cf = {}
                        if existing.data:
                            existing_cf = existing.data[0].get("custom_fields") or {}
                        merged_cf = {**existing_cf, **action_data.get("custom_fields")}
                        update_payload["custom_fields"] = merged_cf

                    # ABC-Klassifizierung, falls die KI eine setzt
                    rating_val = normalize_rating(action_data.get("rating"))
                    if rating_val:
                        update_payload["rating"] = rating_val

                    if existing.data:
                        old_notes = existing.data[0].get("notes", "") or ""
                        new_note = action_data.get("notes_append", "")
                        if new_note:
                            update_payload["notes"] = f"{old_notes}\n[{datetime.today().strftime('%d.%m.%Y')}] {new_note}".strip()
                        supabase.table("contacts").update(update_payload).eq("id", existing.data[0]["id"]).execute()
                        _a_uid, _a_uname = get_actor(request)
                        log_activity("update", contact_name=action_data.get("company_name"),
                                     workspace_id=req.workspace_id, details="per KI-Chat",
                                     user_id=_a_uid, user_name=_a_uname)
                    else:
                        update_payload["notes"] = action_data.get("notes_append", "")
                        update_payload["contact_no"] = generate_contact_no(req.workspace_id)
                        supabase.table("contacts").insert(update_payload).execute()
                        _a_uid, _a_uname = get_actor(request)
                        log_activity("create", contact_name=action_data.get("company_name"),
                                     workspace_id=req.workspace_id, details="per KI-Chat",
                                     user_id=_a_uid, user_name=_a_uname)
            except Exception as e:
                print(f"DB error: {e}")

    clean_response = re.sub(r'<db_action>.*?</db_action>', '', response_text, flags=re.DOTALL).strip()
    return {"reply": clean_response}

# ─────────────────────────────────────────
# SPEECH
# ─────────────────────────────────────────

MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"]
MONTHS_FR = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
MONTHS_EN = ["January","February","March","April","May","June","July","August","September","October","November","December"]

def format_for_speech(text: str, lang: str) -> str:
    months = MONTHS_DE if lang == "de" else MONTHS_FR if lang == "fr" else MONTHS_EN

    def replace_date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        month = months[mo-1] if 1 <= mo <= 12 else m.group(2)
        return f"{d}. {month} {y}"
    text = re.sub(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b', replace_date, text)

    def replace_iso(m):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        month = months[mo-1] if 1 <= mo <= 12 else m.group(2)
        return f"{d}. {month} {y}"
    text = re.sub(r'\b(\d{4})-(\d{2})-(\d{2})\b', replace_iso, text)

    def replace_phone(m):
        digits = m.group(0).replace('+', '00').replace(' ', '').replace('-', '')
        return ' '.join(digits)
    text = re.sub(r'[+]?[\d][\d\s\-]{6,}', replace_phone, text)

    text = re.sub(r'(\d+\.\d{3})€', lambda m: m.group(0).replace('.', '') + ' Euro', text)
    text = re.sub(r'(\d+)€', r'\1 Euro', text)
    text = re.sub(r'(\d+)\$', r'\1 Dollar', text)

    def year_to_words_de(m):
        y = int(m.group(0))
        if 2000 <= y <= 2099:
            rest = y - 2000
            if rest == 0: return "zweitausend"
            elif rest < 10:
                return f"zweitausendund{['null','ein','zwei','drei','vier','fünf','sechs','sieben','acht','neun'][rest]}"
            elif rest < 20:
                teens = ['zehn','elf','zwölf','dreizehn','vierzehn','fünfzehn','sechzehn','siebzehn','achtzehn','neunzehn']
                return f"zweitausendund{teens[rest-10]}"
            else:
                tens = ['','','zwanzig','dreißig','vierzig','fünfzig','sechzig','siebzig','achtzig','neunzig']
                ones = ['','ein','zwei','drei','vier','fünf','sechs','sieben','acht','neun']
                t, o = rest // 10, rest % 10
                if o == 0: return f"zweitausendund{tens[t]}"
                return f"zweitausendund{ones[o]}und{tens[t]}"
        return m.group(0)

    def year_to_words_fr(m):
        y = int(m.group(0))
        if 2000 <= y <= 2099:
            rest = y - 2000
            if rest == 0: return "deux mille"
            elif rest < 20:
                nums = ['','un','deux','trois','quatre','cinq','six','sept','huit','neuf','dix','onze','douze','treize','quatorze','quinze','seize','dix-sept','dix-huit','dix-neuf']
                return f"deux mille {nums[rest]}"
            else: return f"deux mille {rest}"
        return m.group(0)

    def year_to_words_en(m):
        y = int(m.group(0))
        if 2000 <= y <= 2099:
            rest = y - 2000
            if rest == 0: return "two thousand"
            elif rest < 10: return f"two thousand and {rest}"
            else: return f"twenty {rest}"
        return m.group(0)

    year_func = year_to_words_de if lang == "de" else year_to_words_fr if lang == "fr" else year_to_words_en
    text = re.sub(r'\b(20\d{2})\b', year_func, text)
    return text

@app.post("/transcribe")
async def transcribe(request: Request):
    try:
        form = await request.form()
        audio_file = form.get("audio")
        lang = form.get("language", "de")
        companies = form.get("companies", "")

        if not audio_file:
            return JSONResponse({"error": "No audio"}, status_code=400)
        if not openai_client:
            return JSONResponse({"error": "No OpenAI key"}, status_code=400)

        audio_bytes = await audio_file.read()
        filename = audio_file.filename or "audio.webm"

        prompt = ""
        if companies:
            prompt = f"Firmen und Namen: {companies}. "
        prompt += "Dies ist eine Geschäftsnachricht über Kundenkontakte."

        import io
        audio_io = io.BytesIO(audio_bytes)
        audio_io.name = filename
        lang_code = "de" if lang == "de" else "fr" if lang == "fr" else "en"

        if filename.endswith('.mp4') or filename.endswith('.m4a'): mime = "audio/mp4"
        elif filename.endswith('.ogg') or filename.endswith('.oga'): mime = "audio/ogg"
        elif filename.endswith('.wav'): mime = "audio/wav"
        else: mime = "audio/webm"

        transcript = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes, mime),
            language=lang_code,
            prompt=prompt
        )
        return {"transcript": transcript.text.strip()}

    except Exception as e:
        print(f"Transcribe error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/speak")
async def speak(request: Request):
    try:
        body = await request.json()
        text = body.get("text", "")
        lang = body.get("language", "de")

        if not ELEVENLABS_API_KEY:
            return JSONResponse({"error": "No ElevenLabs key"}, status_code=400)

        voice_id = VOICE_IDS.get(lang, VOICE_IDS["de"])
        clean = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        clean = re.sub(r'[*#<>]', '', clean).strip()
        clean = format_for_speech(clean, lang)[:2000]

        async with httpx.AsyncClient(timeout=30) as client:
            el_response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg"
                },
                json={
                    "text": clean,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
                }
            )

        if el_response.status_code == 200:
            return Response(
                content=el_response.content,
                media_type="audio/mpeg",
                headers={"Access-Control-Allow-Origin": "*"}
            )
        else:
            return JSONResponse({"error": f"ElevenLabs {el_response.status_code}"}, status_code=500)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────────────────
# AKTIVITÄTS-LOG (Logbuch) – Helfer
# ─────────────────────────────────────────

def get_actor(request: Request):
    """Wer führt die Aktion aus? Login-Version: echter Nutzer. Spielwiese (ohne Login): 'Gast'."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = active_sessions.get(token)
    if session and session.get("expires") and session["expires"] >= datetime.now():
        return session.get("user_id"), (session.get("full_name") or session.get("email") or "Nutzer")
    return None, "Gast"

def log_activity(action, contact_name=None, workspace_id=None, contact_id=None,
                 details=None, user_id=None, user_name="Gast"):
    """Schreibt einen Eintrag ins Logbuch. Fehler hier dürfen die eigentliche Aktion NIE blockieren."""
    try:
        supabase_admin.table("activity_log").insert({
            "action": action,
            "contact_name": contact_name,
            "workspace_id": workspace_id,
            "contact_id": contact_id,
            "details": details,
            "user_id": user_id,
            "user_name": user_name,
        }).execute()
    except Exception as e:
        print(f"Activity log error: {e}")

def get_user_role(request: Request) -> str:
    """Rolle des angemeldeten Nutzers, oder 'change' für die Spielwiese (kein Login = kein Rollensystem)."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = active_sessions.get(token)
    if session and session.get("expires") and session["expires"] >= datetime.now():
        return session.get("role", "read")
    return "change"  # Spielwiese ohne Login: voller Zugriff, wie bisher

def generate_contact_no(workspace_id):
    """Erzeugt eine 6-stellige Zufallsnummer, die im jeweiligen Workspace noch nicht vergeben ist."""
    import random
    for _ in range(50):
        candidate = random.randint(100000, 999999)
        query = supabase.table("contacts").select("id").eq("contact_no", candidate)
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        else:
            query = query.is_("workspace_id", "null")
        existing = query.execute()
        if not existing.data:
            return candidate
    # Sehr unwahrscheinlicher Fallback
    return random.randint(100000, 999999)

def normalize_rating(value):
    """Lässt nur A, B, C zu – alles andere wird zu None (keine Klassifizierung)."""
    if value is None:
        return None
    v = str(value).strip().upper()
    return v if v in ("A", "B", "C") else None

# ─────────────────────────────────────────
# WORKSPACES & CONTACTS
# ─────────────────────────────────────────

@app.get("/workspaces")
async def get_workspaces():
    result = supabase.table("workspaces").select("*").order("name").execute()
    return result.data

@app.get("/contacts")
async def get_contacts(workspace_id: str = None):
    query = supabase.table("contacts").select("*").is_("deleted_at", "null").order("company_name")
    if workspace_id:
        query = query.eq("workspace_id", workspace_id)
    result = query.execute()
    return result.data

@app.post("/contacts")
async def create_contact(request: Request):
    try:
        body = await request.json()
        if not body.get("company_name", "").strip():
            return JSONResponse({"error": "company_name required"}, status_code=400)
        # ABC-Klassifizierung absichern
        if "rating" in body:
            body["rating"] = normalize_rating(body.get("rating"))
        # Eindeutige Nummer vergeben, falls keine mitgegeben wurde
        if not body.get("contact_no"):
            body["contact_no"] = generate_contact_no(body.get("workspace_id"))
        body["created_at"] = datetime.utcnow().isoformat()
        body["updated_at"] = datetime.utcnow().isoformat()
        result = supabase.table("contacts").insert(body).execute()
        uid, uname = get_actor(request)
        new_id = result.data[0]["id"] if result.data else None
        log_activity("create", contact_name=body.get("company_name"),
                     workspace_id=body.get("workspace_id"), contact_id=new_id,
                     user_id=uid, user_name=uname)
        return {"success": True, "data": result.data}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/contacts/bulk-import")
async def bulk_import_contact(request: Request):
    try:
        body = await request.json()
        company_name = body.get("company_name", "").strip()
        if not company_name:
            return JSONResponse({"error": "company_name required"}, status_code=400)

        workspace_id = body.get("workspace_id")
        query = supabase.table("contacts").select("*").eq("company_name", company_name).is_("deleted_at", "null")
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        existing = query.execute()

        def clean(val, default=""):
            v = body.get(val, "") or ""
            return v.strip() if v.strip() else default

        payload = {"company_name": company_name, "updated_at": datetime.utcnow().isoformat()}
        if workspace_id: payload["workspace_id"] = workspace_id
        if clean("contact_name"): payload["contact_name"] = clean("contact_name")
        if clean("email"): payload["email"] = clean("email")
        if clean("phone"): payload["phone"] = clean("phone")
        payload["language"] = clean("language", "de")
        if clean("status"): payload["status"] = clean("status")
        if clean("notes"): payload["notes"] = clean("notes")

        # ABC-Klassifizierung aus dem Import übernehmen (falls vorhanden)
        rating_val = normalize_rating(body.get("rating") or body.get("klassifizierung") or body.get("abc"))
        if rating_val:
            payload["rating"] = rating_val

        # Eindeutige Nummer: aus der Datei übernehmen, falls vorhanden
        raw_no = body.get("contact_no") or body.get("nummer") or body.get("nr") or ""
        imported_no = None
        try:
            digits = re.sub(r'[^\d]', '', str(raw_no))
            if digits:
                imported_no = int(digits)
        except (ValueError, TypeError):
            imported_no = None
        if imported_no:
            payload["contact_no"] = imported_no

        last_contact = clean("last_contact")
        if last_contact:
            import re as re2
            dm = re2.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', last_contact)
            if dm:
                payload["last_contact"] = f"{dm.group(3)}-{dm.group(2).zfill(2)}-{dm.group(1).zfill(2)}"
            else:
                payload["last_contact"] = last_contact

        if existing.data:
            # Bestehenden Kontakt aktualisieren – vorhandene Nummer nur überschreiben,
            # wenn die Datei explizit eine mitbringt (sonst unverändert lassen).
            supabase.table("contacts").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            # Neuer Kontakt: keine Nummer aus Datei -> automatisch eine vergeben
            if not payload.get("contact_no"):
                payload["contact_no"] = generate_contact_no(workspace_id)
            supabase.table("contacts").insert(payload).execute()

        uid, uname = get_actor(request)
        log_activity("import", contact_name=company_name, workspace_id=workspace_id,
                     user_id=uid, user_name=uname)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, request: Request):
    """Soft Delete: Kontakt wird nur als gelöscht markiert (deleted_at), nicht wirklich entfernt.
    Landet im Papierkorb und kann von Admin/Change wiederhergestellt werden."""
    try:
        info = supabase.table("contacts").select("company_name, workspace_id").eq("id", contact_id).execute()
        cname = info.data[0]["company_name"] if info.data else None
        wsid = info.data[0]["workspace_id"] if info.data else None
        supabase.table("contacts").update({
            "deleted_at": datetime.utcnow().isoformat()
        }).eq("id", contact_id).execute()
        uid, uname = get_actor(request)
        log_activity("delete", contact_name=cname, workspace_id=wsid, contact_id=contact_id,
                     details="In Papierkorb verschoben", user_id=uid, user_name=uname)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, request: Request):
    try:
        body = await request.json()
        # ABC-Klassifizierung absichern
        if "rating" in body:
            body["rating"] = normalize_rating(body.get("rating"))
        # Die eindeutige Nummer darf nur ein Admin über die Oberfläche ändern.
        if "contact_no" in body:
            role = get_user_role(request)
            if role != "admin":
                body.pop("contact_no", None)
            else:
                # Leere Nummer ignorieren (Nummer soll nie gelöscht werden)
                raw = body.get("contact_no")
                digits = re.sub(r'[^\d]', '', str(raw if raw is not None else ""))
                if digits:
                    body["contact_no"] = int(digits)
                else:
                    body.pop("contact_no", None)
        body["updated_at"] = datetime.utcnow().isoformat()
        supabase.table("contacts").update(body).eq("id", contact_id).execute()
        uid, uname = get_actor(request)
        info = supabase.table("contacts").select("company_name, workspace_id").eq("id", contact_id).execute()
        cname = info.data[0]["company_name"] if info.data else body.get("company_name")
        wsid = info.data[0]["workspace_id"] if info.data else None
        changed = [k for k in body.keys() if k != "updated_at"]
        log_activity("update", contact_name=cname, workspace_id=wsid, contact_id=contact_id,
                     details=("Felder: " + ", ".join(changed)) if changed else None,
                     user_id=uid, user_name=uname)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────────────────
# PAPIERKORB (Soft Delete verwalten)
# ─────────────────────────────────────────
# Nur Admin und Change-Rolle dürfen den Papierkorb sehen/wiederherstellen/endgültig löschen.
# In der Spielwiese (kein Login) ist das automatisch erlaubt, da dort kein Rollensystem existiert.

@app.get("/contacts/trash")
async def get_trash(request: Request, workspace_id: str = None):
    role = get_user_role(request)
    if role not in ("admin", "change"):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf den Papierkorb")
    query = supabase.table("contacts").select("*").not_.is_("deleted_at", "null").order("deleted_at", desc=True)
    if workspace_id:
        query = query.eq("workspace_id", workspace_id)
    result = query.execute()
    return result.data

@app.post("/contacts/{contact_id}/restore")
async def restore_contact(contact_id: str, request: Request):
    role = get_user_role(request)
    if role not in ("admin", "change"):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf den Papierkorb")
    try:
        supabase.table("contacts").update({"deleted_at": None}).eq("id", contact_id).execute()
        info = supabase.table("contacts").select("company_name, workspace_id").eq("id", contact_id).execute()
        cname = info.data[0]["company_name"] if info.data else None
        wsid = info.data[0]["workspace_id"] if info.data else None
        uid, uname = get_actor(request)
        log_activity("restore", contact_name=cname, workspace_id=wsid, contact_id=contact_id,
                     details="Aus Papierkorb wiederhergestellt", user_id=uid, user_name=uname)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/contacts/{contact_id}/permanent")
async def permanently_delete_contact(contact_id: str, request: Request):
    """Endgültiges Löschen – nur aus dem Papierkorb heraus, nicht mehr rückholbar."""
    role = get_user_role(request)
    if role not in ("admin", "change"):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf den Papierkorb")
    try:
        info = supabase.table("contacts").select("company_name, workspace_id").eq("id", contact_id).execute()
        cname = info.data[0]["company_name"] if info.data else None
        wsid = info.data[0]["workspace_id"] if info.data else None
        # Zugehörige Bilder mit aufräumen (DB-Einträge + Dateien im Storage)
        try:
            imgs = supabase_admin.table("contact_images").select("storage_path").eq("contact_id", contact_id).execute()
            paths = [i["storage_path"] for i in (imgs.data or []) if i.get("storage_path")]
            if paths:
                supabase_admin.storage.from_(IMAGE_BUCKET).remove(paths)
            supabase_admin.table("contact_images").delete().eq("contact_id", contact_id).execute()
        except Exception as e:
            print(f"Image cleanup error: {e}")
        # Zugehörige Dateien mit aufräumen (DB-Einträge + Dateien im Storage)
        try:
            fls = supabase_admin.table("contact_files").select("storage_path").eq("contact_id", contact_id).execute()
            fpaths = [i["storage_path"] for i in (fls.data or []) if i.get("storage_path")]
            if fpaths:
                supabase_admin.storage.from_(FILE_BUCKET).remove(fpaths)
            supabase_admin.table("contact_files").delete().eq("contact_id", contact_id).execute()
        except Exception as e:
            print(f"File cleanup error: {e}")
        supabase.table("contacts").delete().eq("id", contact_id).execute()
        uid, uname = get_actor(request)
        log_activity("permanent_delete", contact_name=cname, workspace_id=wsid, contact_id=contact_id,
                     details="Endgültig gelöscht", user_id=uid, user_name=uname)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────────────────
# CONTACT IMAGES (Bilder zu Kontakten)
# ─────────────────────────────────────────
# Dateien liegen im privaten Supabase-Storage-Bucket "contact-images".
# In der DB-Tabelle "contact_images" steht nur der Pfad – kein öffentlicher Link.
# Beim Abrufen erzeugt der Server kurzlebige, signierte Links (1 Stunde gültig).

IMAGE_BUCKET = "contact-images"
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"]
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

# Datei-Anhänge: gleicher Bucket wie Bilder, eigene DB-Tabelle "contact_files".
# Fast alle Dateitypen erlaubt – nur potenziell ausführbare/gefährliche werden blockiert.
FILE_BUCKET = "contact-images"
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
BLOCKED_FILE_EXTENSIONS = [
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif",
    ".sh", ".app", ".jar", ".js", ".vbs", ".ps1", ".dll"
]

def _signed_url(storage_path: str, expires: int = 3600) -> str:
    """Erzeugt einen zeitlich begrenzten Link für eine Datei im privaten Bucket."""
    try:
        res = supabase_admin.storage.from_(IMAGE_BUCKET).create_signed_url(storage_path, expires)
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url") or ""
        return getattr(res, "signedURL", "") or getattr(res, "signed_url", "") or ""
    except Exception as e:
        print(f"Signed URL error: {e}")
        return ""

@app.get("/contacts/{contact_id}/images")
async def list_contact_images(contact_id: str):
    try:
        result = supabase_admin.table("contact_images")\
            .select("*").eq("contact_id", contact_id).order("created_at").execute()
        images = result.data or []
        for img in images:
            img["url"] = _signed_url(img.get("storage_path", ""))
        return images
    except Exception as e:
        print(f"List images error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/contacts/{contact_id}/images")
async def upload_contact_image(contact_id: str, request: Request):
    try:
        form = await request.form()
        upload = form.get("image")
        if upload is None or not hasattr(upload, "read"):
            return JSONResponse({"error": "Kein Bild übermittelt"}, status_code=400)

        file_bytes = await upload.read()
        if not file_bytes:
            return JSONResponse({"error": "Leere Datei"}, status_code=400)
        if len(file_bytes) > MAX_IMAGE_BYTES:
            return JSONResponse({"error": "Datei zu groß (max. 10 MB)"}, status_code=400)

        original_name = (getattr(upload, "filename", None) or "bild").strip()
        content_type = getattr(upload, "content_type", None) or "application/octet-stream"
        if content_type not in ALLOWED_IMAGE_TYPES:
            return JSONResponse({"error": f"Dateityp nicht erlaubt: {content_type}"}, status_code=400)

        ext = os.path.splitext(original_name)[1].lower() or ".jpg"
        storage_path = f"{contact_id}/{secrets.token_hex(8)}{ext}"

        supabase_admin.storage.from_(IMAGE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )

        row = supabase_admin.table("contact_images").insert({
            "contact_id": contact_id,
            "storage_path": storage_path,
            "filename": original_name,
            "content_type": content_type
        }).execute()

        img = row.data[0]
        img["url"] = _signed_url(storage_path)

        uid, uname = get_actor(request)
        cinfo = supabase.table("contacts").select("company_name, workspace_id").eq("id", contact_id).execute()
        cname = cinfo.data[0]["company_name"] if cinfo.data else None
        wsid = cinfo.data[0]["workspace_id"] if cinfo.data else None
        log_activity("image_upload", contact_name=cname, workspace_id=wsid, contact_id=contact_id,
                     details=original_name, user_id=uid, user_name=uname)
        return {"success": True, "image": img}

    except Exception as e:
        print(f"Image upload error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/images/{image_id}")
async def delete_contact_image(image_id: str, request: Request):
    try:
        result = supabase_admin.table("contact_images").select("*").eq("id", image_id).execute()
        cid = None
        fname = None
        if result.data:
            storage_path = result.data[0].get("storage_path")
            cid = result.data[0].get("contact_id")
            fname = result.data[0].get("filename")
            if storage_path:
                try:
                    supabase_admin.storage.from_(IMAGE_BUCKET).remove([storage_path])
                except Exception as e:
                    print(f"Storage remove error: {e}")
        supabase_admin.table("contact_images").delete().eq("id", image_id).execute()
        uid, uname = get_actor(request)
        cname = None
        wsid = None
        if cid:
            cinfo = supabase.table("contacts").select("company_name, workspace_id").eq("id", cid).execute()
            if cinfo.data:
                cname = cinfo.data[0]["company_name"]
                wsid = cinfo.data[0]["workspace_id"]
        log_activity("image_delete", contact_name=cname, workspace_id=wsid, contact_id=cid,
                     details=fname, user_id=uid, user_name=uname)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────────────────
# AKTIVITÄTS-LOG abrufen (Logbuch)
# ─────────────────────────────────────────

@app.get("/activity-log")
async def get_activity_log(workspace_id: str = None, limit: int = 200):
    """Gibt die neuesten Logbuch-Einträge zurück (optional nach Workspace gefiltert).
    Die Filterung nach Heute/Woche/Monat passiert im Frontend."""
    try:
        query = supabase_admin.table("activity_log").select("*").order("created_at", desc=True).limit(limit)
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        result = query.execute()
        return result.data
    except Exception as e:
        print(f"Activity log read error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────────────────
# E-MAIL-REPORT (Activity-Log per Resend)
# ─────────────────────────────────────────

# Aktionen in lesbares Deutsch übersetzen (für Anzeige und Mail)
ACTION_LABELS = {
    "create": "Angelegt",
    "update": "Geändert",
    "delete": "In Papierkorb",
    "restore": "Wiederhergestellt",
    "permanent_delete": "Endgültig gelöscht",
    "import": "Importiert",
    "image_upload": "Bild hochgeladen",
    "image_delete": "Bild gelöscht",
    "file_upload": "Datei hochgeladen",
    "file_delete": "Datei gelöscht",
}

def _period_start(period: str):
    """Liefert den Startzeitpunkt (UTC) für 'day' (heute), 'week' (7 Tage), 'month' (30 Tage)."""
    now = datetime.utcnow()
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    return now - timedelta(days=7)

@app.put("/workspaces/{workspace_id}/report-email")
async def set_report_email(workspace_id: str, request: Request):
    """Setzt die Report-Empfänger-Adresse eines Workspace.
    Login-Version: nur Admin. Spielwiese (kein Login): erlaubt."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = active_sessions.get(token)
    if session and session.get("expires") and session["expires"] >= datetime.now():
        # eingeloggt -> muss Admin sein
        if session.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Nur Admin darf die Report-Adresse ändern")
    # nicht eingeloggt = Spielwiese -> erlaubt
    try:
        body = await request.json()
        email = (body.get("report_email") or "").strip()
        supabase.table("workspaces").update({"report_email": email or None}).eq("id", workspace_id).execute()
        return {"success": True, "report_email": email or None}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/send-report")
async def send_report(request: Request):
    """Sendet einen Activity-Report für den gewählten Zeitraum per E-Mail (Resend).
    Empfänger ist die im Workspace hinterlegte report_email. Nur Admin/Spielwiese."""
    role = get_user_role(request)
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = active_sessions.get(token)
    if session and session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Nur Admin darf Reports senden")

    try:
        body = await request.json()
        workspace_id = body.get("workspace_id")
        period = body.get("period", "week")  # day / week / month

        if not workspace_id:
            return JSONResponse({"error": "workspace_id erforderlich"}, status_code=400)

        # Workspace + Empfänger holen
        ws_res = supabase.table("workspaces").select("*").eq("id", workspace_id).execute()
        if not ws_res.data:
            return JSONResponse({"error": "Workspace nicht gefunden"}, status_code=404)
        workspace = ws_res.data[0]
        recipient = (workspace.get("report_email") or "").strip()
        if not recipient:
            return JSONResponse({"error": "Keine Report-Adresse für diesen Bereich hinterlegt"}, status_code=400)

        # Konfiguration prüfen
        if not RESEND_API_KEY or not REPORT_FROM_EMAIL:
            return JSONResponse({"error": "E-Mail-Versand ist serverseitig noch nicht konfiguriert (RESEND_API_KEY / REPORT_FROM_EMAIL fehlen)."}, status_code=400)

        # Aktivitäten im Zeitraum holen
        start = _period_start(period).isoformat()
        query = supabase_admin.table("activity_log").select("*")\
            .eq("workspace_id", workspace_id)\
            .gte("created_at", start)\
            .order("created_at", desc=True).limit(500)
        result = query.execute()
        entries = result.data or []

        period_label = {"day": "Heute", "week": "Diese Woche", "month": "Dieser Monat"}.get(period, "Zeitraum")
        ws_name = workspace.get("name", "")

        # HTML bauen
        rows = ""
        for e in entries:
            when = ""
            try:
                when = datetime.fromisoformat(e["created_at"].replace("Z", "")).strftime("%d.%m.%Y %H:%M")
            except Exception:
                when = e.get("created_at", "")
            action = ACTION_LABELS.get(e.get("action", ""), e.get("action", ""))
            who = e.get("user_name") or "—"
            what = e.get("contact_name") or "—"
            details = e.get("details") or ""
            rows += f"""<tr>
                <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:13px;color:#555">{when}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:13px"><strong>{action}</strong></td>
                <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:13px">{what}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:13px;color:#555">{who}</td>
                <td style="padding:8px 10px;border-bottom:1px solid #eee;font-size:12px;color:#888">{details}</td>
            </tr>"""

        if not rows:
            rows = '<tr><td colspan="5" style="padding:16px;text-align:center;color:#999;font-size:13px">Keine Aktivitäten in diesem Zeitraum.</td></tr>'

        html = f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:0 auto">
            <h2 style="font-size:18px;color:#1a1a1a;margin-bottom:4px">velojo.ai – Aktivitäts-Report</h2>
            <p style="font-size:13px;color:#777;margin-top:0">Bereich: <strong>{ws_name}</strong> &middot; Zeitraum: <strong>{period_label}</strong> &middot; {len(entries)} Einträge</p>
            <table style="width:100%;border-collapse:collapse;margin-top:12px">
                <thead><tr>
                    <th style="text-align:left;padding:8px 10px;border-bottom:2px solid #ddd;font-size:11px;color:#999;text-transform:uppercase">Zeit</th>
                    <th style="text-align:left;padding:8px 10px;border-bottom:2px solid #ddd;font-size:11px;color:#999;text-transform:uppercase">Aktion</th>
                    <th style="text-align:left;padding:8px 10px;border-bottom:2px solid #ddd;font-size:11px;color:#999;text-transform:uppercase">Kontakt</th>
                    <th style="text-align:left;padding:8px 10px;border-bottom:2px solid #ddd;font-size:11px;color:#999;text-transform:uppercase">Wer</th>
                    <th style="text-align:left;padding:8px 10px;border-bottom:2px solid #ddd;font-size:11px;color:#999;text-transform:uppercase">Details</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
            <p style="font-size:11px;color:#aaa;margin-top:20px">Automatisch erstellt von velojo.ai</p>
        </div>"""

        subject = f"velojo.ai Report – {ws_name} – {period_label}"

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": REPORT_FROM_EMAIL,
                    "to": [recipient],
                    "subject": subject,
                    "html": html,
                }
            )

        if r.status_code in (200, 201):
            return {"success": True, "recipient": recipient, "count": len(entries)}
        else:
            return JSONResponse({"error": f"Resend-Fehler {r.status_code}: {r.text}"}, status_code=502)

    except Exception as e:
        print(f"Send report error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ─────────────────────────────────────────
# CONTACT FILES (Dateien zu Kontakten)
# ─────────────────────────────────────────
# Dateien liegen im selben privaten Bucket wie die Bilder ("contact-images"),
# aber unter dem Unterpfad "files/". In der DB-Tabelle "contact_files" steht nur der Pfad.
# Beim Abrufen erzeugt der Server kurzlebige, signierte Links (1 Stunde gültig).

def _file_extension(name: str) -> str:
    return os.path.splitext(name or "")[1].lower()

@app.get("/contacts/{contact_id}/files")
async def list_contact_files(contact_id: str):
    try:
        result = supabase_admin.table("contact_files")\
            .select("*").eq("contact_id", contact_id).order("created_at").execute()
        files = result.data or []
        for f in files:
            f["url"] = _signed_url(f.get("storage_path", ""))
        return files
    except Exception as e:
        print(f"List files error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/contacts/{contact_id}/files")
async def upload_contact_file(contact_id: str, request: Request):
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return JSONResponse({"error": "Keine Datei übermittelt"}, status_code=400)

        file_bytes = await upload.read()
        if not file_bytes:
            return JSONResponse({"error": "Leere Datei"}, status_code=400)
        if len(file_bytes) > MAX_FILE_BYTES:
            return JSONResponse({"error": "Datei zu groß (max. 10 MB)"}, status_code=400)

        original_name = (getattr(upload, "filename", None) or "datei").strip()
        ext = _file_extension(original_name)
        if ext in BLOCKED_FILE_EXTENSIONS:
            return JSONResponse({"error": f"Dateityp nicht erlaubt: {ext}"}, status_code=400)

        content_type = getattr(upload, "content_type", None) or "application/octet-stream"
        storage_path = f"files/{contact_id}/{secrets.token_hex(8)}{ext}"

        supabase_admin.storage.from_(FILE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )

        row = supabase_admin.table("contact_files").insert({
            "contact_id": contact_id,
            "storage_path": storage_path,
            "filename": original_name,
            "content_type": content_type,
            "size_bytes": len(file_bytes)
        }).execute()

        f = row.data[0]
        f["url"] = _signed_url(storage_path)

        uid, uname = get_actor(request)
        cinfo = supabase.table("contacts").select("company_name, workspace_id").eq("id", contact_id).execute()
        cname = cinfo.data[0]["company_name"] if cinfo.data else None
        wsid = cinfo.data[0]["workspace_id"] if cinfo.data else None
        log_activity("file_upload", contact_name=cname, workspace_id=wsid, contact_id=contact_id,
                     details=original_name, user_id=uid, user_name=uname)
        return {"success": True, "file": f}

    except Exception as e:
        print(f"File upload error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/files/{file_id}")
async def delete_contact_file(file_id: str, request: Request):
    try:
        result = supabase_admin.table("contact_files").select("*").eq("id", file_id).execute()
        cid = None
        fname = None
        if result.data:
            storage_path = result.data[0].get("storage_path")
            cid = result.data[0].get("contact_id")
            fname = result.data[0].get("filename")
            if storage_path:
                try:
                    supabase_admin.storage.from_(FILE_BUCKET).remove([storage_path])
                except Exception as e:
                    print(f"Storage remove error: {e}")
        supabase_admin.table("contact_files").delete().eq("id", file_id).execute()
        uid, uname = get_actor(request)
        cname = None
        wsid = None
        if cid:
            cinfo = supabase.table("contacts").select("company_name, workspace_id").eq("id", cid).execute()
            if cinfo.data:
                cname = cinfo.data[0]["company_name"]
                wsid = cinfo.data[0]["workspace_id"]
        log_activity("file_delete", contact_name=cname, workspace_id=wsid, contact_id=cid,
                     details=fname, user_id=uid, user_name=uname)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ─────────────────────────────────────────
# VORLAGEN (Templates) je Workspace
# ─────────────────────────────────────────
# Login-Version: nur Admin darf verwalten. Spielwiese (kein Login): frei.

def _require_template_admin(request: Request):
    """Wirft 403, wenn eingeloggt und NICHT Admin. Spielwiese (keine Session) ist erlaubt."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = active_sessions.get(token)
    if session and session.get("expires") and session["expires"] >= datetime.now():
        if session.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Nur Admin darf Vorlagen verwalten")

@app.get("/templates")
async def get_templates(workspace_id: str = None):
    try:
        query = supabase.table("templates").select("*").order("name")
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        result = query.execute()
        return result.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/templates")
async def create_template(request: Request):
    _require_template_admin(request)
    try:
        body = await request.json()
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse({"error": "Name erforderlich"}, status_code=400)
        payload = {
            "workspace_id": body.get("workspace_id"),
            "name": name,
            "type": (body.get("type") or "sonstiges").strip(),
            "subject": body.get("subject") or "",
            "body": body.get("body") or "",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        result = supabase.table("templates").insert(payload).execute()
        return {"success": True, "template": result.data[0] if result.data else None}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.put("/templates/{template_id}")
async def update_template(template_id: str, request: Request):
    _require_template_admin(request)
    try:
        body = await request.json()
        payload = {"updated_at": datetime.utcnow().isoformat()}
        if "name" in body: payload["name"] = (body.get("name") or "").strip()
        if "type" in body: payload["type"] = (body.get("type") or "sonstiges").strip()
        if "subject" in body: payload["subject"] = body.get("subject") or ""
        if "body" in body: payload["body"] = body.get("body") or ""
        supabase.table("templates").update(payload).eq("id", template_id).execute()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/templates/{template_id}")
async def delete_template(template_id: str, request: Request):
    _require_template_admin(request)
    try:
        supabase.table("templates").delete().eq("id", template_id).execute()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/templates/placeholders")
async def get_placeholders(workspace_id: str = None):
    """Liefert die verfügbaren Platzhalter für einen Workspace:
    Kernfelder + die Custom-Felder des Workspace. Fürs Frontend zum Anzeigen."""
    core = [
        {"key": "firma", "label": "Firma / Name"},
        {"key": "ansprechpartner", "label": "Ansprechpartner"},
        {"key": "email", "label": "E-Mail"},
        {"key": "telefon", "label": "Telefon"},
        {"key": "status", "label": "Status"},
        {"key": "nummer", "label": "Kontaktnummer"},
        {"key": "klassifizierung", "label": "Klassifizierung (ABC)"},
        {"key": "notizen", "label": "Notizen"},
        {"key": "datum", "label": "Heutiges Datum"},
    ]
    custom = []
    if workspace_id:
        try:
            ws = supabase.table("workspaces").select("field_schema").eq("id", workspace_id).execute()
            if ws.data:
                schema = ws.data[0].get("field_schema") or []
                for f in schema:
                    custom.append({"key": f.get("key"), "label": f.get("label")})
        except Exception as e:
            print(f"Placeholder schema error: {e}")
    return {"core": core, "custom": custom}

def _build_placeholder_values(contact: dict) -> dict:
    """Ordnet Platzhalter-Schlüssel den echten Werten eines Kontakts zu.
    Kernfelder + Custom-Felder. Fehlende Werte werden zu leerem String."""
    from datetime import date
    cf = contact.get("custom_fields") or {}
    values = {
        "firma": contact.get("company_name") or "",
        "ansprechpartner": contact.get("contact_name") or "",
        "email": contact.get("email") or "",
        "telefon": contact.get("phone") or "",
        "status": contact.get("status") or "",
        "nummer": str(contact.get("contact_no") or ""),
        "klassifizierung": contact.get("rating") or "",
        "notizen": contact.get("notes") or "",
        "datum": date.today().strftime("%d.%m.%Y"),
    }
    # Custom-Felder ergänzen (Schlüssel wie im field_schema)
    for k, v in cf.items():
        values[k] = "" if v is None else str(v)
    return values

def _fill_placeholders(text: str, values: dict) -> str:
    """Ersetzt {{schluessel}} durch den Wert. Unbekannte Platzhalter werden leer."""
    if not text:
        return ""
    def repl(m):
        key = m.group(1).strip()
        return values.get(key, "")
    return re.sub(r"\{\{\s*([\w]+)\s*\}\}", repl, text)

@app.post("/templates/{template_id}/render")
async def render_template(template_id: str, request: Request):
    """Füllt eine Vorlage mit den Daten eines Kontakts. Gibt Betreff + Text gefüllt zurück."""
    try:
        body = await request.json()
        contact_id = body.get("contact_id")
        if not contact_id:
            return JSONResponse({"error": "contact_id erforderlich"}, status_code=400)

        tpl_res = supabase.table("templates").select("*").eq("id", template_id).execute()
        if not tpl_res.data:
            return JSONResponse({"error": "Vorlage nicht gefunden"}, status_code=404)
        template = tpl_res.data[0]

        c_res = supabase.table("contacts").select("*").eq("id", contact_id).execute()
        if not c_res.data:
            return JSONResponse({"error": "Kontakt nicht gefunden"}, status_code=404)
        contact = c_res.data[0]

        values = _build_placeholder_values(contact)
        subject = _fill_placeholders(template.get("subject") or "", values)
        filled_body = _fill_placeholders(template.get("body") or "", values)

        return {
            "subject": subject,
            "body": filled_body,
            "template_name": template.get("name") or "",
            "contact_email": contact.get("email") or "",
        }
    except Exception as e:
        print(f"Render template error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/ai/polish")
async def ai_polish(request: Request):
    """Glättet einen Text sprachlich: Formulierung, Rechtschreibung, Grammatik.
    Bedeutung, Sprache und Platzhalter ({{...}}) bleiben unverändert.
    Gibt NUR den verbesserten Text zurück."""
    try:
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "Kein Text übergeben"}, status_code=400)

        system_prompt = (
            "Du bist ein professioneller Lektor. Verbessere den folgenden Text: "
            "Formulierung, Rechtschreibung, Grammatik und Lesbarkeit. "
            "WICHTIGE REGELN: "
            "1) Behalte die Sprache des Originals exakt bei (Deutsch bleibt Deutsch usw.). "
            "2) Ändere die Bedeutung und den Inhalt NICHT. "
            "3) Lasse alle Platzhalter der Form {{...}} unverändert und an sinnvoller Stelle stehen. "
            "4) Behalte den Charakter eines geschäftlichen Schreibens (Anrede, Grußformel) bei. "
            "5) Gib AUSSCHLIESSLICH den verbesserten Text zurück – ohne Einleitung, ohne Kommentar, ohne Anführungszeichen."
        )

        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )

        improved = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                improved += block.text
        improved = improved.strip()
        if not improved:
            improved = text  # Fallback: Original zurückgeben

        return {"text": improved}
    except Exception as e:
        print(f"AI polish error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/health")
async def health():
    return {"status": "ok", "elevenlabs": bool(ELEVENLABS_API_KEY), "storage": bool(SUPABASE_SERVICE_KEY)}
