from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel
from supabase import create_client
import anthropic
import os
import re
import json
import httpx
from datetime import datetime
from typing import List

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

VOICE_IDS = {
    "de": "1J0wWp4zPQIvsK7Xwh34",
    "fr": "E4GQ42zEV1kwul03Bl16",
    "en": "Gfpl8Yo74Is0W6cPUWWT",
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
- Proaktiv Vorschläge machen
- In der Sprache des Nutzers antworten (Deutsch, Französisch, Englisch)

Felder: company_name, contact_name, email, phone, language, notes, last_contact, status (aktiv/interessiert/inaktiv)

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

Antworte dann normal in der Sprache des Nutzers. Sei wie ein erfahrener Kollege – kurz, präzise, proaktiv."""

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
    ]) if contacts else "Noch keine Kontakte."

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
        system=SYSTEM_PROMPT,
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
                    existing = supabase.table("contacts").select("*").eq("company_name", action_data["company_name"]).execute()
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
                        supabase.table("contacts").update(update_payload).eq("company_name", action_data["company_name"]).execute()
                    else:
                        update_payload["notes"] = action_data.get("notes_append", "")
                        supabase.table("contacts").insert(update_payload).execute()
            except Exception as e:
                print(f"DB error: {e}")

    clean_response = re.sub(r'<db_action>.*?</db_action>', '', response_text, flags=re.DOTALL).strip()
    return {"reply": clean_response}


@app.post("/speak")
async def speak(request: Request):
    try:
        body = await request.json()
        text = body.get("text", "")
        lang = body.get("language", "de")

        print(f"SPEAK: lang={lang}, key={bool(ELEVENLABS_API_KEY)}, chars={len(text)}")

        if not ELEVENLABS_API_KEY:
            return JSONResponse({"error": "No ElevenLabs key"}, status_code=400)

        voice_id = VOICE_IDS.get(lang, VOICE_IDS["de"])
        clean = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        clean = re.sub(r'[*#<>]', '', clean).strip()[:2000]

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

        print(f"ElevenLabs status: {el_response.status_code}")

        if el_response.status_code == 200:
            return Response(
                content=el_response.content,
                media_type="audio/mpeg",
                headers={"Access-Control-Allow-Origin": "*"}
            )
        else:
            print(f"ElevenLabs error: {el_response.text}")
            return JSONResponse({"error": f"ElevenLabs {el_response.status_code}"}, status_code=500)

    except Exception as e:
        print(f"SPEAK exception: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/contacts")
async def get_contacts():
    result = supabase.table("contacts").select("*").order("company_name").execute()
    return result.data

@app.get("/health")
async def health():
    return {"status": "ok", "elevenlabs": bool(ELEVENLABS_API_KEY)}
