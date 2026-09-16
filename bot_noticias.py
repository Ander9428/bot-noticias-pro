"""
════════════════════════════════════════════════════════════════════════════
 BOT DE TELEGRAM · CALENDARIO ECONÓMICO CON ANÁLISIS FUNDAMENTAL REAL
════════════════════════════════════════════════════════════════════════════

QUÉ CAMBIÉ RESPECTO A TU CÓDIGO ORIGINAL (para que sepas qué esperar):

  1. TU SCRAPING NUNCA EXISTÍA. La función `tu_funcion_de_extraccion()` era
     un comentario, nunca se llamaba a nada. El bot no tenía forma real de
     saber qué noticias hay ni cuándo. Ahora se conecta a un calendario
     económico real (el feed JSON que usa ForexFactory, de acceso público)
     y lo vuelve a consultar cada hora para mantenerse actualizado.

  2. EL "ANÁLISIS FUNDAMENTAL" ERA UN TEXTO FIJO. Decía lo mismo sin
     importar si el dato salió bien o mal. Ahora hay dos analisis:
       - Uno EDUCATIVO antes del dato (qué es, por qué importa) - se amplió
         de 4 a 12 categorías de noticia.
       - Uno REAL después del dato: compara el resultado (actual) contra
         lo esperado (pronóstico) y contra el dato anterior, y te dice si
         eso es alcista o bajista para la divisa Y POR QUÉ, con la lógica
         economica correcta (ej: el desempleo funciona al revés que el PIB).

  3. NO HABÍA PROGRAMACIÓN DINÁMICA REAL. El código de ejemplo mostraba
     "así programarías una noticia" pero comentado, a mano, una por una.
     Ahora un job de sincronización lee el calendario y programa TODAS las
     noticias de alto impacto de tus divisas automáticamente, sin que
     tengas que tocar el código cada semana.

  4. SIN ESO, EL REPORTE DE LAS 6 AM ERA INVENTADO (texto simulado con
     fechas fijas). Ahora arma la lista real del día consultando el
     calendario.

  5. TOKEN Y CHAT_ID iban escritos en el código. Si subes esto a GitHub así,
     cualquiera puede usar tu bot y gastar tu cuota de Telegram. Ahora se
     leen de variables de entorno (nunca se escriben en el archivo).

  6. Se evita mandar la MISMA alerta dos veces si el proceso se reinicia
     (Render reinicia los Web Services gratuitos con frecuencia): se
     guarda un registro en disco de qué ya se programó.

LO QUE SIGUE IGUAL, A PROPÓSITO: Flask como "keep-alive" para Render,
APScheduler para programar, pytz para la zona horaria de Colombia,
polling de Telegram al final. Es tu misma arquitectura, solo que ahora
hace lo que el comentario decía que hacía.

════════════════════════════════════════════════════════════════════════════
 CONFIGURACIÓN NECESARIA (variables de entorno, NO las escribas en el código)
════════════════════════════════════════════════════════════════════════════
  TELEGRAM_TOKEN   -> el token que te da @BotFather
  TELEGRAM_CHAT_ID -> tu ID numérico de Telegram (te lo da @userinfobot)

  En Render: Dashboard -> tu servicio -> Environment -> Add Environment
  Variable. En tu máquina para probar: crea un archivo ".env" (no lo subas
  a GitHub, agrégalo a .gitignore) o expórtalas en la terminal:
      $env:TELEGRAM_TOKEN = "123456:ABC..."      (PowerShell)
      export TELEGRAM_TOKEN="123456:ABC..."      (Linux/Mac)

  requirements.txt necesita (te dejo el archivo aparte, revísalo):
      pyTelegramBotAPI
      flask
      apscheduler
      pytz
      requests
════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import json
import time
import logging
import threading
from datetime import datetime, timedelta

import pytz
import requests
import telebot
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# ══════════════════════════════════════════════════════════════════════════
# 1. CONFIGURACIÓN GENERAL
# ══════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("bot_forex")

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

if not TOKEN or not CHAT_ID:
    raise SystemExit(
        "Faltan las variables de entorno TELEGRAM_TOKEN y/o TELEGRAM_CHAT_ID.\n"
        "Configúralas antes de arrancar el bot (ver la cabecera de este archivo)."
    )

ZONA_HORARIA = pytz.timezone("America/Bogota")

# Divisas que te interesan en tus análisis técnicos
DIVISAS_OBJETIVO = {"EUR", "USD", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"}

# Qué tan fuerte debe ser una noticia para que te avise. El feed usa
# "High" / "Medium" / "Low" / "Holiday". "High" son los "3 toros" de
# ForexFactory. Pon también "Medium" si quieres más cobertura.
IMPACTOS_A_MONITOREAR = {"High"}

# Fuente del calendario económico. Es el feed JSON público que usa
# ForexFactory para su propio calendario (lo consumen decenas de bots y
# paneles de trading, no es un endpoint privado ni requiere autenticación).
# Si algún día cambia de dirección, este es el único lugar que hay que tocar.
URL_CALENDARIO = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Minutos de anticipación de cada aviso antes del evento.
# El primer aviso llega 15 minutos antes (pediste ese margen); el segundo,
# 5 minutos antes, como último recordatorio urgente.
AVISOS_PREVIOS_MIN = [15, 5]

# MEDIDO EN VIVO: se revisaron eventos de alto impacto ya publicados (uno de
# hace 39 horas) y el feed público TODAVÍA no traía el dato "actual". No es
# fiable asumir que el resultado aparece a los 3 minutos. Por eso, en vez de
# revisar una sola vez, se reintenta varias veces con espaciado creciente
# durante media hora; se manda el mensaje en cuanto el dato aparece, o al
# final de la ventana se avisa honestamente que no llegó (en vez de fingir
# que sí hay comparación, o quedarse callado para siempre).
REINTENTOS_REACCION_MIN = [3, 8, 15, 30]

# Cada cuánto se vuelve a consultar el calendario para detectar noticias
# nuevas o cambios de pronóstico (en minutos).
INTERVALO_SINCRONIZACION_MIN = 60

# Dónde se guarda el registro de qué ya se programó, para no duplicar
# avisos si el proceso se reinicia (Render reinicia los free services).
ARCHIVO_ESTADO = "estado_calendario.json"

bot = telebot.TeleBot(TOKEN, parse_mode=None)
app = Flask(__name__)

# Estado en memoria compartido con el endpoint de salud de Flask, solo
# para poder ver desde el navegador que el bot está vivo y qué vio.
_estado_salud = {
    "arranque": datetime.now(ZONA_HORARIA).isoformat(),
    "ultima_sincronizacion": None,
    "eventos_detectados_hoy": 0,
    "avisos_programados_activos": 0,
    "ultimo_error": None,
}


# ══════════════════════════════════════════════════════════════════════════
# 2. PERSISTENCIA SIMPLE (evita mandar el mismo aviso dos veces)
# ══════════════════════════════════════════════════════════════════════════
def _cargar_estado_disco():
    if not os.path.exists(ARCHIVO_ESTADO):
        return {"programados": []}
    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("No se pudo leer %s (%s); se empieza de cero.", ARCHIVO_ESTADO, e)
        return {"programados": []}


def _guardar_estado_disco(estado):
    try:
        with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning("No se pudo guardar %s: %s", ARCHIVO_ESTADO, e)


def _clave_evento(evento_id):
    """ID único y estable de un evento: título+divisa+fecha exacta."""
    return evento_id


def _ya_programado(estado, clave):
    return clave in estado["programados"]


def _marcar_programado(estado, clave):
    estado["programados"].append(clave)
    # Se conservan solo las últimas 500 claves para que el archivo no
    # crezca sin límite; con eso sobra para varias semanas de cobertura.
    estado["programados"] = estado["programados"][-500:]
    _guardar_estado_disco(estado)


# ══════════════════════════════════════════════════════════════════════════
# 3. SISTEMA ANTI-SUSPENSIÓN (FLASK)
# ══════════════════════════════════════════════════════════════════════════
@app.route("/")
def keep_alive():
    return (
        "Bot de calendario económico activo (America/Bogota).\n"
        f"Arrancó: {_estado_salud['arranque']}\n"
        f"Última sincronización del calendario: {_estado_salud['ultima_sincronizacion']}\n"
        f"Eventos de alto impacto detectados hoy: {_estado_salud['eventos_detectados_hoy']}\n"
        f"Avisos con hora ya programada: {_estado_salud['avisos_programados_activos']}\n"
        f"Último error: {_estado_salud['ultimo_error']}\n"
    )


def run_flask():
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=puerto)


# ══════════════════════════════════════════════════════════════════════════
# 4. OBTENCIÓN DEL CALENDARIO ECONÓMICO REAL
# ══════════════════════════════════════════════════════════════════════════
def obtener_calendario():
    """
    Descarga el calendario económico de la semana en curso y devuelve una
    lista de diccionarios ya normalizados. Cada entrada del feed trae:
    title, country, date (ISO con offset horario), impact, forecast,
    previous, actual (vacío mientras no se haya publicado el dato).

    Si la descarga falla (caída del servicio, sin internet, etc.) se
    devuelve una lista vacía y se registra el error, para que el bot no
    se caiga por un problema de red pasajero.
    """
    try:
        respuesta = requests.get(
            URL_CALENDARIO,
            headers={"User-Agent": "Mozilla/5.0 (bot de alertas personal)"},
            timeout=20,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        log.error("No se pudo descargar el calendario económico: %s", e)
        _estado_salud["ultimo_error"] = f"calendario: {e}"
        return []

    eventos = []
    for item in datos:
        fecha_texto = item.get("date")
        if not fecha_texto:
            continue
        try:
            fecha = datetime.fromisoformat(fecha_texto)
        except ValueError:
            # Formato inesperado en esa fila puntual: se ignora esa fila,
            # no todo el calendario.
            continue
        if fecha.tzinfo is None:
            fecha = pytz.utc.localize(fecha)

        eventos.append(
            {
                "titulo": (item.get("title") or "").strip(),
                "divisa": (item.get("country") or "").strip().upper(),
                "impacto": (item.get("impact") or "").strip(),
                "fecha": fecha,
                "pronostico": (item.get("forecast") or "").strip(),
                "anterior": (item.get("previous") or "").strip(),
                "actual": (item.get("actual") or "").strip(),
            }
        )
    return eventos


def eventos_relevantes(eventos, solo_hoy=False):
    """Filtra por divisa objetivo, impacto configurado y, si se pide,
    que caigan en el día de hoy (hora de Colombia)."""
    ahora_bogota = datetime.now(ZONA_HORARIA)
    resultado = []
    for ev in eventos:
        if ev["divisa"] not in DIVISAS_OBJETIVO:
            continue
        if ev["impacto"] not in IMPACTOS_A_MONITOREAR:
            continue
        if solo_hoy:
            fecha_bogota = ev["fecha"].astimezone(ZONA_HORARIA)
            if fecha_bogota.date() != ahora_bogota.date():
                continue
        resultado.append(ev)
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# 5. ANÁLISIS FUNDAMENTAL — motor de clasificación y explicación
# ══════════════════════════════════════════════════════════════════════════
# Cada categoría define:
#   claves         -> palabras que identifican el titular de la noticia
#   nombre         -> nombre limpio en español para mostrar
#   alcista_si_sube -> True si un dato MEJOR de lo esperado fortalece la
#                      divisa (la inmensa mayoría). False en los pocos
#                      indicadores "inversos" (desempleo, solicitudes de
#                      subsidio): un número más alto ahí es MALA noticia.
#   explicacion    -> qué es y por qué mueve el mercado, en criollo
#   razon_alcista / razon_bajista -> el mecanismo económico concreto que
#                      conecta el resultado con el movimiento de la divisa,
#                      para no repetir la misma frase en toda noticia.
CATEGORIAS = {
    "tasas": {
        "claves": [
            "tasa de interés", "tasas de interés", "interest rate",
            "tipo de interés", "fomc statement", "boe rate", "ecb rate",
            "rba rate", "boc rate", "snb rate", "rate decision",
            "decisión de tasas", "decisión de tipos",
        ],
        "nombre": "Decisión de tasas de interés",
        "alcista_si_sube": True,
        "explicacion": (
            "Es la noticia de mayor peso del calendario. Una tasa más alta "
            "atrae capital extranjero que busca mejor rendimiento en bonos "
            "y depósitos de esa divisa; una tasa más baja lo espanta hacia "
            "otras monedas. El comunicado y la rueda de prensa posterior "
            "suelen moverse el par más que la cifra en sí."
        ),
        "razon_alcista": (
            "al subir (o mantenerse más restrictiva de lo esperado) atrae "
            "capital que persigue mejor rendimiento, lo que fortalece la divisa"
        ),
        "razon_bajista": (
            "al bajar (o suavizarse el tono) reduce el atractivo de mantener "
            "esa divisa frente a otras con mejor rendimiento, y suele debilitarla"
        ),
    },
    "pib": {
        "claves": ["pib", "gdp", "producto interno bruto"],
        "nombre": "Producto Interno Bruto (PIB)",
        "alcista_si_sube": True,
        "explicacion": (
            "Mide cuánto creció (o se contrajo) la economía en el periodo. "
            "Es un termómetro general: una economía que crece más de lo "
            "esperado da margen al banco central para mantener tasas altas "
            "sin temor a frenar demasiado la actividad."
        ),
        "razon_alcista": "una economía más fuerte de lo esperado da margen al banco central para sostener tasas altas, lo que favorece a la divisa",
        "razon_bajista": "un crecimiento más débil de lo esperado presiona a que el banco central relaje su política, lo que suele debilitar la divisa",
    },
    "ipc": {
        "claves": [
            "ipc", "cpi", "inflación", "pce", "índice de precios",
            "precios al consumidor", "ppi", "producer price",
            "índice de precios al productor",
        ],
        "nombre": "Inflación (IPC / PCE / PPI)",
        "alcista_si_sube": True,
        "explicacion": (
            "Mide cuánto subió el costo de vida. Una inflación por encima de "
            "lo esperado presiona al banco central a mantener o subir tasas "
            "para enfriar la economía, lo cual en el corto plazo suele "
            "fortalecer la divisa aunque sea una mala noticia para la "
            "economía real."
        ),
        "razon_alcista": "una inflación más alta de lo esperado aumenta la presión para que el banco central mantenga tasas altas, lo que fortalece la divisa en el corto plazo",
        "razon_bajista": "una inflación más baja de lo esperado abre la puerta a recortes de tasas, lo que suele debilitar la divisa",
    },
    "desempleo_tasa": {
        "claves": ["tasa de desempleo", "unemployment rate"],
        "nombre": "Tasa de desempleo",
        "alcista_si_sube": False,  # indicador inverso
        "explicacion": (
            "Este es de los indicadores que funcionan AL REVÉS: un número "
            "más ALTO de lo esperado es una mala noticia (más gente sin "
            "trabajo), no una buena. Un mercado laboral débil presiona al "
            "banco central a bajar tasas."
        ),
        "razon_alcista": "una tasa de desempleo más baja de lo esperado muestra un mercado laboral fuerte, lo que sostiene expectativas de tasas altas y fortalece la divisa",
        "razon_bajista": "una tasa de desempleo más alta de lo esperado muestra un mercado laboral débil, lo que presiona a bajar tasas y suele debilitar la divisa",
    },
    "solicitudes_desempleo": {
        "claves": [
            "solicitudes de desempleo", "solicitudes por desempleo",
            "jobless claims", "unemployment claims",
            "subsidio por desempleo", "claimant count",
        ],
        "nombre": "Solicitudes de subsidio por desempleo",
        "alcista_si_sube": False,  # indicador inverso
        "explicacion": (
            "Cuenta cuánta gente nueva pidió el seguro de desempleo esa "
            "semana. También es inverso: MÁS solicitudes de las esperadas "
            "es una señal de que el mercado laboral se está enfriando, "
            "no una buena noticia."
        ),
        "razon_alcista": "menos solicitudes de las esperadas confirma un mercado laboral sólido, lo que favorece a la divisa",
        "razon_bajista": "más solicitudes de las esperadas es señal temprana de enfriamiento laboral, lo que suele pesar sobre la divisa",
    },
    "empleo": {
        "claves": [
            "nóminas", "nfp", "payroll", "nonfarm", "non-farm",
            "cambio de empleo", "creación de empleo", "empleo no agrícola",
            "employment change",
        ],
        "nombre": "Creación de empleo (Nóminas no agrícolas / NFP)",
        "alcista_si_sube": True,
        "explicacion": (
            "Mide cuántos puestos de trabajo nuevos se crearon. Un mercado "
            "laboral fuerte sostiene el consumo y da margen al banco "
            "central para no bajar tasas. Es de las noticias que más "
            "mechas violentas genera en 1m y 5m nada más publicarse."
        ),
        "razon_alcista": "más empleos de los esperados confirma una economía sólida y sostiene expectativas de tasas altas, lo que fortalece la divisa",
        "razon_bajista": "menos empleos de los esperados es señal de debilidad económica y anticipa una postura más laxa del banco central, lo que suele debilitar la divisa",
    },
    "pmi": {
        "claves": [
            "pmi", "ism", "índice de gerentes de compra",
            "actividad manufacturera", "actividad de servicios",
        ],
        "nombre": "PMI / ISM (actividad manufacturera o de servicios)",
        "alcista_si_sube": True,
        "explicacion": (
            "Encuesta a gerentes de compra sobre si el negocio mejora o "
            "empeora. Por encima de 50 significa expansión, por debajo "
            "contracción. Se adelanta varias semanas a los datos oficiales "
            "de PIB, por eso el mercado le presta atención."
        ),
        "razon_alcista": "un PMI mejor de lo esperado (o por encima de 50) señala expansión económica, lo que favorece a la divisa",
        "razon_bajista": "un PMI peor de lo esperado (o por debajo de 50) señala contracción, lo que suele pesar sobre la divisa",
    },
    "ventas_minoristas": {
        "claves": ["ventas minoristas", "retail sales"],
        "nombre": "Ventas minoristas",
        "alcista_si_sube": True,
        "explicacion": (
            "Mide el gasto de los consumidores, que en la mayoría de "
            "economías desarrolladas es el motor principal del PIB. "
            "Un consumidor que gasta más de lo esperado es señal de "
            "confianza económica."
        ),
        "razon_alcista": "un consumo mayor al esperado sostiene el crecimiento económico, lo que favorece a la divisa",
        "razon_bajista": "un consumo menor al esperado anticipa un crecimiento más débil, lo que suele pesar sobre la divisa",
    },
    "balanza_comercial": {
        "claves": ["balanza comercial", "trade balance"],
        "nombre": "Balanza comercial",
        "alcista_si_sube": True,
        "explicacion": (
            "La diferencia entre lo que un país exporta e importa. Un "
            "superávit mayor (o un déficit menor) al esperado significa "
            "que entra más dinero extranjero al país del que sale, lo que "
            "en teoría respalda la divisa, aunque su efecto suele ser más "
            "moderado que el de empleo o inflación."
        ),
        "razon_alcista": "un mejor saldo comercial de lo esperado implica más entrada neta de divisas extranjeras",
        "razon_bajista": "un peor saldo comercial de lo esperado implica más salida neta de divisas, lo que puede presionar a la baja",
    },
    "confianza_consumidor": {
        "claves": [
            "confianza del consumidor", "consumer confidence",
            "sentimiento del consumidor", "consumer sentiment",
        ],
        "nombre": "Confianza / sentimiento del consumidor",
        "alcista_si_sube": True,
        "explicacion": (
            "Encuesta directa a los hogares sobre cómo ven su situación "
            "económica. Un consumidor optimista tiende a gastar más en los "
            "meses siguientes, así que el dato se usa como adelanto del "
            "consumo real."
        ),
        "razon_alcista": "un consumidor más optimista de lo esperado anticipa mayor gasto futuro, lo que favorece a la divisa",
        "razon_bajista": "un consumidor más pesimista de lo esperado anticipa menor gasto futuro, lo que suele pesar sobre la divisa",
    },
    "vivienda": {
        "claves": [
            "vivienda", "housing", "permisos de construcción",
            "building permits", "housing starts", "inicios de construcción",
        ],
        "nombre": "Sector vivienda",
        "alcista_si_sube": True,
        "explicacion": (
            "El sector inmobiliario es de los más sensibles a las tasas de "
            "interés, así que sirve como termómetro indirecto de qué tanto "
            "está enfriando (o no) la política monetaria a la economía real."
        ),
        "razon_alcista": "más actividad de la esperada en vivienda sugiere que la economía tolera bien las tasas actuales",
        "razon_bajista": "menos actividad de la esperada en vivienda sugiere que las tasas altas ya están frenando la economía",
    },
    "discurso": {
        "claves": [
            "discurso", "habla", "speech", "testimonio", "testimony",
            "conferencia de prensa", "press conference", "comparece",
        ],
        "nombre": "Discurso o comparecencia de un banquero central",
        "alcista_si_sube": None,  # no aplica comparación numérica
        "explicacion": (
            "No trae una cifra que comparar: el movimiento depende del TONO. "
            "Si suena más duro de lo esperado sobre la inflación (\"hawkish\"), "
            "suele fortalecer la divisa. Si suena más preocupado por el "
            "crecimiento y abierto a bajar tasas (\"dovish\"), suele "
            "debilitarla. Se recomienda leer el titular de la noticia en "
            "vivo en vez de operar a ciegas apenas empieza a hablar."
        ),
        "razon_alcista": None,
        "razon_bajista": None,
    },
    "actas": {
        "claves": ["actas", "minutes", "fomc minutes"],
        "nombre": "Actas de la última reunión del banco central",
        "alcista_si_sube": None,
        "explicacion": (
            "Es el detalle de la discusión interna de la última reunión de "
            "tasas. No trae cifra que comparar: lo que mueve el mercado es "
            "si el texto revela más o menos preocupación por la inflación "
            "de lo que el mercado ya tenía asumido."
        ),
        "razon_alcista": None,
        "razon_bajista": None,
    },
}

CATEGORIA_DEFECTO = {
    "nombre": "Noticia de alto impacto",
    "alcista_si_sube": None,
    "explicacion": (
        "No es uno de los indicadores más comunes, pero el calendario la "
        "marca como de alto impacto (\"3 toros\"). Trátala con el mismo "
        "respeto: protege posiciones abiertas y espera a que el spread se "
        "normalice antes de buscar entradas nuevas."
    ),
    "razon_alcista": None,
    "razon_bajista": None,
}


def clasificar_evento(titulo):
    """Identifica a qué categoría económica pertenece el titular de la
    noticia, comparando por palabras clave. Si no reconoce ninguna,
    devuelve la categoría por defecto (sigue tratándose como noticia
    de alto impacto, solo que sin la explicación específica)."""
    titulo_normalizado = titulo.lower()
    for datos in CATEGORIAS.values():
        if any(clave in titulo_normalizado for clave in datos["claves"]):
            return datos
    return CATEGORIA_DEFECTO


def _a_numero(texto):
    """Convierte '3.2%', '170K', '-0.4B', '1,234' a un float comparable.
    Se asume que actual/pronóstico/anterior del MISMO evento comparten
    unidad y sufijo, así que basta con quitarlos igual en ambos lados
    antes de restar. Devuelve None si no se puede interpretar (dato aún
    no publicado, o formato inesperado)."""
    if not texto:
        return None
    limpio = texto.strip().replace("%", "").replace(",", "")
    limpio = limpio.rstrip("KMB")
    try:
        return float(limpio)
    except ValueError:
        return None


def analizar_resultado(evento):
    """
    Compara el dato PUBLICADO contra el PRONÓSTICO y arma una lectura
    fundamentada, no un texto genérico. Devuelve None si el dato todavía
    no se ha publicado o la categoría no admite comparación numérica
    (discursos, actas).
    """
    categoria = clasificar_evento(evento.get("titulo", ""))
    if categoria.get("alcista_si_sube") is None:
        return None

    actual = _a_numero(evento.get("actual"))
    pronostico = _a_numero(evento.get("pronostico"))
    if actual is None or pronostico is None:
        return None

    diferencia = actual - pronostico
    if abs(diferencia) < 1e-9:
        return {
            "resultado_txt": "salió exactamente en línea con lo esperado",
            "direccion": "neutral",
            "razon": (
                "sin sorpresa frente al pronóstico, no debería generar un "
                "movimiento direccional fuerte por sí solo"
            ),
        }

    salio_por_encima = diferencia > 0
    es_alcista = salio_por_encima if categoria["alcista_si_sube"] else not salio_por_encima
    razon = categoria["razon_alcista"] if es_alcista else categoria["razon_bajista"]

    return {
        "resultado_txt": (
            "salió por ENCIMA de lo esperado" if salio_por_encima
            else "salió por DEBAJO de lo esperado"
        ),
        "direccion": "alcista" if es_alcista else "bajista",
        "razon": razon,
    }


# ══════════════════════════════════════════════════════════════════════════
# 6. CONSTRUCCIÓN DE MENSAJES  ·  todo en español, incluido lo que el feed
#    entrega en inglés (nivel de impacto y nombre de la noticia)
# ══════════════════════════════════════════════════════════════════════════
_IMPACTO_ES = {
    "High": "Alto", "Medium": "Medio", "Low": "Bajo", "Holiday": "Festivo",
}


def traducir_impacto(impacto):
    """'High' -> 'Alto', etc. Si el feed manda algo que no se reconoce, se
    muestra tal cual en vez de dejarlo en blanco."""
    return _IMPACTO_ES.get(impacto, impacto)


# Traducción del NOMBRE de la noticia. El feed (ForexFactory) entrega los
# títulos siempre en inglés y no hay forma de pedírselos en español. Esta
# lista cubre los ~45 indicadores de alto impacto que se repiten cada
# semana o cada mes para cualquier país (PIB, IPC, tasas, empleo, PMI...),
# que es prácticamente todo lo que vas a recibir en la práctica.
#
# HONESTIDAD: un indicador rarísimo que no esté en esta lista se queda con
# su nombre original en inglés (no se inventa una traducción). Aun así, la
# explicación de "Análisis Fundamental" debajo del título SIEMPRE está en
# español, así que nunca te quedas sin saber qué significa la noticia.
#
# El orden importa: los patrones MÁS ESPECÍFICOS van primero (ej. "Core CPI"
# antes que "CPI"), porque una vez que "CPI" se reemplaza por "IPC", el
# patrón de "Core CPI" ya no encontraría la palabra "CPI" para matchear.
_TRADUCCIONES_TITULO = [
    (r"\bADP Non-Farm Employment Change\b", "Cambio de Empleo ADP (sector privado)"),
    (r"\bNon-Farm Employment Change\b", "Cambio de Empleo No Agrícola"),
    (r"\bNon-Farm Payrolls\b", "Nóminas No Agrícolas"),
    (r"\bEmployment Change\b", "Cambio en el Empleo"),
    (r"\bAverage Hourly Earnings\b", "Ingreso Medio por Hora"),
    (r"\bUnemployment Claims\b", "Solicitudes de Subsidio por Desempleo"),
    (r"\bInitial Jobless Claims\b", "Solicitudes Iniciales de Subsidio por Desempleo"),
    (r"\bContinuing Jobless Claims\b", "Solicitudes Continuas de Subsidio por Desempleo"),
    (r"\bClaimant Count Change\b", "Cambio en Solicitudes de Desempleo"),
    (r"\bUnemployment Rate\b", "Tasa de Desempleo"),
    (r"\bCore PCE Price Index\b", "Índice de Precios PCE Subyacente"),
    (r"\bPCE Price Index\b", "Índice de Precios PCE"),
    (r"\bMedian CPI\b", "IPC Mediano"),
    (r"\bTrimmed CPI\b", "IPC Recortado"),
    (r"\bCore CPI\b", "IPC Subyacente"),
    (r"\bCPI\b", "IPC"),
    (r"\bProducer Price Index\b", "Índice de Precios al Productor"),
    (r"\bPPI\b", "IPP"),
    (r"\bPrelim GDP\b", "PIB Preliminar"),
    (r"\bFinal GDP\b", "PIB Final"),
    (r"\bGDP\b", "PIB"),
    (r"\bCore Retail Sales\b", "Ventas Minoristas Subyacentes"),
    (r"\bRetail Sales\b", "Ventas Minoristas"),
    (r"\bTrade Balance\b", "Balanza Comercial"),
    (r"\bCurrent Account\b", "Cuenta Corriente"),
    (r"\bConsumer Confidence\b", "Confianza del Consumidor"),
    (r"\bConsumer Sentiment\b", "Sentimiento del Consumidor"),
    (r"\bBusiness Confidence\b", "Confianza Empresarial"),
    (r"\bEconomic Sentiment\b", "Sentimiento Económico"),
    (r"\bBuilding Permits\b", "Permisos de Construcción"),
    (r"\bHousing Starts\b", "Inicios de Construcción de Viviendas"),
    (r"\bExisting Home Sales\b", "Ventas de Viviendas Existentes"),
    (r"\bNew Home Sales\b", "Ventas de Viviendas Nuevas"),
    (r"\bISM Manufacturing PMI\b", "PMI Manufacturero ISM"),
    (r"\bISM Services PMI\b", "PMI de Servicios ISM"),
    (r"\bManufacturing PMI\b", "PMI Manufacturero"),
    (r"\bServices PMI\b", "PMI de Servicios"),
    (r"\bComposite PMI\b", "PMI Compuesto"),
    (r"\bInterest Rate Decision\b", "Decisión de Tipos de Interés"),
    (r"\bFederal Funds Rate\b", "Tasa de Fondos Federales"),
    (r"\bOfficial Bank Rate\b", "Tasa Oficial del Banco"),
    (r"\bOvernight Rate\b", "Tasa Overnight"),
    (r"\bCash Rate\b", "Tasa de Efectivo"),
    (r"\bFOMC Statement\b", "Comunicado del FOMC"),
    (r"\bFOMC Meeting Minutes\b", "Actas de la Reunión del FOMC"),
    (r"\bFOMC Press Conference\b", "Rueda de Prensa del FOMC"),
    (r"\bMonetary Policy Statement\b", "Comunicado de Política Monetaria"),
    (r"\bMonetary Policy Report\b", "Informe de Política Monetaria"),
    (r"\bRate Statement\b", "Comunicado de Tasas"),
    (r"\bPress Conference\b", "Rueda de Prensa"),
    (r"\bSpeaks\b", "habla"),
    (r"\bSpeech\b", "Discurso"),
    (r"\bTestimony\b", "Comparecencia"),
    (r"\bIndustrial Production\b", "Producción Industrial"),
    (r"\bFactory Orders\b", "Pedidos de Fábrica"),
    (r"\bCore Durable Goods Orders\b", "Pedidos de Bienes Duraderos Subyacentes"),
    (r"\bDurable Goods Orders\b", "Pedidos de Bienes Duraderos"),
    (r"\bWholesale Inventories\b", "Inventarios Mayoristas"),
    # Adjetivos de país que suelen ir delante del nombre del indicador
    # (ej. "German ZEW Economic Sentiment"). Van al final porque son
    # palabras sueltas genéricas, no frases completas del indicador.
    (r"\bGerman\b", "Alemán"),
    (r"\bFrench\b", "Francés"),
    (r"\bItalian\b", "Italiano"),
    (r"\bSpanish\b", "Español"),
    (r"\bChinese\b", "Chino"),
    (r"\bAustralian\b", "Australiano"),
    (r"\bCanadian\b", "Canadiense"),
    (r"\bBritish\b", "Británico"),
    (r"\bSwiss\b", "Suizo"),
    (r"\bJapanese\b", "Japonés"),
]
_TRADUCCIONES_TITULO_COMPILADAS = [
    (re.compile(patron, re.IGNORECASE), reemplazo)
    for patron, reemplazo in _TRADUCCIONES_TITULO
]


def traducir_titulo(titulo):
    """Traduce las partes reconocidas del título. Lo que no reconoce lo
    deja en inglés (mejor eso que inventar una traducción incorrecta)."""
    resultado = titulo or ""
    for patron, reemplazo in _TRADUCCIONES_TITULO_COMPILADAS:
        resultado = patron.sub(reemplazo, resultado)
    return resultado


def _escapar(texto):
    """Telegram (modo Markdown clásico) rompe el mensaje si el texto trae
    guiones bajos o asteriscos sueltos (frecuente en títulos de noticias
    en inglés, ej. 'Non-Farm_Payrolls'). Se neutralizan para que el envío
    nunca falle por esto."""
    return (texto or "").replace("_", "-").replace("*", "").replace("`", "'")


def mensaje_previo(evento, minutos):
    """
    OJO: antes esta función tenía el texto "faltan 30 minutos" escrito a
    mano. Si cambiabas AVISOS_PREVIOS_MIN, el número de la config cambiaba
    pero el MENSAJE seguía diciendo "30" por dentro, mintiendo sobre el
    tiempo real. Ahora el número sale siempre de la variable `minutos`,
    así que un cambio en AVISOS_PREVIOS_MIN se refleja automáticamente en
    el texto que llega a Telegram.
    """
    categoria = clasificar_evento(evento["titulo"])
    titulo = _escapar(traducir_titulo(evento["titulo"]))
    hora_local = evento["fecha"].astimezone(ZONA_HORARIA).strftime("%H:%M")

    # El aviso más urgente es el que tiene MENOS minutos de anticipación
    # (el "último recordatorio"), sea cual sea el valor configurado.
    es_urgente = minutos <= min(AVISOS_PREVIOS_MIN)
    palabra_min = "minuto" if minutos == 1 else "minutos"

    if not es_urgente:
        cabecera = f"⚠️ *ALERTA: faltan {minutos} {palabra_min}*"
        # Antes decía "revisa si el precio se acerca a niveles 00/25/50/75":
        # se quitó a propósito. Se midió con datos reales (28 activos, 2 años,
        # y de nuevo en vivo contra OANDA) que esos niveles NO tienen ventaja
        # estadística sobre una línea puesta al azar. Repetirlo aquí sería
        # venderte una certeza que no existe.
        cierre = (
            "Decide de antemano si vas a operar la noticia o vas a esperar a "
            "que se calme la volatilidad inicial. No es buen momento para "
            "abrir posiciones nuevas sin un plan de gestión de riesgo claro."
        )
    else:
        cabecera = f"🚨 *ALERTA INMINENTE: faltan {minutos} {palabra_min}*"
        cierre = (
            "Asegura Stop Loss o cierra posiciones sensibles: en los primeros "
            "segundos tras la publicación el spread se amplía y hay alta "
            "probabilidad de slippage."
        )

    return (
        f"{cabecera}\n\n"
        f"📌 *Noticia:* {titulo}\n"
        f"💱 *Divisa:* {evento['divisa']} (impacto {traducir_impacto(evento['impacto'])})\n"
        f"🕒 *Hora:* {hora_local} (Colombia)\n"
        f"📊 Pronóstico: {evento['pronostico'] or 'sin dato'} | "
        f"Anterior: {evento['anterior'] or 'sin dato'}\n\n"
        f"🧠 *{categoria['nombre']}:* {categoria['explicacion']}\n\n"
        f"👉 {cierre}"
    )


def mensaje_publicacion(evento):
    titulo = _escapar(traducir_titulo(evento["titulo"]))
    categoria = clasificar_evento(evento["titulo"])
    if categoria.get("alcista_si_sube") is None:
        seguimiento = (
            "Esta noticia no trae una cifra que comparar (discurso, actas o "
            "similar). Guíate por la reacción real del precio."
        )
    else:
        seguimiento = (
            f"Revisando el resultado real cada pocos minutos durante la "
            f"próxima media hora, para compararlo contra el pronóstico en "
            f"cuanto el calendario lo publique."
        )
    return (
        f"💥 *NOTICIA PUBLICADA AHORA*\n\n"
        f"📌 *Noticia:* {titulo}\n"
        f"💱 *Divisa:* {evento['divisa']}\n"
        f"📊 Pronóstico: {evento['pronostico'] or 'sin dato'} | "
        f"Anterior: {evento['anterior'] or 'sin dato'}\n\n"
        f"{seguimiento}"
    )


def mensaje_reaccion(evento, analisis, agotado=False):
    titulo = _escapar(traducir_titulo(evento["titulo"]))
    if analisis is None:
        if agotado:
            return (
                f"📎 *Seguimiento: {titulo}* ({evento['divisa']})\n\n"
                f"Pasaron 30 minutos y el calendario público que usa este bot "
                f"todavía no muestra el dato *actual*. Pasa a veces con este "
                f"feed gratuito. Verifica el resultado directamente en "
                f"forexfactory.com o en el calendario económico de "
                f"TradingView, y guíate por la reacción real del precio en "
                f"el gráfico."
            )
        return None  # no es el ultimo intento: se espera en silencio

    emoji = {"alcista": "🟢", "bajista": "🔴", "neutral": "⚪"}[analisis["direccion"]]
    linea_razon = f"\n\n📐 *Por qué:* {analisis['razon']}" if analisis["razon"] else ""

    return (
        f"{emoji} *RESULTADO REAL: {titulo}*\n\n"
        f"💱 *Divisa:* {evento['divisa']}\n"
        f"📈 Actual: *{evento['actual']}* | Pronóstico: {evento['pronostico']} "
        f"| Anterior: {evento['anterior']}\n\n"
        f"El dato {analisis['resultado_txt']}. "
        f"Lectura fundamental: *{analisis['direccion'].upper()}* para "
        f"{evento['divisa']}.{linea_razon}"
    )


def mensaje_reporte_matutino(eventos_hoy):
    if not eventos_hoy:
        return (
            "🌅 *Resumen del mercado - hoy*\n\n"
            "No hay noticias de alto impacto programadas hoy para tus "
            "divisas objetivo. Día tranquilo en el calendario (no "
            "necesariamente en el precio)."
        )

    eventos_hoy = sorted(eventos_hoy, key=lambda e: e["fecha"])
    lineas = ["🌅 *Resumen del mercado - Alto impacto (3 toros)*\n"]
    lineas.append(f"🗓️ Hoy tienes {len(eventos_hoy)} inyecciones de liquidez:\n")
    for ev in eventos_hoy:
        hora = ev["fecha"].astimezone(ZONA_HORARIA).strftime("%H:%M")
        titulo = _escapar(traducir_titulo(ev["titulo"]))
        pron = f" (pronóstico: {ev['pronostico']})" if ev["pronostico"] else ""
        lineas.append(f"• {hora} | {ev['divisa']} | {titulo}{pron}")
    lineas.append("\nPrepara tus sesiones y marca tus bloques de órdenes.")
    return "\n".join(lineas)


# ══════════════════════════════════════════════════════════════════════════
# 7. ENVÍO
# ══════════════════════════════════════════════════════════════════════════
def _enviar(mensaje):
    try:
        bot.send_message(CHAT_ID, mensaje, parse_mode="Markdown")
    except Exception as e:  # nunca dejar que un fallo de Telegram tumbe el scheduler
        log.error("Fallo al enviar mensaje a Telegram: %s", e)
        _estado_salud["ultimo_error"] = f"envío: {e}"


def job_aviso_previo(evento, minutos):
    _enviar(mensaje_previo(evento, minutos))


def job_publicacion(evento):
    _enviar(mensaje_publicacion(evento))


# Eventos para los que YA se mandó la comparación real, para no repetirla
# en cada reintento una vez que se consiguió el dato. Vive en memoria: si
# el proceso se reinicia a mitad de la ventana de 30 minutos, en el peor
# caso se manda un mensaje de más, nunca de menos.
_eventos_con_reaccion_enviada = set()


def _clave_reaccion(evento):
    return f"{evento['divisa']}|{evento['titulo']}|{evento['fecha'].isoformat()}"


def job_reaccion(evento, intento, total_intentos):
    """
    Se llama varias veces por evento (ver REINTENTOS_REACCION_MIN), no una
    sola. En cada llamada vuelve a descargar el calendario completo (el
    'actual' puede tardar en aparecer) y compara contra el pronóstico.

    - Si ya se mandó la comparación en un intento anterior, no hace nada.
    - Si consigue el dato, manda el resultado real y no vuelve a intentar.
    - Si no hay dato y todavía quedan intentos, se espera en silencio.
    - Si no hay dato y este era el ÚLTIMO intento, avisa honestamente que
      el dato no llegó en vez de fingir una comparación o quedarse callado
      para siempre.
    """
    clave = _clave_reaccion(evento)
    if clave in _eventos_con_reaccion_enviada:
        return

    eventos_frescos = obtener_calendario()
    actualizado = evento
    for ev in eventos_frescos:
        if ev["titulo"] == evento["titulo"] and ev["divisa"] == evento["divisa"] \
                and ev["fecha"] == evento["fecha"]:
            actualizado = ev
            break

    analisis = analizar_resultado(actualizado)
    es_ultimo_intento = intento >= total_intentos
    mensaje = mensaje_reaccion(actualizado, analisis, agotado=es_ultimo_intento)

    if mensaje is None:
        return  # todavia no hay dato y quedan mas intentos: se espera

    _eventos_con_reaccion_enviada.add(clave)
    _enviar(mensaje)


def job_seguimiento_no_comparable(evento):
    """Para discursos, actas y similares: no hay cifra que comparar por
    diseño (no es que 'no haya llegado el dato'), así que se manda UNA
    nota aclaratoria y no se reintenta."""
    titulo = _escapar(traducir_titulo(evento["titulo"]))
    _enviar(
        f"📎 *Seguimiento: {titulo}* ({evento['divisa']})\n\n"
        f"Este tipo de noticia no trae una cifra que comparar contra un "
        f"pronóstico. Lo que mueve el mercado es el TONO del mensaje: revisa "
        f"el titular en vivo y la reacción real del precio en el gráfico."
    )


def job_reporte_matutino():
    eventos = obtener_calendario()
    hoy = eventos_relevantes(eventos, solo_hoy=True)
    _estado_salud["eventos_detectados_hoy"] = len(hoy)
    _enviar(mensaje_reporte_matutino(hoy))


# ══════════════════════════════════════════════════════════════════════════
# 8. SINCRONIZACIÓN Y PROGRAMACIÓN DINÁMICA
# ══════════════════════════════════════════════════════════════════════════
scheduler = BackgroundScheduler(timezone=ZONA_HORARIA)


def sincronizar_calendario():
    """
    Se ejecuta al arrancar y luego cada INTERVALO_SINCRONIZACION_MIN.
    Descarga el calendario, filtra tus divisas y el impacto que
    monitoreas, y programa (si no estaban programados ya) los avisos de
    cada noticia futura: 15 min antes, 5 min antes, al momento, y la
    comparación real del resultado (con reintentos hasta por 30 minutos
    después, o una nota única si es un discurso/actas sin cifra que
    comparar).
    """
    ahora = datetime.now(pytz.utc)
    estado = _cargar_estado_disco()
    eventos = obtener_calendario()
    relevantes = eventos_relevantes(eventos, solo_hoy=False)
    ventana_reaccion = max(REINTENTOS_REACCION_MIN)

    nuevos = 0
    for ev in relevantes:
        clave_base = f"{ev['divisa']}|{ev['titulo']}|{ev['fecha'].isoformat()}"
        if _ya_programado(estado, clave_base):
            continue
        if ev["fecha"] < ahora - timedelta(minutes=ventana_reaccion):
            # Ya pasó de largo (por ejemplo el bot estuvo caído); no tiene
            # sentido mandar un aviso de "faltan 15 minutos" para algo que
            # ya ocurrió hace horas.
            _marcar_programado(estado, clave_base)
            continue

        for minutos in AVISOS_PREVIOS_MIN:
            momento = ev["fecha"] - timedelta(minutes=minutos)
            if momento > ahora:
                scheduler.add_job(
                    job_aviso_previo, "date", run_date=momento,
                    args=[ev, minutos],
                    id=f"{clave_base}|previo{minutos}", replace_existing=True,
                )

        if ev["fecha"] > ahora:
            scheduler.add_job(
                job_publicacion, "date", run_date=ev["fecha"],
                args=[ev], id=f"{clave_base}|ahora", replace_existing=True,
            )

        categoria = clasificar_evento(ev["titulo"])
        if categoria.get("alcista_si_sube") is None:
            # Discurso, actas o similar: no hay cifra que comparar, una
            # sola nota aclaratoria basta, reintentar no tendría sentido.
            scheduler.add_job(
                job_seguimiento_no_comparable, "date",
                run_date=ev["fecha"] + timedelta(minutes=REINTENTOS_REACCION_MIN[0]),
                args=[ev], id=f"{clave_base}|seguimiento", replace_existing=True,
            )
        else:
            for idx, minutos_despues in enumerate(REINTENTOS_REACCION_MIN, start=1):
                scheduler.add_job(
                    job_reaccion, "date",
                    run_date=ev["fecha"] + timedelta(minutes=minutos_despues),
                    args=[ev, idx, len(REINTENTOS_REACCION_MIN)],
                    id=f"{clave_base}|reaccion{idx}", replace_existing=True,
                )

        _marcar_programado(estado, clave_base)
        nuevos += 1

    _estado_salud["ultima_sincronizacion"] = datetime.now(ZONA_HORARIA).isoformat()
    _estado_salud["avisos_programados_activos"] = len(scheduler.get_jobs())
    log.info(
        "Sincronización de calendario: %d eventos relevantes, %d nuevos programados.",
        len(relevantes), nuevos,
    )


def programar_trabajos_fijos():
    scheduler.add_job(job_reporte_matutino, "cron", hour=6, minute=0, id="reporte_matutino")
    scheduler.add_job(
        sincronizar_calendario, "interval",
        minutes=INTERVALO_SINCRONIZACION_MIN, id="sincronizacion_periodica",
    )
    scheduler.start()
    # Primera sincronización inmediata al arrancar, para no esperar una
    # hora completa antes de tener algo programado.
    sincronizar_calendario()


# ══════════════════════════════════════════════════════════════════════════
# 9. EJECUCIÓN PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("Arrancando bot de calendario económico...")

    programar_trabajos_fijos()

    hilo_web = threading.Thread(target=run_flask, daemon=True)
    hilo_web.start()

    log.info("Servidor web y programador activos. Iniciando polling de Telegram...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            # Si Telegram corta la conexión (pasa de vez en cuando en
            # servicios gratuitos), se reintenta en vez de morir el proceso.
            log.error("El polling de Telegram se cortó (%s); reintentando en 15s.", e)
            _estado_salud["ultimo_error"] = f"polling: {e}"
            time.sleep(15)
