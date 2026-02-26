"""
Scraper de búsqueda en Mercado Libre (solo búsqueda, sin login).
Pide en consola: término de búsqueda y cantidad de artículos.
Abre Mercado Libre, busca, extrae los datos y guarda en un archivo .json.
"""
from playwright.sync_api import sync_playwright
import os
import time
import random
import json
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    for _p in [
        os.path.join(_script_dir, "..", "..", ".env"),
        os.path.join(os.getcwd(), "wscrapper_v1", ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]:
        if os.path.isfile(_p):
            load_dotenv(_p)
            break
except ImportError:
    pass

BASE_URL = os.environ.get("MERCADOLIBRE_BASE_URL", "https://www.mercadolibre.com.ve/").rstrip("/")
LISTADO_URL = os.environ.get("MERCADOLIBRE_LISTADO_URL", "https://listado.mercadolibre.com.ve/").rstrip("/") + "/"
USAR_CHROME = os.environ.get("MERCADOLIBRE_USAR_CHROMIUM", "").strip().lower() not in ("1", "true", "sí", "si", "yes")


def _espera_humana() -> None:
    time.sleep(random.uniform(0.8, 2))


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


def _nombre_archivo_safe(termino: str) -> str:
    """Genera un nombre de archivo seguro a partir del término de búsqueda."""
    s = re.sub(r"[^\w\s-]", "", termino.strip().lower())
    s = re.sub(r"[-\s]+", "_", s).strip("_") or "busqueda"
    return f"mercadolibre_{s}.json"


if __name__ == "__main__":
    print("\n  --- Búsqueda en Mercado Libre (sin login) ---\n")
    termino = input("  Término de búsqueda (ej: laptop, smartphone): ").strip()
    if not termino:
        print("  No se ingresó término. Saliendo.")
        exit(1)
    cantidad_str = input("  Cantidad de artículos a extraer (ej: 20): ").strip()
    try:
        cantidad = max(1, min(500, int(cantidad_str)))
    except ValueError:
        cantidad = 20
        print(f"  Usando cantidad por defecto: {cantidad}")
    print(f"\n  Buscar: \"{termino}\" | Extraer: {cantidad} artículos\n")

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
                print("  → Usando Chrome instalado.\n")
        except Exception as e:
            if USAR_CHROME:
                print(f"  → Chrome no encontrado ({e}). Usando Chromium.\n")
                launch_opts.pop("channel", None)
            browser = p.chromium.launch(**launch_opts)

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
        timeout = 20000

        # 1. Ir a Mercado Libre
        print("  Abriendo Mercado Libre...")
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=timeout)
        _espera_humana()

        # 2. Buscar en la barra
        try:
            search_input = page.get_by_placeholder("Buscar productos, marcas y más").or_(
                page.locator('input[placeholder*="Buscar"]')
            ).first
            search_input.wait_for(state="visible", timeout=10000)
            search_input.fill(termino)
            _espera_humana()
            search_input.press("Enter")
            print(f"  Buscando \"{termino}\"...")
        except Exception as e:
            print(f"  Barra no encontrada ({e}), navegando al listado directo...")
            termino_url = termino.strip().replace(" ", "-").lower()
            termino_url = re.sub(r"[^\w-]", "", termino_url) or "busqueda"
            page.goto(f"{LISTADO_URL}{termino_url}", wait_until="domcontentloaded", timeout=timeout)

        _espera_humana()

        # 3. Esperar resultados y extraer
        selector_item = "li.ui-search-layout__item"
        try:
            page.wait_for_selector(selector_item, timeout=15000)
        except Exception as e:
            print(f"  Error esperando resultados: {e}")
            input("  Presiona Enter para cerrar...")
            browser.close()
            exit(1)

        resultados = _extraer_resultados(page, selector_item, limite=cantidad)

        # 4. Mostrar resumen y guardar en JSON
        print("\n" + "=" * 60)
        print(f"  RESULTADOS: {len(resultados)} artículos")
        print("=" * 60)
        for i, r in enumerate(resultados[:10], 1):
            titulo = (r.get("titulo") or "")[:55] + ("..." if len(r.get("titulo") or "") > 55 else "")
            precio = (r.get("precio") or "-").strip()
            print(f"  [{i}] {titulo}  |  {precio}")
        if len(resultados) > 10:
            print(f"  ... y {len(resultados) - 10} más")
        print("=" * 60)

        nombre_archivo = _nombre_archivo_safe(termino)
        with open(nombre_archivo, "w", encoding="utf-8") as f:
            json.dump(resultados, f, indent=2, ensure_ascii=False)
        print(f"\n  Datos guardados en: {nombre_archivo}")

        browser.close()
        print("  Navegador cerrado.")
