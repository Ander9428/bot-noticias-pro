import telebot
from flask import Flask
import threading
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from datetime import datetime, timedelta
import time

# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================
TOKEN = 'TU_TOKEN_DE_TELEGRAM'
CHAT_ID = 'TU_CHAT_ID'  # Tu ID de usuario para recibir los mensajes
ZONA_HORARIA = pytz.timezone('America/Bogota')

# Filtro de las divisas que operas en tus análisis técnicos
DIVISAS_OBJETIVO = ["EUR", "USD", "JPY", "GBP", "AUD", "CAD", "CHF"]

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ==========================================
# 1. SISTEMA ANTI-SUSPENSIÓN (FLASK)
# ==========================================
@app.route('/')
def keep_alive():
    return "Servidor del Bot Activo y Sincronizado (UTC-5)."

def run_flask():
    # El puerto 10000 es el estándar que Render asigna a los Web Services
    app.run(host='0.0.0.0', port=10000)

# ==========================================
# 2. ANÁLISIS FUNDAMENTAL (FÁCIL DE ENTENDER)
# ==========================================
def generar_explicacion_fundamental(evento, divisa):
    """
    Entrega una explicación clara, sin jerga innecesaria, de lo que 
    significa la noticia y cómo afecta la liquidez en tus gráficos.
    """
    evento_lower = evento.lower()
    explicacion = ""
    
    if "pib" in evento_lower or "gdp" in evento_lower:
        explicacion = "Mide la salud económica general. Si sale mayor a lo esperado, fortalece la divisa; si sale menor, la debilita. Espera alta volatilidad."
    elif "ipc" in evento_lower or "cpi" in evento_lower or "inflación" in evento_lower:
        explicacion = "Mide el costo de vida. Una inflación alta obliga a los bancos a subir tasas, fortaleciendo la divisa temporalmente pero dañando la economía a largo plazo."
    elif "tasas" in evento_lower or "interest rate" in evento_lower:
        explicacion = "La noticia más fuerte. Si suben las tasas, entra capital extranjero y la divisa se dispara. Si las bajan, el dinero sale a buscar mejores rendimientos."
    elif "nóminas" in evento_lower or "nfp" in evento_lower or "desempleo" in evento_lower:
        explicacion = "Mide la creación de empleo. Un desempleo alto debilita la divisa. Suele generar mechazos violentos en temporalidades de 5m y 15m."
    else:
        explicacion = "Noticia de alto impacto (3 toros). Protege tus posiciones (Breakeven) y espera a que el spread se normalice antes de buscar entradas por Smart Money."
        
    return f"\n🧠 **Análisis Fundamental:** {explicacion}"

# ==========================================
# 3. MOTOR DE ALERTAS (MENSAJES)
# ==========================================
def enviar_alerta(evento, divisa, impacto, tipo_alerta):
    if divisa not in DIVISAS_OBJETIVO:
        return # Ignora divisas como NZD, CNY, etc.

    analisis = generar_explicacion_fundamental(evento, divisa)
    
    if tipo_alerta == "30_MIN":
        mensaje = f"⚠️ **ALERTA: Faltan 30 Minutos** ⚠️\n\n📌 **Noticia:** {evento}\n💱 **Divisa:** {divisa} (Impacto: {impacto})\n{analisis}\n\n*Recomendación:* Revisa si el precio se acerca a tus niveles institucionales (00, 25, 50, 75)."
    elif tipo_alerta == "5_MIN":
        mensaje = f"🚨 **ALERTA INMINENTE: Faltan 5 Minutos** 🚨\n\n📌 **Noticia:** {evento}\n💱 **Divisa:** {divisa}\n\n*Acción:* Asegura Stop Loss, alta probabilidad de deslizamiento (slippage) y manipulación del spread."
    elif tipo_alerta == "AHORA":
        mensaje = f"💥 **NOTICIA PUBLICADA AHORA** 💥\n\n📌 **Noticia:** {evento}\n💱 **Divisa:** {divisa}"
        
    bot.send_message(CHAT_ID, mensaje, parse_mode='Markdown')

# ==========================================
# 4. REPORTE MATUTINO (6:00 AM)
# ==========================================
def reporte_matutino():
    """Se ejecuta todos los días a las 6:00 AM hora Colombia."""
    # AQUÍ DEBES LLAMAR A TU FUNCIÓN DE SCRAPING DE INVESTING/FOREX FACTORY
    # noticias_hoy = tu_funcion_de_extraccion() 
    
    # Ejemplo simulado:
    mensaje = "🌅 **Resumen del Mercado - Alto Impacto (3 Toros)** 🌅\n\n"
    mensaje += "🗓️ Hoy tenemos las siguientes inyecciones de liquidez:\n"
    mensaje += "- 08:30 AM | USD | IPC (Inflación)\n"
    mensaje += "- 02:00 PM | USD | Decisión de Tasas de Interés\n\n"
    mensaje += "Prepara tus sesiones y marca tus bloques de órdenes."
    
    bot.send_message(CHAT_ID, mensaje, parse_mode='Markdown')

# ==========================================
# 5. PROGRAMADOR CRONOLÓGICO (SCHEDULER)
# ==========================================
def programar_eventos():
    scheduler = BackgroundScheduler(timezone=ZONA_HORARIA)
    
    # 1. Programar el reporte de las 6 AM todos los días
    scheduler.add_job(reporte_matutino, 'cron', hour=6, minute=0)
    
    # 2. AQUÍ PROGRAMARÍAS LAS ALERTAS BASADO EN TU SCRAPING
    # Ejemplo de cómo programar una noticia específica de forma dinámica:
    # fecha_noticia = datetime(2026, 9, 10, 14, 0, 0, tzinfo=ZONA_HORARIA) # 2:00 PM
    # scheduler.add_job(enviar_alerta, 'date', run_date=fecha_noticia - timedelta(minutes=30), args=['Decisión de Tasas', 'USD', '3 Toros', '30_MIN'])
    # scheduler.add_job(enviar_alerta, 'date', run_date=fecha_noticia - timedelta(minutes=5), args=['Decisión de Tasas', 'USD', '3 Toros', '5_MIN'])
    
    scheduler.start()

# ==========================================
# EJECUCIÓN PRINCIPAL
# ==========================================
if __name__ == "__main__":
    # Iniciar el programador de tiempo
    programar_eventos()
    
    # Iniciar el servidor web (Flask) en un hilo secundario para evitar bloqueos
    hilo_web = threading.Thread(target=run_flask)
    hilo_web.start()
    
    print("Iniciando Bot de Telegram y Servidor Web...")
    # Iniciar la escucha continua del bot de Telegram
    bot.infinity_polling(timeout=10, long_polling_timeout = 5)
