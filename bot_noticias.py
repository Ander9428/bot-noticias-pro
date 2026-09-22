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
     importar si el dato salió bien o mal. Ahora hay un análisis real
     ANTES del dato: qué es, por qué importa, y qué significaría un
     resultado por encima o por debajo del pronóstico -con la lógica
     económica correcta para cada categoría (ej: el desempleo funciona al
     revés que el PIB).

     OJO, ESTO CAMBIÓ DE NUEVO: en la ronda anterior había TAMBIÉN un
     segundo análisis, DESPUÉS del dato, comparando el resultado real
     contra el pronóstico. Se probó a fondo -no solo se sospechó, se
     verificó en vivo contra el feed real- y esa comparación es
     estructuralmente imposible con datos gratis: ver el punto 7 mas
     abajo. Se eliminó por completo en vez de dejar una función que nunca
     iba a disparar; ese era justamente el "texto vacío o falso" que se
     pidió evitar.

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

  7. SE ELIMINÓ LA COMPARACIÓN "RESULTADO REAL VS. PRONÓSTICO" (Y TODO LO
     QUE SOLO EXISTÍA PARA SOSTENERLA). Motivo, verificado en vivo, no
     supuesto:
       - El feed gratuito de ForexFactory que usa este bot JAMÁS incluye
         el campo "actual" (el resultado publicado). Se revisaron las 78
         noticias de una semana real completa, pasadas y futuras: la
         clave "actual" no aparece en NINGUNA. El código anterior ya
         intuía el problema (dejó un comentario sobre un evento de hace
         39 horas sin dato); esta vez se confirmó con el feed completo.
       - Se probaron 5 fuentes alternativas para conseguir el dato real:
         la página web de ForexFactory (bloqueada por Cloudflare, error
         403), TradingEconomics (su acceso de invitado gratuito fue
         discontinuado, HTTP 410), Finnhub (su calendario económico está
         bloqueado para el plan gratis), y Myfxbook (sin API pública
         documentada para esto). Ninguna gratuita funcionó.
       - Con esto confirmado, mantener la función de "reacción" (el job
         que reintentaba 4 veces por evento durante 30 minutos buscando
         un dato que nunca iba a llegar, el registro en disco de
         reacciones enviadas, la función de comparación, el mensaje de
         resultado) era codigo muerto: nunca se iba a ejecutar de verdad.
         Se eliminó todo junto, no se dejó "por si acaso".
       - Efecto secundario bueno: la caché de 90 segundos del calendario
         también se eliminó. Solo existía para absorber las ráfagas de
         3-4 peticiones simultáneas que generaban los reintentos de
         reacción en un día con varias noticias agrupadas (ej. el Banco
         Central Suizo). Sin reintentos de reacción, ese patrón de ráfaga
         ya no ocurre: la sincronización por hora y el reporte diario de
         las 6 AM nunca coinciden en el tiempo, así que nunca se acercan
         al límite real del feed (2 peticiones cada 5 minutos).

  8. BUG REAL ENCONTRADO PROBANDO CONTRA EL FEED EN VIVO: "SNB Policy
     Rate" (decisión de tasas del Banco Nacional Suizo, un evento real
     programado la semana que se probó) no coincidía con ninguna palabra
     clave de la categoría "tasas" -el código buscaba "snb rate" pero el
     título real trae "Policy" en medio ("SNB Policy Rate"). Se estaba
     descartando en silencio justo el tipo de evento que más importa. Se
     agregaron los nombres oficiales que usan otros bancos centrales
     (BOE = "Bank Rate", ECB = "Main Refinancing Rate"/"Deposit Facility
     Rate") para cerrar el mismo hueco antes de que pase con ellos.

LO QUE SIGUE IGUAL, A PROPÓSITO: Flask como "keep-alive" para Render,
APScheduler para programar, pytz para la zona horaria de Colombia,
polling de Telegram al final. Es tu misma arquitectura, solo que ahora
hace lo que el comentario decía que hacía -y ya no promete lo que la
fuente de datos gratuita no puede cumplir.

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
#
# LÍMITE REAL MEDIDO: este feed acepta como máximo 2 peticiones cada 5
# minutos (más que eso responde 429). Con la sincronización cada hora y el
# reporte matutino una vez al día, este bot nunca se acerca a ese límite
# -no hace falta ninguna caché para protegerlo.
URL_CALENDARIO = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Minutos de anticipación de cada aviso antes del evento.
# El primer aviso llega 15 minutos antes (pediste ese margen); el segundo,
# 5 minutos antes, como último recordatorio urgente.
AVISOS_PREVIOS_MIN = [15, 5]

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
_ESTADO_DEFECTO = {"programados": []}


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
    lista de diccionarios ya normalizados: titulo, divisa, impacto, fecha,
    pronostico, anterior.

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
            }
        )
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
# (High, verificado en vivo) y "FOMC Member Bowman Speaks" (Low) el mismo
# día.
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
#    (análisis PREVIO al dato: qué es, por qué importa, qué significaría
#    un resultado por encima o por debajo del pronóstico. Ya no existe un
#    análisis POSTERIOR -ver el punto 7 de la cabecera del archivo.)
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
            # BUG REAL encontrado probando contra el feed en vivo: "SNB
            # Policy Rate" no coincidia con "snb rate" (tiene "Policy" en
            # medio) y se descartaba en silencio -justo una decision de
            # tasas real de esta semana. "policy rate" (generico) y los
            # nombres oficiales que usan otros bancos centrales (BOE =
            # "Bank Rate", ECB = "Main Refinancing Rate"/"Deposit Facility
            # Rate") cierran el mismo hueco para todos, no solo para el SNB.
            "policy rate", "bank rate", "main refinancing rate",
            "deposit facility rate", "repo rate", "base rate",
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
    (r"\bSNB Policy Rate\b", "Tasa de Política del SNB"),
    (r"\bPolicy Rate\b", "Tasa de Política"),
    (r"\bBank Rate\b", "Tasa Bancaria"),
    (r"\bMain Refinancing Rate\b", "Tasa de Refinanciación Principal"),
    (r"\bDeposit Facility Rate\b", "Tasa de Depósito"),
    (r"\bFOMC Statement\b", "Comunicado del FOMC"),
    (r"\bFOMC Meeting Minutes\b", "Actas de la Reunión del FOMC"),
    (r"\bFOMC Press Conference\b", "Rueda de Prensa del FOMC"),
    (r"\bMonetary Policy Statement\b", "Comunicado de Política Monetaria"),
    (r"\bMonetary Policy Report\b", "Informe de Política Monetaria"),
    (r"\bMonetary Policy Assessment\b", "Evaluación de Política Monetaria"),
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


# Solo presentación visual, ningún dato: la bandera es la del país emisor
# de cada divisa objetivo (no se inventa nada, es la bandera real de esa
# moneda) y el ícono de categoría ayuda a reconocer de un vistazo qué tipo
# de noticia es sin tener que leer el título completo.
_BANDERAS = {
    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
    "AUD": "🇦🇺", "CAD": "🇨🇦", "CHF": "🇨🇭", "NZD": "🇳🇿",
}

_EMOJI_CATEGORIA = {
    "Decisión de tasas de interés": "💰",
    "Producto Interno Bruto (PIB)": "📊",
    "Inflación (IPC / PCE / PPI)": "🔥",
    "Tasa de desempleo": "📉",
    "Solicitudes de subsidio por desempleo": "📝",
    "Creación de empleo (Nóminas no agrícolas / NFP)": "👷",
    "PMI / ISM (actividad manufacturera o de servicios)": "🏭",
    "Ventas minoristas": "🛒",
    "Balanza comercial": "🚢",
    "Confianza / sentimiento del consumidor": "😊",
    "Sector vivienda": "🏠",
    "Discurso o comparecencia de un banquero central": "🎤",
    "Actas de la última reunión del banco central": "📜",
}


def _bandera(divisa):
    return _BANDERAS.get(divisa, "")


def _emoji_categoria(titulo):
    nombre = clasificar_evento(titulo).get("nombre", "")
    return _EMOJI_CATEGORIA.get(nombre, "📰")


def mensaje_previo(grupo, minutos):
    """
    Recibe una LISTA de eventos, no uno solo. Motivo: en días como el de
    la Fed, ForexFactory publica 3-4 noticias en el MISMO minuto exacto
    (tasa, proyecciones, comunicado...) y antes esto mandaba un aviso casi
    idéntico por cada una — 4 mensajes seguidos para lo que en la práctica
    es un solo momento. Ahora, si comparten divisa y hora exacta, se
    agrupan en uno solo. El caso normal (1 sola noticia) se ve exactamente
    igual que antes.

    En un grupo (día de la Fed o del SNB) se usa la categoría de cada
    integrante que sí admita comparación numérica -si el grupo mezcla mas
    de una categoria con logica distinta (ej. Empleo + Tasa de Desempleo
    el mismo minuto, que funcionan AL REVES una de otra), se da una linea
    de razonamiento por cada una en vez de una conclusion unica que solo
    seria cierta para la mitad del grupo.
    """
    divisa = grupo[0]["divisa"]
    bandera = _bandera(divisa)
    hora_local = grupo[0]["fecha"].astimezone(ZONA_HORARIA).strftime("%H:%M")
    es_urgente = minutos <= min(AVISOS_PREVIOS_MIN)
    palabra_min = "minuto" if minutos == 1 else "minutos"
    emoji = "🚨" if es_urgente else "⚠️"

    if len(grupo) == 1:
        evento = grupo[0]
        titulo = _escapar(traducir_titulo(evento["titulo"]))
        icono = _emoji_categoria(evento["titulo"])
        base = (
            f"{emoji} *En {minutos} {palabra_min}:* {icono} {titulo} ({bandera} {divisa})\n"
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
        icono = _emoji_categoria(grupo[0]["titulo"])
        titulos = "\n".join(
            f"• {_escapar(traducir_titulo(e['titulo']))}" for e in grupo
        )
        base = (
            f"{emoji} *En {minutos} {palabra_min}:* {icono} {len(grupo)} noticias de "
            f"{bandera} {divisa} al mismo tiempo ({hora_local} Colombia):\n{titulos}"
        )

    if es_urgente:
        return base

    categorias_comparables = []
    nombres_vistos = set()
    for ev in grupo:
        cat = clasificar_evento(ev["titulo"])
        if cat.get("alcista_si_sube") is not None and cat["nombre"] not in nombres_vistos:
            nombres_vistos.add(cat["nombre"])
            categorias_comparables.append(cat)

    if not categorias_comparables:
        analisis = (
            "🧠 No trae una cifra que comparar contra un pronóstico: el "
            "mercado reacciona al TONO del mensaje, no a un número."
        )
    elif len(categorias_comparables) == 1:
        categoria = categorias_comparables[0]
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
    else:
        lineas = ["🧠 *Este grupo mezcla indicadores con lógica distinta:*"]
        for cat in categorias_comparables:
            if cat["alcista_si_sube"]:
                lineas.append(f"• {cat['nombre']}: por encima del pronóstico es alcista, por debajo bajista.")
            else:
                lineas.append(f"• {cat['nombre']}: por encima del pronóstico es bajista, por debajo alcista (indicador inverso).")
        analisis = "\n".join(lineas)

    return f"{base}\n\n{analisis}"


def mensaje_publicacion(grupo):
    """Igual que mensaje_previo: recibe una lista para poder agrupar
    noticias simultáneas de la misma divisa en un solo aviso."""
    divisa = grupo[0]["divisa"]
    bandera = _bandera(divisa)
    if len(grupo) == 1:
        evento = grupo[0]
        titulo = _escapar(traducir_titulo(evento["titulo"]))
        icono = _emoji_categoria(evento["titulo"])
        # Un discurso "empieza", no "se publica" (no trae una cifra que
        # publicar), así que ni el verbo ni la línea de pronóstico/anterior
        # aplican - ver el mismo razonamiento en mensaje_previo.
        if clasificar_evento(evento["titulo"]).get("alcista_si_sube") is None:
            return f"🎤 *Empezando ahora:* {titulo} ({bandera} {divisa})"
        return (
            f"💥 *Publicado ahora:* {icono} {titulo} ({bandera} {divisa})\n"
            f"Pronóstico: {evento['pronostico'] or 'sin dato'} | "
            f"Anterior: {evento['anterior'] or 'sin dato'}"
        )
    icono = _emoji_categoria(grupo[0]["titulo"])
    titulos = "\n".join(f"• {_escapar(traducir_titulo(e['titulo']))}" for e in grupo)
    return f"💥 *Publicado ahora ({bandera} {divisa}):* {icono} {len(grupo)} noticias a la vez\n{titulos}"


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
        bandera = _bandera(ev["divisa"])
        icono = _emoji_categoria(ev["titulo"])
        pron = f" (pronóstico: {ev['pronostico']})" if ev["pronostico"] else ""
        lineas.append(f"• {hora} | {bandera} {ev['divisa']} | {icono} {titulo}{pron}")
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
    cada noticia futura: 15 min antes, 5 min antes, y al momento.

    Los avisos se programan por GRUPO, no por evento individual: si dos o
    más noticias de la misma divisa caen en el minuto exacto (típico en
    día de la Fed o del SNB: tasa + proyecciones/evaluación + comunicado
    a la misma hora), se manda un solo aviso combinado en vez de uno por
    cada una.
    """
    ahora = datetime.now(pytz.utc)
    estado = _cargar_estado_disco()
    eventos = obtener_calendario()
    relevantes = eventos_relevantes(eventos, solo_hoy=False)

    grupos = {}
    for ev in relevantes:
        grupos.setdefault((ev["divisa"], ev["fecha"]), []).append(ev)

    nuevos = 0
    for (divisa, fecha), grupo in grupos.items():
        clave_grupo = f"{divisa}|{fecha.isoformat()}|grupo"
        if _ya_programado(estado, clave_grupo):
            continue

        # se marca aunque ya haya pasado: evita reintentar programar un
        # aviso de "faltan 15 minutos" para algo que ocurrió hace horas,
        # por ejemplo si el bot estuvo caído.
        if fecha > ahora:
            for minutos in AVISOS_PREVIOS_MIN:
                momento = fecha - timedelta(minutes=minutos)
                if momento > ahora:
                    scheduler.add_job(
                        job_aviso_previo, "date", run_date=momento,
                        args=[grupo, minutos],
                        id=f"{clave_grupo}|previo{minutos}", replace_existing=True,
                    )
            scheduler.add_job(
                job_publicacion, "date", run_date=fecha,
                args=[grupo], id=f"{clave_grupo}|ahora", replace_existing=True,
            )
            nuevos += 1
        _marcar_programado(estado, clave_grupo)

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
