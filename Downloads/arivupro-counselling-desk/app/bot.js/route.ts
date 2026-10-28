export const dynamic = 'force-dynamic';

export async function GET() {
  const BOT_API = 'https://arivu-counselling.arivupro.com/api/bot';

  const js = `
(function() {
  if (window.__arivuBotLoaded) return;
  window.__arivuBotLoaded = true;

  // ── State ──────────────────────────────────────────────────────────────
  var sessionId = 'xxxx-xxxx-4xxx-yxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
  var history = [];
  var collectedData = {};
  var sessionMeta = { turnCount: 0, noMatchCount: 0, repeatCount: 0, cumulativeEscalationScore: 0 };
  var isOpen = false;
  var isLoading = false;
  var mediaRecorder = null;
  var audioChunks = [];
  var isRecording = false;

  // ── Styles ─────────────────────────────────────────────────────────────
  var style = document.createElement('style');
  style.textContent = \`
    #arivu-bot-btn {
      position: fixed; bottom: 24px; right: 24px; z-index: 99999;
      width: 56px; height: 56px; border-radius: 50%;
      background: #2e8857; color: #fff; border: none; cursor: pointer;
      box-shadow: 0 4px 16px rgba(0,0,0,0.18);
      font-size: 24px; display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #arivu-bot-btn:hover { transform: scale(1.08); box-shadow: 0 6px 20px rgba(0,0,0,0.22); }
    #arivu-bot-window {
      position: fixed; bottom: 90px; right: 24px; z-index: 99998;
      width: 360px; max-width: calc(100vw - 32px);
      height: 520px; max-height: calc(100vh - 120px);
      background: #fff; border-radius: 16px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.18);
      display: flex; flex-direction: column; overflow: hidden;
      transition: opacity 0.2s, transform 0.2s;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    #arivu-bot-window.hidden { opacity: 0; transform: translateY(12px); pointer-events: none; }
    #arivu-bot-header {
      background: #2e8857; color: #fff; padding: 14px 16px;
      display: flex; align-items: center; gap: 10px; flex-shrink: 0;
    }
    #arivu-bot-header .avatar {
      width: 36px; height: 36px; border-radius: 50%; background: rgba(255,255,255,0.2);
      display: flex; align-items: center; justify-content: center; font-size: 18px;
    }
    #arivu-bot-header .info strong { display: block; font-size: 14px; }
    #arivu-bot-header .info span { font-size: 11px; opacity: 0.8; }
    #arivu-bot-close {
      margin-left: auto; background: none; border: none; color: #fff;
      font-size: 20px; cursor: pointer; opacity: 0.8; padding: 4px;
    }
    #arivu-bot-messages {
      flex: 1; overflow-y: auto; padding: 16px; display: flex;
      flex-direction: column; gap: 10px;
    }
    .arivu-msg { max-width: 80%; padding: 10px 13px; border-radius: 14px; font-size: 13.5px; line-height: 1.5; word-break: break-word; }
    .arivu-msg.bot { background: #f0f4f0; color: #1a2e1a; border-bottom-left-radius: 4px; align-self: flex-start; }
    .arivu-msg.student { background: #2e8857; color: #fff; border-bottom-right-radius: 4px; align-self: flex-end; }
    .arivu-msg.loading { opacity: 0.6; }
    #arivu-bot-calendly {
      padding: 12px 16px; border-top: 1px solid #e8f0e8; flex-shrink: 0; display: none;
    }
    #arivu-bot-calendly a {
      display: block; background: #2e8857; color: #fff; text-align: center;
      padding: 11px; border-radius: 10px; font-size: 13px; font-weight: 600;
      text-decoration: none;
    }
    #arivu-bot-calendly a:hover { background: #256b46; }
    #arivu-bot-input-row {
      padding: 12px 16px; border-top: 1px solid #e8f0e8;
      display: flex; gap: 8px; flex-shrink: 0;
    }
    #arivu-bot-input {
      flex: 1; border: 1.5px solid #d1e8d8; border-radius: 10px;
      padding: 9px 13px; font-size: 13.5px; outline: none;
      font-family: inherit; resize: none; line-height: 1.4;
    }
    #arivu-bot-input:focus { border-color: #2e8857; }
    #arivu-bot-send {
      background: #2e8857; color: #fff; border: none; border-radius: 10px;
      padding: 9px 14px; cursor: pointer; font-size: 18px; flex-shrink: 0;
    }
    #arivu-bot-send:disabled { opacity: 0.5; cursor: not-allowed; }
    .arivu-escalation-note {
      font-size: 11px; color: #666; text-align: center; padding: 6px 16px;
      background: #fffbeb; border-top: 1px solid #fde68a;
    }
    #arivu-bot-mic {
      background: #f0f4f0; color: #2e8857; border: 1.5px solid #d1e8d8;
      border-radius: 10px; padding: 9px 12px; cursor: pointer; font-size: 16px; flex-shrink: 0;
    }
    #arivu-bot-mic.recording { background: #fee2e2; border-color: #fca5a5; color: #dc2626; animation: pulse 1s infinite; }
    @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }
  \`;
  document.head.appendChild(style);

  // ── DOM ────────────────────────────────────────────────────────────────
  var btn = document.createElement('button');
  btn.id = 'arivu-bot-btn';
  btn.setAttribute('aria-label', 'Chat with Arivu');
  btn.innerHTML = '💬';

  var win = document.createElement('div');
  win.id = 'arivu-bot-window';
  win.className = 'hidden';
  win.innerHTML = \`
    <div id="arivu-bot-header">
      <div class="avatar">🎓</div>
      <div class="info">
        <strong>Arivu</strong>
        <span>ArivuPro AI Counsellor · Online</span>
      </div>
      <button id="arivu-bot-close">✕</button>
    </div>
    <div id="arivu-bot-messages"></div>
    <div id="arivu-bot-calendly">
      <a id="arivu-calendly-link" href="#" target="_blank">📅 Book a free counselling session</a>
    </div>
    <div id="arivu-bot-input-row">
      <textarea id="arivu-bot-input" rows="1" placeholder="Ask anything about CA, CMA, ACCA..."></textarea>
      <button id="arivu-bot-mic" title="Voice input">🎤</button>
      <button id="arivu-bot-send">➤</button>
    </div>
  \`;

  document.body.appendChild(btn);
  document.body.appendChild(win);

  // ── Helpers ────────────────────────────────────────────────────────────
  function appendMsg(role, text) {
    var msgs = document.getElementById('arivu-bot-messages');
    var div = document.createElement('div');
    div.className = 'arivu-msg ' + role;
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function showCalendly(url) {
    var block = document.getElementById('arivu-bot-calendly');
    var link = document.getElementById('arivu-calendly-link');
    link.href = url;
    block.style.display = 'block';
  }

  function greet() {
    appendMsg('bot', "Hi! I'm Arivu, your ArivuPro counsellor 🎓\\nAsk me anything about CA, CMA, ACCA, or any course.\\nநான் தமிழிலயும் பேசுவேன் 😊");
  }

  // ── Voice recording ────────────────────────────────────────────────────
  function toggleRecording() {
    if (isRecording) {
      mediaRecorder.stop();
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function(stream) {
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      isRecording = true;
      var micBtn = document.getElementById('arivu-bot-mic');
      micBtn.className = 'recording';
      micBtn.textContent = '⏹';

      mediaRecorder.ondataavailable = function(e) { audioChunks.push(e.data); };
      mediaRecorder.onstop = function() {
        isRecording = false;
        micBtn.className = '';
        micBtn.textContent = '🎤';
        stream.getTracks().forEach(function(t) { t.stop(); });

        var blob = new Blob(audioChunks, { type: 'audio/webm' });
        var reader = new FileReader();
        reader.onloadend = function() {
          var base64 = reader.result.split(',')[1];
          sendAudio(base64);
        };
        reader.readAsDataURL(blob);
      };
      mediaRecorder.start();
    }).catch(function() {
      appendMsg('bot', 'Microphone access denied. Please allow microphone and try again.');
    });
  }

  async function sendAudio(audioBase64) {
    if (isLoading) return;
    isLoading = true;
    appendMsg('student', '🎤 Voice message');
    var loadingDiv = appendMsg('bot', '...');
    loadingDiv.className += ' loading';
    document.getElementById('arivu-bot-send').disabled = true;

    try {
      var res = await fetch('${BOT_API}', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId: sessionId, audioBase64: audioBase64, isVoice: true,
          history: history.slice(-10), collectedData: collectedData, sessionMeta: sessionMeta
        })
      });
      var data = await res.json();
      loadingDiv.remove();
      var reply = data.reply || 'Sorry, could not process voice.';
      appendMsg('bot', reply);
      history.push({ role: 'bot', content: reply });
      if (data.collectedData) collectedData = data.collectedData;
      if (data.sessionMeta) sessionMeta = data.sessionMeta;
      if (data.action === 'show_calendly' && data.calendlyUrl) showCalendly(data.calendlyUrl);

      // Play TTS audio if provided
      if (data.replyAudio) {
        var audio = new Audio('data:audio/wav;base64,' + data.replyAudio);
        audio.play().catch(function(){});
      }
    } catch(e) {
      loadingDiv.textContent = 'Voice error. Please try again.';
      loadingDiv.className = 'arivu-msg bot';
    }
    isLoading = false;
    document.getElementById('arivu-bot-send').disabled = false;
  }

  // ── Send message ───────────────────────────────────────────────────────
  async function send(text) {
    if (!text.trim() || isLoading) return;
    isLoading = true;

    appendMsg('student', text);
    history.push({ role: 'student', content: text });

    var loadingDiv = appendMsg('bot', '...');
    loadingDiv.className += ' loading';

    document.getElementById('arivu-bot-send').disabled = true;
    document.getElementById('arivu-bot-input').value = '';

    try {
      var res = await fetch('${BOT_API}', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId: sessionId,
          message: text,
          history: history.slice(-10),
          collectedData: collectedData,
          sessionMeta: sessionMeta
        })
      });

      var data = await res.json();

      loadingDiv.remove();

      var reply = data.reply || 'Sorry, something went wrong. Please try again.';
      appendMsg('bot', reply);
      history.push({ role: 'bot', content: reply });

      // Update state
      if (data.collectedData) collectedData = data.collectedData;
      if (data.sessionMeta) sessionMeta = data.sessionMeta;

      // Show Calendly if escalated
      if (data.action === 'show_calendly' && data.calendlyUrl) {
        showCalendly(data.calendlyUrl);
      }

    } catch (e) {
      loadingDiv.textContent = 'Connection error. Please try again.';
      loadingDiv.className = 'arivu-msg bot';
    }

    isLoading = false;
    document.getElementById('arivu-bot-send').disabled = false;
  }

  // ── Events ─────────────────────────────────────────────────────────────
  btn.addEventListener('click', function() {
    isOpen = !isOpen;
    win.className = isOpen ? '' : 'hidden';
    btn.innerHTML = isOpen ? '✕' : '💬';
    if (isOpen && document.getElementById('arivu-bot-messages').children.length === 0) {
      greet();
    }
    if (isOpen) setTimeout(function() { document.getElementById('arivu-bot-input').focus(); }, 100);
  });

  document.getElementById('arivu-bot-close').addEventListener('click', function() {
    isOpen = false;
    win.className = 'hidden';
    btn.innerHTML = '💬';
  });

  document.getElementById('arivu-bot-send').addEventListener('click', function() {
    var input = document.getElementById('arivu-bot-input');
    send(input.value);
    input.value = '';
  });

  document.getElementById('arivu-bot-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send(this.value);
      this.value = '';
    }
  });

  document.getElementById('arivu-bot-mic').addEventListener('click', function() { toggleRecording(); });

})();
`;

  return new Response(js, {
    headers: {
      'Content-Type': 'application/javascript; charset=utf-8',
      'Cache-Control': 'public, max-age=300',
      'Access-Control-Allow-Origin': '*',
    },
  });
}
