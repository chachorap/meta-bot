import os, random, time, threading
from dotenv import load_dotenv
from flask import Flask, jsonify
import telebot
from telebot import types

# --- Configuración inicial ---
load_dotenv()
TG_TOKEN = os.getenv("TG_TOKEN")
if not TG_TOKEN:
    raise RuntimeError("Falta TG_TOKEN en variables de entorno")

bot = telebot.TeleBot(TG_TOKEN)
STATE = {}
DEFAULT_BUDGET = 80000  # Presupuesto por defecto

# --- Generador de variaciones IA ---
def gen_variations(title, desc):
    emojis = ["🔥", "⚡", "🏃‍♀️", "💥", "✅", "✨", "🎯"]
    hooks = ["Edición limitada", "Últimas unidades", "Llévalo hoy", "Nueva colección", "Calidad premium"]
    t2 = f"{random.choice(emojis)} {title} | {random.choice(hooks)}"
    t3 = f"{title} {random.choice(['al mejor precio','lista para entrenar','que sí rinde'])} {random.choice(emojis)}"
    d2 = f"{desc} {random.choice(['Disponible en tallas S-XL.', 'Envíos a todo el país.', 'Pago contra entrega.'])}"
    d3 = f"{random.choice(['Confort y rendimiento.', 'Diseño que destaca.', 'Te acompaña en cada entrenamiento.'])} {desc}"
    return (t2, t3, d2, d3)

# --- Comandos principales ---
@bot.message_handler(commands=['start'])
def start(m):
    cid = m.chat.id
    STATE[cid] = {"step": "line", "budget": DEFAULT_BUDGET}
    bot.send_message(cid, "👋 Bienvenido (modo simulación IA)\nEscribe la **Línea de Producto** (ej: short, conjunto).")

@bot.message_handler(commands=['reset'])
def reset_cmd(m):
    cid = m.chat.id
    STATE[cid] = {"step": "line", "budget": DEFAULT_BUDGET}
    bot.send_message(cid, "🔄 Estado reiniciado. Escribe la **Línea de Producto** (ej: short, conjunto).")

@bot.message_handler(commands=['budget'])
def set_budget(m):
    cid = m.chat.id
    try:
        _, value = m.text.split(' ', 1)
        value = int(value.strip().replace('.', '').replace(',', ''))
        STATE.setdefault(cid, {"step": "line"})
        STATE[cid]["budget"] = value
        bot.send_message(cid, f"💰 Presupuesto actualizado a {value:,} COP.")
    except Exception:
        bot.send_message(cid, "Formato incorrecto. Ejemplo: `/budget 120000`", parse_mode="Markdown")

@bot.message_handler(commands=['sim'])
def sim_cmd(m):
    \"\"
    Uso: /sim linea | titulo | descripcion | media(opcional)
    Ejemplo:
    /sim conjuntos running | 3 conjuntos por 75 mil | Envío gratis. Pago contraentrega. Tallas S-XL. | https://miimagen.jpg
    \"\"
    cid = m.chat.id
    payload = m.text.split(' ', 1)
    if len(payload) < 2:
        bot.send_message(cid, "Formato: /sim linea | titulo | descripcion | media(opcional)")
        return
    parts = [p.strip() for p in payload[1].split('|')]
    if len(parts) < 3:
        bot.send_message(cid, "Necesito al menos: linea | titulo | descripcion")
        return
    linea, titulo, desc = parts[0], parts[1], parts[2]
    media = parts[3] if len(parts) >= 4 else "📷 (sin archivo detectado)"

    STATE[cid] = {"line": linea, "title": titulo, "desc": desc, "media": media, "budget": STATE.get(cid, {}).get("budget", DEFAULT_BUDGET)}
    proceed_publish(cid)

# --- Flujo conversacional ---
@bot.message_handler(content_types=['photo','video'])
def media_handler(m):
    cid = m.chat.id
    st = STATE.get(cid, {})
    if st.get("step") == "media":
        if m.photo:
            STATE[cid]["media"] = f"photo:{m.photo[-1].file_id}"
        elif m.video:
            STATE[cid]["media"] = f"video:{m.video.file_id}"
        bot.send_message(cid, "Perfecto 👍\nAhora escribe el **Título Base** para el anuncio:")
        STATE[cid]["step"] = "title"

@bot.message_handler(func=lambda m: True, content_types=['text'])
def text_handler(m):
    cid = m.chat.id
    txt = m.text.strip()
    st = STATE.get(cid, {})
    step = st.get("step")

    if step == "line":
        STATE[cid]["line"] = txt
        adset_exists = random.choice([True, False])
        adset_name = f"Línea - {txt.capitalize()}"
        if adset_exists:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("Opción A: Agregar", callback_data="opt_A"),
                   types.InlineKeyboardButton("Opción B: Reemplazar", callback_data="opt_B"))
            bot.send_message(cid, f"🔎 (Simulación) Existe '{adset_name}'. ¿Qué deseas hacer?", reply_markup=kb)
            STATE[cid]["step"] = "choose_option"
        else:
            STATE[cid]["option"] = "A"
            bot.send_message(cid, f"🆕 (Simulación) Crearé '{adset_name}' con presupuesto {st.get('budget', DEFAULT_BUDGET):,} COP.")
            bot.send_message(cid, "Por favor envía la **imagen o video del producto**.")
            STATE[cid]["step"] = "media"

    elif step == "media":
        STATE[cid]["media"] = txt
        bot.send_message(cid, "Perfecto 👍\nAhora escribe la **Descripción Base**.")
        STATE[cid]["step"] = "desc" if STATE[cid].get("title") else "title"

    elif step == "title":
        STATE[cid]["title"] = txt
        bot.send_message(cid, "Excelente 👌\nAhora escribe la **Descripción Base**.")
        STATE[cid]["step"] = "desc"

    elif step == "desc":
        STATE[cid]["desc"] = txt
        proceed_publish(cid)

@bot.callback_query_handler(func=lambda c: c.data in ['opt_A','opt_B'])
def cb_handler(c):
    cid = c.message.chat.id
    STATE.setdefault(cid, {"budget": DEFAULT_BUDGET})
    STATE[cid]["option"] = "A" if c.data == "opt_A" else "B"
    bot.answer_callback_query(c.id, "Opción registrada")
    bot.send_message(cid, "Genial 👍\nPor favor envía la **imagen o video del producto**.")
    STATE[cid]["step"] = "media"

# --- Publicador simulado ---
def proceed_publish(cid):
    st = STATE[cid]
    line, title, desc = st.get("line"), st.get("title"), st.get("desc")
    media = st.get("media", "📷 (sin archivo detectado)")
    t2, t3, d2, d3 = gen_variations(title, desc)
    budget = st.get("budget", DEFAULT_BUDGET)

    bot.send_message(cid,
        f"🤖 (Simulación)\nPublicaría 3 anuncios en 'Línea - {line.capitalize()}':\n\n"
        f"🖼️ Media: {media}\n\n"
        f"1️⃣ {title} — {desc}\n"
        f"2️⃣ {t2} — {d2}\n"
        f"3️⃣ {t3} — {d3}\n\n"
        f"💰 Presupuesto: {budget:,} COP\n"
        "Opción: Simulación IA 🧠")

# --- Polling ---
def start_polling():
    while True:
        try:
            bot.polling(timeout=30, long_polling_timeout=25, allowed_updates=['message','callback_query'])
        except Exception as e:
            print("⚠️ Polling error:", repr(e))
            time.sleep(5)

# --- Servidor Flask ---
app = Flask(__name__)

@app.get("/")
def root():
    return "OK", 200

@app.get("/healthz")
def healthz():
    return jsonify(status="ok"), 200

if __name__ == "__main__":
    t = threading.Thread(target=start_polling, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
