import os
import requests
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

# ==========================================
# 1. CREDENCIALES DE TELEGRAM
# Reemplaza 'TU_TOKEN_AQUI' y 'TU_CHAT_ID_AQUI' con tus datos reales
# o usa variables de entorno para mayor seguridad.
# ==========================================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8007552290:AAHH8KQrYklwR6oh8Tjw2_VbUvXs1D8Zd_I")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "848594835")

COLOMBIA_TZ = pytz.timezone("America/Bogota")
scheduler = BlockingScheduler(timezone=COLOMBIA_TZ)

def enviar_telegram(mensaje):
    """Envía el mensaje a Telegram"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        respuesta = requests.post(url, json=payload, timeout=10)
        respuesta.raise_for_status()
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")

def obtener_analisis_fundamental(titulo):
    """Evalúa el evento y retorna el análisis en español"""
    titulo_lower = titulo.lower()
    
    if "speaks" in titulo_lower or "powell" in titulo_lower or "testifies" in titulo_lower or "president" in titulo_lower:
        return (
            "🗣️ *ANÁLISIS FUNDAMENTAL (COMPARECENCIA):*\n"
            "Los discursos oficiales generan picos de volatilidad impredecibles. Los algoritmos institucionales leen el texto en vivo buscando pistas.\n"
            "• *Tono Hawkish (Agresivo):* Apoyo a tasas altas o alerta de inflación = *Divisa sube fuerte*.\n"
            "• *Tono Dovish (Suave):* Preocupación por economía o recortes = *Divisa cae*.\n"
            "⚠️ _Precaución: El precio suele hacer movimientos falsos (barridos de liquidez) antes de tomar dirección._"
        )
    elif "cpi" in titulo_lower or "inflation" in titulo_lower or "pce" in titulo_lower:
        return (
            "📊 *ANÁLISIS FUNDAMENTAL (INFLACIÓN):*\n"
            "Mide el costo de vida. Es el dato más importante para los bancos centrales.\n"
            "• *Dato mayor al esperado:* Presiona al banco a subir/mantener tasas = *Divisa sube*.\n"
            "• *Dato menor al esperado:* Alivia la presión, acerca recortes de tasas = *Divisa cae*."
        )
    elif "rate" in titulo_lower or "fund" in titulo_lower:
        return (
            "🏦 *ANÁLISIS FUNDAMENTAL (TASAS DE INTERÉS):*\n"
            "Define qué tan 'atractiva' es la divisa para los inversores extranjeros.\n"
            "• *Subida de tasa (o mantención inesperada):* Atrae capital = *Divisa sube*.\n"
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
    """Envía la alerta preventiva estructurada"""
    titulo = evento.get("title")
    divisa = evento.get("country")
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
    """Consulta el calendario a las 6:00 AM y programa las alertas del día"""
    print("Revisando el calendario económico de hoy...")
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    try:
        respuesta = requests.get(url, headers=headers, timeout=10)
        respuesta.raise_for_status()
        datos = respuesta.json()
        
        ahora_col = datetime.now(COLOMBIA_TZ)
        fecha_hoy = ahora_col.strftime("%Y-%m-%d")
        
        eventos_hoy = []
        
        for evento in datos:
            fecha_evento = evento.get("date", "")
            if evento.get("impact") == "High" and fecha_evento.startswith(fecha_hoy):
                # Formatear la cadena ISO para asegurar compatibilidad con la zona horaria UTC
                if fecha_evento.endswith("Z"):
                    fecha_evento = fecha_evento[:-1] + "+00:00"
                
                hora_utc = datetime.fromisoformat(fecha_evento)
                hora_colombia = hora_utc.astimezone(COLOMBIA_TZ)
                
                evento['hora_formateada'] = hora_colombia.strftime("%I:%M %p")
                eventos_hoy.append(evento)
                
                # Programar la alarma 15 minutos antes
                hora_alerta = hora_colombia - timedelta(minutes=15)
                
                # Solo programa si la hora de la alerta aún no ha pasado
                if hora_alerta > ahora_col:
                    scheduler.add_job(
                        enviar_alerta_15_min, 
                        'date', 
                        run_date=hora_alerta, 
                        args=[evento]
                    )
        
        # Enviar el resumen matutino con la lista de eventos
        if len(eventos_hoy) > 0:
            msg_matutino = f"🚨 *REPORTE INSTITUCIONAL DE NOTICIAS* 🚨\n📅 *Fecha:* {fecha_hoy}\n\n⚠️ *Alto Impacto Hoy:*\n\n"
            for ev in eventos_hoy:
                msg_matutino += f"🔴 *{ev['country']}* - {ev['title']}\n⏰ *Hora:* {ev['hora_formateada']} COT\n\n"
            msg_matutino += "💡 _Las alertas con análisis fundamental llegarán 15 minutos antes de cada evento._"
            enviar_telegram(msg_matutino)
        else:
            enviar_telegram("✅ *REPORTE MATUTINO*\n\nHoy no hay noticias de Alto Impacto (Carpeta Roja) programadas. Mercado limpio.")
            
    except Exception as e:
        print(f"Error consultando calendario: {e}")
        enviar_telegram(f"⚠️ Error al conectar con el calendario económico: {e}")

def iniciar_bot():
    enviar_telegram("🤖 *Bot de Noticias Pro Iniciado*\nSincronizado con zona horaria UTC-5 (Colombia). El bot está activo y monitoreando el mercado.")
    
    # 1. Ejecutar de inmediato al arrancar el servidor
    procesar_rutina_diaria()
    
    # 2. Programar la rutina a las 6:00 AM para los días siguientes
    scheduler.add_job(procesar_rutina_diaria, 'cron', hour=6, minute=0)
    
    print("Bot corriendo 24/7...")
    scheduler.start()

if __name__ == "__main__":
    iniciar_bot()
