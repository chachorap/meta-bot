import os, time, threading, random
from dotenv import load_dotenv
from flask import Flask, jsonify
import telebot
from telebot import types

# =====================
# Config
# =====================
load_dotenv()
TG_TOKEN = os.getenv("TG_TOKEN")
if not TG_TOKEN:
    raise RuntimeError("Falta TG_TOKEN en variables de entorno")

bot = telebot.TeleBot(TG_TOKEN, parse_mode=None)  # sin parse_mode global
DEFAULT_BUDGET = 80_000
PURGE_WINDOW = 120  # cuántos mensajes hacia atrás intentar borrar en grupos

# Estado mínimo por chat
S = {}  # {chat_id: {"step": str, "budget": int, "line":..., "title":..., "desc":..., "media":..., "outbox":[ids] }}

# =====================
# Helpers
# =====================
def st(cid):
    """Obtiene/crea estado mínimo por chat."""
    if cid not in S:
        S[cid] = {"step": "line", "budget": DEFAULT_BUDGET, "outbox": []}
    return S[cid]

def send(cid, text, **kwargs):
    """Envía y guarda message_id para poder limpiarlo luego con /reset."""
    m = bot.send_message(cid, text, **kwargs)
    st(cid)["outbox"].append(m.message_id)
    return m

def clean_private(cid):
    """En chat privado: solo borra mensajes del bot (limitación de Telegram)."""
    state = st(cid)
    deleted = 0
    for mid in state.get("outbox", []):
        try:
            bot.delete_message(cid, mid)
            deleted += 1
        except Exception:
            pass
    S[cid] = {"step": "line", "budget": DEFAULT_BUDGET, "outbox": []}
    send(cid, f"🧹 Limpié {deleted} mensajes del bot. Por seguridad de Telegram, no puedo borrar tus mensajes en chats privados.\nEscribe la **Línea de Producto** (ej: short, conjunto).")

def bot_is_admin(chat_id):
    """Devuelve (es_admin, puede_borrar) si el bot es admin en el chat."""
    try:
        me = bot.get_me()
        admins = bot.get_chat_administrators(chat_id)
        for a in admins:
            if a.user.id == me.id:
                return True, getattr(a, "can_delete_messages", True)
        return False, False
    except Exception:
        return False, False

def purge_group(chat_id, from_message_id, n=PURGE_WINDOW):
    """Intenta borrar los últimos n mensajes (del bot y de usuarios) en grupos/supergrupos/canales."""
    deleted = 0
    start_id = max(1, from_message_id - n)
    for mid in range(from_message_id, start_id - 1, -1):
        try:
            bot.delete_message(chat_id, mid)
            deleted += 1
        except Exception:
            pass
    return deleted

def variations(title, desc):
    """Genera 2 variaciones simples de título y descripción."""
    emojis = ["🔥", "⚡", "🏃‍♀️", "💥", "✅", "✨", "🎯"]
    hooks = ["Edición limitada", "Últimas unidades", "Llévalo hoy", "Nueva colección", "Calidad premium"]
    t2 = f"{random.choice(emojis)} {title} | {random.choice(hooks)}"
    t3 = f"{title} {random.choice(['al mejor precio','lista para entrenar','que sí rinde'])} {random.choice(emojis)}"
    d2 = f"{desc} {random.choice(['Disponible en tallas S-XL.', 'Envíos a todo el país.', 'Pago contra entrega.'])}"
    d3 = f"{random.choice(['Confort y rendimiento.', 'Diseño que destaca.', 'Te acompaña en cada entrenamiento.'])} {desc}"
    return t2, t3, d2, d3

def summarize(cid):
    """Envia el resumen de 3 anuncios simulados."""
    state = st(cid)
    line  = state.get("line", "(sin línea)")
    title = state.get("title", "(sin título)")
    desc  = state.get("desc", "(sin descripción)")
    media = state.get("media", "📷 (sin archivo detectado)")
    budget = state.get("budget", DEFAULT_BUDGET)
    t2, t3, d2, d3 = variations(title, desc)

    send(cid,
        f"🤖 (Simulación)\nPublicaría 3 anuncios en 'Línea - {str(line).capitalize()}':\n\n"
        f"🖼️ Media: {media}\n\n"
        f"1️⃣ {title} — {desc}\n"
        f"2️⃣ {t2} — {d2}\n"
        f"3️⃣ {t3} — {d3}\n\n"
        f"💰 Presupuesto: {budget:,} COP\n"
        "Opción: Simulación IA 🧠"
    )

# =====================
# Comandos
# =====================
@bot.message_handler(commands=['start', 'star'])
def cmd_start(m):
    cid = m.chat.id
    st(cid)  # inicializa
    S[cid]["step"] = "line"
    send(cid, "👋 Bienvenido (simulación IA).\nEscribe la **Línea de Producto** (ej: short, conjunto).")

@bot.message_handler(commands=['reset'])
def cmd_reset(m):
    cid = m.chat.id
    chat_type = getattr(m.chat, "type", "private")
    if chat_type in ("group", "supergroup", "channel"):
        is_admin, can_delete = bot_is_admin(cid)
        if is_admin and can_delete:
            deleted = purge_group(cid, m.message_id, n=PURGE_WINDOW)
            S[cid] = {"step": "line", "budget": DEFAULT_BUDGET, "outbox": []}
            send(cid, f"🧹 Chat limpiado. Intenté borrar los últimos {PURGE_WINDOW} mensajes. Eliminados: {deleted}.\nEscribe la **Línea de Producto** (ej: short, conjunto).")
        else:
            clean_private(cid)
    else:
        clean_private(cid)

@bot.message_handler(commands=['budget'])
def cmd_budget(m):
    cid = m.chat.id
    try:
        _, value = m.text.split(' ', 1)
        value = int(value.strip().replace('.', '').replace(',', ''))
        st(cid)["budget"] = value
        send(cid, f"💰 Presupuesto actualizado a {value:,} COP.")
    except Exception:
        bot.send_message(cid, "Formato incorrecto. Ejemplo: `/budget 120000`", parse_mode="Markdown")

@bot.message_handler(commands=['sim'])
def cmd_sim(m):
    """
    Uso: /sim linea | titulo | descripcion | media(opcional)
    Ejemplo:
    /sim conjuntos running | 3 conjuntos por 75 mil | Envío gratis. Pago contraentrega. Tallas S-XL. | https://miimagen.jpg
    """
    cid = m.chat.id
    payload = m.text.split(' ', 1)
    if len(payload) < 2:
        send(cid, "Formato: /sim linea | titulo | descripcion | media(opcional)")
        return
    parts = [p.strip() for p in payload[1].split('|')]
    if len(parts) < 3:
        send(cid, "Necesito al menos: linea | titulo | descripcion")
        return
    S[cid] = {"step": "done", "budget": st(cid)["budget"], "outbox": [],
              "line": parts[0], "title": parts[1], "desc": parts[2],
              "media": parts[3] if len(parts) >= 4 else "📷 (sin archivo detectado)"}
    summarize(cid)

# =====================
# Flujo conversacional
# =====================
@bot.message_handler(content_types=['photo','video'])
def media_handler(m):
    cid = m.chat.id
    state = st(cid)
    if state.get("step") == "media":
        if m.photo:
            state["media"] = f"photo:{m.photo[-1].file_id}"
        elif m.video:
            state["media"] = f"video:{m.video.file_id}"
        send(cid, "Perfecto 👍\nAhora escribe el **Título Base** para el anuncio:")
        state["step"] = "title"

# IGNORAR comandos en el handler genérico para evitar duplicados
@bot.message_handler(content_types=['text'], func=lambda m: not (m.text or '').startswith('/'))
def text_handler(m):
    cid = m.chat.id
    txt = m.text.strip()
    state = st(cid)
    step = state.get("step", "line")

    if step == "line":
        state["line"] = txt
        exists = random.choice([True, False])
        adset = f"Línea - {txt.capitalize()}"
        if exists:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("Opción A: Agregar", callback_data="opt_A"),
                   types.InlineKeyboardButton("Opción B: Reemplazar", callback_data="opt_B"))
            send(cid, f"🔎 (Simulación) Existe '{adset}'. ¿Qué deseas hacer?", reply_markup=kb)
            state["step"] = "choose_option"
        else:
            state["option"] = "A"
            send(cid, f"🆕 (Simulación) Crearé '{adset}' con presupuesto {state['budget']:,} COP.")
            send(cid, "Por favor envía la **imagen o video del producto**.")
            state["step"] = "media"

    elif step == "media":
        state["media"] = txt
        send(cid, "Perfecto 👍\nAhora escribe la **Descripción Base**.")
        state["step"] = "desc" if state.get("title") else "title"

    elif step == "title":
        state["title"] = txt
        send(cid, "Excelente 👌\nAhora escribe la **Descripción Base**.")
        state["step"] = "desc"

    elif step == "desc":
        state["desc"] = txt
        summarize(cid)

@bot.callback_query_handler(func=lambda c: c.data in ["opt_A", "opt_B"])
def on_choice(c):
    cid = c.message.chat.id
    state = st(cid)
    state["option"] = "A" if c.data == "opt_A" else "B"
    bot.answer_callback_query(c.id, "Opción registrada")
    send(cid, "Genial 👍\nPor favor envía la **imagen o video del producto**.")
    state["step"] = "media"

# =====================
# Polling + Flask
# =====================
def run_polling():
    while True:
        try:
            bot.polling(timeout=30, long_polling_timeout=25, allowed_updates=["message","callback_query"])
        except Exception as e:
            print("⚠️ Polling error:", repr(e))
            time.sleep(5)

app = Flask(__name__)

@app.get("/")
def root():
    return "OK", 200

@app.get("/healthz")
def healthz():
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    threading.Thread(target=run_polling, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
