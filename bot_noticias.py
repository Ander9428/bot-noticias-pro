import os
import requests
import threading
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==========================================
# 1. CREDENCIALES Y CONFIGURACIÓN
# ==========================================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8007552290:AAHH8KQrYklwR6oh8Tjw2_VbUvXs1D8Zd_I")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "848594835")
API_KEY_FMP = os.getenv("FMP_API_KEY", "LVP44JAPKM0cxlSSnWu1BSRCE4ykLQA0")

COLOMBIA_TZ = pytz.timezone("America/Bogota")
scheduler = BlockingScheduler(timezone=COLOMBIA_TZ)

# ==========================================
# 2. SERVIDOR WEB INTERNO (PARA PLAN GRATUITO EN RENDER)
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot de Noticias activo 24/7 en Render Free Tier")

    def log_message(self, format, *args):
        return  # Desactiva logs molestos de HTTP en la consola

def iniciar_servidor_web():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Servidor web escuchando en el puerto {port} (Render Free Tier Activo)")
    server.serve_forever()

# ==========================================
# 3. LÓGICA DEL BOT Y TELEGRAM
# ==========================================
def enviar_telegram(mensaje):
    """Envía un mensaje a Telegram"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        respuesta = requests.post(url, json=payload, timeout=10)
        respuesta.raise_for_status()
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")

def obtener_analisis_fundamental(titulo):
    """Evalúa el evento y retorna el análisis técnico-fundamental en español"""
    titulo_lower = titulo.lower()
    
    if "speaks" in titulo_lower or "powell" in titulo_lower or "testifies" in titulo_lower or "president" in titulo_lower:
        return (
            "🗣️ *ANÁLISIS FUNDAMENTAL (COMPARECENCIA):*\n"
            "Los discursos oficiales generan picos de volatilidad impredecibles. Los algoritmos institucionales leen el texto en vivo buscando pistas.\n"
            "• *Tono Hawkish (Agresivo):* Apoyo a tasas altas o alerta de inflación = *Divisa sube fuerte*.\n"
            "• *Tono Dovish (Suave):* Preocupación por economía o recortes = *Divisa cae*.\n"
            "⚠️ _Precaución: El precio suele hacer movimientos falsos antes de tomar dirección._"
        )
    elif "cpi" in titulo_lower or "inflation" in titulo_lower or "pce" in titulo_lower:
        return (
            "📊 *ANÁLISIS FUNDAMENTAL (INFLACIÓN):*\n"
            "Mide el costo de vida. Es el dato más importante para los bancos centrales.\n"
            "• *Dato mayor al esperado:* Presiona al banco a subir tasas = *Divisa sube*.\n"
            "• *Dato menor al esperado:* Alivia la presión, acerca recortes = *Divisa cae*."
        )
    elif "rate" in titulo_lower or "fund" in titulo_lower:
        return (
            "🏦 *ANÁLISIS FUNDAMENTAL (TASAS DE INTERÉS):*\n"
            "Define qué tan 'atractiva' es la divisa para los inversores extranjeros.\n"
            "• *Subida de tasa:* Atrae capital = *Divisa sube*.\n"
            "• *Corte de tasa:* Aleja capital buscando mejor rendimiento = *Divisa cae*."
        )
    elif "nfp" in titulo_lower or "employment" in titulo_lower or "payrolls" in titulo_lower or "unemployment" in titulo_lower:
        return (
            "💼 *ANÁLISIS FUNDAMENTAL (EMPLEO):*\n"
            "Mide la salud económica. Si hay mucho empleo, hay gasto e inflación.\n"
            "• *Más empleo del esperado:* Economía fuerte = *Divisa sube*.\n"
            "• *Menos empleo (o más desempleo):* Economía débil = *Divisa cae*."
        )
    else:
        return (
            "📊 *ANÁLISIS FUNDAMENTAL:*\n"
            "Dato de alto impacto. Una desviación grande entre el dato 'Actual' y 'Esperado' generará un fuerte desequilibrio institucional.\n"
            "⚠️ _Asegura posiciones y espera a que el mercado absorba la liquidez._"
        )

def enviar_alerta_15_min(evento):
    """Envía la alerta preventiva 15 minutos antes de la noticia"""
    titulo = evento.get("event")
    divisa = evento.get("currency", evento.get("country", "Global"))
    hora = evento.get("hora_formateada")
    
    analisis = obtener_analisis_fundamental(titulo)
    
    mensaje = (
        "🚨 *ALERTA PREVENTIVA (FALTAN 15 MINUTOS)* 🚨\n\n"
        f"🔴 *Divisa:* {divisa}\n"
        f"🏛 *Evento:* {titulo}\n"
        f"⏰ *Hora de Impacto:* {hora} COT\n\n"
        f"{analisis}"
    )
    enviar_telegram(mensaje)

def procesar_rutina_diaria():
    """Consulta la API de FMP a las 6:00 AM y programa las alarmas"""
    print("Revisando el calendario económico institucional...")
    
    ahora_col = datetime.now(COLOMBIA_TZ)
    fecha_hoy = ahora_col.strftime("%Y-%m-%d")
    
    url = f"https://financialmodelingprep.com/api/v3/economic_calendar?from={fecha_hoy}&to={fecha_hoy}&apikey={API_KEY_FMP}"
    
    try:
        respuesta = requests.get(url, timeout=10)
        respuesta.raise_for_status()
        datos = respuesta.json()
        
        eventos_hoy = []
        
        for evento in datos:
            if evento.get("impact") == "High":
                fecha_str = evento.get("date")  # Formato FMP: "YYYY-MM-DD HH:MM:SS" (UTC)
                
                hora_utc = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S")
                hora_utc = pytz.utc.localize(hora_utc)
                hora_colombia = hora_utc.astimezone(COLOMBIA_TZ)
                
                evento['hora_formateada'] = hora_colombia.strftime("%I:%M %p")
                eventos_hoy.append(evento)
                
                # Programar la alarma 15 minutos antes
                hora_alerta = hora_colombia - timedelta(minutes=15)
                
                if hora_alerta > ahora_col:
                    scheduler.add_job(
                        enviar_alerta_15_min,
                        'date',
                        run_date=hora_alerta,
                        args=[evento]
                    )
        
        # Enviar reporte diario matutino
        if len(eventos_hoy) > 0:
            msg_matutino = f"🚨 *REPORTE INSTITUCIONAL DE NOTICIAS* 🚨\n📅 *Fecha:* {fecha_hoy}\n\n⚠️ *Alto Impacto Hoy:*\n\n"
            for ev in eventos_hoy:
                div = ev.get('currency', ev.get('country', 'Global'))
                msg_matutino += f"🔴 *{div}* - {ev['event']}\n⏰ *Hora:* {ev['hora_formateada']} COT\n\n"
            msg_matutino += "💡 _Las alertas con análisis fundamental llegarán 15 minutos antes de cada evento._"
            enviar_telegram(msg_matutino)
        else:
            enviar_telegram("✅ *REPORTE MATUTINO*\n\nHoy no hay noticias de Alto Impacto (Carpeta Roja) programadas. Mercado limpio.")
            
    except Exception as e:
        print(f"Error consultando calendario: {e}")
        enviar_telegram(f"⚠️ Error al conectar con la API de noticias: {e}")

def iniciar_bot():
    # 1. Iniciar servidor web interno en segundo plano para Render Gratis
    threading.Thread(target=iniciar_servidor_web, daemon=True).start()
    
    enviar_telegram("🤖 *Bot de Noticias Pro Iniciado*\nSincronizado con zona horaria UTC-5 (Colombia) en servidor gratuito.")
    
    # 2. Ejecución inmediata
    procesar_rutina_diaria()
    
    # 3. Programación diaria a las 6:00 AM COT
    scheduler.add_job(procesar_rutina_diaria, 'cron', hour=6, minute=0)
    
    print("Bot corriendo 24/7...")
    scheduler.start()

if __name__ == "__main__":
    iniciar_bot()
