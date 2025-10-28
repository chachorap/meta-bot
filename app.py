import os, time, threading, random, json
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

DATA_FILE = os.getenv("DATA_FILE", "data.json")  # archivo json para persistencia simple
bot = telebot.TeleBot(TG_TOKEN, parse_mode=None)
DEFAULT_BUDGET = 80_000
PURGE_WINDOW = 120

# =====================
# Estado y Persistencia
# =====================
# S[cid] = {"step":..., "budget":..., "outbox":[...], "store": { line: {"ads":[{"title","desc","media","msg","cpm","spent"}]}},
#           "line":..., "title":..., "desc":..., "media":..., "option":... }
S = {}

def load_all():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # data = {str(cid): {"store": {...}}}
        for k, v in data.items():
            cid = int(k)
            S[cid] = S.get(cid, {"step": "line", "budget": DEFAULT_BUDGET, "outbox": [], "store": {}})
            S[cid]["store"] = v.get("store", {})
    except Exception:
        pass

def save_all():
    try:
        data = {}
        for cid, state in S.items():
            data[str(cid)] = {"store": state.get("store", {})}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("⚠️ save_all error:", repr(e))

# cargar en arranque
load_all()

# =====================
# Helpers
# =====================
def st(cid):
    if cid not in S:
        S[cid] = {"step": "line", "budget": DEFAULT_BUDGET, "outbox": [], "store": {}}
    S[cid].setdefault("store", {})
    return S[cid]

def send(cid, text, **kwargs):
    m = bot.send_message(cid, text, **kwargs)
    st(cid)["outbox"].append(m.message_id)
    return m

def send_main_menu(cid):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🧪 Simular anuncio", callback_data="menu_sim"),
           types.InlineKeyboardButton("💰 Cambiar presupuesto", callback_data="menu_budget"))
    kb.add(types.InlineKeyboardButton("🧹 Reset / Limpiar", callback_data="menu_reset"),
           types.InlineKeyboardButton("❓ Ayuda", callback_data="menu_help"))
    kb.add(types.InlineKeyboardButton("🗂️ Ver/Eliminar LÍNEA", callback_data="menu_del_line"),
           types.InlineKeyboardButton("🗑️ Ver/Eliminar ANUNCIO", callback_data="menu_del_ad"))
    send(cid, "Elige una opción:", reply_markup=kb)

def clean_private(cid):
    state = st(cid)
    deleted = 0
    for mid in state.get("outbox", []):
        try:
            bot.delete_message(cid, mid)
            deleted += 1
        except Exception:
            pass
    # Conservar store, resetear resto
    old_store = state.get("store", {})
    S[cid] = {"step": "line", "budget": DEFAULT_BUDGET, "outbox": [], "store": old_store}
    save_all()
    send(cid, f"🧹 Limpié {deleted} mensajes del bot. Por seguridad de Telegram, no puedo borrar tus mensajes en chats privados.\nEscribe la **Línea de Producto** (ej: short, conjunto).")
    send_main_menu(cid)

def bot_is_admin(chat_id):
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
    emojis = ["🔥", "⚡", "🏃‍♀️", "💥", "✅", "✨", "🎯"]
    hooks = ["Edición limitada", "Últimas unidades", "Llévalo hoy", "Nueva colección", "Calidad premium"]
    t2 = f"{random.choice(emojis)} {title} | {random.choice(hooks)}"
    t3 = f"{title} {random.choice(['al mejor precio','lista para entrenar','que sí rinde'])} {random.choice(emojis)}"
    d2 = f"{desc} {random.choice(['Disponible en tallas S-XL.', 'Envíos a todo el país.', 'Pago contra entrega.'])}"
    d3 = f"{random.choice(['Confort y rendimiento.', 'Diseño que destaca.', 'Te acompaña en cada entrenamiento.'])} {desc}"
    return t2, t3, d2, d3

def simulate_costs(budget):
    weights = [random.uniform(0.8, 1.2), random.uniform(0.8, 1.2), random.uniform(0.8, 1.2)]
    s = sum(weights)
    alloc = [budget * w / s for w in weights]
    base_cpm = [random.uniform(800, 2500) for _ in range(3)]
    msgs = [max(1, int(a / c)) for a, c in zip(alloc, base_cpm)]
    cpm_final = [max(1, int(round(a / m))) for a, m in zip(alloc, msgs)]
    alloc_rounded = [int(round(a)) for a in alloc]
    return list(zip(msgs, cpm_final, alloc_rounded))

def store_ads(cid, line, ads_triplet, replace=False):
    store = st(cid)["store"]
    if line not in store:
        store[line] = {"ads": []}
    if replace:
        store[line]["ads"] = []  # reemplazar
    store[line]["ads"].extend(ads_triplet)
    save_all()

def list_lines_kb(cid):
    store = st(cid).get("store", {})
    kb = types.InlineKeyboardMarkup()
    if not store:
        kb.add(types.InlineKeyboardButton("— No hay líneas —", callback_data="noop"))
    else:
        for ln in sorted(store.keys()):
            count = len(store[ln].get("ads", []))
            kb.add(types.InlineKeyboardButton(f"🗂️ {ln} ({count})", callback_data=f"choose_line::{ln}"))
    kb.add(types.InlineKeyboardButton("⬅️ Volver", callback_data="back_menu"))
    return kb

def list_ads_kb(cid, line):
    store = st(cid).get("store", {})
    kb = types.InlineKeyboardMarkup()
    if line not in store or not store[line]["ads"]:
        kb.add(types.InlineKeyboardButton("— Sin anuncios —", callback_data="noop"))
    else:
        for idx, ad in enumerate(store[line]["ads"]):
            title = ad.get("title", "(sin título)")
            kb.add(types.InlineKeyboardButton(f"🗑️ {idx+1}. {title[:40]}", callback_data=f"del_ad::{line}::{idx}"))
        kb.add(types.InlineKeyboardButton("🗑️ Eliminar TODA la línea", callback_data=f"del_line::{line}"))
    kb.add(types.InlineKeyboardButton("⬅️ Volver", callback_data="back_menu"))
    return kb

def summarize(cid):
    state = st(cid)
    line  = state.get("line", "(sin línea)")
    title = state.get("title", "(sin título)")
    desc  = state.get("desc", "(sin descripción)")
    media = state.get("media", "📷 (sin archivo detectado)")
    budget = state.get("budget", DEFAULT_BUDGET)
    t2, t3, d2, d3 = variations(title, desc)

    (m1, c1, s1), (m2, c2, s2), (m3, c3, s3) = simulate_costs(budget)

    replace = (state.get("option") == "B")
    ads = [
        {"title": title, "desc": desc, "media": media, "msg": m1, "cpm": c1, "spent": s1},
        {"title": t2, "desc": d2, "media": media, "msg": m2, "cpm": c2, "spent": s2},
        {"title": t3, "desc": d3, "media": media, "msg": m3, "cpm": c3, "spent": s3},
    ]
    store_ads(cid, line, ads, replace=replace)

    send(cid,
        f"🤖 (Simulación)\nPublicaría 3 anuncios en 'Línea - {str(line).capitalize()}':\n\n"
        f"🖼️ Media: {media}\n\n"
        f"1️⃣ {title} — {desc}\n"
        f"   • Mensajes: {m1}  • Costo por mensaje: {c1:,} COP  • Gasto: {s1:,} COP\n"
        f"2️⃣ {t2} — {d2}\n"
        f"   • Mensajes: {m2}  • Costo por mensaje: {c2:,} COP  • Gasto: {s2:,} COP\n"
        f"3️⃣ {t3} — {d3}\n"
        f"   • Mensajes: {m3}  • Costo por mensaje: {c3:,} COP  • Gasto: {s3:,} COP\n\n"
        f"💰 Presupuesto total: {budget:,} COP\n"
        "Opción: Simulación IA 🧠\n"
        "_(Valores simulados para pruebas.)_"
    , parse_mode="Markdown")
    send_main_menu(cid)

def render_line_summary(store, line):
    items = store.get(line, {}).get("ads", [])
    if not items:
        return "— Sin anuncios —"
    lines = []
    for i, ad in enumerate(items, 1):
        lines.append(f"{i}. {ad.get('title','(sin título)')} — {ad.get('desc','')[:60]}")
    return "\n".join(lines)

# =====================
# Comandos
# =====================
@bot.message_handler(commands=['start', 'star'])
def cmd_start(m):
    cid = m.chat.id
    st(cid)
    S[cid]["step"] = "line"
    send(cid, "👋 Bienvenido (simulación IA).\nEscribe la **Línea de Producto** (ej: short, conjunto).")
    send_main_menu(cid)

@bot.message_handler(commands=['menu'])
def cmd_menu(m):
    send_main_menu(m.chat.id)

@bot.message_handler(commands=['view'])
def cmd_view(m):
    """Muestra todas las líneas y un resumen de sus anuncios."""
    cid = m.chat.id
    store = st(cid).get("store", {})
    if not store:
        send(cid, "No tienes líneas guardadas todavía. Usa *Simular anuncio* para crear una.", parse_mode="Markdown")
        return
    for line in sorted(store.keys()):
        summary = render_line_summary(store, line)
        send(cid, f"📋 **{line}**\n{summary}", parse_mode="Markdown")

@bot.message_handler(commands=['reset'])
def cmd_reset(m):
    cid = m.chat.id
    chat_type = getattr(m.chat, "type", "private")
    if chat_type in ("group", "supergroup", "channel"):
        is_admin, can_delete = bot_is_admin(cid)
        if is_admin and can_delete:
            deleted = purge_group(cid, m.message_id, n=PURGE_WINDOW)
            old_store = st(cid).get("store", {})
            S[cid] = {"step": "line", "budget": DEFAULT_BUDGET, "outbox": [], "store": old_store}
            save_all()
            send(cid, f"🧹 Chat limpiado. Eliminados: {deleted}.\nEscribe la **Línea de Producto** (ej: short, conjunto).")
            send_main_menu(cid)
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
    cid = m.chat.id
    payload = m.text.split(' ', 1)
    if len(payload) < 2:
        send(cid, "Formato: /sim linea | titulo | descripcion | media(opcional)")
        return
    parts = [p.strip() for p in payload[1].split('|')]
    if len(parts) < 3:
        send(cid, "Necesito al menos: linea | titulo | descripcion")
        return
    S[cid].update({
        "step": "done",
        "line": parts[0],
        "title": parts[1],
        "desc": parts[2],
        "media": parts[3] if len(parts) >= 4 else "📷 (sin archivo detectado)"
    })
    summarize(cid)

# =====================
# Callbacks del menú
# =====================
@bot.callback_query_handler(func=lambda c: c.data in ["menu_sim", "menu_budget", "menu_reset", "menu_help", "menu_del_line", "menu_del_ad", "back_menu", "noop"] or c.data.startswith(("choose_line::", "del_line::", "del_ad::")))
def on_menu(c):
    cid = c.message.chat.id
    data = c.data
    if data == "menu_sim":
        bot.answer_callback_query(c.id, "Vamos a simular un anuncio")
        # Mantener store, reiniciar el flujo
        S[cid] = {"step": "line", "budget": st(cid)["budget"], "outbox": [], "store": st(cid).get("store", {})}
        save_all()
        send(cid, "Escribe la **Línea de Producto** (ej: short, conjunto).")
    elif data == "menu_budget":
        bot.answer_callback_query(c.id, "Cambiar presupuesto")
        send(cid, "Envía el comando con el nuevo presupuesto, por ejemplo:\n`/budget 120000`", parse_mode="Markdown")
    elif data == "menu_reset":
        bot.answer_callback_query(c.id, "Reseteando…")
        class Obj: pass
        fake = Obj(); fake.chat = Obj(); fake.chat.id = cid; fake.chat.type = "private"; fake.message_id = c.message.message_id
        cmd_reset(fake)
    elif data == "menu_help":
        bot.answer_callback_query(c.id, "Ayuda")
        help_txt = (
            "🧭 *Comandos disponibles:*\n"
            "• `/start` — Mostrar menú y comenzar flujo\n"
            "• `/menu` — Mostrar menú en cualquier momento\n"
            "• `/view` — Ver líneas y anuncios guardados\n"
            "• `/sim linea | titulo | descripcion | media(opcional)` — Simulación rápida\n"
            "• `/budget 120000` — Cambiar presupuesto simulado\n"
            "• `/reset` — Limpiar chat (si es grupo y el bot es admin)\n"
            "• Notas: 'Existe' depende de tu historial; datos se guardan en JSON (DATA_FILE).\n"
        )
        bot.send_message(cid, help_txt, parse_mode="Markdown")
    elif data == "menu_del_line":
        bot.answer_callback_query(c.id, "Líneas disponibles")
        kb = list_lines_kb(cid)
        send(cid, "Selecciona la **línea** que quieres eliminar o consultar:", reply_markup=kb)
    elif data == "menu_del_ad":
        bot.answer_callback_query(c.id, "Líneas con anuncios")
        kb = list_lines_kb(cid)
        send(cid, "Elige la **línea** para ver y eliminar anuncios individuales:", reply_markup=kb)
    elif data.startswith("choose_line::"):
        _, line = data.split("::", 1)
        bot.answer_callback_query(c.id, f"Línea: {line}")
        kb = list_ads_kb(cid, line)
        # además de teclado, envío resumen textual para que veas qué hay
        summary = render_line_summary(st(cid)["store"], line)
        send(cid, f"Anuncios en **{line}**:\n{summary}", parse_mode="Markdown", reply_markup=kb)
    elif data.startswith("del_line::"):
        _, line = data.split("::", 1)
        store = st(cid)["store"]
        if line in store:
            del store[line]
            save_all()
            bot.answer_callback_query(c.id, f"Línea '{line}' eliminada")
            send(cid, f"🗑️ Línea **{line}** eliminada completamente.", parse_mode="Markdown")
        else:
            bot.answer_callback_query(c.id, f"No existe la línea '{line}'")
            send(cid, f"⚠️ No encontré la línea **{line}**.", parse_mode="Markdown")
        send_main_menu(cid)
    elif data.startswith("del_ad::"):
        _, line, idx_str = data.split("::", 2)
        try:
            idx = int(idx_str)
        except:
            bot.answer_callback_query(c.id, "Índice inválido")
            return
        store = st(cid)["store"]
        if line in store and 0 <= idx < len(store[line]["ads"]):
            ad = store[line]["ads"].pop(idx)
            save_all()
            bot.answer_callback_query(c.id, "Anuncio eliminado")
            send(cid, f"🗑️ Eliminado: **{ad.get('title', '(sin título)')}** de la línea **{line}**.", parse_mode="Markdown")
            if not store[line]["ads"]:
                del store[line]
                save_all()
                send(cid, f"ℹ️ La línea **{line}** quedó vacía y fue eliminada.", parse_mode="Markdown")
        else:
            bot.answer_callback_query(c.id, "No encontrado")
            send(cid, "⚠️ No pude encontrar ese anuncio.", parse_mode="Markdown")
        send_main_menu(cid)
    elif data == "back_menu":
        bot.answer_callback_query(c.id, "Volver al menú")
        send_main_menu(cid)
    elif data == "noop":
        bot.answer_callback_query(c.id, "Sin elementos")
        send_main_menu(cid)

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

@bot.message_handler(content_types=['text'], func=lambda m: not (m.text or '').startswith('/'))
def text_handler(m):
    cid = m.chat.id
    txt = m.text.strip()
    state = st(cid)
    step = state.get("step", "line")

    if step == "line":
        state["line"] = txt
        store = st(cid)["store"]
        exists = txt in store
        adset = f"Línea - {txt.capitalize()}"
        if exists:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("Opción A: Agregar", callback_data="opt_A"),
                   types.InlineKeyboardButton("Opción B: Reemplazar", callback_data="opt_B"))
            send(cid, f"🔎 (Simulación) Ya tienes '{adset}' en tu historial. ¿Qué deseas hacer?", reply_markup=kb)
            state["step"] = "choose_option"
        else:
            store[txt] = {"ads": []}  # inicia línea para ver en menú
            save_all()
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
