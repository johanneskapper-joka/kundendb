from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import anthropic
import os
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase & Anthropic clients
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

class ChatRequest(BaseModel):
    message: str
    language: str = "de"

SYSTEM_PROMPT = """Du bist ein intelligenter CRM-Assistent für ein kleines Team.
Du hast Zugriff auf eine Kundendatenbank und kannst:
- Neue Informationen zu Kunden erfassen und speichern
- Bestehende Kundeninformationen abrufen und zusammenfassen
- In der Sprache des Nutzers antworten (Deutsch, Französisch, Englisch, etc.)

Die Datenbank enthält folgende Felder pro Kontakt:
- company_name: Firmenname
- contact_name: Ansprechpartner
- email: E-Mail
- phone: Telefon
- language: bevorzugte Sprache des Kunden
- notes: Freitext-Notizen (alle Infos, Gesprächsnotizen, etc.)
- last_contact: Datum des letzten Kontakts
- status: Status (aktiv, interessiert, inaktiv, etc.)

Wenn der Nutzer neue Infos nennt, antworte IMMER mit einem JSON-Block in diesem Format:
<db_action>
{
  "action": "update" oder "create" oder "none",
  "company_name": "...",
  "contact_name": "...",
  "notes_append": "Neue Info die angehängt wird",
  "status": "...",
  "last_contact": "YYYY-MM-DD"
}
</db_action>

Dann antworte dem Nutzer normal in seiner Sprache.
Wenn du nur Infos abrufst, verwende action: "none".
Sei freundlich, präzise und professionell."""

@app.post("/chat")
async def chat(req: ChatRequest):
    # Alle Kontakte aus DB laden
    result = supabase.table("contacts").select("*").execute()
    contacts = result.data

    contacts_text = "\n\n".join([
        f"Firma: {c.get('company_name','')}\n"
        f"Kontakt: {c.get('contact_name','')}\n"
        f"Email: {c.get('email','')}\n"
        f"Tel: {c.get('phone','')}\n"
        f"Status: {c.get('status','')}\n"
        f"Letzter Kontakt: {c.get('last_contact','')}\n"
        f"Notizen: {c.get('notes','')}"
        for c in contacts
    ]) if contacts else "Noch keine Kontakte vorhanden."

    user_message = f"""Aktuelle Kundendatenbank:
{contacts_text}

---
Nutzer-Nachricht ({req.language}): {req.message}"""

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    response_text = response.content[0].text

    # DB-Aktion verarbeiten
    if "<db_action>" in response_text:
        import json, re
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
                        "contact_name": action_data.get("contact_name"),
                        "status": action_data.get("status"),
                        "last_contact": action_data.get("last_contact", datetime.today().strftime('%Y-%m-%d')),
                        "updated_at": datetime.utcnow().isoformat()
                    }

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

    # <db_action> Block aus Antwort entfernen
    clean_response = re.sub(r'<db_action>.*?</db_action>', '', response_text, flags=re.DOTALL).strip()

    return {"reply": clean_response}

@app.get("/contacts")
async def get_contacts():
    result = supabase.table("contacts").select("*").order("company_name").execute()
    return result.data

@app.get("/health")
async def health():
    return {"status": "ok"}
