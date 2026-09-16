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

# Si defines TELEGRAM_TOKEN / TELEGRAM_CHAT_ID como variables de entorno
# (por ejemplo en Render → Environment), esas tienen prioridad y estos
# valores de aquí nunca se usan. Quedan como respaldo para que el bot
# arranque igual si lo corres local sin configurar nada.
#
# OJO SI SUBES ESTO A GITHUB: si el repositorio es público (o se vuelve
# público más adelante, o alguien lo clona), cualquiera que lea este
# archivo puede controlar tu bot con este token. Si vas a subirlo, lo más
# seguro sigue siendo borrar los valores de abajo y configurarlos como
# variables de entorno en Render en su lugar.
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8007552290:AAHH8KQrYklwR6oh8Tjw2_VbUvXs1D8Zd_I").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "848594835").strip()

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

# EL FILTRO DE VERDAD: que la fuente marque algo "High" no significa que
# de verdad mueva el mercado. Investing.com, por ejemplo, desglosa el "dot
# plot" de la Fed en 5 líneas separadas (una por cada año de proyección) y
# marca "Flujos de capital a largo plazo" como 3 toros — cosas que ningún
# trader serio opera. Cada categoría en CATEGORIAS tiene un "nivel":
#   "clave"      -> tasas, PIB, IPC, empleo, PMI, discursos/actas de
#                    bancos centrales. Los movedores de mercado reales.
#   "secundario" -> ventas minoristas, balanza comercial, confianza del
#                    consumidor, vivienda, solicitudes de desempleo.
#                    Importan, pero mueven menos.
#   "descartar"  -> todo lo que no encaja en ninguna categoría reconocida
#                    (la CATEGORIA_DEFECTO). Por más que el feed lo marque
#                    "High", si no se reconoce el indicador, no se avisa.
# Con INCLUIR_SECUNDARIOS en False (por defecto) solo llegan avisos de
# "clave". Ponlo en True si quieres más cobertura a cambio de más avisos.
INCLUIR_SECUNDARIOS = False

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
# durante media hora; se manda el mensaje en cuanto el dato aparece. Si tras
# el último intento nunca llegó (o el evento no es comparable, ej. un
# discurso), no se manda nada — silencio, no una nota de "no lo conseguí".
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
_ESTADO_DEFECTO = {"programados": [], "reacciones_enviadas": []}


def _cargar_estado_disco():
    if not os.path.exists(ARCHIVO_ESTADO):
        return dict(_ESTADO_DEFECTO)
    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            estado = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("No se pudo leer %s (%s); se empieza de cero.", ARCHIVO_ESTADO, e)
        return dict(_ESTADO_DEFECTO)
    # por si el archivo viene de una version anterior sin esta clave
    estado.setdefault("reacciones_enviadas", [])
    estado.setdefault("programados", [])
    return estado


def _guardar_estado_disco(estado):
    try:
        with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning("No se pudo guardar %s: %s", ARCHIVO_ESTADO, e)


def _ya_programado(estado, clave):
    return clave in estado["programados"]


def _marcar_programado(estado, clave):
    estado["programados"].append(clave)
    # Se conservan solo las últimas 500 claves para que el archivo no
    # crezca sin límite; con eso sobra para varias semanas de cobertura.
    estado["programados"] = estado["programados"][-500:]
    _guardar_estado_disco(estado)


def _ya_reaccion_enviada(clave):
    """
    A diferencia de `_ya_programado`, esto SÍ se persiste en disco (antes
    solo vivía en un set en memoria). Si Render reinicia el proceso a
    mitad de la ventana de 30 minutos de reintentos -pasa seguido en el
    plan gratis-, sin esto se podía mandar la MISMA comparación real dos
    veces. Se lee el archivo fresco en cada llamada porque job_reaccion se
    dispara pocas veces por evento, el costo es insignificante.
    """
    estado = _cargar_estado_disco()
    return clave in estado["reacciones_enviadas"]


def _marcar_reaccion_enviada(clave):
    estado = _cargar_estado_disco()
    estado["reacciones_enviadas"].append(clave)
    estado["reacciones_enviadas"] = estado["reacciones_enviadas"][-500:]
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
# CACHÉ CORTA: en un día con varios eventos agrupados (ej. la Fed: tasa +
# proyecciones + comunicado a la misma hora) cada uno programa sus propios
# 4 reintentos de reacción en los MISMOS minutos después (+3, +8, +15, +30).
# Sin caché, eso son 3-4 peticiones casi simultáneas al mismo feed gratuito
# justo en el momento de mayor tráfico -y ya se comprobó en vivo que este
# feed responde 429 (demasiadas peticiones) bajo uso repetido seguido. Con
# esta caché, todas esas llamadas que caen dentro de la misma ventana de
# 90 segundos comparten una sola descarga real.
_CACHE_CALENDARIO = {"eventos": None, "momento": None}
_CACHE_TTL_SEGUNDOS = 90
_lock_cache_calendario = threading.Lock()


def obtener_calendario():
    """
    Descarga el calendario económico de la semana en curso y devuelve una
    lista de diccionarios ya normalizados. Cada entrada del feed trae:
    title, country, date (ISO con offset horario), impact, forecast,
    previous, actual (vacío mientras no se haya publicado el dato).

    Si la descarga falla (caída del servicio, sin internet, etc.) se
    devuelve una lista vacía y se registra el error, para que el bot no
    se caiga por un problema de red pasajero. Reutiliza el resultado si
    se pidió hace menos de _CACHE_TTL_SEGUNDOS (ver comentario arriba).

    La descarga ocurre CON el candado tomado (no solo la lectura de la
    caché): si dos reintentos de reacción caen en el mismo instante -el
    caso típico de un grupo de la Fed-, el segundo espera a que el primero
    termine de descargar en vez de disparar su propia petición en paralelo,
    y al liberarse ya encuentra la caché fresca.
    """
    with _lock_cache_calendario:
        momento_cache = _CACHE_CALENDARIO["momento"]
        if momento_cache is not None:
            edad = (datetime.now(pytz.utc) - momento_cache).total_seconds()
            if edad < _CACHE_TTL_SEGUNDOS:
                return _CACHE_CALENDARIO["eventos"]

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
        _CACHE_CALENDARIO["eventos"] = eventos
        _CACHE_CALENDARIO["momento"] = datetime.now(pytz.utc)
        return eventos


def _nivel_de_relevancia(titulo):
    """'clave', 'secundario' o 'descartar' — ver el comentario de
    INCLUIR_SECUNDARIOS arriba para qué significa cada uno."""
    return clasificar_evento(titulo).get("nivel", "descartar")


# MEDIDO CONTRA EL FEED REAL: ForexFactory casi nunca marca "High" el
# discurso de un banquero central salvo que sea la rueda de prensa oficial
# tras una decisión de tasas. Un discurso normal de Powell, Lagarde o
# Bailey suele venir como "Medium", y el de un miembro cualquiera del
# comité (no el presidente) como "Medium" o "Low" — visto en vivo con
# "ECB President Lagarde Speaks" (Medium), "RBA Gov Bullock Speaks"
# (Medium) y "FOMC Member Bowman Speaks" (Low) el mismo día.
#
# Esto se soluciona distinguiendo PRESIDENTE/GOBERNADOR (el jefe del banco
# central, cuyas palabras sí mueven el mercado aunque la fuente lo marque
# "Medium") de un MIEMBRO o ADJUNTO cualquiera (para quien sí se respeta
# el impacto que diga la fuente, o sencillamente no se avisa).
_PALABRAS_JEFE_BANCO_CENTRAL = ["chair", "president", "governor", " gov ", "chairman"]
_PALABRAS_NO_ES_EL_JEFE = ["assist", "deputy", "vice", "member"]


def _es_jefe_banco_central(titulo, divisa):
    """True solo para el jefe del banco central que de verdad fija la
    política de esa divisa (Powell, Lagarde, Bailey, Bullock...), nunca
    para un adjunto, vice o miembro cualquiera del comité.

    CASO ESPECIAL EUR: la eurozona tiene un banco central POR PAÍS
    (Bundesbank en Alemania, Banque de France, Banca d'Italia...) pero
    solo UNO fija la tasa del euro: el BCE. Visto en vivo un día real:
    "German Buba President Nagel Speaks" pasaba el filtro (tiene
    "president") con impacto Bajo, tratándose igual que Lagarde -pero el
    presidente del Bundesbank opina, no decide solo, y su discurso no
    mueve el mercado como el de la presidenta del BCE. Por eso para EUR
    no basta con "president"/"governor": el titular debe mencionar
    explícitamente al BCE."""
    t = f" {(titulo or '').lower()} "
    if any(p in t for p in _PALABRAS_NO_ES_EL_JEFE):
        return False
    if not any(p in t for p in _PALABRAS_JEFE_BANCO_CENTRAL):
        return False
    if divisa == "EUR" and "ecb" not in t and "bce" not in t:
        return False
    return True


def eventos_relevantes(eventos, solo_hoy=False):
    """Filtra por divisa objetivo, impacto de la fuente, y por si el
    indicador es de los que de verdad mueven el mercado (ver
    INCLUIR_SECUNDARIOS). Que ForexFactory diga "High" ya no basta por sí
    solo — y a la inversa: si es el PRESIDENTE de un banco central
    hablando, se avisa aunque la fuente lo marque "Medium" o "Low", porque
    sus palabras mueven el mercado más de lo que esa etiqueta sugiere."""
    ahora_bogota = datetime.now(ZONA_HORARIA)
    resultado = []
    for ev in eventos:
        if ev["divisa"] not in DIVISAS_OBJETIVO:
            continue
        nivel = _nivel_de_relevancia(ev["titulo"])
        if nivel == "descartar":
            continue
        if nivel == "secundario" and not INCLUIR_SECUNDARIOS:
            continue
        categoria = clasificar_evento(ev["titulo"])
        es_jefe_hablando = (
            categoria.get("nombre") == "Discurso o comparecencia de un banquero central"
            and _es_jefe_banco_central(ev["titulo"], ev["divisa"])
        )
        if ev["impacto"] not in IMPACTOS_A_MONITOREAR and not es_jefe_hablando:
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
            # Estos dos faltaban y por eso "Federal Funds Rate" -el numero
            # de la tasa en si, lo mas importante del dia de la Fed- se
            # estaba CLASIFICANDO COMO "descartar" mientras que el
            # comunicado y la rueda de prensa si pasaban. Se encontro
            # probando el filtro contra el calendario real, no a ojo.
            "federal funds rate", "official bank rate", "overnight rate",
            "cash rate", "economic projections", "summary of economic projections",
            "dot plot",
        ],
        "nombre": "Decisión de tasas de interés",
        "nivel": "clave",
        "alcista_si_sube": True,
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
        "nivel": "clave",
        "alcista_si_sube": True,
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
        "nivel": "clave",
        "alcista_si_sube": True,
        "razon_alcista": "una inflación más alta de lo esperado aumenta la presión para que el banco central mantenga tasas altas, lo que fortalece la divisa en el corto plazo",
        "razon_bajista": "una inflación más baja de lo esperado abre la puerta a recortes de tasas, lo que suele debilitar la divisa",
    },
    "desempleo_tasa": {
        "claves": ["tasa de desempleo", "unemployment rate"],
        "nombre": "Tasa de desempleo",
        "nivel": "clave",
        "alcista_si_sube": False,  # indicador inverso
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
        "nivel": "secundario",
        "alcista_si_sube": False,  # indicador inverso
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
        "nivel": "clave",
        "alcista_si_sube": True,
        "razon_alcista": "más empleos de los esperados confirma una economía sólida y sostiene expectativas de tasas altas, lo que fortalece la divisa",
        "razon_bajista": "menos empleos de los esperados es señal de debilidad económica y anticipa una postura más laxa del banco central, lo que suele debilitar la divisa",
    },
    "pmi": {
        "claves": [
            "pmi", "ism", "índice de gerentes de compra",
            "actividad manufacturera", "actividad de servicios",
        ],
        "nombre": "PMI / ISM (actividad manufacturera o de servicios)",
        "nivel": "clave",
        "alcista_si_sube": True,
        "razon_alcista": "un PMI mejor de lo esperado (o por encima de 50) señala expansión económica, lo que favorece a la divisa",
        "razon_bajista": "un PMI peor de lo esperado (o por debajo de 50) señala contracción, lo que suele pesar sobre la divisa",
    },
    "ventas_minoristas": {
        "claves": ["ventas minoristas", "retail sales"],
        "nombre": "Ventas minoristas",
        "nivel": "secundario",
        "alcista_si_sube": True,
        "razon_alcista": "un consumo mayor al esperado sostiene el crecimiento económico, lo que favorece a la divisa",
        "razon_bajista": "un consumo menor al esperado anticipa un crecimiento más débil, lo que suele pesar sobre la divisa",
    },
    "balanza_comercial": {
        "claves": ["balanza comercial", "trade balance"],
        "nombre": "Balanza comercial",
        "nivel": "secundario",
        "alcista_si_sube": True,
        "razon_alcista": "un mejor saldo comercial de lo esperado implica más entrada neta de divisas extranjeras",
        "razon_bajista": "un peor saldo comercial de lo esperado implica más salida neta de divisas, lo que puede presionar a la baja",
    },
    "confianza_consumidor": {
        "claves": [
            "confianza del consumidor", "consumer confidence",
            "sentimiento del consumidor", "consumer sentiment",
        ],
        "nombre": "Confianza / sentimiento del consumidor",
        "nivel": "secundario",
        "alcista_si_sube": True,
        "razon_alcista": "un consumidor más optimista de lo esperado anticipa mayor gasto futuro, lo que favorece a la divisa",
        "razon_bajista": "un consumidor más pesimista de lo esperado anticipa menor gasto futuro, lo que suele pesar sobre la divisa",
    },
    "vivienda": {
        "claves": [
            "vivienda", "housing", "permisos de construcción",
            "building permits", "housing starts", "inicios de construcción",
        ],
        "nombre": "Sector vivienda",
        "nivel": "secundario",
        "alcista_si_sube": True,
        "razon_alcista": "más actividad de la esperada en vivienda sugiere que la economía tolera bien las tasas actuales",
        "razon_bajista": "menos actividad de la esperada en vivienda sugiere que las tasas altas ya están frenando la economía",
    },
    "discurso": {
        "claves": [
            # "speaks" faltaba, y es justo como ForexFactory titula la
            # inmensa mayoria de estos ("Powell Speaks", "Lagarde Speaks",
            # "BOE Gov Bailey Speaks", "FOMC Member Waller Speaks"...).
            # Sin esta palabra, TODOS esos discursos se estaban
            # descartando en silencio -se encontro probando directo
            # contra nombres reales del feed, no a ojo.
            "discurso", "habla", "speech", "speaks", "speak", "remarks",
            "testimonio", "testimony", "conferencia de prensa",
            "press conference", "comparece",
        ],
        "nombre": "Discurso o comparecencia de un banquero central",
        "nivel": "clave",
        "alcista_si_sube": None,  # no aplica comparación numérica
        "razon_alcista": None,
        "razon_bajista": None,
    },
    "actas": {
        "claves": ["actas", "minutes", "fomc minutes"],
        "nombre": "Actas de la última reunión del banco central",
        "nivel": "clave",
        "alcista_si_sube": None,
        "razon_alcista": None,
        "razon_bajista": None,
    },
}

CATEGORIA_DEFECTO = {
    "nombre": "Noticia de alto impacto",
    "nivel": "descartar",
    "alcista_si_sube": None,
    "razon_alcista": None,
    "razon_bajista": None,
}


# Algunas fuentes (Investing.com, no la que usa este bot, pero por si algún
# día se cambia o se cruza contra otro calendario) desglosan el "dot plot"
# de la Fed en 5 líneas sueltas: "Interest Rate Projection - Third Year",
# "- Second Year", etc. Contienen la frase "interest rate" y por eso
# calificarían como "tasas" (clave) sin este filtro, cuando en realidad son
# el mismo dato reempaquetado 5 veces — justo el tipo de ruido que se
# pidió excluir. Se descartan ANTES de la clasificación normal.
_PATRON_PROYECCION_SUELTA = re.compile(
    r"(interest rate|rate) projection.*\b(year|qtr|quarter)\b", re.IGNORECASE
)


def clasificar_evento(titulo):
    """Identifica a qué categoría económica pertenece el titular de la
    noticia, comparando por palabras clave. Si no reconoce ninguna,
    devuelve la categoría por defecto (sigue tratándose como noticia
    de alto impacto, solo que sin la explicación específica)."""
    if _PATRON_PROYECCION_SUELTA.search(titulo or ""):
        return CATEGORIA_DEFECTO
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

    Además compara contra el dato ANTERIOR (no solo contra el pronóstico):
    si ambas comparaciones apuntan en la misma dirección, es una señal más
    fuerte (doble confirmación); si el dato anterior era mejor, es una
    señal mixta que vale la pena marcar en vez de callar. Esto es lectura
    real de trader, no un dato de más.
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
            "confirmacion": None,
        }

    salio_por_encima = diferencia > 0
    es_alcista = salio_por_encima if categoria["alcista_si_sube"] else not salio_por_encima
    razon = categoria["razon_alcista"] if es_alcista else categoria["razon_bajista"]

    confirmacion = None
    anterior = _a_numero(evento.get("anterior"))
    if anterior is not None and abs(actual - anterior) > 1e-9:
        mejora_vs_anterior = (
            (actual > anterior) if categoria["alcista_si_sube"] else (actual < anterior)
        )
        if mejora_vs_anterior == es_alcista:
            confirmacion = "doble confirmación: también mejora frente al dato anterior"
        else:
            confirmacion = "el dato anterior era mejor: lectura mixta, cautela"

    return {
        "resultado_txt": (
            "salió por ENCIMA de lo esperado" if salio_por_encima
            else "salió por DEBAJO de lo esperado"
        ),
        "direccion": "alcista" if es_alcista else "bajista",
        "razon": razon,
        "confirmacion": confirmacion,
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


def mensaje_previo(grupo, minutos):
    """
    Recibe una LISTA de eventos, no uno solo. Motivo: en días como el de
    la Fed, ForexFactory publica 3-4 noticias en el MISMO minuto exacto
    (tasa, proyecciones, comunicado...) y antes esto mandaba un aviso casi
    idéntico por cada una — 4 mensajes seguidos para lo que en la práctica
    es un solo momento. Ahora, si comparten divisa y hora exacta, se
    agrupan en uno solo. El caso normal (1 sola noticia) se ve exactamente
    igual que antes.

    Se quitó el consejo de trading ("asegura tu stop") y la definición de
    manual ("el PIB mide..."). Lo que sí se quedó, y es más útil que
    antes: qué puede ocasionar el dato para el mercado en los dos sentidos
    posibles, con la MISMA lógica económica real del análisis post-noticia.
    Solo se agrega en el aviso NO urgente (nunca en el de último minuto,
    para no repetir el mismo texto dos veces seguidas).

    En un grupo (día de la Fed) se usa la categoría del PRIMER integrante
    que sí admita comparación numérica -normalmente todos comparten la
    misma familia ("tasas": la tasa en sí, las proyecciones, el
    comunicado), así que un solo análisis compartido aplica igual de bien
    a los tres. Antes esto se omitía por completo para cualquier grupo,
    dejando sin análisis fundamental justo el momento de más peso del
    calendario -pediste que eso se corrigiera.
    """
    divisa = grupo[0]["divisa"]
    hora_local = grupo[0]["fecha"].astimezone(ZONA_HORARIA).strftime("%H:%M")
    es_urgente = minutos <= min(AVISOS_PREVIOS_MIN)
    palabra_min = "minuto" if minutos == 1 else "minutos"
    emoji = "🚨" if es_urgente else "⚠️"

    if len(grupo) == 1:
        evento = grupo[0]
        titulo = _escapar(traducir_titulo(evento["titulo"]))
        base = (
            f"{emoji} *En {minutos} {palabra_min}:* {titulo} ({divisa})\n"
            f"Impacto: {traducir_impacto(evento['impacto'])} · {hora_local} (Colombia)"
        )
        # Un discurso o unas actas nunca traen pronóstico ni dato anterior
        # (no es una cifra que comparar) - mostrar "sin dato" en ambos
        # campos es ruido, no información, así que esa línea solo se
        # agrega cuando el evento SÍ es de los que traen una cifra.
        if clasificar_evento(evento["titulo"]).get("alcista_si_sube") is not None:
            base += (
                f"\nPronóstico: {evento['pronostico'] or 'sin dato'} | "
                f"Anterior: {evento['anterior'] or 'sin dato'}"
            )
    else:
        titulos = "\n".join(
            f"• {_escapar(traducir_titulo(e['titulo']))}" for e in grupo
        )
        base = (
            f"{emoji} *En {minutos} {palabra_min}:* {len(grupo)} noticias de "
            f"{divisa} al mismo tiempo ({hora_local} Colombia):\n{titulos}"
        )

    if es_urgente:
        return base

    categoria = None
    for ev in grupo:
        cat = clasificar_evento(ev["titulo"])
        if cat.get("alcista_si_sube") is not None:
            categoria = cat
            break

    if categoria is None:
        analisis = (
            "🧠 No trae una cifra que comparar contra un pronóstico: el "
            "mercado reacciona al TONO del mensaje, no a un número."
        )
    else:
        if categoria["alcista_si_sube"]:
            dir_encima, dir_debajo = "alcista", "bajista"
            razon_encima, razon_debajo = categoria["razon_alcista"], categoria["razon_bajista"]
        else:
            dir_encima, dir_debajo = "bajista", "alcista"
            razon_encima, razon_debajo = categoria["razon_bajista"], categoria["razon_alcista"]
        analisis = (
            f"🧠 *Por encima del pronóstico:* {dir_encima} para {divisa} "
            f"— {razon_encima}.\n"
            f"*Por debajo:* {dir_debajo} — {razon_debajo}."
        )

    return f"{base}\n\n{analisis}"


def mensaje_publicacion(grupo):
    """Igual que mensaje_previo: recibe una lista para poder agrupar
    noticias simultáneas de la misma divisa en un solo aviso."""
    divisa = grupo[0]["divisa"]
    if len(grupo) == 1:
        evento = grupo[0]
        titulo = _escapar(traducir_titulo(evento["titulo"]))
        # Un discurso "empieza", no "se publica" (no trae una cifra que
        # publicar), así que ni el verbo ni la línea de pronóstico/anterior
        # aplican - ver el mismo razonamiento en mensaje_previo.
        if clasificar_evento(evento["titulo"]).get("alcista_si_sube") is None:
            return f"🎤 *Empezando ahora:* {titulo} ({divisa})"
        return (
            f"💥 *Publicado ahora:* {titulo} ({divisa})\n"
            f"Pronóstico: {evento['pronostico'] or 'sin dato'} | "
            f"Anterior: {evento['anterior'] or 'sin dato'}"
        )
    titulos = "\n".join(f"• {_escapar(traducir_titulo(e['titulo']))}" for e in grupo)
    return f"💥 *Publicado ahora ({divisa}):* {len(grupo)} noticias a la vez\n{titulos}"


def mensaje_reaccion(evento, analisis):
    """
    Solo se llama cuando SÍ hay un resultado real que mostrar. Si el
    calendario nunca publica el dato 'actual' (pasa con este feed gratis),
    o el evento es un discurso/actas sin cifra que comparar, `job_reaccion`
    nunca invoca esta función y no se manda nada — pediste exactamente
    eso: si no hay resultado, silencio, no una nota diciendo que no llegó.
    """
    titulo = _escapar(traducir_titulo(evento["titulo"]))
    emoji = {"alcista": "🟢", "bajista": "🔴", "neutral": "⚪"}[analisis["direccion"]]
    linea_lectura = f"Lectura: {analisis['direccion'].upper()} para {evento['divisa']}"
    if analisis.get("confirmacion"):
        linea_lectura += f" ({analisis['confirmacion']})"
    return (
        f"{emoji} *{titulo}* ({evento['divisa']}): {evento['actual']} vs "
        f"{evento['pronostico']} esperado · anterior {evento['anterior']}\n"
        f"{linea_lectura}"
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


def job_aviso_previo(grupo, minutos):
    _enviar(mensaje_previo(grupo, minutos))


def job_publicacion(grupo):
    _enviar(mensaje_publicacion(grupo))


def _clave_reaccion(evento):
    return f"{evento['divisa']}|{evento['titulo']}|{evento['fecha'].isoformat()}"


def job_reaccion(evento):
    """
    Se llama varias veces por evento (ver REINTENTOS_REACCION_MIN), no una
    sola. En cada llamada vuelve a descargar el calendario completo (el
    'actual' puede tardar en aparecer) y compara contra el pronóstico.

    - Si ya se mandó la comparación en un intento anterior, no hace nada
      (esto se guarda EN DISCO, no solo en memoria, para que sobreviva a
      un reinicio de Render a mitad de la ventana de 30 minutos).
    - Si consigue el dato, manda el resultado real UNA vez y no vuelve a
      intentar.
    - Si no hay dato (todavía no se publicó, nunca se publica en este feed
      gratis, o el evento es un discurso/actas sin cifra que comparar), NO
      SE MANDA NADA. Pediste exactamente eso: si no hay resultado, silencio,
      nunca una nota diciendo "no lo conseguí, ve a verificar tú mismo".
    """
    clave = _clave_reaccion(evento)
    if _ya_reaccion_enviada(clave):
        return

    eventos_frescos = obtener_calendario()
    actualizado = evento
    for ev in eventos_frescos:
        if ev["titulo"] == evento["titulo"] and ev["divisa"] == evento["divisa"] \
                and ev["fecha"] == evento["fecha"]:
            actualizado = ev
            break

    analisis = analizar_resultado(actualizado)
    if analisis is None:
        return  # sin dato (o no comparable): silencio, se reintenta despues

    _marcar_reaccion_enviada(clave)
    _enviar(mensaje_reaccion(actualizado, analisis))


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
    comparación real del resultado (con reintentos hasta 30 minutos
    después; si nunca hay dato que comparar, no se manda nada — ver
    job_reaccion).

    Los avisos previos y el de publicación se programan por GRUPO, no por
    evento individual: si dos o más noticias de la misma divisa caen en el
    minuto exacto (típico en día de la Fed: tasa + proyecciones +
    comunicado a las 13:00 en punto), se manda un solo aviso combinado en
    vez de uno por cada una. La comparación real del resultado (reacción)
    sí se maneja por evento individual, porque cada indicador tiene su
    propio número que comparar y agruparlos ahí perdería información en
    vez de solo reducir ruido.
    """
    ahora = datetime.now(pytz.utc)
    estado = _cargar_estado_disco()
    eventos = obtener_calendario()
    relevantes = eventos_relevantes(eventos, solo_hoy=False)
    ventana_reaccion = max(REINTENTOS_REACCION_MIN)

    grupos = {}
    for ev in relevantes:
        grupos.setdefault((ev["divisa"], ev["fecha"]), []).append(ev)

    nuevos = 0
    for (divisa, fecha), grupo in grupos.items():
        clave_grupo = f"{divisa}|{fecha.isoformat()}|grupo"
        ya_paso = fecha < ahora - timedelta(minutes=ventana_reaccion)

        if not _ya_programado(estado, clave_grupo):
            if not ya_paso:
                for minutos in AVISOS_PREVIOS_MIN:
                    momento = fecha - timedelta(minutes=minutos)
                    if momento > ahora:
                        scheduler.add_job(
                            job_aviso_previo, "date", run_date=momento,
                            args=[grupo, minutos],
                            id=f"{clave_grupo}|previo{minutos}", replace_existing=True,
                        )
                if fecha > ahora:
                    scheduler.add_job(
                        job_publicacion, "date", run_date=fecha,
                        args=[grupo], id=f"{clave_grupo}|ahora", replace_existing=True,
                    )
            # se marca aunque ya haya pasado (ya_paso): evita reintentar
            # programar un aviso de "faltan 15 minutos" para algo que
            # ocurrió hace horas, por ejemplo si el bot estuvo caído.
            _marcar_programado(estado, clave_grupo)

        # Reintentos de reacción: uno por evento individual dentro del grupo.
        for ev in grupo:
            clave_ev = f"{ev['divisa']}|{ev['titulo']}|{ev['fecha'].isoformat()}"
            if _ya_programado(estado, clave_ev):
                continue
            if ev["fecha"] < ahora - timedelta(minutes=ventana_reaccion):
                _marcar_programado(estado, clave_ev)
                continue
            # Mismo bloque de reintentos para cualquier evento: si es un
            # discurso/actas sin cifra, o si el dato nunca llega,
            # job_reaccion simplemente no manda nada (ver su docstring).
            for idx, minutos_despues in enumerate(REINTENTOS_REACCION_MIN):
                scheduler.add_job(
                    job_reaccion, "date",
                    run_date=ev["fecha"] + timedelta(minutes=minutos_despues),
                    args=[ev], id=f"{clave_ev}|reaccion{idx}", replace_existing=True,
                )
            _marcar_programado(estado, clave_ev)
            nuevos += 1

    _estado_salud["ultima_sincronizacion"] = datetime.now(ZONA_HORARIA).isoformat()
    _estado_salud["avisos_programados_activos"] = len(scheduler.get_jobs())
    log.info(
        "Sincronización de calendario: %d eventos relevantes en %d grupos, %d nuevos programados.",
        len(relevantes), len(grupos), nuevos,
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
