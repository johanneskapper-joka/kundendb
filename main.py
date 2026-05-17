<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KundenDB – CRM Assistant</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0f0f0f;
    --surface: #1a1a1a;
    --surface2: #222222;
    --border: #2e2e2e;
    --accent: #c8a96e;
    --accent2: #e8c98e;
    --text: #f0ece4;
    --text-muted: #888;
    --user-bubble: #1e2a1e;
    --ai-bubble: #1a1a2e;
    --success: #4caf82;
    --radius: 16px;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'DM Sans', sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
    gap: 10px;
    flex-wrap: wrap;
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .logo-icon {
    width: 34px;
    height: 34px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    border-radius: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
  }

  .logo-text {
    font-family: 'DM Serif Display', serif;
    font-size: 20px;
    letter-spacing: -0.5px;
  }

  .logo-text span { color: var(--accent); }

  .header-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .lang-selector {
    display: flex;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }

  .lang-btn {
    padding: 6px 12px;
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    font-size: 12px;
    font-weight: 500;
    transition: all 0.2s;
  }

  .lang-btn.active { background: var(--accent); color: #0f0f0f; }
  .lang-btn:hover:not(.active) { color: var(--text); }

  .icon-btn {
    padding: 7px 14px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-muted);
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    font-weight: 500;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
  }

  .icon-btn:hover { color: var(--text); border-color: var(--accent); }
  .icon-btn.active { border-color: var(--accent); color: var(--accent); }

  .main {
    display: flex;
    flex: 1;
    overflow: hidden;
    position: relative;
  }

  /* Sidebar */
  .sidebar {
    width: 280px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    transition: width 0.3s ease, opacity 0.3s ease;
    overflow: hidden;
  }

  .sidebar.hidden {
    width: 0;
    opacity: 0;
    pointer-events: none;
  }

  .sidebar-header {
    padding: 16px 18px 12px;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text-muted);
    white-space: nowrap;
  }

  .sidebar-search {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
  }

  .sidebar-search input {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 11px;
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    outline: none;
    transition: border-color 0.2s;
    white-space: nowrap;
  }

  .sidebar-search input:focus { border-color: var(--accent); }
  .sidebar-search input::placeholder { color: var(--text-muted); }

  .contacts-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }

  .contact-card {
    padding: 11px 13px;
    border-radius: 10px;
    cursor: pointer;
    transition: background 0.2s;
    border: 1px solid transparent;
    margin-bottom: 3px;
    white-space: nowrap;
  }

  .contact-card:hover { background: var(--surface2); border-color: var(--border); }

  .contact-company { font-weight: 600; font-size: 13px; margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; }
  .contact-name { font-size: 12px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; }

  .contact-status {
    display: inline-block;
    margin-top: 5px;
    padding: 2px 7px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 500;
    background: var(--surface2);
    color: var(--text-muted);
  }

  .contact-status.aktiv { background: #1a2e1a; color: var(--success); }
  .contact-status.interessiert { background: #1a1a2e; color: #7eb8e8; }

  /* Chat */
  .chat-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 24px 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .messages::-webkit-scrollbar { width: 4px; }
  .messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  .welcome {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 40px 20px;
    gap: 14px;
  }

  .welcome-icon {
    width: 60px;
    height: 60px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    border-radius: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    margin-bottom: 6px;
  }

  .welcome h2 { font-family: 'DM Serif Display', serif; font-size: 24px; }
  .welcome p { font-size: 14px; color: var(--text-muted); max-width: 340px; line-height: 1.7; }

  .suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    justify-content: center;
    margin-top: 6px;
  }

  .suggestion {
    padding: 7px 14px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    font-size: 12px;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.2s;
  }

  .suggestion:hover { border-color: var(--accent); color: var(--accent); }

  .message {
    display: flex;
    gap: 10px;
    opacity: 0;
    animation: slideIn 0.3s ease forwards;
  }

  .message.user { flex-direction: row-reverse; align-self: flex-end; max-width: 85%; }
  .message.assistant { align-self: flex-start; max-width: 85%; }

  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 15px;
    flex-shrink: 0;
    margin-top: 2px;
  }

  .message.user .avatar { background: linear-gradient(135deg, #2a3a2a, #3a5a3a); }
  .message.assistant .avatar { background: linear-gradient(135deg, var(--accent), var(--accent2)); }

  .bubble {
    padding: 12px 16px;
    border-radius: var(--radius);
    font-size: 14px;
    line-height: 1.7;
  }

  .message.user .bubble {
    background: var(--user-bubble);
    border: 1px solid #2a3a2a;
    border-top-right-radius: 4px;
  }

  .message.assistant .bubble {
    background: var(--ai-bubble);
    border: 1px solid #1e1e3a;
    border-top-left-radius: 4px;
  }

  .bubble-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
  }

  .bubble-time { font-size: 11px; color: var(--text-muted); }

  /* Vorlesen Button – groß und sichtbar */
  .speak-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    color: var(--text-muted);
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    font-size: 12px;
    font-weight: 500;
    transition: all 0.2s;
  }

  .speak-btn:hover { border-color: var(--accent); color: var(--accent); }
  .speak-btn.speaking {
    background: #1a1a2e;
    border-color: var(--accent);
    color: var(--accent);
    animation: speakPulse 1.5s infinite;
  }

  @keyframes speakPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(200,169,110,0.3); }
    50% { box-shadow: 0 0 0 5px rgba(200,169,110,0); }
  }

  .typing {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 12px 16px;
    background: var(--ai-bubble);
    border: 1px solid #1e1e3a;
    border-radius: var(--radius);
    border-top-left-radius: 4px;
    width: fit-content;
  }

  .typing span {
    width: 6px;
    height: 6px;
    background: var(--accent);
    border-radius: 50%;
    animation: bounce 1.2s infinite;
    opacity: 0.5;
  }

  .typing span:nth-child(2) { animation-delay: 0.2s; }
  .typing span:nth-child(3) { animation-delay: 0.4s; }

  /* Input */
  .input-area {
    padding: 16px 20px 20px;
    border-top: 1px solid var(--border);
    background: var(--surface);
    flex-shrink: 0;
  }

  .input-wrapper {
    display: flex;
    gap: 8px;
    align-items: flex-end;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 10px 12px;
    transition: border-color 0.2s;
  }

  .input-wrapper:focus-within { border-color: var(--accent); }

  textarea {
    flex: 1;
    background: none;
    border: none;
    outline: none;
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    resize: none;
    max-height: 120px;
    line-height: 1.6;
  }

  textarea::placeholder { color: var(--text-muted); }

  .action-btn {
    width: 38px;
    height: 38px;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: all 0.2s;
    font-size: 18px;
  }

  .mic-btn {
    background: var(--surface);
    border: 1px solid var(--border) !important;
    border: none;
  }

  .mic-btn:hover { border-color: var(--accent) !important; }

  .mic-btn.recording {
    background: #2e1a1a;
    border-color: #e05555 !important;
    animation: recPulse 1s infinite;
  }

  @keyframes recPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(224,85,85,0.4); }
    50% { box-shadow: 0 0 0 6px rgba(224,85,85,0); }
  }

  .send-btn {
    background: linear-gradient(135deg, var(--accent), var(--accent2));
  }

  .send-btn:hover { opacity: 0.9; transform: scale(1.05); }
  .send-btn:active { transform: scale(0.95); }
  .send-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

  .send-btn svg { width: 17px; height: 17px; fill: #0f0f0f; }

  .input-hint {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 7px;
    text-align: center;
  }

  .contacts-list::-webkit-scrollbar { width: 4px; }
  .contacts-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  @keyframes fadeIn { to { opacity: 1; } }
  @keyframes slideIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
  @keyframes bounce { 0%, 60%, 100% { transform: translateY(0); opacity: 0.5; } 30% { transform: translateY(-6px); opacity: 1; } }

  @media (max-width: 600px) {
    .sidebar { position: absolute; z-index: 20; height: 100%; box-shadow: 4px 0 20px rgba(0,0,0,0.5); }
    .messages { padding: 16px 14px; }
    .input-area { padding: 12px 14px 16px; }
    header { padding: 12px 14px; }
  }
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">📋</div>
    <div class="logo-text">Kunden<span>DB</span></div>
  </div>
  <div class="header-right">
    <button class="icon-btn" id="sidebarToggle" onclick="toggleSidebar()">👥 Kontakte</button>
    <div class="lang-selector">
      <button class="lang-btn active" onclick="setLang('de', this)">🇩🇪 DE</button>
      <button class="lang-btn" onclick="setLang('fr', this)">🇫🇷 FR</button>
      <button class="lang-btn" onclick="setLang('en', this)">🇬🇧 EN</button>
    </div>
  </div>
</header>

<div class="main">
  <div class="sidebar hidden" id="sidebar">
    <div class="sidebar-header">Alle Kontakte</div>
    <div class="sidebar-search">
      <input type="text" id="searchInput" placeholder="Suchen..." oninput="filterContacts()">
    </div>
    <div class="contacts-list" id="contactsList">
      <div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">Wird geladen...</div>
    </div>
  </div>

  <div class="chat-area">
    <div class="messages" id="messages">
      <div class="welcome" id="welcome">
        <div class="welcome-icon">🤝</div>
        <h2>Willkommen bei KundenDB</h2>
        <p>Sprich oder schreib mit mir über deine Kunden. Ich merke mir alles und halte deine Datenbank aktuell.</p>
        <div class="suggestions">
          <div class="suggestion" onclick="useSuggestion(this)">Was weißt du über Müller GmbH?</div>
          <div class="suggestion" onclick="useSuggestion(this)">Trag ein: Schmidt AG hat angerufen</div>
          <div class="suggestion" onclick="useSuggestion(this)">Welche Kunden sind aktiv?</div>
          <div class="suggestion" onclick="useSuggestion(this)">Qui sont mes clients intéressés?</div>
        </div>
      </div>
    </div>

    <div class="input-area">
      <div class="input-wrapper">
        <textarea
          id="messageInput"
          placeholder="Schreib oder sprich etwas über einen Kunden..."
          rows="1"
          onkeydown="handleKey(event)"
          oninput="autoResize(this)"
        ></textarea>
        <button class="action-btn mic-btn" id="micBtn" onclick="toggleMic()" title="Spracheingabe">🎤</button>
        <button class="action-btn send-btn" id="sendBtn" onclick="sendMessage()" title="Senden">
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
      <div class="input-hint">Enter zum Senden · Shift+Enter für neue Zeile · 🎤 für Spracheingabe</div>
    </div>
  </div>
</div>

<script>
  const BACKEND_URL = "https://kundendb.onrender.com";

  let currentLang = "de";
  let allContacts = [];
  let sidebarVisible = false;
  let voiceMode = false; // true wenn letzte Eingabe per Mikrofon war

  // Sidebar
  function toggleSidebar() {
    sidebarVisible = !sidebarVisible;
    document.getElementById('sidebar').classList.toggle('hidden', !sidebarVisible);
    document.getElementById('sidebarToggle').classList.toggle('active', sidebarVisible);
    if (sidebarVisible) loadContacts();
  }

  // Sprache
  function setLang(lang, btn) {
    currentLang = lang;
    document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const placeholders = { de: 'Schreib oder sprich etwas über einen Kunden...', fr: 'Écris ou parle d\'un client...', en: 'Write or speak about a customer...' };
    document.getElementById('messageInput').placeholder = placeholders[lang];
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }

  function useSuggestion(el) {
    document.getElementById('messageInput').value = el.textContent;
    sendMessage();
  }

  function formatTime() {
    return new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  }

  // Nachrichten
  function addMessage(role, text) {
    const welcome = document.getElementById('welcome');
    if (welcome) welcome.style.display = 'none';

    const messages = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = `message ${role}`;

    if (role === 'assistant') {
      div.innerHTML = `
        <div class="avatar">✨</div>
        <div>
          <div class="bubble">${text.replace(/\n/g, '<br>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')}</div>
          <div class="bubble-meta">
            <span class="bubble-time">${formatTime()}</span>
            <button class="speak-btn" onclick="speakText(this)">🔊 Vorlesen</button>
          </div>
        </div>
      `;
      div.querySelector('.speak-btn').dataset.text = text;
    } else {
      div.innerHTML = `
        <div class="avatar">👤</div>
        <div>
          <div class="bubble">${text.replace(/\n/g, '<br>')}</div>
          <div class="bubble-meta"><span class="bubble-time">${formatTime()}</span></div>
        </div>
      `;
    }

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function showTyping() {
    const messages = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.id = 'typing';
    div.innerHTML = `<div class="avatar">✨</div><div class="typing"><span></span><span></span><span></span></div>`;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function removeTyping() {
    const t = document.getElementById('typing');
    if (t) t.remove();
  }

  // Nachricht senden
  async function sendMessage() {
    const input = document.getElementById('messageInput');
    const text = input.value.trim();
    if (!text) return;

    const btn = document.getElementById('sendBtn');
    btn.disabled = true;
    input.value = '';
    input.style.height = 'auto';

    addMessage('user', text);
    showTyping();

    try {
      const res = await fetch(`${BACKEND_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, language: currentLang })
      });
      const data = await res.json();
      removeTyping();
      const msgDiv = addMessage('assistant', data.reply || 'Keine Antwort erhalten.');

      // Automatisch vorlesen wenn Spracheingabe verwendet wurde
      if (voiceMode && data.reply) {
        const speakBtn = msgDiv.querySelector('.speak-btn');
        if (speakBtn) speakText(speakBtn);
      }

      if (sidebarVisible) loadContacts();
    } catch (err) {
      removeTyping();
      addMessage('assistant', '⚠️ Verbindungsfehler. Bitte Backend-URL prüfen.');
    }

    voiceMode = false;
    btn.disabled = false;
    input.focus();
  }

  // Kontakte laden
  async function loadContacts() {
    try {
      const res = await fetch(`${BACKEND_URL}/contacts`);
      allContacts = await res.json();
      renderContacts(allContacts);
    } catch (e) {
      document.getElementById('contactsList').innerHTML =
        '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">Nicht erreichbar</div>';
    }
  }

  function renderContacts(contacts) {
    const list = document.getElementById('contactsList');
    if (!contacts || !contacts.length) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">Noch keine Kontakte</div>';
      return;
    }
    list.innerHTML = contacts.map(c => `
      <div class="contact-card" onclick="askAbout('${(c.company_name||'').replace(/'/g,"\\'")}')">
        <div class="contact-company">${c.company_name || '–'}</div>
        <div class="contact-name">${c.contact_name || ''}</div>
        ${c.status ? `<div class="contact-status ${c.status.toLowerCase()}">${c.status}</div>` : ''}
      </div>
    `).join('');
  }

  function filterContacts() {
    const q = document.getElementById('searchInput').value.toLowerCase();
    renderContacts(allContacts.filter(c =>
      (c.company_name||'').toLowerCase().includes(q) ||
      (c.contact_name||'').toLowerCase().includes(q)
    ));
  }

  function askAbout(company) {
    const phrases = { de: `Was weißt du über ${company}?`, fr: `Que sais-tu sur ${company}?`, en: `What do you know about ${company}?` };
    document.getElementById('messageInput').value = phrases[currentLang];
    sendMessage();
  }

  // 🎤 Spracheingabe
  let recognition = null;
  let isRecording = false;

  function toggleMic() {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert('Bitte Chrome oder Edge verwenden für Spracheingabe.');
      return;
    }
    if (isRecording) { recognition.stop(); return; }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.lang = currentLang === 'de' ? 'de-DE' : currentLang === 'fr' ? 'fr-FR' : 'en-US';
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = () => {
      isRecording = true;
      document.getElementById('micBtn').classList.add('recording');
      document.getElementById('micBtn').textContent = '⏹️';
    };

    recognition.onresult = (e) => {
      const transcript = e.results[0][0].transcript;
      document.getElementById('messageInput').value = transcript;
      autoResize(document.getElementById('messageInput'));
      voiceMode = true;
    };

    recognition.onend = () => {
      isRecording = false;
      document.getElementById('micBtn').classList.remove('recording');
      document.getElementById('micBtn').textContent = '🎤';
      if (document.getElementById('messageInput').value.trim()) sendMessage();
    };

    recognition.onerror = () => {
      isRecording = false;
      document.getElementById('micBtn').classList.remove('recording');
      document.getElementById('micBtn').textContent = '🎤';
    };

    recognition.start();
  }

  // 🔊 Sprachausgabe
  let currentUtterance = null;

  function speakText(btn) {
    // Stop wenn gerade läuft
    if (currentUtterance) {
      window.speechSynthesis.cancel();
      document.querySelectorAll('.speak-btn').forEach(b => { b.textContent = '🔊 Vorlesen'; b.classList.remove('speaking'); });
      currentUtterance = null;
      return;
    }

    const text = btn.dataset.text || '';
    const clean = text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/[*#]/g, '').replace(/-\s/g, '').trim();

    const utter = new SpeechSynthesisUtterance(clean);
    utter.lang = currentLang === 'de' ? 'de-DE' : currentLang === 'fr' ? 'fr-FR' : 'en-US';
    utter.rate = 1.0;

    utter.onend = () => {
      btn.innerHTML = '🔊 Vorlesen';
      btn.classList.remove('speaking');
      currentUtterance = null;
    };

    currentUtterance = utter;
    btn.innerHTML = '⏹️ Stop';
    btn.classList.add('speaking');
    window.speechSynthesis.speak(utter);
  }
</script>
</body>
</html>
