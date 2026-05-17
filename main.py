from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from supabase import create_client
import anthropic
import os
import re
import json
import httpx
from datetime import datetime
from typing import List, Optional

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
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# Stimmen pro Sprache
VOICE_IDS = {
    "de": "pNInz6obpgDQGcFmaJgB",  # Adam – klar und natürlich
    "fr": "VR6AewLTigWG4xSOukaG",  # Arnold – französisch
    "en": "21m00Tcm4TlvDq8ikWAM",  # Rachel – englisch
}

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    language: str = "de"
    history: List[Message] = []

SYSTEM_PROMPT = """Du bist ein intelligenter CRM-Assistent für ein kleines Team.
Du führst echte Gespräche – du erinnerst dich an alles was in dieser Unterhaltung gesagt wurde, hakst nach, machst Vorschläge und denkst mit.

Du hast Zugriff auf eine Kundendatenbank und kannst:
- Neue Informationen zu Kunden erfassen und speichern
- Bestehende Kundeninformationen abrufen und zusammenfassen
- Zusammenhänge zwischen Kunden erkennen
- Proaktiv Vorschläge machen (z.B. Folgetermine, offene Punkte)
- In der Sprache des Nutzers antworten (Deutsch, Französisch, Englisch)

Die Datenbank enthält folgende Felder pro Kontakt:
- company_name: Firmenname
- contact_name: Ansprechpartner
- email: E-Mail
- phone: Telefon
- language: bevorzugte Sprache des Kunden
- notes: Freitext-Notizen
- last_contact: Datum des letzten Kontakts
- status: aktiv, interessiert, inaktiv

Wenn der Nutzer neue Infos nennt, antworte IMMER mit einem JSON-Block:
<db_action>
{
  "action": "update" oder "create" oder "none",
  "company_name": "...",
  "contact_name": "...",
  "notes_append": "Neue Info",
  "status": "...",
  "last_contact": "YYYY-MM-DD"
}
</db_action>

Dann antworte dem Nutzer normal in seiner Sprache.
Sei wie ein erfahrener Kollege – kurz, präzise, proaktiv."""

@app.post("/chat")
async def chat(req: ChatRequest):
    result = supabase.table("contacts").select("*").execute()
    contacts = result.data

    contacts_text = "\n\n".join([
        f"Firma: {c.get('company_name','')}\n"
        f"Kontakt: {c.get('contact_name','')}\n"
        f"Status: {c.get('status','')}\n"
        f"Letzter Kontakt: {c.get('last_contact','')}\n"
        f"Notizen: {c.get('notes','')}"
        for c in contacts
    ]) if contacts else "Noch keine Kontakte vorhanden."

    # Gesprächshistorie aufbauen
    messages = []
    
    # Erste Nachricht enthält immer die DB
    first_content = f"Aktuelle Kundendatenbank:\n{contacts_text}\n\n---\nNutzer-Nachricht ({req.language}): "
    
    if req.history:
        # Erster Eintrag mit DB-Kontext
        first_msg = req.history[0]
        messages.append({
            "role": first_msg.role,
            "content": first_content + first_msg.content
        })
        # Rest der Historie normal
        for msg in req.history[1:]:
            messages.append({"role": msg.role, "content": msg.content})
        # Aktuelle Nachricht
        messages.append({"role": "user", "content": req.message})
    else:
        messages.append({"role": "user", "content": first_content + req.message})

    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=messages
    )

    response_text = response.content[0].text

    # DB-Aktion verarbeiten
    if "<db_action>" in response_text:
        match = re.search(r'<db_action>(.*?)</db_action>', response_text, re.DOTALL)
        if match:
            try:
                action_data = json.loads(match.group(1).strip())
                action = action_data.get("action")
                if action in ["create", "update"] and action_data.get("company_name"):
                    existing = supabase.table("contacts").select("*").eq(
                        "company_name", action_data["company_name"]
                    ).execute()
                    update_payload = {
                        "company_name": action_data.get("company_name"),
                        "status": action_data.get("status"),
                        "last_contact": action_data.get("last_contact", datetime.today().strftime('%Y-%m-%d')),
                        "updated_at": datetime.utcnow().isoformat()
                    }
                    if action_data.get("contact_name"):
                        update_payload["contact_name"] = action_data.get("contact_name")
                    if existing.data:
                        old_notes = existing.data[0].get("notes", "") or ""
                        new_note = action_data.get("notes_append", "")
                        if new_note:
                            update_payload["notes"] = f"{old_notes}\n[{datetime.today().strftime('%d.%m.%Y')}] {new_note}".strip()
                        supabase.table("contacts").update(update_payload).eq(
                            "company_name", action_data["company_name"]
                        ).execute()
                    else:
                        update_payload["notes"] = action_data.get("notes_append", "")
                        supabase.table("contacts").insert(update_payload).execute()
            except Exception as e:
                print(f"DB action error: {e}")

    clean_response = re.sub(r'<db_action>.*?</db_action>', '', response_text, flags=re.DOTALL).strip()
    return {"reply": clean_response}


@app.post("/speak")
async def speak(request: Request):
    body = await request.json()
    text = body.get("text", "")
    lang = body.get("language", "de")
    
    if not ELEVENLABS_API_KEY:
        return JSONResponse({"error": "No ElevenLabs key"}, status_code=400)

    voice_id = VOICE_IDS.get(lang, VOICE_IDS["de"])
    
    # Text bereinigen
    clean = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    clean = re.sub(r'[*#]', '', clean).strip()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "text": clean,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return StreamingResponse(
                iter([response.content]),
                media_type="audio/mpeg",
                headers={"Access-Control-Allow-Origin": "*"}
            )
        else:
            return JSONResponse({"error": "ElevenLabs error"}, status_code=500)


@app.get("/contacts")
async def get_contacts():
    result = supabase.table("contacts").select("*").order("company_name").execute()
    return result.data

@app.get("/health")
async def health():
    return {"status": "ok"}
