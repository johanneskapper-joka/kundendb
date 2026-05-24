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
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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

def fuzzy_match_companies(text: str, contacts: list) -> str:
    """Ersetzt ähnlich klingende Firmennamen im Text durch die korrekten DB-Einträge."""
    if not contacts or not text:
        return text

    company_names = [c.get('company_name', '') for c in contacts if c.get('company_name')]
    if not company_names:
        return text

    words = text.split()
    result_words = []
    i = 0

    while i < len(words):
        # Versuche 1-4 Wörter als Firmenname zu matchen
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

            # Nur ersetzen wenn sehr ähnlich (>75%)
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
    """Berechnet Ähnlichkeit zwischen zwei Strings (0-1)."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    # Enthält-Check
    if a in b or b in a:
        return 0.85

    # Gemeinsame Zeichen
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

    if matches == 0:
        return 0.0

    score = (matches / len(shorter) + matches / len(longer)) / 2

    # Bonus für gleichen Anfangsbuchstaben
    if a[0] == b[0]:
        score = min(1.0, score + 0.1)

    return score


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

Antworte dann normal in der Sprache des Nutzers.

WICHTIG für Antworten:
- Maximal 2-3 Sätze – nie länger
- Direkt zum Punkt, kein Vorgeplänkel
- Beantworte NUR was gefragt wurde – niemals andere Firmen oder Themen einbringen
- Nur was WIRKLICH in den Daten steht – niemals spekulieren oder Verbindungen erfinden
- Wenn etwas nicht in den Daten steht: "Dazu habe ich keine Information"
- Niemals Aktionen vorschlagen die nicht explizit angefragt wurden (kein Löschen, kein Statuswechsel)
- Bei Datenabruf: Status + letzter Kontakt + 1 wichtige Notiz – fertig"""

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


MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"]
MONTHS_FR = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
MONTHS_EN = ["January","February","March","April","May","June","July","August","September","October","November","December"]

def format_for_speech(text: str, lang: str) -> str:
    months = MONTHS_DE if lang == "de" else MONTHS_FR if lang == "fr" else MONTHS_EN

    # Datum DD.MM.YYYY → z.B. "10. Mai 2026"
    def replace_date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        month = months[mo-1] if 1 <= mo <= 12 else m.group(2)
        return f"{d}. {month} {y}"
    text = re.sub(r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b', replace_date, text)

    # Datum YYYY-MM-DD → z.B. "10. Mai 2026"
    def replace_iso(m):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        month = months[mo-1] if 1 <= mo <= 12 else m.group(2)
        return f"{d}. {month} {y}"
    text = re.sub(r'\b(\d{4})-(\d{2})-(\d{2})\b', replace_iso, text)

    # Telefonnummern: +49 621 123456 → Ziffern mit Leerzeichen
    def replace_phone(m):
        digits = m.group(0).replace('+', '00').replace(' ', '').replace('-', '')
        return ' '.join(digits)
    text = re.sub(r'[+]?[\d][\d\s\-]{6,}', replace_phone, text)

    # Währung: 8.000€ oder 8000€ → "achttausend Euro"
    text = re.sub(r'(\d+\.\d{3})€', lambda m: m.group(0).replace('.', '') + ' Euro', text)
    text = re.sub(r'(\d+)€', r'\1 Euro', text)
    text = re.sub(r'(\d+)\$', r'\1 Dollar', text)

    # Jahreszahlen ausschreiben (2020-2029)
    def year_to_words_de(m):
        y = int(m.group(0))
        if 2000 <= y <= 2099:
            rest = y - 2000
            if rest == 0:
                return "zweitausend"
            elif rest < 10:
                return f"zweitausendund{['null','ein','zwei','drei','vier','fünf','sechs','sieben','acht','neun'][rest]}"
            elif rest < 20:
                teens = ['zehn','elf','zwölf','dreizehn','vierzehn','fünfzehn','sechzehn','siebzehn','achtzehn','neunzehn']
                return f"zweitausendund{teens[rest-10]}"
            else:
                tens = ['','','zwanzig','dreißig','vierzig','fünfzig','sechzig','siebzig','achtzig','neunzig']
                ones = ['','ein','zwei','drei','vier','fünf','sechs','sieben','acht','neun']
                t, o = rest // 10, rest % 10
                if o == 0:
                    return f"zweitausendund{tens[t]}"
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
            else:
                return f"deux mille {rest}"
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

        # Firmenname-Hints für bessere Erkennung
        prompt = ""
        if companies:
            prompt = f"Firmen und Namen: {companies}. "
        prompt += "Dies ist eine Geschäftsnachricht über Kundenkontakte."

        import io
        audio_io = io.BytesIO(audio_bytes)
        audio_io.name = filename

        lang_code = "de" if lang == "de" else "fr" if lang == "fr" else "en"

        # MIME-Typ korrekt setzen basierend auf Dateiendung
        if filename.endswith('.mp4') or filename.endswith('.m4a'):
            mime = "audio/mp4"
        elif filename.endswith('.ogg') or filename.endswith('.oga'):
            mime = "audio/ogg"
        elif filename.endswith('.wav'):
            mime = "audio/wav"
        else:
            mime = "audio/webm"

        transcript = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes, mime),
            language=lang_code,
            prompt=prompt
        )

        text = transcript.text.strip()
        return {"transcript": text}

    except Exception as e:
        print(f"Transcribe error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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

@app.post("/contacts/bulk-import")
async def bulk_import_contact(request: Request):
    try:
        body = await request.json()
        company_name = body.get("company_name", "").strip()
        if not company_name:
            return JSONResponse({"error": "company_name required"}, status_code=400)

        existing = supabase.table("contacts").select("*").eq("company_name", company_name).execute()

        def clean(val, default=""):
            v = body.get(val, "") or ""
            return v.strip() if v.strip() else default

        payload = {
            "company_name": company_name,
            "updated_at": datetime.utcnow().isoformat()
        }

        # Nur nicht-leere Felder setzen
        if clean("contact_name"): payload["contact_name"] = clean("contact_name")
        if clean("email"): payload["email"] = clean("email")
        if clean("phone"): payload["phone"] = clean("phone")
        payload["language"] = clean("language", "de")
        if clean("status"): payload["status"] = clean("status")
        if clean("notes"): payload["notes"] = clean("notes")

        last_contact = clean("last_contact")
        if last_contact:
            # Datum konvertieren DD.MM.YYYY -> YYYY-MM-DD
            import re as re2
            dm = re2.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', last_contact)
            if dm:
                payload["last_contact"] = f"{dm.group(3)}-{dm.group(2).zfill(2)}-{dm.group(1).zfill(2)}"
            else:
                payload["last_contact"] = last_contact

        if existing.data:
            supabase.table("contacts").update(payload).eq("company_name", company_name).execute()
        else:
            supabase.table("contacts").insert(payload).execute()

        return {"success": True}
    except Exception as e:
        print(f"Import error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str):
    try:
        supabase.table("contacts").delete().eq("id", contact_id).execute()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, request: Request):
    try:
        body = await request.json()
        body["updated_at"] = datetime.utcnow().isoformat()
        supabase.table("contacts").update(body).eq("id", contact_id).execute()
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



@app.get("/health")
async def health():
    return {"status": "ok", "elevenlabs": bool(ELEVENLABS_API_KEY)}
