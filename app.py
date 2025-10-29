import telebot
from telebot import types
import os
import json
from flask import Flask, request
import requests

TOKEN = os.getenv("TG_TOKEN")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN")
FB_AD_ACCOUNT_ID = os.getenv("FB_AD_ACCOUNT_ID")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_WABA_PHONE = os.getenv("FB_WABA_PHONE")
FB_API_VERSION = os.getenv("FB_API_VERSION", "20.0")
PORT = int(os.getenv("PORT", 10000))

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"lineas": {}, "modo": "SIMULACION"}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url="https://your-app-url.onrender.com/" + TOKEN)
    return "Bot activo", 200

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("➕ Crear anuncio")
    btn2 = types.KeyboardButton("👀 Ver líneas")
    btn3 = types.KeyboardButton("🧹 Reset")
    btn4 = types.KeyboardButton("🧠 Cambiar modo (Simulación / Real)")
    btn5 = types.KeyboardButton("🧾 Check Meta")
    markup.add(btn1, btn2, btn3, btn4, btn5)

    bot.send_message(message.chat.id, "👋 ¡Bienvenido! Soy tu asistente de anuncios.
Elige una opción:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "🧹 Reset")
def reset_chat(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🧹 Borrando mensajes...")
    for i in range(20):
        try:
            bot.delete_message(chat_id, message.message_id - i)
        except:
            pass
    bot.send_message(chat_id, "✅ Chat reiniciado. Usa /start para comenzar.")

@bot.message_handler(func=lambda msg: msg.text == "🧠 Cambiar modo (Simulación / Real)")
def cambiar_modo(message):
    data = load_data()
    if data["modo"] == "SIMULACION":
        data["modo"] = "REAL"
        bot.send_message(message.chat.id, "🔁 Modo cambiado a: REAL ✅")
    else:
        data["modo"] = "SIMULACION"
        bot.send_message(message.chat.id, "🔁 Modo cambiado a: SIMULACIÓN 🧠")
    save_data(data)

@bot.message_handler(func=lambda msg: msg.text == "🧾 Check Meta")
def check_meta(message):
    try:
        url = f"https://graph.facebook.com/v{FB_API_VERSION}/me/adaccounts?access_token={FB_ACCESS_TOKEN}"
        resp = requests.get(url).json()
        cuentas = resp.get("data", [])
        if not cuentas:
            bot.send_message(message.chat.id, "⚠️ No se encontraron cuentas publicitarias. Revisa el token o permisos.")
            return
        msg = "✅ *Cuentas publicitarias vinculadas:*
"
        for c in cuentas:
            msg += f"- {c['id']} ({c.get('name','Sin nombre')})
"
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error verificando conexión con Meta:
{e}")

@bot.message_handler(func=lambda msg: msg.text == "➕ Crear anuncio")
def crear_anuncio(message):
    data = load_data()
    bot.send_message(message.chat.id, "🧩 Escribe la *Línea de Producto* (ej: short, conjunto, conjunto niño):", parse_mode="Markdown")
    bot.register_next_step_handler(message, recibir_linea)

def recibir_linea(message):
    data = load_data()
    linea = message.text.strip().lower()
    if linea not in data["lineas"]:
        data["lineas"][linea] = []
        bot.send_message(message.chat.id, f"🆕 Línea '{linea}' creada con presupuesto inicial de 80.000 COP.")
    else:
        bot.send_message(message.chat.id, f"⚙️ Línea '{linea}' ya existe. Se agregará un nuevo test.")
    save_data(data)
    bot.send_message(message.chat.id, "📸 Sube la *foto (formato Reels)* del producto:")
    bot.register_next_step_handler(message, recibir_foto, linea)

def recibir_foto(message, linea):
    if not message.photo:
        bot.send_message(message.chat.id, "❌ Por favor envía una imagen válida.")
        return
    file_id = message.photo[-1].file_id
    bot.send_message(message.chat.id, "✏️ Escribe el *Título Base* del anuncio:", parse_mode="Markdown")
    bot.register_next_step_handler(message, recibir_titulo, linea, file_id)

def recibir_titulo(message, linea, file_id):
    titulo = message.text
    bot.send_message(message.chat.id, "📝 Escribe la *Descripción Base* del anuncio:", parse_mode="Markdown")
    bot.register_next_step_handler(message, recibir_descripcion, linea, file_id, titulo)

def recibir_descripcion(message, linea, file_id, titulo):
    descripcion = message.text
    data = load_data()
    modo = data["modo"]
    variaciones = [
        {"titulo": titulo, "descripcion": descripcion},
        {"titulo": f"🔥 {titulo} | Nueva colección", "descripcion": f"{descripcion} Disponible en tallas S-XL."},
        {"titulo": f"{titulo} que sí rinde ✅", "descripcion": f"{descripcion} — Diseño que destaca."}
    ]

    anuncios = [f"🟢 {v['titulo']}
{v['descripcion']}" for v in variaciones]
    resumen = "\n\n".join(anuncios)
    bot.send_message(message.chat.id, f"🤖 ({modo}) Publicaría 3 anuncios para 'Línea - {linea}':\n\n{resumen}\n\n💰 Presupuesto: 80.000 COP", parse_mode="Markdown")

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🟢 Activar campaña")
    btn2 = types.KeyboardButton("⏸️ Dejar en borrador")
    markup.add(btn1, btn2)
    bot.send_message(message.chat.id, "¿Deseas activar la campaña o dejarla pausada?", reply_markup=markup)
    data["lineas"][linea].append({"titulo": titulo, "descripcion": descripcion})
    save_data(data)

@bot.message_handler(func=lambda msg: msg.text == "👀 Ver líneas")
def ver_lineas(message):
    data = load_data()
    if not data["lineas"]:
        bot.send_message(message.chat.id, "🚫 No hay líneas creadas todavía.")
        return
    msg = "📋 *Líneas activas:*
"
    for linea, anuncios in data["lineas"].items():
        msg += f"• {linea} ({len(anuncios)} anuncios)
"
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
