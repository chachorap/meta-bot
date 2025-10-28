import os, random
import telebot
from telebot import types
from dotenv import load_dotenv

load_dotenv()
TG_TOKEN = os.getenv("TG_TOKEN")
bot = telebot.TeleBot(TG_TOKEN)
STATE = {}

def gen_variations(title, desc):
    emojis = ["🔥","⚡","🏃‍♀️","💥","✅","✨","🎯"]
    hooks = ["Edición limitada","Últimas unidades","Llévalo hoy","Nueva colección","Calidad premium"]
    t2 = f"{random.choice(emojis)} {title} | {random.choice(hooks)}"
    t3 = f"{title} {random.choice(['al mejor precio','lista para entrenar','que sí rinde'])} {random.choice(emojis)}"
    d2 = f"{desc} {random.choice(['Disponible en tallas S-XL.','Envíos a todo el país.','Pago contra entrega.'])}"
    d3 = f"{random.choice(['Confort y rendimiento.','Diseño que destaca.','Te acompaña en cada entrenamiento.'])} {desc}"
    return (t2,t3,d2,d3)

@bot.message_handler(commands=['start'])
def start(m):
    cid = m.chat.id
    STATE[cid] = {"step":"line"}
    bot.send_message(cid,"👋 Bienvenido (modo simulación). Escribe la **Línea de Producto** (ej: short, conjunto).")

@bot.message_handler(content_types=['photo','video'])
def media_handler(m):
    cid=m.chat.id
    st=STATE.get(cid,{})
    if st.get("step")=="media":
        STATE[cid]["media"]="photo" if m.photo else "video"
        bot.send_message(cid,"Perfecto 👍 Ahora escribe el **Título Base** para el anuncio:")
        STATE[cid]["step"]="title"

@bot.message_handler(func=lambda m:True,content_types=['text'])
def text_handler(m):
    cid=m.chat.id
    txt=m.text.strip()
    st=STATE.get(cid,{})
    step=st.get("step")
    if step=="line":
        STATE[cid]["line"]=txt
        adset_exists=random.choice([True,False])
        adset_name=f"Línea - {txt.capitalize()}"
        if adset_exists:
            kb=types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("Opción A: Agregar",callback_data="opt_A"),
                   types.InlineKeyboardButton("Opción B: Reemplazar",callback_data="opt_B"))
            bot.send_message(cid,f"🔎 (Simulación) Existe '{adset_name}'. ¿Qué deseas hacer?",reply_markup=kb)
            STATE[cid]["step"]="choose_option"
        else:
            STATE[cid]["option"]="A"
            bot.send_message(cid,f"🆕 (Simulación) Crearé '{adset_name}' con presupuesto 80 000 COP.")
            bot.send_message(cid,"Por favor envía la **imagen o video del producto**.")
            STATE[cid]["step"]="media"
    elif step=="media":
        STATE[cid]["media"]=txt
        bot.send_message(cid,"Perfecto 👍 Ahora escribe el **Título Base** para el anuncio:")
        STATE[cid]["step"]="title"
    elif step=="title":
        STATE[cid]["title"]=txt
        bot.send_message(cid,"Excelente 👌 Ahora escribe la **Descripción Base**.")
        STATE[cid]["step"]="desc"
    elif step=="desc":
        STATE[cid]["desc"]=txt
        publish(cid)

def publish(cid):
    st=STATE[cid]
    line,title,desc=st["line"],st["title"],st["desc"]
    media=st.get("media","📷 (no detectada)")
    t2,t3,d2,d3=gen_variations(title,desc)
    bot.send_message(cid,
        f"🤖 (Simulación)\nPublicaría 3 anuncios en 'Línea - {line.capitalize()}':\n\n"
        f"🖼️ Media: {media}\n\n"
        f"1️⃣ {title} — {desc}\n"
        f"2️⃣ {t2} — {d2}\n"
        f"3️⃣ {t3} — {d3}\n\n"
        "Presupuesto: 80 000 COP\nOpción: Simulación IA 🧠")

@bot.callback_query_handler(func=lambda c:c.data in ["opt_A","opt_B"])
def cb(c):
    cid=c.message.chat.id
    STATE.setdefault(cid,{})
    STATE[cid]["option"]="A" if c.data=="opt_A" else "B"
    bot.answer_callback_query(c.id,"Opción registrada")
    bot.send_message(cid,"Genial 👍 Envía la **imagen o video del producto**.")
    STATE[cid]["step"]="media"

bot.infinity_polling()
