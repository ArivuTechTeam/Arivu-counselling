export const dynamic = 'force-dynamic';

export async function GET() {
  const css = [
    "#arivu-bot-btn{position:fixed;bottom:24px;right:24px;z-index:99999;width:56px;height:56px;border-radius:50%;background:#2e8857;color:#fff;border:none;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,0.18);font-size:24px;display:flex;align-items:center;justify-content:center;transition:transform 0.2s}",
    "#arivu-bot-btn:hover{transform:scale(1.08)}",
    "#arivu-bot-window{position:fixed;bottom:90px;right:24px;z-index:99998;width:370px;max-width:calc(100vw - 32px);height:540px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;box-shadow:0 8px 40px rgba(0,0,0,0.18);display:flex;flex-direction:column;overflow:hidden;transition:opacity 0.2s,transform 0.2s;font-family:sans-serif}",
    "#arivu-bot-window.hidden{opacity:0;transform:translateY(12px);pointer-events:none}",
    "#arivu-bot-header{background:linear-gradient(135deg,#2e8857 0%,#1d6640 100%);color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px;flex-shrink:0}",
    "#arivu-bot-header .av{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:18px}",
    "#arivu-bot-header .inf strong{display:block;font-size:14px}",
    "#arivu-bot-header .inf span{font-size:11px;opacity:0.8}",
    "#arivu-bot-close{margin-left:auto;background:none;border:none;color:#fff;font-size:20px;cursor:pointer;opacity:0.8;padding:4px}",
    "#arivu-bot-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}",
    ".arivu-msg-wrap{display:flex;flex-direction:column;gap:4px}",
    ".arivu-msg-wrap.student{align-items:flex-end}",
    ".arivu-msg-wrap.bot{align-items:flex-start}",
    ".arivu-msg{max-width:84%;padding:10px 13px;border-radius:14px;font-size:13.5px;line-height:1.55;word-break:break-word}",
    ".arivu-msg.bot{background:#f0f4f0;color:#1a2e1a;border-bottom-left-radius:4px}",
    ".arivu-msg.student{background:#2e8857;color:#fff;border-bottom-right-radius:4px}",
    ".arivu-msg.loading{opacity:0.5}",
    ".arivu-msg-actions{display:flex;gap:6px;padding:2px 2px 0}",
    ".arivu-msg-actions button{background:none;border:1px solid #d1e8d8;border-radius:8px;padding:3px 8px;font-size:11px;cursor:pointer;color:#2e8857;transition:background 0.15s;white-space:nowrap}",
    ".arivu-msg-actions button:hover{background:#e8f5ec}",
    ".arivu-esc-row{display:flex;gap:8px;padding:4px 0 2px}",
    ".arivu-esc-yes{background:#2e8857;color:#fff;border:none;border-radius:10px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer;flex:1}",
    ".arivu-esc-no{background:#f0f4f0;color:#555;border:1px solid #d1e8d8;border-radius:10px;padding:9px 16px;font-size:13px;cursor:pointer;flex:1}",
    "#arivu-bot-input-row{padding:12px 16px;border-top:1px solid #e8f0e8;display:flex;gap:8px;flex-shrink:0}",
    "#arivu-bot-input{flex:1;border:1.5px solid #d1e8d8;border-radius:10px;padding:9px 13px;font-size:13.5px;outline:none;font-family:inherit;resize:none;line-height:1.4}",
    "#arivu-bot-input:focus{border-color:#2e8857}",
    "#arivu-bot-send{background:#2e8857;color:#fff;border:none;border-radius:10px;padding:9px 14px;cursor:pointer;font-size:18px;flex-shrink:0}",
    "#arivu-bot-send:disabled{opacity:0.5;cursor:not-allowed}",
    "#arivu-bot-mic{background:#f0f4f0;color:#2e8857;border:1.5px solid #d1e8d8;border-radius:10px;padding:9px 12px;cursor:pointer;font-size:16px;flex-shrink:0;transition:background 0.15s,border-color 0.15s}",
    "#arivu-bot-mic.listening{background:#dcfce7;border-color:#2e8857;animation:arv-mic-pulse 1s ease-in-out infinite}",
    "@keyframes arv-mic-pulse{0%,100%{box-shadow:0 0 0 0 rgba(46,136,87,0.4)}50%{box-shadow:0 0 0 6px rgba(46,136,87,0)}}",
    "#arivu-cal-overlay{position:fixed;inset:0;z-index:999999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.55);backdrop-filter:blur(3px)}",
    "#arivu-cal-overlay.hidden{display:none}",
    "#arivu-cal-modal{background:#fff;border-radius:16px;width:min(680px,96vw);height:min(720px,92vh);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 16px 60px rgba(0,0,0,0.35)}",
    "#arivu-cal-modal-header{background:#2e8857;color:#fff;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}",
    "#arivu-cal-modal-header span{font-size:14px;font-weight:600}",
    "#arivu-cal-close{background:none;border:none;color:#fff;font-size:22px;cursor:pointer;opacity:0.85;line-height:1}",
    "#arivu-cal-iframe{flex:1;border:none;width:100%}",
  ].join("\n");

  const js = `(function(){
if(window.__arivuBotLoaded)return;
window.__arivuBotLoaded=true;

/* ── Session state ── */
var BOT_API=(window.location.hostname==='localhost'||window.location.hostname==='127.0.0.1')
  ?window.location.origin+'/api/bot'
  :'https://arivu-counselling.arivupro.com/api/bot';
var TTS_API=(window.location.hostname==='localhost'||window.location.hostname==='127.0.0.1')
  ?window.location.origin+'/api/bot-tts'
  :'https://arivu-counselling.arivupro.com/api/bot-tts';

var sessionId=Math.random().toString(36).slice(2)+Date.now().toString(36);
var history=[];
var collectedData={};
var sessionMeta={turnCount:0,noMatchCount:0,repeatCount:0,cumulativeEscalationScore:0};
var isOpen=false;
var isLoading=false;
var escalationPending=false;
var collectStep=null;
var currentLang='en';

/* STT state */
var sttRec=null;
var sttActive=false;

var style=document.createElement('style');
style.textContent=${JSON.stringify(css)};
document.head.appendChild(style);

/* ── DOM ── */
var btn=document.createElement('button');
btn.id='arivu-bot-btn';
btn.title='Chat with Arivu';
btn.textContent='\\u{1F4AC}';

var win=document.createElement('div');
win.id='arivu-bot-window';
win.className='hidden';

var hdr=document.createElement('div');
hdr.id='arivu-bot-header';
hdr.innerHTML='<div class="av">\\u{1F393}</div><div class="inf"><strong>Arivu</strong><span>ArivuPro AI Counsellor &middot; Online</span></div><button id="arivu-bot-close">&#x2715;</button>';

var msgBox=document.createElement('div');
msgBox.id='arivu-bot-messages';

var inputRow=document.createElement('div');
inputRow.id='arivu-bot-input-row';
inputRow.innerHTML='<textarea id="arivu-bot-input" rows="1" placeholder="Ask anything about CA, CMA, ACCA..."></textarea><button id="arivu-bot-mic" title="Speak your message">&#127908;</button><button id="arivu-bot-send">&#9658;</button>';

win.appendChild(hdr);
win.appendChild(msgBox);
win.appendChild(inputRow);
document.body.appendChild(btn);
document.body.appendChild(win);

/* ── Calendly modal ── */
var calOverlay=document.createElement('div');
calOverlay.id='arivu-cal-overlay';
calOverlay.className='hidden';
var calModal=document.createElement('div');
calModal.id='arivu-cal-modal';
var calHdr=document.createElement('div');
calHdr.id='arivu-cal-modal-header';
calHdr.innerHTML='<span>&#128197; Book your free counselling session</span><button id="arivu-cal-close">&#x2715;</button>';
var calIframe=document.createElement('iframe');
calIframe.id='arivu-cal-iframe';
calIframe.title='Book counselling';
calIframe.setAttribute('allowfullscreen','');
calModal.appendChild(calHdr);
calModal.appendChild(calIframe);
calOverlay.appendChild(calModal);
document.body.appendChild(calOverlay);
document.getElementById('arivu-cal-close').addEventListener('click',function(){calOverlay.className='hidden';calIframe.src='';});
calOverlay.addEventListener('click',function(e){if(e.target===calOverlay){calOverlay.className='hidden';calIframe.src='';}});
function showCalModal(url){calIframe.src=url;calOverlay.className='';}

/* ── Helpers ── */
function clean(t){
  return t.replace(/\\*\\*(.*?)\\*\\*/g,'$1').replace(/\\*(.*?)\\*/g,'$1')
          .replace(/^\\s*[\\*\\-]\\s+/gm,'\\u2022 ').replace(/#{1,6}\\s+/g,'').trim();
}

/* ── STT — Web Speech API (built-in browser, works offline, handles Indian languages) ── */

function toggleSTT(){
  if(sttActive) stopSTT();
  else startSTT();
}

function startSTT(){
  var SpeechRec=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SpeechRec){
    addMsg('bot','Voice input is not supported in this browser. Please use Chrome or Edge.');
    return;
  }
  var micBtn=document.getElementById('arivu-bot-mic');
  var inp=document.getElementById('arivu-bot-input');
  if(!micBtn||!inp)return;

  sttRec=new SpeechRec();
  sttRec.continuous=false;
  sttRec.interimResults=true;
  /* Multi-language: en-IN primary, Tamil, Hindi as alternatives */
  sttRec.lang='en-IN';
  sttRec.maxAlternatives=1;

  sttRec.onstart=function(){
    sttActive=true;
    micBtn.className='listening';
    micBtn.title='Tap to stop';
    inp.placeholder='Listening...';
  };

  sttRec.onresult=function(e){
    var interim='';var final='';
    for(var i=e.resultIndex;i<e.results.length;i++){
      if(e.results[i].isFinal) final+=e.results[i][0].transcript;
      else interim+=e.results[i][0].transcript;
    }
    inp.value=(final||interim).trim();
    inp.style.height='auto';
    inp.style.height=Math.min(inp.scrollHeight,120)+'px';
  };

  sttRec.onend=function(){
    var text=inp.value.trim();
    stopSTT();
    if(text){
      send(text);
      inp.value='';
      inp.style.height='auto';
    }
  };

  sttRec.onerror=function(e){
    stopSTT();
    if(e.error==='not-allowed') addMsg('bot','Microphone access denied. Please allow mic access in your browser settings.');
    else if(e.error!=='no-speech') addMsg('bot','Voice input error ('+e.error+'). Please try again.');
  };

  try{ sttRec.start(); }catch(e){ stopSTT(); }
}

function stopSTT(){
  sttActive=false;
  if(sttRec){try{sttRec.stop();}catch(e){}sttRec=null;}
  var micBtn=document.getElementById('arivu-bot-mic');
  var inp=document.getElementById('arivu-bot-input');
  if(micBtn){micBtn.className='';micBtn.title='Speak your message';}
  if(inp&&inp.placeholder==='Listening...')inp.placeholder='Ask anything about CA, CMA, ACCA...';
}

/* ── Streaming TTS — plays audio chunks as they arrive from Gemini ── */
function base64ToFloat32(b64){
  var bin=atob(b64);
  var bytes=new Uint8Array(bin.length);
  for(var i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
  var int16=new Int16Array(bytes.buffer);
  var float32=new Float32Array(int16.length);
  for(var j=0;j<int16.length;j++)float32[j]=int16[j]/32768.0;
  return float32;
}

function getAudioCtx(){
  if(!window.__arivuAudioCtx||window.__arivuAudioCtx.state==='closed'){
    window.__arivuAudioCtx=new (window.AudioContext||window.webkitAudioContext)({sampleRate:24000});
  }
  return window.__arivuAudioCtx;
}

async function speakStreaming(text,onDone){
  try{
    var ctx=getAudioCtx();
    if(ctx.state==='suspended')await ctx.resume();
    var res=await fetch(TTS_API,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:text})
    });
    if(!res.ok||!res.body){speakWebSpeech(text,'en',onDone);return;}

    var contentType=res.headers.get('content-type')||'';
    if(contentType.indexOf('application/json')!==-1){
      var d=await res.json();
      if(d.audio){playAudioBase64(d.audio).catch(function(){speakWebSpeech(text,'en',onDone);}).then(onDone||function(){});}
      else{speakWebSpeech(text,'en',onDone);}
      return;
    }

    var reader=res.body.getReader();
    var decoder=new TextDecoder();
    var buf='';
    var nextPlayTime=ctx.currentTime+0.05;
    var lastSource=null;
    var finished=false;

    function scheduleChunk(b64){
      if(!b64.trim())return;
      try{
        var pcm=base64ToFloat32(b64.trim());
        var audioBuffer=ctx.createBuffer(1,pcm.length,24000);
        audioBuffer.copyToChannel(pcm,0);
        var src=ctx.createBufferSource();
        src.buffer=audioBuffer;
        src.connect(ctx.destination);
        var startAt=Math.max(nextPlayTime,ctx.currentTime+0.01);
        src.start(startAt);
        nextPlayTime=startAt+audioBuffer.duration;
        lastSource=src;
      }catch(e){}
    }

    async function pump(){
      while(true){
        var r2=await reader.read();
        if(r2.done){finished=true;break;}
        buf+=decoder.decode(r2.value,{stream:true});
        var lines=buf.split('\\n');
        buf=lines.pop()||'';
        for(var i=0;i<lines.length;i++)scheduleChunk(lines[i]);
      }
      if(buf.trim())scheduleChunk(buf);
      if(lastSource&&onDone){lastSource.onended=onDone;}
      else if(onDone){setTimeout(onDone,100);}
    }
    pump().catch(function(){if(!finished){speakWebSpeech(text,'en',onDone);}});
  }catch(e){
    speakWebSpeech(text,'en',onDone);
  }
}

/* Web Speech TTS — Indian female voice, falls back gracefully */
function speakWebSpeech(text,lang,onEnd){
  if(!window.speechSynthesis){if(onEnd)onEnd();return;}
  var localeLang=(lang==='ta')?'ta-IN':(lang==='hi'||lang==='hinglish')?'hi-IN':'en-IN';
  var utt=new SpeechSynthesisUtterance(text);
  utt.lang=localeLang;
  utt.rate=0.88;
  utt.pitch=1.15;
  utt.volume=1;

  function pickVoice(){
    var voices=window.speechSynthesis.getVoices();
    if(!voices.length)return null;
    /* Priority: exact locale + female name keywords */
    var FEMALE=['lekha','neerja','heera','aditi','priya','meera','raveena','veena','female','zira'];
    var MALE=['rishi','raj','male','david','mark','daniel','google us english'];
    var v=voices.find(function(vo){
      var n=vo.name.toLowerCase();
      return vo.lang===localeLang&&FEMALE.some(function(f){return n.includes(f);});
    });
    /* Any Indian female */
    if(!v)v=voices.find(function(vo){
      var n=vo.name.toLowerCase();
      return vo.lang.startsWith('en-IN')&&!MALE.some(function(m){return n.includes(m);});
    });
    /* Any Indian English */
    if(!v)v=voices.find(function(vo){return vo.lang.startsWith('en-IN');});
    /* Last resort: any English */
    if(!v)v=voices.find(function(vo){return vo.lang.startsWith('en');});
    return v||null;
  }

  function doSpeak(){
    var voice=pickVoice();
    if(voice)utt.voice=voice;
    utt.onend=function(){if(onEnd)onEnd();};
    utt.onerror=function(){if(onEnd)onEnd();};
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utt);
  }

  var voices=window.speechSynthesis.getVoices();
  if(voices.length>0){doSpeak();}
  else{
    window.speechSynthesis.addEventListener('voiceschanged',function h(){
      window.speechSynthesis.removeEventListener('voiceschanged',h);
      doSpeak();
    });
  }
}

function playAudioBase64(b64){
  return new Promise(function(resolve,reject){
    var a=new Audio('data:audio/wav;base64,'+b64);
    a.onended=resolve;a.onerror=reject;
    a.play().catch(reject);
  });
}

async function speakText(text,lang,btn){
  if(btn)btn.textContent='\\u{1F50A} Speaking...';
  await speakStreaming(text,function(){if(btn)btn.textContent='\\u{1F50A} Speak';});
}

/* ── Message rendering ── */
function addMsg(role,text){
  var wrap=document.createElement('div');
  wrap.className='arivu-msg-wrap '+role;
  var d=document.createElement('div');
  d.className='arivu-msg '+role;
  d.textContent=(role==='bot')?clean(text):text;
  wrap.appendChild(d);
  msgBox.appendChild(wrap);
  msgBox.scrollTop=msgBox.scrollHeight;
  return {wrap:wrap,bubble:d};
}

function addBotMsg(text,preloadedAudio,lang,onRegen){
  var wrap=document.createElement('div');
  wrap.className='arivu-msg-wrap bot';
  var d=document.createElement('div');
  d.className='arivu-msg bot';
  d.textContent=clean(text);
  wrap.appendChild(d);

  var acts=document.createElement('div');
  acts.className='arivu-msg-actions';

  var cpBtn=document.createElement('button');
  cpBtn.textContent='\\u{1F4CB} Copy';
  cpBtn.onclick=function(){
    if(navigator.clipboard)navigator.clipboard.writeText(text).then(function(){
      cpBtn.textContent='\\u2714 Copied!';setTimeout(function(){cpBtn.textContent='\\u{1F4CB} Copy';},1500);
    });
  };
  acts.appendChild(cpBtn);

  var spkBtn=document.createElement('button');
  spkBtn.textContent='\\u{1F50A} Speak';
  spkBtn.onclick=function(){
    spkBtn.disabled=true;
    spkBtn.textContent='\\u{1F50A} Speaking...';
    if(preloadedAudio){
      /* Audio was pre-generated with the reply — play instantly, no API call */
      playAudioBase64(preloadedAudio)
        .catch(function(){return speakText(text,lang,null);})
        .then(function(){spkBtn.textContent='\\u{1F50A} Speak';spkBtn.disabled=false;});
    } else {
      speakText(text,lang,spkBtn).then(function(){spkBtn.disabled=false;}).catch(function(){spkBtn.disabled=false;spkBtn.textContent='\\u{1F50A} Speak';});
    }
  };
  acts.appendChild(spkBtn);

  if(typeof onRegen==='function'){
    var rgBtn=document.createElement('button');
    rgBtn.textContent='\\u{1F504} Redo';
    rgBtn.onclick=onRegen;
    acts.appendChild(rgBtn);
  }

  wrap.appendChild(acts);
  msgBox.appendChild(wrap);
  msgBox.scrollTop=msgBox.scrollHeight;
  return {wrap:wrap,bubble:d};
}

/* ── Escalation prompt ── */
function addEscalationPrompt(){
  if(escalationPending)return;
  escalationPending=true;
  var wrap=document.createElement('div');
  wrap.className='arivu-msg-wrap bot';
  var d=document.createElement('div');
  d.className='arivu-msg bot';
  d.textContent='\\u{1F4DE} Would you like a FREE 30-min counselling session with our expert team?';
  wrap.appendChild(d);
  var br=document.createElement('div');
  br.className='arivu-esc-row';
  var y=document.createElement('button');y.className='arivu-esc-yes';y.textContent='\\u2705 Yes, I want counselling!';
  y.onclick=function(){wrap.remove();escalationPending=false;startCollection();};
  var n=document.createElement('button');n.className='arivu-esc-no';n.textContent='Not now';
  n.onclick=function(){wrap.remove();escalationPending=false;};
  br.appendChild(y);br.appendChild(n);
  wrap.appendChild(br);
  msgBox.appendChild(wrap);
  msgBox.scrollTop=msgBox.scrollHeight;
}

/* ── Contact collection ── */
var VALIDATION={
  name_invalid:{en:'Please enter your full name (at least 2 characters).',ta:'Ungal peyar sari illa. Correct aa type pannunga.',tanglish:'Peyar correctly enter pannunga (min 2 letters).',hinglish:'Apna poora naam likhein please.'},
  phone_invalid:{en:'Please enter a valid 10-digit Indian mobile number starting with 6, 7, 8 or 9.',ta:'Correct 10 digit mobile number enter pannunga (6/7/8/9 la start aaganum).',tanglish:'Valid 10-digit number enter pannunga — 6, 7, 8 or 9 la start aaganum.',hinglish:'10 digit valid mobile number daalein jo 6, 7, 8 ya 9 se shuru ho.'},
  email_invalid:{en:'That email doesn\\'t look right. Please enter a valid email (e.g. yourname@gmail.com).',ta:'Email address correct illa. Correct aa enter pannunga (e.g. yourname@gmail.com).',tanglish:'Email correct illa — try again panunga (e.g. yourname@gmail.com).',hinglish:'Email sahi nahi lag raha. Dobara likhein (e.g. yourname@gmail.com).'},
};
var EMAIL_TYPOS={
  'gmila.com':'gmail.com','gmial.com':'gmail.com','gamil.com':'gmail.com',
  'gmal.com':'gmail.com','gmali.com':'gmail.com','gnail.com':'gmail.com',
  'gmaill.com':'gmail.com','gemail.com':'gmail.com','gmai.com':'gmail.com',
  'gmail.co':'gmail.com','gmail.con':'gmail.com','gmail.cpm':'gmail.com',
  'gmail.ocm':'gmail.com','gmail.cm':'gmail.com','gmail.coim':'gmail.com',
  'gmila.ocm':'gmail.com','gmial.ocm':'gmail.com','gamil.ocm':'gmail.com',
  'gmal.ocm':'gmail.com','gmali.ocm':'gmail.com','gnail.ocm':'gmail.com',
  'gmila.con':'gmail.com','gmial.con':'gmail.com','gamil.con':'gmail.com',
  'yaho.com':'yahoo.com','yahooo.com':'yahoo.com','yahoo.co':'yahoo.com',
  'yahoo.con':'yahoo.com','yahoo.ocm':'yahoo.com','yhoo.com':'yahoo.com',
  'hotmial.com':'hotmail.com','hotmal.com':'hotmail.com',
  'hotmail.con':'hotmail.com','hotmail.ocm':'hotmail.com','hotmaill.com':'hotmail.com',
  'outlok.com':'outlook.com','outloook.com':'outlook.com',
  'outlook.con':'outlook.com','outlook.ocm':'outlook.com',
  'redifmail.com':'rediffmail.com','redifmail.in':'rediffmail.com',
  'rediffmail.con':'rediffmail.com',
};
var TLD_FIXES={'ocm':'com','cmo':'com','con':'com','cpm':'com','vom':'com','xom':'com','om':'com','cm':'com'};

function getMsg(key){return VALIDATION[key][currentLang]||VALIDATION[key]['en'];}

function validateEmail(em){
  em=em.toLowerCase().trim();
  var atParts=em.split('@');
  if(atParts.length!==2)return{ok:false,msg:null};
  var local=atParts[0];var domain=atParts[1];
  if(!local||local.length<1)return{ok:false,msg:null};
  if(!domain||domain.indexOf('.')===-1)return{ok:false,msg:null};
  if(em.indexOf(' ')!==-1)return{ok:false,msg:null};
  var lastDot=domain.lastIndexOf('.');
  if(lastDot<1)return{ok:false,msg:null};
  var tld=domain.slice(lastDot+1);
  if(tld.length<2)return{ok:false,msg:null};
  var domainBase=domain.slice(0,lastDot);
  var correctedTld=TLD_FIXES[tld]||tld;
  var lookupDomain=domainBase+'.'+correctedTld;
  var fix=EMAIL_TYPOS[lookupDomain]||EMAIL_TYPOS[domain];
  if(fix)return{ok:false,msg:'Did you mean '+local+'@'+fix+'? Please re-enter.'};
  if(TLD_FIXES[tld])return{ok:false,msg:'Check your email — did you mean .'+TLD_FIXES[tld]+' instead of .'+tld+'?'};
  return{ok:true,msg:null};
}

function startCollection(){
  collectStep='name';
  addMsg('bot','What is your name?');
}

function handleCollectionInput(text){
  var trimmed=text.trim();
  if(collectStep==='name'){
    if(trimmed.length<2||/^\\d+$/.test(trimmed)){
      addMsg('student',text);addMsg('bot',getMsg('name_invalid'));return true;
    }
    collectedData.name=trimmed;addMsg('student',text);
    collectStep='phone';addMsg('bot','Thanks '+collectedData.name+'! Your 10-digit mobile number?');return true;
  }
  if(collectStep==='phone'){
    var digits=trimmed.replace(/[\\s\\-()+]/g,'');
    if(!/^[6-9]\\d{9}$/.test(digits)){
      addMsg('student',text);addMsg('bot',getMsg('phone_invalid'));return true;
    }
    collectedData.phone=digits;addMsg('student',text);
    collectStep='email';addMsg('bot','Last one — your email address?');return true;
  }
  if(collectStep==='email'){
    var result=validateEmail(trimmed);
    if(!result.ok){addMsg('student',text);addMsg('bot',result.msg||getMsg('email_invalid'));return true;}
    collectedData.email=trimmed.toLowerCase().trim();addMsg('student',text);
    collectStep=null;openCalendly();return true;
  }
  return false;
}

function openCalendly(){
  var base='https://calendly.com/tech-arivupro/30min';
  var p=new URLSearchParams();
  if(collectedData.name)p.set('name',collectedData.name);
  if(collectedData.email)p.set('email',collectedData.email);
  p.set('hide_gdpr_banner','1');
  p.set('primary_color','2e8857');
  addMsg('bot','Opening your booking calendar now...');
  setTimeout(function(){showCalModal(base+'?'+p.toString());},400);
}

/* ── Greeting ── */
function greet(){
  addMsg('bot','Hi! I am Arivu, your ArivuPro AI Counsellor.');
  addMsg('bot','Ask me anything about CA, CMA, ACCA, CFA or any course we offer.');
  addMsg('bot','Type in any language — English, Tamil, Tanglish, Hindi, or any mix!');
}

/* ── Send text message ── */
async function send(text){
  if(!text.trim()||isLoading)return;
  if(collectStep){if(handleCollectionInput(text))return;}
  isLoading=true;
  addMsg('student',text);
  history.push({role:'student',content:text});
  var {wrap:ldWrap,bubble:ldBubble}=addMsg('bot','...');
  ldBubble.className='arivu-msg bot loading';
  document.getElementById('arivu-bot-send').disabled=true;
  try{
    var payload={
      sessionId:sessionId,message:text,
      history:history.slice(-10),
      collectedData:Object.assign({},collectedData),
      sessionMeta:sessionMeta
    };
    var res=await fetch(BOT_API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var data=await res.json();
    ldWrap.remove();
    var reply=data.reply||'Sorry, something went wrong. Please try again.';
    if(data.language)currentLang=data.language;
    if(data.collectedData)collectedData=data.collectedData;
    if(data.sessionMeta)sessionMeta=data.sessionMeta;
    var capturedText=reply;var capturedLang=data.language||'en';
    addBotMsg(reply,data.replyAudio||null,capturedLang,function(){send(capturedText);});
    history.push({role:'bot',content:reply});
    if(data.action==='show_calendly'&&data.calendlyUrl){
      showCalModal(data.calendlyUrl);
    } else if((data.action==='collect_name'||data.action==='collect_phone'||data.action==='collect_email')&&!collectStep){
      escalationPending=false;
      if(data.action==='collect_name')collectStep='name';
      else if(data.action==='collect_phone')collectStep='phone';
      else collectStep='email';
      var nextQ={name:'What is your name?',phone:'Your 10-digit mobile number?',email:'Your email address?'};
      addMsg('bot',nextQ[collectStep]);
    } else if((data.cumulativeScore||0)>0.65&&!escalationPending&&!collectStep){
      addEscalationPrompt();
    }
  }catch(e){
    ldBubble.textContent='Connection error. Please try again.';
    ldBubble.className='arivu-msg bot';
  }
  isLoading=false;
  document.getElementById('arivu-bot-send').disabled=false;
}

/* ── Events ── */
btn.addEventListener('click',function(){
  isOpen=!isOpen;
  win.className=isOpen?'':'hidden';
  btn.textContent=isOpen?'\\u2715':'\\u{1F4AC}';
  if(isOpen&&msgBox.children.length===0)setTimeout(greet,50);
  if(isOpen)setTimeout(function(){var el=document.getElementById('arivu-bot-input');if(el)el.focus();},100);
});
document.getElementById('arivu-bot-close').addEventListener('click',function(){
  isOpen=false;win.className='hidden';btn.textContent='\\u{1F4AC}';
  if(sttActive)stopSTT();
});
document.getElementById('arivu-bot-send').addEventListener('click',function(){
  var el=document.getElementById('arivu-bot-input');if(el){send(el.value);el.value='';}
});
document.getElementById('arivu-bot-input').addEventListener('keydown',function(e){
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send(this.value);this.value='';}
});
document.getElementById('arivu-bot-mic').addEventListener('click',toggleSTT);

})();`;

  return new Response(js, {
    headers: {
      'Content-Type': 'application/javascript; charset=utf-8',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Access-Control-Allow-Origin': '*',
    },
  });
}
