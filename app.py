"""
TwitchBot Panel v2 — Fichier unique (HTML intégré, pas besoin du dossier templates/)
"""
import threading, asyncio, json, os
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, jsonify, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import twitchio
from twitchio.ext import commands

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'changez-moi-en-production')

USERS_FILE  = 'users.json'
CONFIG_FILE = 'config.json'
DEFAULT_CONFIG = {
    'bot_token':      os.environ.get('BOT_TOKEN', ''),
    'lurk_message':   '{user} part en mode lurk dans les buissons... 👀🌿',
    'unlurk_message': '👋 {user} est de retour ! Bienvenue !'
}

def load_users():
    return json.load(open(USERS_FILE)) if os.path.exists(USERS_FILE) else {}

def save_users(u):
    json.dump(u, open(USERS_FILE,'w'), indent=2, ensure_ascii=False)

def load_config():
    return {**DEFAULT_CONFIG, **json.load(open(CONFIG_FILE))} if os.path.exists(CONFIG_FILE) else DEFAULT_CONFIG.copy()

def save_config(c):
    json.dump(c, open(CONFIG_FILE,'w'), indent=2, ensure_ascii=False)

config = load_config()

def login_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'username' not in session: return redirect(url_for('login_page'))
        return f(*a,**k)
    return d

def admin_required(f):
    @wraps(f)
    def d(*a,**k):
        if 'username' not in session: return redirect(url_for('login_page'))
        if not load_users().get(session['username'],{}).get('admin'): return jsonify({'error':'Admin requis'}),403
        return f(*a,**k)
    return d

logs = []
def add_log(msg, level='info', channel=None):
    e = {'time': datetime.now().strftime('%H:%M:%S'), 'msg': msg, 'level': level, 'channel': channel or ''}
    logs.append(e)
    if len(logs) > 500: logs.pop(0)
    print(f"[{e['time']}] {msg}")

bot_instance = bot_thread = bot_loop = None
bot_running  = False

class TwitchBot(commands.Bot):
    def __init__(self, token, channels, lurk_msg, unlurk_msg):
        super().__init__(token=token, prefix='!', initial_channels=channels or ['_placeholder_'])
        self.lurk_msg = lurk_msg; self.unlurk_msg = unlurk_msg

    async def event_ready(self):
        add_log(f'Bot connecté : {self.nick}', 'success')
        for ch in self.connected_channels: add_log(f'Canal rejoint : #{ch.name}', 'info', ch.name)

    async def event_message(self, message):
        if message.echo: return
        await self.handle_commands(message)

    @commands.command(name='addbot')
    async def addbot(self, ctx):
        users = load_users(); ch = ctx.channel.name.lower()
        for uname, data in users.items():
            if data.get('channel','').lower() == ch and data.get('status') == 'pending':
                users[uname]['status'] = 'active'; save_users(users)
                await ctx.send(f'✅ Bot activé sur #{ch} ! Commandes : !lurk / !unlurk 🎉')
                add_log(f'#{ch} activé par {ctx.author.name}', 'success', ch); return
        if any(d.get('channel','').lower()==ch and d.get('status')=='active' for d in users.values()):
            await ctx.send('ℹ️ Le bot est déjà actif sur ce canal !')

    @commands.command(name='lurk')
    async def lurk(self, ctx):
        users = load_users(); ch = ctx.channel.name.lower()
        if not any(d.get('channel','').lower()==ch and d.get('status')=='active' for d in users.values()): return
        await ctx.send(self.lurk_msg.format(user=ctx.author.name))
        add_log(f'{ctx.author.name} → !lurk', 'command', ch)

    @commands.command(name='unlurk')
    async def unlurk(self, ctx):
        users = load_users(); ch = ctx.channel.name.lower()
        if not any(d.get('channel','').lower()==ch and d.get('status')=='active' for d in users.values()): return
        await ctx.send(self.unlurk_msg.format(user=ctx.author.name))
        add_log(f'{ctx.author.name} → !unlurk', 'command', ch)

    async def event_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound): return
        add_log(f'Erreur : {error}', 'error')

def _get_channels():
    return [d['channel'] for d in load_users().values() if d.get('channel') and d.get('status') in ('pending','active')]

def _run_bot(token, channels, lurk_msg, unlurk_msg):
    global bot_instance, bot_loop, bot_running
    bot_loop = asyncio.new_event_loop(); asyncio.set_event_loop(bot_loop)
    bot_instance = TwitchBot(token, channels, lurk_msg, unlurk_msg)
    try:
        bot_running = True; bot_instance.run()
    except Exception as e: add_log(f'Erreur fatale : {e}', 'error')
    finally: bot_running = False; add_log('Bot arrêté', 'warning')

def start_bot():
    global bot_thread
    if bot_thread and bot_thread.is_alive(): return
    token = config.get('bot_token','')
    if not token: return
    bot_thread = threading.Thread(target=_run_bot,
        args=(token, _get_channels(), config['lurk_message'], config['unlurk_message']), daemon=True)
    bot_thread.start(); add_log('Bot démarré', 'info')

def join_live(ch):
    if bot_instance and bot_loop and bot_running and not bot_loop.is_closed():
        asyncio.run_coroutine_threadsafe(bot_instance.join_channels([ch]), bot_loop)
        add_log(f'Rejoint #{ch}', 'success', ch)

# ── HTML TEMPLATES ───────────────────────────────────────────────────────────

AUTH_HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TwitchBot — {{ 'Connexion' if mode=='login' else 'Inscription' }}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080c14;--surf:#0f1520;--surf2:#141c2e;--border:#1e2840;--purple:#9146ff;--pd:#7b2fff;--pg:rgba(145,70,255,.12);--green:#0dffc8;--red:#ff4757;--text:#c8d4f0;--muted:#4a5778}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:'Syne',sans-serif}
body{background-image:linear-gradient(rgba(145,70,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(145,70,255,.03) 1px,transparent 1px);background-size:32px 32px;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:1.5rem}
.card{width:100%;max-width:420px;background:var(--surf);border:1px solid var(--border);border-radius:20px;padding:2.25rem 2rem;box-shadow:0 24px 80px rgba(0,0,0,.5)}
.logo{display:flex;align-items:center;gap:.75rem;margin-bottom:2rem}
.logo-icon{width:42px;height:42px;background:var(--purple);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.3rem;box-shadow:0 0 24px rgba(145,70,255,.45);flex-shrink:0}
.logo h1{font-size:1.2rem;font-weight:800;color:#fff}.logo span{font-size:.68rem;color:var(--muted);font-family:'Space Mono',monospace;display:block}
.tabs{display:flex;margin-bottom:1.75rem;background:var(--surf2);border-radius:10px;padding:3px}
.tab{flex:1;padding:.55rem;text-align:center;border-radius:8px;font-size:.85rem;font-weight:700;cursor:pointer;color:var(--muted);border:none;background:none;font-family:'Syne',sans-serif;transition:all .2s}
.tab.active{background:var(--border);color:var(--text)}
.field{display:flex;flex-direction:column;gap:.45rem;margin-bottom:1rem}
label{font-size:.78rem;font-weight:600;color:#7a8cb0}
input{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text);font-family:'Space Mono',monospace;font-size:.82rem;padding:.72rem 1rem;outline:none;transition:border-color .2s,box-shadow .2s}
input:focus{border-color:var(--purple);box-shadow:0 0 0 3px var(--pg)}
.hint{font-size:.7rem;color:var(--muted);font-family:'Space Mono',monospace;line-height:1.5;margin-top:-.25rem}
.btn{width:100%;padding:.9rem;border-radius:12px;border:none;background:var(--purple);color:#fff;font-family:'Syne',sans-serif;font-size:1rem;font-weight:700;cursor:pointer;margin-top:.5rem;transition:all .2s;box-shadow:0 4px 20px rgba(145,70,255,.35)}
.btn:hover:not(:disabled){background:var(--pd);transform:translateY(-1px)}.btn:disabled{opacity:.4;cursor:not-allowed}
.alert{border-radius:10px;padding:.7rem 1rem;font-family:'Space Mono',monospace;font-size:.78rem;display:none;margin-top:.75rem;line-height:1.5}
.alert.err{background:rgba(255,71,87,.1);border:1px solid rgba(255,71,87,.3);color:var(--red)}
.alert.ok{background:rgba(13,255,200,.08);border:1px solid rgba(13,255,200,.2);color:var(--green)}
.alert.show{display:block}
.fs{display:none}.fs.active{display:block}
</style></head><body>
<div class="card">
  <div class="logo"><div class="logo-icon">🤖</div><div><h1>TwitchBot Panel</h1><span>Multi-canal · 24/7</span></div></div>
  <div class="tabs">
    <button class="tab {% if mode=='login' %}active{% endif %}" id="tL" onclick="sw('login')">Connexion</button>
    <button class="tab {% if mode=='register' %}active{% endif %}" id="tR" onclick="sw('register')">Inscription</button>
  </div>
  <div class="fs {% if mode=='login' %}active{% endif %}" id="fL">
    <div class="field"><label>Nom d'utilisateur</label><input type="text" id="lU" placeholder="ton_pseudo" autocomplete="username"></div>
    <div class="field"><label>Mot de passe</label><input type="password" id="lP" placeholder="••••••••" onkeydown="if(event.key==='Enter')login()"></div>
    <button class="btn" id="bL" onclick="login()">Se connecter</button>
    <div class="alert" id="aL"></div>
  </div>
  <div class="fs {% if mode=='register' %}active{% endif %}" id="fR">
    <div class="field"><label>Nom d'utilisateur (panel)</label><input type="text" id="rU" placeholder="ton_pseudo"></div>
    <div class="field"><label>Mot de passe</label><input type="password" id="rP" placeholder="6 caractères minimum"></div>
    <div class="field"><label>Ton canal Twitch</label><input type="text" id="rC" placeholder="nom_du_canal (sans #)" onkeydown="if(event.key==='Enter')register()">
    <p class="hint">Tu devras taper <code style="background:var(--surf2);padding:1px 5px;border-radius:4px">!addbot</code> dans ton chat pour activer le bot.</p></div>
    <button class="btn" id="bR" onclick="register()">Créer mon compte</button>
    <div class="alert" id="aR"></div>
  </div>
</div>
<script>
function sw(m){
  document.getElementById('fL').classList.toggle('active',m==='login');
  document.getElementById('fR').classList.toggle('active',m==='register');
  document.getElementById('tL').classList.toggle('active',m==='login');
  document.getElementById('tR').classList.toggle('active',m==='register');
  history.replaceState(null,'',m==='login'?'/login':'/register');
}
function alert_(id,msg,type){const e=document.getElementById(id);e.textContent=msg;e.className='alert '+type+' show';}
async function login(){
  const b=document.getElementById('bL');b.disabled=true;b.textContent='Connexion...';
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('lU').value,password:document.getElementById('lP').value})});
  const d=await r.json();
  if(r.ok){window.location.href='/dashboard';}else{alert_('aL','❌ '+d.error,'err');b.disabled=false;b.textContent='Se connecter';}
}
async function register(){
  const b=document.getElementById('bR');b.disabled=true;b.textContent='Création...';
  const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('rU').value,password:document.getElementById('rP').value,channel:document.getElementById('rC').value})});
  const d=await r.json();
  if(r.ok){window.location.href='/dashboard';}else{alert_('aR','❌ '+d.error,'err');b.disabled=false;b.textContent='Créer mon compte';}
}
</script></body></html>"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TwitchBot — Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#080c14;--surf:#0f1520;--surf2:#141c2e;--border:#1e2840;--purple:#9146ff;--pd:#7b2fff;--pg:rgba(145,70,255,.12);--green:#0dffc8;--red:#ff4757;--yellow:#ffcc00;--text:#c8d4f0;--muted:#4a5778}
html,body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif}
body{background-image:linear-gradient(rgba(145,70,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(145,70,255,.03) 1px,transparent 1px);background-size:32px 32px;min-height:100vh}
.shell{max-width:920px;margin:0 auto;padding:2rem 1.5rem 4rem}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;padding-bottom:1.5rem;border-bottom:1px solid var(--border)}
.logo{display:flex;align-items:center;gap:.75rem}
.logo-icon{width:40px;height:40px;background:var(--purple);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.3rem;box-shadow:0 0 24px rgba(145,70,255,.45)}
.logo h1{font-size:1.2rem;font-weight:800;color:#fff}.logo sub{font-size:.68rem;color:var(--muted);font-family:'Space Mono',monospace;display:block}
.hright{display:flex;align-items:center;gap:.6rem}
.upill{font-family:'Space Mono',monospace;font-size:.75rem;color:var(--muted);background:var(--surf);border:1px solid var(--border);border-radius:999px;padding:.35rem .85rem}
.upill strong{color:var(--text)}
.blgout{background:none;border:1px solid var(--border);border-radius:8px;padding:.35rem .75rem;color:var(--muted);font-size:.72rem;cursor:pointer;font-family:'Space Mono',monospace;transition:all .2s}
.blgout:hover{border-color:var(--red);color:var(--red)}
.card{background:var(--surf);border:1px solid var(--border);border-radius:16px;padding:1.75rem;margin-bottom:1.25rem}
.ctitle{font-size:.63rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-family:'Space Mono',monospace;margin-bottom:1.25rem}
.banner{border-radius:14px;padding:1.25rem 1.5rem;display:flex;align-items:flex-start;gap:1rem;margin-bottom:1.25rem;border:1px solid}
.banner.pending{background:rgba(255,204,0,.06);border-color:rgba(255,204,0,.25)}
.banner.active{background:rgba(13,255,200,.06);border-color:rgba(13,255,200,.2)}
.banner.idle{background:rgba(74,87,120,.08);border-color:var(--border)}
.bicon{font-size:1.75rem;flex-shrink:0;margin-top:.1rem}
.btitle{font-size:1rem;font-weight:700;color:#fff;margin-bottom:.3rem}
.bdesc{font-size:.82rem;color:var(--muted);line-height:1.6}
code{font-family:'Space Mono',monospace;background:var(--surf2);border:1px solid var(--border);padding:1px 7px;border-radius:5px;font-size:.82rem;color:var(--text)}
.steps{margin-top:.75rem;display:flex;flex-direction:column;gap:.55rem}
.si{display:flex;align-items:flex-start;gap:.75rem;font-size:.82rem;color:var(--muted);line-height:1.5}
.sn{width:22px;height:22px;border-radius:50%;border:1px solid var(--purple);display:flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:700;font-family:'Space Mono',monospace;flex-shrink:0;margin-top:1px;color:var(--purple)}
.cmds{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
@media(max-width:560px){.cmds{grid-template-columns:1fr}}
.cmd{background:var(--surf2);border:1px solid var(--border);border-radius:12px;padding:1rem 1.25rem}
.cname{font-family:'Space Mono',monospace;font-size:.9rem;font-weight:700;color:var(--purple);margin-bottom:.3rem}
.cdesc{font-size:.78rem;color:var(--muted);line-height:1.5}
.lhdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem}
.lterm{background:#04070f;border:1px solid var(--border);border-radius:12px;height:240px;overflow-y:auto;padding:1rem;font-family:'Space Mono',monospace;font-size:.78rem;line-height:1.9}
.lterm::-webkit-scrollbar{width:4px}.lterm::-webkit-scrollbar-thumb{background:var(--border);border-radius:99px}
.ll{display:flex;gap:.75rem}.lt{color:var(--muted);flex-shrink:0}
.ll.info .lm{color:var(--text)}.ll.success .lm{color:var(--green)}.ll.error .lm{color:var(--red)}.ll.warning .lm{color:var(--yellow)}.ll.command .lm{color:var(--purple);font-weight:700}
.lempty{color:var(--muted);font-style:italic;text-align:center;padding-top:1.5rem;font-family:'Space Mono',monospace;font-size:.78rem}
.lcnt{font-family:'Space Mono',monospace;font-size:.72rem;color:var(--muted)}
.bclr{background:none;border:none;color:var(--muted);font-family:'Space Mono',monospace;font-size:.72rem;cursor:pointer;padding:.25rem .6rem;border-radius:6px}
.bclr:hover{background:var(--border);color:var(--text)}
.abadge{font-size:.65rem;font-family:'Space Mono',monospace;background:var(--pg);border:1px solid rgba(145,70,255,.3);color:var(--purple);border-radius:999px;padding:2px 9px;margin-left:.5rem;vertical-align:middle}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
@media(max-width:580px){.g2{grid-template-columns:1fr}}
.field{display:flex;flex-direction:column;gap:.45rem;margin-bottom:.9rem}
label{font-size:.78rem;font-weight:600;color:#7a8cb0}
input,textarea{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:10px;color:var(--text);font-family:'Space Mono',monospace;font-size:.82rem;padding:.7rem 1rem;outline:none;transition:border-color .2s,box-shadow .2s}
input:focus,textarea:focus{border-color:var(--purple);box-shadow:0 0 0 3px var(--pg)}
textarea{resize:vertical;min-height:65px;line-height:1.5}
.hint{font-size:.7rem;color:var(--muted);font-family:'Space Mono',monospace}
.btn{padding:.7rem 1.25rem;border-radius:10px;border:none;font-family:'Syne',sans-serif;font-size:.85rem;font-weight:700;cursor:pointer;transition:all .2s;display:inline-flex;align-items:center;gap:.4rem}
.bprimary{background:var(--purple);color:#fff;box-shadow:0 4px 16px rgba(145,70,255,.3)}.bprimary:hover:not(:disabled){background:var(--pd);transform:translateY(-1px)}
.bdanger{background:transparent;border:1px solid rgba(255,71,87,.3);color:var(--red)}.bdanger:hover:not(:disabled){background:rgba(255,71,87,.1)}
.bghost{background:transparent;border:1px solid var(--border);color:var(--muted)}.bghost:hover:not(:disabled){border-color:var(--text);color:var(--text)}
.btn:disabled{opacity:.35;cursor:not-allowed;transform:none}
.ctrls{display:flex;gap:.75rem;flex-wrap:wrap;margin-top:.75rem}
.alrt{border-radius:9px;padding:.65rem .9rem;font-family:'Space Mono',monospace;font-size:.78rem;display:none;margin-top:.75rem}
.alrt.err{background:rgba(255,71,87,.1);border:1px solid rgba(255,71,87,.3);color:var(--red)}
.alrt.ok{background:rgba(13,255,200,.08);border:1px solid rgba(13,255,200,.2);color:var(--green)}.alrt.show{display:block}
.bstatus{display:flex;align-items:center;gap:.6rem;padding:.4rem .85rem;border-radius:999px;border:1px solid var(--border);background:var(--surf2);font-size:.75rem;font-family:'Space Mono',monospace;color:var(--muted)}
.bstatus.on{border-color:rgba(13,255,200,.3);color:var(--green)}
.bdot{width:7px;height:7px;border-radius:50%;background:var(--muted)}
.bstatus.on .bdot{background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.75)}}
.utbl{width:100%;border-collapse:collapse;font-size:.82rem}
.utbl th{text-align:left;padding:.6rem .75rem;font-size:.63rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-family:'Space Mono',monospace;border-bottom:1px solid var(--border)}
.utbl td{padding:.65rem .75rem;border-bottom:1px solid rgba(30,40,64,.5);vertical-align:middle}
.utbl tr:last-child td{border-bottom:none}.utbl tr:hover td{background:var(--surf2)}
.spill{font-family:'Space Mono',monospace;font-size:.7rem;padding:2px 9px;border-radius:999px;border:1px solid}
.spill.active{background:rgba(13,255,200,.08);border-color:rgba(13,255,200,.25);color:var(--green)}
.spill.pending{background:rgba(255,204,0,.08);border-color:rgba(255,204,0,.25);color:var(--yellow)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:3px}
.dot.on{background:var(--green);box-shadow:0 0 6px var(--green)}.dot.off{background:var(--muted)}
.bsm{padding:.28rem .6rem;font-size:.72rem;border-radius:7px}
#adm{display:none}
</style></head>
<body><div class="shell">
<header>
  <div class="logo"><div class="logo-icon">🤖</div><div><h1>TwitchBot Panel</h1><sub>Multi-canal · 24/7</sub></div></div>
  <div class="hright">
    <div class="upill">Connecté : <strong id="hU">...</strong></div>
    <button class="blgout" onclick="location.href='/logout'">Déconnexion</button>
  </div>
</header>

<div id="banner" class="banner idle"><div class="bicon" id="bico">⏳</div><div><div class="btitle" id="btit">Chargement...</div><div class="bdesc" id="bdesc"></div></div></div>

<div class="card" id="cmdCard" style="display:none">
  <div class="ctitle">⚡ Commandes disponibles</div>
  <div class="cmds">
    <div class="cmd"><div class="cname">!lurk</div><div class="cdesc">Le viewer annonce qu'il passe en mode lurk. Le bot envoie le message personnalisé.</div></div>
    <div class="cmd"><div class="cname">!unlurk</div><div class="cdesc">Le viewer annonce son retour du lurk. Le bot le souhaite la bienvenue.</div></div>
  </div>
</div>

<div class="card">
  <div class="lhdr"><div class="ctitle" style="margin:0">📡 Journal de ton canal</div><div style="display:flex;gap:.5rem;align-items:center"><span class="lcnt" id="lCnt">0 entrée(s)</span><button class="bclr" onclick="clrLog()">Effacer</button></div></div>
  <div class="lterm" id="lTerm"><div class="lempty">Aucune activité pour l'instant...</div></div>
</div>

<div id="adm">
  <div class="card">
    <div class="ctitle">🔧 Config du bot <span class="abadge">ADMIN</span></div>
    <div class="g2">
      <div class="field"><label>Token OAuth du bot</label><input type="password" id="aTok" placeholder="oauth:xxxxxxxxxxxxxxxx"><p class="hint"><a href="https://twitchtokengenerator.com" target="_blank" style="color:var(--purple)">twitchtokengenerator.com</a> — scopes : chat:read + chat:edit</p></div>
      <div>
        <div class="field"><label>Message !lurk</label><textarea id="aLurk" rows="2"></textarea></div>
        <div class="field"><label>Message !unlurk</label><textarea id="aUnlurk" rows="2"></textarea></div>
      </div>
    </div>
    <button class="btn bprimary" onclick="saveConf()">💾 Sauvegarder</button>
    <div class="alrt" id="alConf"></div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem">
      <div class="ctitle" style="margin:0">🎛️ Contrôle du bot <span class="abadge">ADMIN</span></div>
      <div class="bstatus" id="bsBadge"><div class="bdot"></div><span id="bsTxt">Hors ligne</span></div>
    </div>
    <div class="ctrls">
      <button class="btn bprimary" id="btnSt" onclick="startBot()">▶ Démarrer</button>
      <button class="btn bdanger"  id="btnSp" onclick="stopBot()" disabled>⏹ Arrêter</button>
    </div>
    <div class="alrt" id="alBot"></div>
  </div>

  <div class="card">
    <div class="ctitle">👥 Utilisateurs <span class="abadge">ADMIN</span></div>
    <table class="utbl"><thead><tr><th>Utilisateur</th><th>Canal</th><th>Statut</th><th>Bot</th><th></th></tr></thead>
    <tbody id="uTbody"><tr><td colspan="5" style="text-align:center;color:var(--muted);padding:1rem;font-family:'Space Mono',monospace;font-size:.78rem">Chargement...</td></tr></tbody></table>
  </div>

  <div class="card">
    <div class="lhdr"><div class="ctitle" style="margin:0">📡 Journal complet <span class="abadge">ADMIN</span></div><div style="display:flex;gap:.5rem;align-items:center"><span class="lcnt" id="alCnt">0 entrée(s)</span><button class="bclr" onclick="clrAdm()">Effacer</button></div></div>
    <div class="lterm" id="alTerm"><div class="lempty">En attente...</div></div>
  </div>
</div>
</div>

<script>
let seenL=0,seenA=0,isAdmin=false;
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function alrt(id,msg,type){const e=document.getElementById(id);e.textContent=msg;e.className='alrt '+type+' show';setTimeout(()=>e.classList.remove('show'),5000);}

function renderBanner(d){
  const bn=document.getElementById('banner'),ic=document.getElementById('bico'),tt=document.getElementById('btit'),ds=document.getElementById('bdesc');
  document.getElementById('cmdCard').style.display='none';
  document.getElementById('banner').querySelector('.bicon').parentElement.querySelector('#bdesc').innerHTML='';
  const old=document.getElementById('actSteps');if(old)old.remove();
  if(d.status==='active'&&d.connected){
    bn.className='banner active';ic.textContent='✅';tt.textContent='Bot actif sur #'+d.channel;
    ds.innerHTML='Le bot est connecté. Commandes <code>!lurk</code> et <code>!unlurk</code> disponibles dans ton chat.';
    document.getElementById('cmdCard').style.display='block';
  } else if(d.status==='active'){
    bn.className='banner idle';ic.textContent='🔄';tt.textContent='Connexion en cours sur #'+d.channel;
    ds.innerHTML='Le bot rejoint ton canal...';
  } else if(d.status==='pending'){
    bn.className='banner pending';ic.textContent='⏳';tt.textContent='Activation requise — #'+d.channel;
    ds.innerHTML='Tape <code>!addbot</code> dans ton chat Twitch pour activer le bot.';
    const st=document.createElement('div');st.id='actSteps';st.className='steps';
    st.innerHTML='<div class="si"><div class="sn">1</div><span>Ouvre ton chat Twitch sur <strong style="color:var(--text)">twitch.tv/'+esc(d.channel)+'</strong></span></div><div class="si"><div class="sn">2</div><span>Tape dans le chat : <code>!addbot</code></span></div><div class="si"><div class="sn">3</div><span>Cette page se mettra à jour automatiquement ✅</span></div>';
    ds.after(st);
  } else {
    bn.className='banner idle';ic.textContent='❓';tt.textContent='Statut inconnu';
  }
}

function renderLogs(logs,termId,cntId,seen){
  if(!logs||!logs.length) return seen;
  const t=document.getElementById(termId),atB=t.scrollHeight-t.scrollTop<=t.clientHeight+40;
  const empty=t.querySelector('.lempty');if(empty)empty.remove();
  logs.slice(seen).forEach(l=>{const d=document.createElement('div');d.className='ll '+(l.level||'info');d.innerHTML='<span class="lt">'+l.time+'</span><span class="lm">'+esc(l.msg)+'</span>';t.appendChild(d);});
  seen=logs.length;document.getElementById(cntId).textContent=seen+' entrée(s)';
  if(atB)t.scrollTop=t.scrollHeight;return seen;
}
function clrLog(){document.getElementById('lTerm').innerHTML='<div class="lempty">Journal effacé.</div>';seenL=0;document.getElementById('lCnt').textContent='0 entrée(s)';}
function clrAdm(){document.getElementById('alTerm').innerHTML='<div class="lempty">Journal effacé.</div>';seenA=0;document.getElementById('alCnt').textContent='0 entrée(s)';}

function renderUsers(users,running){
  const tb=document.getElementById('uTbody');tb.innerHTML='';
  users.forEach(u=>{const tr=document.createElement('tr');
    tr.innerHTML='<td style="font-family:\'Space Mono\',monospace;color:var(--text)">'+(u.admin?'👑 ':'')+esc(u.username)+'</td><td style="color:var(--purple);font-family:\'Space Mono\',monospace">#'+esc(u.channel)+'</td><td><span class="spill '+u.status+'">'+u.status+'</span></td><td><span class="dot '+(u.connected?'on':'off')+'"></span>'+(u.connected?'Connecté':'Hors ligne')+'</td><td>'+(u.admin?'':'<button class="btn bdanger bsm" onclick="rmUser(\''+u.username+'\')">✕</button>')+'</td>';
    tb.appendChild(tr);});
  const bs=document.getElementById('bsBadge'),bt=document.getElementById('bsTxt');
  if(running){bs.className='bstatus on';bt.textContent='En ligne';document.getElementById('btnSt').disabled=true;document.getElementById('btnSp').disabled=false;}
  else{bs.className='bstatus';bt.textContent='Hors ligne';document.getElementById('btnSt').disabled=false;document.getElementById('btnSp').disabled=true;}
}

async function rmUser(u){if(!confirm('Supprimer '+u+' ?'))return;const r=await fetch('/api/admin/user/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u})});if(!r.ok){const d=await r.json();alert(d.error);}else poll();}
async function saveConf(){
  const r=await fetch('/api/admin/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bot_token:document.getElementById('aTok').value||undefined,lurk_message:document.getElementById('aLurk').value,unlurk_message:document.getElementById('aUnlurk').value})});
  const d=await r.json();r.ok?alrt('alConf','✅ Sauvegardé !','ok'):alrt('alConf','❌ '+d.error,'err');
}
async function startBot(){
  document.getElementById('btnSt').disabled=true;document.getElementById('btnSt').textContent='⏳...';
  const r=await fetch('/api/admin/bot/start',{method:'POST'});const d=await r.json();
  if(!r.ok){alrt('alBot','❌ '+(d.error||'Erreur'),'err');document.getElementById('btnSt').disabled=false;document.getElementById('btnSt').textContent='▶ Démarrer';}
  else{alrt('alBot','✅ Démarrage...','ok');setTimeout(poll,1500);}
}
async function stopBot(){document.getElementById('btnSp').disabled=true;await fetch('/api/admin/bot/stop',{method:'POST'});setTimeout(poll,1200);}

async function loadConf(){try{const d=await fetch('/api/admin/config').then(r=>r.json());if(d.lurk_message)document.getElementById('aLurk').value=d.lurk_message;if(d.unlurk_message)document.getElementById('aUnlurk').value=d.unlurk_message;}catch(_){}}

async function poll(){
  try{
    const me=await fetch('/api/me').then(r=>r.json());
    document.getElementById('hU').textContent=me.username;
    renderBanner(me);
    seenL=renderLogs(me.logs,'lTerm','lCnt',seenL);
    if(me.admin){
      document.getElementById('adm').style.display='block';
      const ad=await fetch('/api/admin/users').then(r=>r.json());
      renderUsers(ad.users,ad.bot_running);
      seenA=renderLogs(ad.logs,'alTerm','alCnt',seenA);
    }
  }catch(_){}
}

poll();setInterval(poll,3000);setTimeout(loadConf,600);
</script></body></html>"""

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'username' in session else url_for('login_page'))

@app.route('/login')
def login_page():
    if 'username' in session: return redirect(url_for('dashboard'))
    return render_template_string(AUTH_HTML, mode='login')

@app.route('/register')
def register_page():
    if 'username' in session: return redirect(url_for('dashboard'))
    return render_template_string(AUTH_HTML, mode='register')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login_page'))

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username','').strip().lower()
    users = load_users(); user = users.get(username)
    if user and check_password_hash(user['password'], data.get('password','')):
        session['username'] = username
        return jsonify({'status':'ok','admin':user.get('admin',False)})
    return jsonify({'error':'Identifiants incorrects'}), 401

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    username = data.get('username','').strip().lower()
    password = data.get('password','')
    channel  = data.get('channel','').strip().lower().lstrip('#')
    if not all([username, password, channel]):
        return jsonify({'error':'Tous les champs sont requis'}), 400
    if len(username) < 3: return jsonify({'error':"Nom trop court (3 min)"}), 400
    if len(password) < 6: return jsonify({'error':'Mot de passe trop court (6 min)'}), 400
    users = load_users()
    if username in users: return jsonify({'error':"Nom d'utilisateur déjà pris"}), 400
    if any(d.get('channel','').lower()==channel for d in users.values()):
        return jsonify({'error':'Ce canal est déjà enregistré'}), 400
    is_admin = len(users) == 0
    users[username] = {'password':generate_password_hash(password),'channel':channel,'status':'pending','admin':is_admin,'created_at':datetime.now().isoformat()}
    save_users(users); session['username'] = username
    if bot_running: join_live(channel)
    else: start_bot()
    add_log(f'Inscription : {username} → #{channel}', 'info', channel)
    return jsonify({'status':'ok','admin':is_admin})

@app.route('/api/me')
@login_required
def api_me():
    users = load_users(); user = users.get(session['username'],{})
    ch = user.get('channel','')
    conn = [c.name.lower() for c in bot_instance.connected_channels] if bot_instance and bot_running else []
    return jsonify({'username':session['username'],'channel':ch,'status':user.get('status','pending'),'admin':user.get('admin',False),'connected':ch.lower() in conn,'bot_running':bot_running,'logs':[l for l in logs[-40:] if not l['channel'] or l['channel'].lower()==ch.lower() or user.get('admin')]})

@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    users = load_users()
    running = bot_running and bot_thread and bot_thread.is_alive()
    conn = [c.name.lower() for c in bot_instance.connected_channels] if bot_instance and running else []
    result = [{'username':u,'channel':d.get('channel',''),'status':d.get('status','pending'),'connected':d.get('channel','').lower() in conn,'admin':d.get('admin',False)} for u,d in users.items()]
    return jsonify({'users':result,'bot_running':running,'logs':logs[-60:]})

@app.route('/api/admin/config', methods=['GET','POST'])
@admin_required
def api_admin_config():
    global config
    if request.method == 'POST':
        data = request.get_json() or {}
        if data.get('bot_token'): config['bot_token'] = data['bot_token']
        if data.get('lurk_message'): config['lurk_message'] = data['lurk_message']
        if data.get('unlurk_message'): config['unlurk_message'] = data['unlurk_message']
        save_config(config); return jsonify({'status':'saved'})
    return jsonify({**config, 'bot_token':'●'*24 if config['bot_token'] else ''})

@app.route('/api/admin/bot/start', methods=['POST'])
@admin_required
def api_bot_start():
    if not config.get('bot_token'): return jsonify({'error':'Token bot manquant'}), 400
    start_bot(); return jsonify({'status':'starting'})

@app.route('/api/admin/bot/stop', methods=['POST'])
@admin_required
def api_bot_stop():
    global bot_instance, bot_loop, bot_running
    if bot_instance and bot_loop and not bot_loop.is_closed():
        asyncio.run_coroutine_threadsafe(bot_instance.close(), bot_loop)
        add_log('Bot arrêté par admin', 'warning')
    else: bot_running = False
    return jsonify({'status':'stopping'})

@app.route('/api/admin/user/remove', methods=['POST'])
@admin_required
def api_remove_user():
    data = request.get_json() or {}
    target = data.get('username','').lower()
    users = load_users()
    if target not in users: return jsonify({'error':'Introuvable'}), 404
    if users[target].get('admin'): return jsonify({'error':'Impossible de supprimer un admin'}), 400
    ch = users[target].get('channel','')
    del users[target]; save_users(users)
    if bot_instance and bot_loop and bot_running and not bot_loop.is_closed() and ch:
        asyncio.run_coroutine_threadsafe(bot_instance.part_channels([ch]), bot_loop)
    add_log(f'Utilisateur supprimé : {target}', 'warning')
    return jsonify({'status':'removed'})

if __name__ == '__main__':
    if config.get('bot_token') and _get_channels():
        threading.Timer(2.0, start_bot).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
