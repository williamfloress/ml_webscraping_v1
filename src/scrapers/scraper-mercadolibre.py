"""
Scraper de Mercado Libre: automatiza correo, Continuar, opción E-mail y (opcional)
la lectura del código de verificación por IMAP. Luego búsqueda y extracción de N resultados.
"""
from playwright.sync_api import sync_playwright
import os
import time
import random
import csv
import json
import re
import imaplib
import email
from email.utils import parsedate_to_datetime
from email.header import decode_header
from datetime import datetime, timezone
import os.path

# Meses en inglés para IMAP SENTSINCE (el servidor suele esperar inglés)
_IMAP_MESES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

try:
    from dotenv import load_dotenv
    load_dotenv()
    # Asegurar que se cargue .env de wscrapper_v1 si el script está en src/scrapers/
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _env_paths = [
        os.path.join(_script_dir, "..", "..", ".env"),
        os.path.join(os.getcwd(), "wscrapper_v1", ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for _p in _env_paths:
        if os.path.isfile(_p):
            load_dotenv(_p)
            break
except ImportError:
    pass

BASE_URL = "https://www.mercadolibre.com.ve/"
LISTADO_URL = "https://listado.mercadolibre.com.ve/"
MERCADOLIBRE_EMAIL = os.environ.get("MERCADOLIBRE_EMAIL", "")

# Navegador: por defecto se usa Chrome instalado (menos detectado por reCAPTCHA).
# Para forzar Chromium: MERCADOLIBRE_USAR_CHROMIUM=1
USAR_CHROME = os.environ.get("MERCADOLIBRE_USAR_CHROMIUM", "").strip().lower() not in ("1", "true", "sí", "si", "yes")

# IMAP: para leer el código de verificación del correo (opcional)
IMAP_SERVER = os.environ.get("IMAP_SERVER", "imap.gmail.com")
IMAP_USER = (os.environ.get("IMAP_USER", MERCADOLIBRE_EMAIL) or "").strip().strip('"').strip("'")
IMAP_PASSWORD = (os.environ.get("IMAP_PASSWORD", "") or "").strip().strip('"').strip("'")

TERMINO_BUSQUEDA = os.environ.get("MERCADOLIBRE_BUSQUEDA", "laptop")
CANTIDAD_ARTICULOS = 20  # Número de artículos a extraer por búsqueda


def _espera_humana() -> None:
    time.sleep(random.uniform(1, 3))


def _escribir_como_humano(page, locator, texto: str, delay_min_ms: int = 50, delay_max_ms: int = 220) -> None:
    """Escribe texto letra por letra con pausas aleatorias (ms) para parecer más humano."""
    locator.wait_for(state="visible", timeout=10000)
    locator.click()
    time.sleep(random.uniform(0.2, 0.5))
    locator.fill("")
    time.sleep(random.uniform(0.1, 0.3))
    for char in texto:
        locator.press_sequentially(char, delay=random.randint(delay_min_ms, delay_max_ms))


def _decodificar_cabecera(valor: str) -> str:
    """Decodifica una cabecera de correo que puede estar en encoded-word (ej. Subject)."""
    if not valor:
        return ""
    try:
        partes = decode_header(valor)
        resultado = []
        for texto, encoding in partes:
            if isinstance(texto, bytes):
                resultado.append(texto.decode(encoding or "utf-8", errors="replace"))
            else:
                resultado.append(texto)
        return "".join(resultado)
    except Exception:
        return str(valor)


def _decodificar_payload(part) -> str:
    """Decodifica el cuerpo de una parte del correo (text/plain o text/html)."""
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return ""


def _quitar_html(texto: str) -> str:
    """Quita etiquetas HTML y normaliza espacios para extraer solo texto."""
    if not texto:
        return ""
    # Quitar etiquetas <...>
    sin_html = re.sub(r"<[^>]+>", " ", texto)
    # Normalizar espacios y saltos de línea
    sin_html = re.sub(r"\s+", " ", sin_html).strip()
    return sin_html


def _extraer_codigo_del_cuerpo(body: str) -> str | None:
    """
    Extrae el código de verificación (4-6 dígitos) del cuerpo del correo.
    Mercado Libre suele poner el código como único contenido de un <p>, ej: <p ...>142515</p>
    """
    if not body or not body.strip():
        return None

    # 1) Primero: código como único contenido de una etiqueta (como en el correo de ML)
    # Ej: <p class="...">142515</p> o <span>142515</span>
    solo_en_tag = re.findall(r">\s*(\d{6})\s*<", body)
    if solo_en_tag:
        return solo_en_tag[0]
    solo_en_tag_4_5 = re.findall(r">\s*(\d{4,5})\s*<", body)
    if solo_en_tag_4_5:
        return solo_en_tag_4_5[0]

    # 2) Texto sin HTML y búsqueda por contexto
    texto = _quitar_html(body)
    palabras_clave = r"(?:código|codigo|code|verificaci[oó]n|verification|seguridad|tu\s+código|ingresa|ingresar)"
    codigo_re = re.compile(r"\b(\d{4,6})\b")
    todos = codigo_re.findall(texto)
    if not todos:
        return None
    codigos_6 = [c for c in todos if len(c) == 6]
    if codigos_6:
        texto_lower = texto.lower()
        for c in codigos_6:
            pos = texto.find(c)
            if pos == -1:
                continue
            ventana = texto_lower[max(0, pos - 80) : pos + len(c) + 80]
            if re.search(palabras_clave, ventana):
                return c
        return codigos_6[0]
    return todos[0]


def _obtener_codigo_desde_correo(
    imap_server: str,
    imap_user: str,
    imap_password: str,
    timeout_sec: int = 120,
    intervalo_sec: int = 12,
) -> str | None:
    """
    Conecta por IMAP, busca correos recientes de Mercado Libre y extrae el código
    de verificación (4-6 dígitos). Devuelve None si no encuentra en el tiempo dado.
    """
    if not imap_user or not imap_password:
        return None
    inicio = time.time()
    intento = 0
    while (time.time() - inicio) < timeout_sec:
        intento += 1
        try:
            print(f"  → IMAP: Conectando a {imap_server} (intento {intento})...")
            mail = imaplib.IMAP4_SSL(imap_server)
            mail.login(imap_user, imap_password)
            status, _ = mail.select("INBOX")
            if status != "OK":
                print(f"  → IMAP: No se pudo seleccionar INBOX (status={status})")
                mail.logout()
                time.sleep(intervalo_sec)
                continue
            # ALL: SENTSINCE en Gmail a veces devuelve 0 por zona horaria. Filtramos por fecha en código.
            _, msg_ids = mail.search(None, "ALL")
            raw_ids = msg_ids[0] if msg_ids else b""
            id_list = raw_ids.split() if raw_ids else []
            print(f"  → IMAP: Correos en INBOX: {len(id_list)}")
            if not id_list:
                print("  → IMAP: Si ves 0 pero tienes correos, activa IMAP en Gmail (Configuración → Ver toda la configuración → Reenvío e IMAP) y usa contraseña de aplicación.")
                mail.logout()
                time.sleep(intervalo_sec)
                continue
            ahora = time.time()
            for eid in reversed(id_list[-30:]):
                try:
                    _, data = mail.fetch(eid, "(RFC822)")
                    if not data or not data[0]:
                        continue
                    raw = data[0][1]
                    if raw is None:
                        continue
                    msg = email.message_from_bytes(raw)
                    date_header = msg.get("Date")
                    if date_header:
                        try:
                            dt = parsedate_to_datetime(date_header)
                            if (ahora - dt.timestamp()) > 900:
                                continue
                        except Exception:
                            pass
                    from_raw = msg.get("From", "")
                    subject_raw = msg.get("Subject", "")
                    from_ = _decodificar_cabecera(str(from_raw or "")).lower()
                    subject = _decodificar_cabecera(str(subject_raw or ""))
                    from_sin_espacios = from_.replace(" ", "")
                    subject_lower = subject.lower()
                    if "mercadolibre" not in from_sin_espacios and "mercadolibre" not in subject_lower.replace(" ", ""):
                        if not re.search(r"código|code|verificaci[oó]n|seguridad", subject_lower):
                            continue
                    print(f"  → IMAP: Correo de ML: \"{subject[:60]}...\"")
                    body = ""
                    for part in msg.walk():
                        if part.get_content_maintype() == "text":
                            body += _decodificar_payload(part)
                    codigo = _extraer_codigo_del_cuerpo(body)
                    if codigo:
                        print(f"  → IMAP: Código extraído: {codigo}")
                        mail.logout()
                        return codigo
                    snippet = (_quitar_html(body))[:200].replace("\n", " ")
                    print(f"  → IMAP: Correo de ML sin código en el cuerpo. Fragmento: ...{snippet}...")
                except Exception as ex:
                    print(f"  → IMAP: Error leyendo correo: {ex}")
                    continue
            mail.logout()
        except Exception as e:
            print(f"  → IMAP: {e}")
        time.sleep(intervalo_sec)
    print("  → IMAP: Tiempo agotado sin encontrar código.")
    return None


def _extraer_resultados(
    page, selector_item: str = "li.ui-search-layout__item", limite: int = 20
) -> list[dict]:
    """Extrae hasta `limite` ítems con titulo, precio, ubicacion, vendedor, rating_vendedor."""
    return page.evaluate(
        """
        (params) => {
            const items = document.querySelectorAll(params.selector);
            const limit = Math.min(params.limit, items.length);
            return Array.from(items).slice(0, limit).map(item => {
                const tituloEl = item.querySelector(".ui-search-item__title, h2 a, [class*='title']");
                const precioEl = item.querySelector(".andes-money-amount__fraction, .ui-search-price__part, [class*='price']");
                const ubicacionEl = item.querySelector(".ui-search-item__location, [class*='location']");
                const vendedorEl = item.querySelector("[class*='seller'], [class*='vendedor'], .ui-search-link");
                const ratingEl = item.querySelector("[class*='rating'], [class*='reputation']");
                return {
                    titulo: tituloEl ? tituloEl.textContent.trim() : "",
                    precio: precioEl ? precioEl.textContent.trim() : "",
                    ubicacion: ubicacionEl ? ubicacionEl.textContent.trim() : "",
                    vendedor: vendedorEl ? vendedorEl.textContent.trim() : "",
                    rating_vendedor: ratingEl ? ratingEl.textContent.trim() : ""
                };
            });
        }
        """,
        {"selector": selector_item, "limit": limite},
    )


def guardar_csv(resultados: list[dict], nombre_archivo: str = "mercadolibre_resultados.csv") -> None:
    if not resultados:
        return
    fieldnames = ["titulo", "precio", "ubicacion", "vendedor", "rating_vendedor"]
    with open(nombre_archivo, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(resultados)
    print(f"Datos guardados en {nombre_archivo}")


def guardar_json(resultados: list[dict], nombre_archivo: str = "mercadolibre_resultados.json") -> None:
    with open(nombre_archivo, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"Datos guardados en {nombre_archivo}")


if __name__ == "__main__":
    if not MERCADOLIBRE_EMAIL:
        print("Configura MERCADOLIBRE_EMAIL: ponlo en wscrapper_v1/.env o ejecuta en la terminal:")
        print('  $env:MERCADOLIBRE_EMAIL = "tu_correo@ejemplo.com"')
        print("Si usas .env, instala: pip install python-dotenv")
        exit(1)
    if not IMAP_USER or not IMAP_PASSWORD:
        print("(Para que el código se lea del correo automáticamente, configura IMAP_USER e IMAP_PASSWORD en .env)\n")

    with sync_playwright() as p:
        launch_opts = {
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if USAR_CHROME:
            launch_opts["channel"] = "chrome"
        try:
            browser = p.chromium.launch(**launch_opts)
            if USAR_CHROME:
                print("  → Usando Chrome instalado en el sistema.\n")
        except Exception as e:
            if USAR_CHROME:
                print(f"  → Chrome no encontrado ({e}). Usando Chromium.\n")
                launch_opts.pop("channel", None)
                browser = p.chromium.launch(**launch_opts)
            else:
                raise
        # Contexto más natural para reducir detección de automatización (reCAPTCHA)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-VE",
            timezone_id="America/Caracas",
        )
        page = context.new_page()
        timeout = 15000

        # 1. Ir a la página inicial de Mercado Libre (espera corta para que no parezca bot)
        _espera_humana()
        page.goto(BASE_URL.rstrip("/"), wait_until="domcontentloaded", timeout=timeout)
        _espera_humana()

        # 2. Clic en "Ingresa"
        login_link = page.locator('a[data-link-id="login"]').or_(
            page.get_by_role("link", name="Ingresa")
        ).or_(page.get_by_role("link", name="Ya tengo cuenta")).first
        login_link.wait_for(state="visible", timeout=timeout)
        login_link.click()

        # 3. Esperar página de login y rellenar correo
        page.wait_for_url(lambda url: "/login/" in url, timeout=timeout)
        _espera_humana()
        email_input = page.locator('input#user_id').or_(
            page.locator('input[name="user_id"]')
        ).or_(page.locator('[data-testid="user_id"]')).first
        email_input.wait_for(state="visible", timeout=timeout)
        _escribir_como_humano(page, email_input, MERCADOLIBRE_EMAIL, delay_min_ms=60, delay_max_ms=250)
        _espera_humana()

        # 4. Clic en "Continuar" (automático)
        btn_continuar = page.locator('button.login-form__submit').or_(
            page.get_by_role("button", name="Continuar")
        ).first
        btn_continuar.wait_for(state="visible", timeout=8000)
        btn_continuar.click()

        # 4b. Esperar a que la página cargue la siguiente pantalla (reCAPTCHA o método de verificación)
        print("\n  Esperando siguiente pantalla (puede aparecer reCAPTCHA o directamente verificación)...")
        try:
            page.wait_for_load_state("load", timeout=15000)
        except Exception:
            pass
        time.sleep(5)
        pantalla_verificacion = page.get_by_text("método de verificación", exact=False).or_(
            page.get_by_text("Elige un método", exact=False)
        ).first
        try:
            pantalla_verificacion.wait_for(state="visible", timeout=60000)
            print("  → Pantalla de verificación detectada.\n")
        except Exception:
            print("\n  >>> Si ves reCAPTCHA ('No soy un robot'), resuélvelo en el navegador.")
            print("  >>> Si la página está en blanco o cargando, espera a que aparezca algo.")
            print("  >>> Cuando veas la pantalla para elegir método (E-mail, SMS, etc.), presiona Enter.\n")
            input("  [Presiona Enter cuando veas la pantalla de verificación (o si sigue en blanco, para reintentar)...] ")
            try:
                pantalla_verificacion.wait_for(state="visible", timeout=90000)
                print("  → Pantalla de verificación detectada.\n")
            except Exception as e:
                print(f"\n  No se detectó la pantalla de verificación: {e}")
                print("  Comprueba en el navegador si hay reCAPTCHA o error. Presiona Enter para seguir intentando o Ctrl+C para salir.")
                input("  [Enter para esperar 90 s más la pantalla de verificación...] ")
                pantalla_verificacion.wait_for(state="visible", timeout=90000)

        # 5. Clic en "E-mail" (automático)
        try:
            _espera_humana()
            opcion_email = page.locator("#code_validation button").or_(
                page.locator('button.andes-ui-list_item-actionable[aria-labelledby="code_validation-content"]')
            ).or_(page.get_by_role("button", name="E-mail")).first
            opcion_email.wait_for(state="visible", timeout=5000)
            opcion_email.click()
            print("  → Opción 'E-mail' seleccionada. Se enviará el código a tu correo.")
            _espera_humana()
        except Exception as e:
            print(f"  → No se pudo hacer clic en E-mail automáticamente: {e}. Selecciónalo tú en el navegador.")

        # 6. Código de verificación: ML usa 6 cajas (.andes-code-input), no un solo input
        codigo_ingresado = False
        # Contenedor del código en Mercado Libre (clases de la imagen)
        code_container = page.locator('[data-andes-codeinput="true"]').or_(
            page.locator(".andes-code-input")
        ).first
        try:
            code_container.wait_for(state="visible", timeout=30000)
        except Exception:
            print("  → No se detectó la pantalla del código. ¿Ves 'Ingresa el código' en el navegador?")
        if IMAP_USER and IMAP_PASSWORD:
            _mask = IMAP_USER[:3] + "..." + IMAP_USER.split("@")[-1] if "@" in IMAP_USER else "***"
            print(f"\n  IMAP configurado ({_mask}). Esperando 5 s, luego se busca el código en el correo (cada 5 s, hasta 1 min 30)...")
            time.sleep(5)
            codigo = _obtener_codigo_desde_correo(
                IMAP_SERVER, IMAP_USER, IMAP_PASSWORD, timeout_sec=90, intervalo_sec=5
            )
            if codigo:
                try:
                    code_container.wait_for(state="visible", timeout=15000)
                    # Preferir entrada pausada (menos sospechosa). 1) Seis cajas, 2) teclado, 3) JS como respaldo.
                    filled = False
                    inputs = code_container.locator("input").all()
                    if len(inputs) >= 6:
                        for i, char in enumerate(codigo[:6]):
                            if i < len(inputs):
                                inputs[i].fill(char)
                                time.sleep(random.uniform(0.25, 0.5))
                        filled = True
                    if not filled:
                        code_container.click()
                        time.sleep(0.2)
                        for char in codigo[:6]:
                            page.keyboard.type(char, delay=random.randint(180, 320))
                        filled = True
                    if not filled:
                        filled = page.evaluate(
                            """([codeStr]) => {
                                const input = document.querySelector('input[name="code"]');
                                if (input) {
                                    input.focus();
                                    input.value = codeStr;
                                    input.dispatchEvent(new Event('input', { bubbles: true }));
                                    input.dispatchEvent(new Event('change', { bubbles: true }));
                                    return true;
                                }
                                return false;
                            }""",
                            [codigo],
                        )
                    _espera_humana()
                    btn = page.get_by_role("button", name="Confirmar código").or_(
                        page.get_by_role("button", name="Continuar")
                    ).or_(page.get_by_role("button", name="Verificar")).first
                    btn.wait_for(state="visible", timeout=8000)
                    btn.click()
                    codigo_ingresado = True
                    print("  → Código ingresado automáticamente.")
                    _espera_humana()
                except Exception as e:
                    print(f"  → No se pudo rellenar el código automáticamente: {e}")
            else:
                print("  → No se encontró el código en el correo. Comprueba que IMAP_USER/IMAP_PASSWORD en .env sean del mismo correo que recibe el código de ML.")
        else:
            print("\n  IMAP no configurado. Añade IMAP_USER e IMAP_PASSWORD en .env (mismo correo que MERCADOLIBRE_EMAIL) para que el código se lea del correo automáticamente.")
        if not codigo_ingresado:
            print("Revisa tu correo e ingresa el código en el navegador.")
            input("Cuando hayas ingresado el código y entres al sitio, presiona Enter aquí para continuar...")

        # 7. Asegurarnos de estar en el home (sin cerrar el navegador si algo falla)
        context = page.context
        try:
            # Si ya estamos en el home, la barra de búsqueda estará visible; no hacer goto
            search_input = page.get_by_placeholder("Buscar productos, marcas y más").or_(
                page.locator('input[placeholder*="Buscar"]')
            ).first
            search_input.wait_for(state="visible", timeout=4000)
            print("Ya estás en la página de inicio.")
            _espera_humana()
        except Exception:
            ir_al_home = False
            try:
                print("Cargando página de inicio...")
                page.goto(BASE_URL.rstrip("/"), wait_until="domcontentloaded", timeout=25000)
                ir_al_home = True
            except Exception as e:
                print(f"Error al cargar el home: {e}")
                if context.pages:
                    page = context.pages[-1]
                    try:
                        print("Usando la pestaña actual. Cargando home...")
                        page.goto(BASE_URL.rstrip("/"), wait_until="domcontentloaded", timeout=25000)
                        ir_al_home = True
                    except Exception as e2:
                        print(f"Tampoco pudo cargar en la pestaña actual: {e2}")
                if not ir_al_home:
                    print("No se pudo cargar la página de inicio. No cierres el navegador antes de pulsar Enter.")
                    input("Presiona Enter para cerrar...")
                    browser.close()
                    exit(1)
            if ir_al_home:
                _espera_humana()

        # 8. Búsqueda: usar la barra de búsqueda del home
        try:
            search_input = page.get_by_placeholder("Buscar productos, marcas y más").or_(
                page.locator('input[placeholder*="Buscar"]')
            ).first
            search_input.wait_for(state="visible", timeout=8000)
            search_input.fill(TERMINO_BUSQUEDA)
            _espera_humana()
            search_input.press("Enter")
            print(f"Buscando: {TERMINO_BUSQUEDA}. Esperando resultados...")
        except Exception as e:
            print(f"Barra de búsqueda no encontrada, navegando directo al listado: {e}")
            termino_url = TERMINO_BUSQUEDA.strip().replace(" ", "-").lower()
            page.goto(f"{LISTADO_URL}{termino_url}", wait_until="domcontentloaded", timeout=timeout)

        _espera_humana()

        # 9. Esperar resultados y extraer los primeros N artículos
        selector_item = "li.ui-search-layout__item"
        try:
            page.wait_for_selector(selector_item, timeout=15000)
        except Exception as e:
            print(f"Error esperando resultados (selector '{selector_item}'): {e}")
            print("Comprueba en el navegador si la página de búsqueda cargó correctamente.")
            input("Presiona Enter para cerrar el navegador...")
            browser.close()
            exit(1)

        resultados = _extraer_resultados(page, selector_item, limite=CANTIDAD_ARTICULOS)

        # Mostrar resultados con formato claro
        print("\n" + "=" * 60)
        print(f"  RESULTADOS OBTENIDOS: {len(resultados)} artículos")
        print("=" * 60)
        for i, r in enumerate(resultados, 1):
            titulo = (r.get("titulo") or "").strip()
            precio = (r.get("precio") or "").strip()
            ubicacion = (r.get("ubicacion") or "").strip()
            vendedor = (r.get("vendedor") or "").strip()
            rating = (r.get("rating_vendedor") or "").strip()
            if len(titulo) > 55:
                titulo = titulo[:52] + "..."
            print(f"\n  [{i}] {titulo}")
            print(f"      Precio:      {precio or '-'}")
            print(f"      Ubicación:   {ubicacion or '-'}")
            print(f"      Vendedor:    {vendedor or '-'}")
            print(f"      Rating:      {rating or '-'}")
        print("\n" + "=" * 60)

        # Guardar resultados en CSV y JSON automáticamente (sin preguntar en consola)
        guardar_csv(resultados)
        guardar_json(resultados)

        # Cerrar sesión en Mercado Libre antes de cerrar el navegador (flujo natural)
        print("\n  Cerrando sesión en Mercado Libre...")
        try:
            menu_usuario = page.locator('a[aria-label*="menu"]').or_(
                page.locator('a.nav-header-user-myml')
            ).or_(page.locator('label[for="nav-header-user-switch"]')).first
            menu_usuario.wait_for(state="visible", timeout=5000)
            menu_usuario.click()
            _espera_humana()
            salir = page.locator('a[data-id="logout"]').or_(
                page.get_by_role("link", name="Salir")
            ).first
            salir.wait_for(state="visible", timeout=5000)
            salir.click()
            time.sleep(2)
            print("  → Sesión cerrada correctamente.")
        except Exception as e:
            print(f"  → No se pudo cerrar sesión automáticamente: {e}")

        input("\nPresiona Enter para cerrar el navegador...")
        browser.close()
