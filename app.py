import os, json, time, threading
from dotenv import load_dotenv
from flask import Flask, jsonify, request
import telebot
from telebot import types
import requests

# =====================
# Config
# =====================
load_dotenv()
TG_TOKEN         = os.getenv("TG_TOKEN")
DATA_FILE        = os.getenv("DATA_FILE", "data.json")
PORT             = int(os.getenv("PORT", 10000))

# Meta / Facebook Marketing API (modo REAL)
FB_ACCESS_TOKEN  = os.getenv("FB_ACCESS_TOKEN")
FB_AD_ACCOUNT_ID = os.getenv("FB_AD_ACCOUNT_ID")  # ej: act_1234567890
FB_PAGE_ID       = os.getenv("FB_PAGE_ID")        # ej: 123456789012345
FB_WABA_PHONE    = os.getenv("FB_WABA_PHONE")     # ej: 57XXXXXXXXXX
FB_API_VERSION   = os.getenv("FB_API_VERSION", "20.0")

if not TG_TOKEN:
    raise RuntimeError("Falta TG_TOKEN")

bot = telebot.TeleBot(TG_TOKEN)
DEFAULT_BUDGET = 80_000

# =====================
# Estado & Persistencia
# =====================
S = {}  # S[cid] = {'step', 'line', 'title','desc','media','budget','store','outbox'}
def st(cid):
    if cid not in S:
        S[cid] = {"step":"idle", "budget":DEFAULT_BUDGET, "store":{}, "outbox":[]}
    S[cid].setdefault("store", {})
    return S[cid]

def load_all():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k,v in data.items():
            cid = int(k)
            S[cid] = {"step":"idle", "budget":v.get("budget", DEFAULT_BUDGET),
                      "store":v.get("store", {}), "outbox":[]}
    except Exception:
        pass

def save_all():
    data = {str(cid): {"budget": s.get("budget", DEFAULT_BUDGET),
                       "store": s.get("store", {})}
            for cid,s in S.items()}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

load_all()

def send(cid, text, **kw):
    m = bot.send_message(cid, text, **kw)
    st(cid)["outbox"].append(m.message_id)
    return m

# =====================
# Menú principal (sin simulación)
# =====================
def home_menu():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Nueva campaña", callback_data="new_line"),
        types.InlineKeyboardButton("🗂️ Mis líneas", callback_data="lines"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 Métricas", callback_data="metrics"),
        types.InlineKeyboardButton("💰 Presupuesto", callback_data="budget"),
    )
    kb.add(
        types.InlineKeyboardButton("⚙️ Configuración", callback_data="settings"),
        types.InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm"),
    )
    kb.add(types.InlineKeyboardButton("❓Ayuda", callback_data="help"))
    return kb

def lines_kb(cid):
    store = st(cid)["store"]
    kb = types.InlineKeyboardMarkup(row_width=1)
    if not store:
        kb.add(types.InlineKeyboardButton("— No hay líneas —", callback_data="noop"))
    else:
        for ln in sorted(store.keys()):
            kb.add(types.InlineKeyboardButton(f"🗂️ {ln} ({len(store[ln].get('ads',[]))})", callback_data=f"open_line::{ln}"))
    kb.add(types.InlineKeyboardButton("⬅️ Volver", callback_data="home"))
    return kb

def line_detail_kb(cid, line):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Ver anuncios", callback_data=f"view_ads::{line}"),
        types.InlineKeyboardButton("🗑️ Eliminar línea", callback_data=f"del_line::{line}"),
    )
    kb.add(types.InlineKeyboardButton("⬅️ Volver", callback_data="lines"))
    return kb

def ads_kb(cid, line):
    store = st(cid)["store"]
    kb = types.InlineKeyboardMarkup(row_width=1)
    ads = store.get(line,{}).get("ads",[])
    if not ads:
        kb.add(types.InlineKeyboardButton("— Sin anuncios —", callback_data="noop"))
    else:
        for i, ad in enumerate(ads, 1):
            title = ad.get("title","(sin título)")
            kb.add(types.InlineKeyboardButton(f"{i}. {title[:40]}  ⏯ / 🗑", callback_data=f"ad_menu::{line}::{i-1}"))
    kb.add(types.InlineKeyboardButton("⬅️ Volver", callback_data=f"open_line::{line}"))
    return kb

def ad_item_kb(line, idx):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("⏯ Activar/Pausar", callback_data=f"ad_toggle::{line}::{idx}"),
        types.InlineKeyboardButton("🗑 Eliminar anuncio", callback_data=f"del_ad::{line}::{idx}"),
    )
    kb.add(types.InlineKeyboardButton("⬅️ Volver", callback_data=f"view_ads::{line}"))
    return kb

# =====================
# Meta helpers (REAL)
# =====================
def fb_init():
    if not (FB_ACCESS_TOKEN and FB_AD_ACCOUNT_ID and FB_PAGE_ID and FB_WABA_PHONE):
        raise RuntimeError("Faltan variables FB_* para Meta.")
    from facebook_business.api import FacebookAdsApi
    FacebookAdsApi.init(access_token=FB_ACCESS_TOKEN, api_version=FB_API_VERSION)
    from facebook_business.adobjects.adaccount import AdAccount
    return AdAccount(FB_AD_ACCOUNT_ID)

def publish_to_meta(line, title, desc, budget_cop, activate_now):
    from facebook_business.adobjects.campaign import Campaign
    from facebook_business.adobjects.adset import AdSet
    from facebook_business.adobjects.adcreative import AdCreative
    from facebook_business.adobjects.ad import Ad

    account = fb_init()
    status = 'ACTIVE' if activate_now else 'PAUSED'

    # 1) Campaña
    campaign = account.create_campaign(params={
        Campaign.Field.name: f"Línea - {line}",
        Campaign.Field.objective: 'MESSAGES',
        Campaign.Field.configured_status: status
    })
    campaign_id = campaign[Campaign.Field.id]

    # 2) AdSet
    params = {
        AdSet.Field.name: f"AdSet - {line}",
        AdSet.Field.campaign_id: campaign_id,
        AdSet.Field.daily_budget: max(1000, int(budget_cop)),
        AdSet.Field.billing_event: 'IMPRESSIONS',
        AdSet.Field.optimization_goal: 'LEAD_GENERATION',
        AdSet.Field.promoted_object: {'page_id': FB_PAGE_ID, 'whatsapp_phone_number': FB_WABA_PHONE},
        AdSet.Field.targeting: {'geo_locations': {'countries': ['CO']}, 'age_min': 18, 'age_max': 65},
        AdSet.Field.configured_status: status,
    }
    try:
        params['destination_type'] = 'WHATSAPP'
        adset = account.create_ad_set(params=params)
    except Exception:
        params.pop('destination_type', None)
        params['message_destination'] = 'WHATSAPP'
        adset = account.create_ad_set(params=params)
    adset_id = adset[AdSet.Field.id]

    # 3) Creativo básico (CTA WhatsApp)
    creative = account.create_ad_creative(params={
        AdCreative.Field.name: f"Creative - {line}",
        AdCreative.Field.object_story_spec: {
            'page_id': FB_PAGE_ID,
            'link_data': {
                'message': desc,
                'name': title,
                'call_to_action': {'type': 'WHATSAPP_MESSAGE'},
                'link': 'https://www.facebook.com'
            }
        }
    })
    creative_id = creative[AdCreative.Field.id]

    # 4) Ad
    ad = account.create_ad(params={
        Ad.Field.name: f"Ad - {line}",
        Ad.Field.adset_id: adset_id,
        Ad.Field.creative: {'creative_id': creative_id},
        Ad.Field.configured_status: status,
    })
    ad_id = ad[Ad.Field.id]
    return {"campaign_id": campaign_id, "adset_id": adset_id, "status": status, "ad_id": ad_id}

# =====================
# Comandos
# =====================
@bot.message_handler(commands=['start'])
def start(m):
    cid = m.chat.id
    send(cid, "👋 Bienvenido. Elige una opción:", reply_markup=home_menu())
    st(cid)["step"] = "idle"

@bot.message_handler(commands=['reset'])
def reset_cmd(m):
    cid = m.chat.id
    deleted = 0
    for mid in st(cid)["outbox"]:
        try:
            bot.delete_message(cid, mid); deleted += 1
        except: pass
    st(cid)["outbox"].clear()
    send(cid, f"🧹 Listo, limpié {deleted} mensajes del bot. Usa /start.")

@bot.message_handler(commands=['check_meta'])
def cmd_check_meta(m):
    cid = m.chat.id
    if not FB_ACCESS_TOKEN:
        send(cid, "⚠️ Falta FB_ACCESS_TOKEN en las variables de entorno.")
        return
    try:
        url = f"https://graph.facebook.com/v{FB_API_VERSION}/me/adaccounts?access_token={FB_ACCESS_TOKEN}"
        r = requests.get(url, timeout=20)
        data = r.json()
        if "error" in data:
            err = data["error"]
            send(cid, f"❌ Error Meta: {err.get('message','')}\nCódigo: {err.get('code','')}")
            return

        cuentas = data.get("data", [])
        if not cuentas:
            send(cid, "ℹ️ No se encontraron cuentas publicitarias para este token.")
            return

        msg = "✅ *Cuentas publicitarias vinculadas:*\n"
        for c in cuentas:
            nombre = c.get("name", "Sin nombre")
            acc_id = c.get("id", "—")
            msg += f"- {acc_id} ({nombre})\n"
        send(cid, msg, parse_mode="Markdown")

    except Exception as e:
        send(cid, f"❌ Error conectando a Meta: {e}")

# =====================
# Callback menu
# =====================
@bot.callback_query_handler(func=lambda c: True)
def on_cb(c):
    cid = c.message.chat.id
    data = c.data
    state = st(cid)

    if data == "home":
        bot.answer_callback_query(c.id)
        send(cid, "🏠 Menú principal", reply_markup=home_menu())

    elif data == "new_line":
        bot.answer_callback_query(c.id)
        send(cid, "🧩 Escribe la *Línea de producto* (ej: short, conjunto):", parse_mode="Markdown")
        state["step"] = "new_line"

    elif data == "lines":
        bot.answer_callback_query(c.id)
        send(cid, "🗂️ Tus líneas:", reply_markup=lines_kb(cid))

    elif data.startswith("open_line::"):
        _, line = data.split("::",1)
        bot.answer_callback_query(c.id)
        send(cid, f"📁 Línea: *{line}*", parse_mode="Markdown", reply_markup=line_detail_kb(cid, line))

    elif data.startswith("view_ads::"):
        _, line = data.split("::",1)
        bot.answer_callback_query(c.id)
        store = state["store"]
        ads = store.get(line,{}).get("ads",[])
        if not ads:
            send(cid, "— Sin anuncios —", reply_markup=ads_kb(cid, line))
        else:
            for i, ad in enumerate(ads, 1):
                msg = (f"{i}. *{ad.get('title','(sin título)')}*\n"
                       f"{ad.get('desc','')}\n")
                send(cid, msg, parse_mode="Markdown", reply_markup=ad_item_kb(line, i-1))

    elif data.startswith("ad_menu::"):
        _, line, i = data.split("::",2)
        bot.answer_callback_query(c.id)
        i = int(i)
        store = state["store"]
        ad = store.get(line,{}).get("ads",[])[i]
        msg = f"*{ad.get('title') }*\n{ad.get('desc') }"
        send(cid, msg, parse_mode="Markdown", reply_markup=ad_item_kb(line, i))

    elif data.startswith("del_line::"):
        _, line = data.split("::",1)
        bot.answer_callback_query(c.id, "Eliminado")
        store = state["store"]
        if line in store: del store[line]; save_all()
        send(cid, f"🗑️ Línea *{line}* eliminada.", parse_mode="Markdown", reply_markup=lines_kb(cid))

    elif data.startswith("del_ad::"):
        _, line, i = data.split("::",2)
        bot.answer_callback_query(c.id, "Eliminado")
        i = int(i)
        store = state["store"]
        ads = store.get(line,{}).get("ads",[])
        if 0 <= i < len(ads):
            ads.pop(i); save_all()
        if not ads: store.pop(line, None); save_all()
        send(cid, "✅ Eliminado.", reply_markup=ads_kb(cid, line))

    elif data.startswith("ad_toggle::"):
        _, line, i = data.split("::",2)
        bot.answer_callback_query(c.id)
        # Aquí puedes llamar a Meta para pausar/activar usando ad_id guardado en store[line]["ads"][i]["meta"]["ad_id"]
        send(cid, "⏯ (Demo) Alternar estado del anuncio en Meta.")

    elif data == "metrics":
        bot.answer_callback_query(c.id)
        send(cid, "📊 Métricas próximamente (24h / 7d / 28d).")

    elif data == "budget":
        bot.answer_callback_query(c.id)
        store = state["store"]
        if not store:
            send(cid, "No hay líneas aún.")
        else:
            kb = types.InlineKeyboardMarkup(row_width=1)
            for ln in sorted(store.keys()):
                kb.add(types.InlineKeyboardButton(f"{ln} — {state['budget']:,} COP", callback_data=f"budget_edit::{ln}"))
            kb.add(types.InlineKeyboardButton("⬅️ Volver", callback_data="home"))
            send(cid, "Selecciona la línea para editar presupuesto:", reply_markup=kb)

    elif data.startswith("budget_edit::"):
        _, line = data.split("::",1)
        bot.answer_callback_query(c.id)
        state["editing_line"] = line
        send(cid, f"💰 Nuevo presupuesto (COP) para *{line}*:", parse_mode="Markdown")
        state["step"] = "edit_budget"

    elif data == "settings":
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🧾 Check Meta", callback_data="cfg_check_meta"))
        send(cid,
             "⚙️ Configuración\n"
             f"• Cuenta: {FB_AD_ACCOUNT_ID}\n"
             f"• Página: {FB_PAGE_ID}\n"
             f"• WA: {FB_WABA_PHONE}\n"
             f"• API: v{FB_API_VERSION}",
             reply_markup=kb)

    elif data == "cfg_check_meta":
        bot.answer_callback_query(c.id, "Verificando Meta…")
        class Dummy:
            def __init__(self, chat_id): self.chat = type("C", (), {"id": chat_id})
        cmd_check_meta(Dummy(cid))

    elif data == "reset_confirm":
        bot.answer_callback_query(c.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ Sí, limpiar", callback_data="reset_go"),
               types.InlineKeyboardButton("❌ Cancelar", callback_data="home"))
        send(cid, "¿Deseas limpiar los mensajes del bot en este chat?", reply_markup=kb)

    elif data == "reset_go":
        bot.answer_callback_query(c.id, "Limpiando...")
        deleted = 0
        for mid in st(cid)["outbox"]:
            try: bot.delete_message(cid, mid); deleted += 1
            except: pass
        st(cid)["outbox"].clear()
        send(cid, f"🧹 Listo, limpié {deleted} mensajes del bot. Usa /start.")

    elif data == "help":
        bot.answer_callback_query(c.id)
        send(cid, "❓Ayuda\n1) ➕ Nueva campaña\n2) Completa línea, media, título y descripción\n3) Publica: 🟢 Activar o ⏸️ Pausada\n4) Gestiona desde 🗂️ Mis líneas")

    elif data == "noop":
        bot.answer_callback_query(c.id)

# =====================
# Flujo de texto
# =====================
@bot.message_handler(content_types=['photo','video'])
def media_handler(m):
    cid = m.chat.id
    state = st(cid)
    if state.get("step") == "ask_media":
        if m.photo:
            state["media"] = f"photo:{m.photo[-1].file_id}"
        elif m.video:
            state["media"] = f"video:{m.video.file_id}"
        send(cid, "✏️ Escribe el *Título* del anuncio:", parse_mode="Markdown")
        state["step"] = "ask_title"

@bot.message_handler(func=lambda m: not (m.text or '').startswith('/'))
def text_handler(m):
    cid = m.chat.id
    txt = (m.text or '').strip()
    state = st(cid)
    step = state.get("step","idle")

    if step == "new_line":
        state["line"] = txt
        store = state["store"]
        if txt not in store: store[txt] = {"ads":[]}; save_all()
        send(cid, "📸 Sube *imagen o video* del producto:", parse_mode="Markdown")
        state["step"] = "ask_media"

    elif step == "ask_title":
        state["title"] = txt
        send(cid, "📝 Escribe la *Descripción* del anuncio:", parse_mode="Markdown")
        state["step"] = "ask_desc"

    elif step == "ask_desc":
        state["desc"] = txt
        # Resumen + publicar
        line, title, desc = state["line"], state["title"], state["desc"]
        budget = state.get("budget", DEFAULT_BUDGET)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🟢 Activar ahora", callback_data="go_live_ACTIVE"),
               types.InlineKeyboardButton("⏸️ Dejar pausada", callback_data="go_live_PAUSED"))
        send(cid, (f"Resumen:\n• Línea: {line}\n• Título: {title}\n• Desc: {desc}\n"
                   f"• Presupuesto: {budget:,} COP\n\n¿Publicar activada o pausada?"),
             reply_markup=kb)
        state["step"] = "confirm_publish"

    elif step == "edit_budget":
        try:
            val = int(txt.replace(".","").replace(",",""))
            state["budget"] = max(1000, val); save_all()
            send(cid, f"✅ Presupuesto actualizado: {state['budget']:,} COP", reply_markup=home_menu())
            state["step"] = "idle"
        except:
            send(cid, "Formato inválido. Escribe solo números.")

# =====================
# Publicación (confirm)
# =====================
@bot.callback_query_handler(func=lambda c: c.data.startswith("go_live_"))
def do_publish(c):
    cid = c.message.chat.id
    state = st(cid)
    status = c.data.split("_", 2)[2]  # ACTIVE | PAUSED
    activate = (status == "ACTIVE")
    try:
        res = publish_to_meta(
            line = state.get("line"),
            title = state.get("title"),
            desc = state.get("desc"),
            budget_cop = state.get("budget", DEFAULT_BUDGET),
            activate_now = activate
        )
        # guardar anuncio mínimo local
        store = state["store"]
        store[state["line"]]["ads"].append({
            "title": state["title"],
            "desc": state["desc"],
            "meta": res
        })
        save_all()
        bot.answer_callback_query(c.id, "Publicado")
        send(cid, (f"✅ Publicado en Meta\n"
                   f"Campaña: `{res['campaign_id']}`\n"
                   f"Ad Set: `{res['adset_id']}`\n"
                   f"Ad: `{res['ad_id']}`\n"
                   f"Estado: **{res['status']}**"), parse_mode="Markdown", reply_markup=home_menu())
        state["step"] = "idle"
    except Exception as e:
        bot.answer_callback_query(c.id, "Error")
        send(cid, f"❌ Error publicando: {e}", reply_markup=home_menu())

# =====================
# Polling + Flask
# =====================
def run_polling():
    print("▶️ Iniciando polling…")
    # Evita conflicto si quedó webhook viejo
    try:
        bot.remove_webhook()
    except Exception:
        pass
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, allowed_updates=["message","callback_query"])
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
    print(f"🌐 Servidor Flask en 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT)