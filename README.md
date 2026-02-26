# wscrapper_v1

Proyecto de web scraping desarrollado con fines netamente educacionales y de investigacion. El codigo fue realizado bajo estudio y practica de tecnicas de extraccion de datos web, automatizacion con navegador y manejo de paginas dinamicas. No debe utilizarse para violar terminos de uso de sitios terceros ni para fines comerciales no autorizados.

**Autor:** William Flores

---

## Descripcion del proyecto

Este repositorio contiene varios scripts de scraping en Python que utilizan **Playwright** para controlar un navegador y extraer informacion de sitios web. Incluye ejemplos desde un sitio de practica (Books to Scrape) hasta flujos mas complejos en Mercado Libre (busqueda con y sin inicio de sesion).

**Dependencias principales:**

- Python 3.x
- Playwright (`pip install playwright` y luego `playwright install` para los navegadores)
- python-dotenv (para variables de entorno desde `.env`)

---

## Estructura del proyecto

```
wscrapper_v1/
  .env                    # Variables de entorno (credenciales, IMAP, etc.). No subir a control de versiones.
  .gitignore
  README.md
  src/
    scrapers/
      scraper-v1.py                 # Scraper de ejemplo: Books to Scrape
      scraper-mercadolibre-busqueda.py  # Busqueda en Mercado Libre sin login
      scraper-mercadolibre.py       # Flujo completo Mercado Libre con login y (opcional) IMAP
```

---

## Archivos scraper: funcionamiento y utilidad

### 1. `scraper-v1.py`

**Ubicacion:** `src/scrapers/scraper-v1.py`

**Que hace:** Scraper de ejemplo sobre el sitio de practica [Books to Scrape](https://books.toscrape.com/). Recorre todas las paginas del catalogo de libros, extrae por cada libro: titulo, precio, disponibilidad (en stock o no) y valoracion (rating). Guarda los datos en `libros.csv` y `libros.json`.

**Como funciona:**

- Usa Playwright en modo headless (sin ventana visible).
- Navega a la URL base y luego a cada pagina del catalogo (`page-1`, `page-2`, etc.).
- En cada pagina ejecuta JavaScript en el navegador (`page.evaluate`) para obtener los nodos `.product_pod` y leer titulo, precio, clase de stock y clase de estrellas.
- Acumula todos los libros en una lista y al final llama a `guardar_en_csv` y `guardar_en_json`.

**Para que sirve:** Sirve como introduccion al scraping con Playwright: seleccion de elementos, evaluacion en la pagina, paginacion y exportacion a CSV/JSON. Es util para aprender sin depender de login ni de sitios con protecciones anti-bot.

---

### 2. `scraper-mercadolibre-busqueda.py`

**Ubicacion:** `src/scrapers/scraper-mercadolibre-busqueda.py`

**Que hace:** Realiza busquedas en Mercado Libre (Venezuela por defecto) **sin iniciar sesion**. Pide por consola el termino de busqueda y la cantidad de articulos a extraer. Abre el sitio, escribe en la barra de busqueda, espera resultados y extrae titulo, precio, ubicacion, vendedor y rating del vendedor. Guarda todo en un archivo JSON con nombre derivado del termino (por ejemplo `mercadolibre_laptop.json`).

**Como funciona:**

- Carga variables desde `.env` (opcional): `MERCADOLIBRE_BASE_URL`, `MERCADOLIBRE_LISTADO_URL`, `MERCADOLIBRE_USAR_CHROMIUM`.
- Lanza el navegador en modo visible (`headless: False`) y con opciones para reducir deteccion de automatizacion.
- Puede usar Chrome instalado en el sistema (recomendado) o Chromium de Playwright segun configuracion.
- Navega a la pagina principal, localiza el input de busqueda (por placeholder o selector), escribe el termino y pulsa Enter.
- Si no encuentra la barra, construye la URL del listado y navega directamente.
- Espera a que aparezcan los items (`li.ui-search-layout__item`) y ejecuta `_extraer_resultados`: con `page.evaluate` recorre los elementos y lee titulo, precio, ubicacion, vendedor y rating con selectores flexibles.
- Limita la cantidad de resultados al numero pedido y guarda en JSON con nombre seguro (`_nombre_archivo_safe`).

**Para que sirve:** Permite obtener datos de busquedas de Mercado Libre sin cuentas ni verificacion. Util para practicar extraccion en un sitio real, manejo de consola y exportacion JSON. Ideal cuando solo se necesita datos publicos de listados.

---

### 3. `scraper-mercadolibre.py`

**Ubicacion:** `src/scrapers/scraper-mercadolibre.py`

**Que hace:** Flujo completo en Mercado Libre con **inicio de sesion**: automatiza el ingreso con correo, el boton "Continuar", la eleccion del metodo de verificacion "E-mail" y, de forma opcional, la lectura del codigo de verificacion desde el correo via IMAP y su ingreso en la pagina. Tras iniciar sesion, realiza una busqueda (termino configurable), extrae N articulos con los mismos campos que el scraper de busqueda y guarda en CSV y JSON. Al final intenta cerrar sesion de forma automatica.

**Como funciona:**

- **Configuracion:** Lee de `.env`: `MERCADOLIBRE_EMAIL` (obligatorio), `IMAP_SERVER`, `IMAP_USER`, `IMAP_PASSWORD` (opcionales, para leer el codigo del correo), `MERCADOLIBRE_BUSQUEDA` (termino a buscar), `MERCADOLIBRE_USAR_CHROMIUM` (usar Chromium en lugar de Chrome). Constantes internas definen la cantidad de articulos a extraer y URLs base.
- **Navegador:** Igual que en busqueda: ventana visible, argumentos para parecer menos automatizado, preferencia por Chrome instalado.
- **Login:** Navega a Mercado Libre, hace clic en "Ingresa", rellena el correo con escritura simulada humana (`_escribir_como_humano` con delays aleatorios), pulsa "Continuar". Espera la pantalla de verificacion (o reCAPTCHA; en ese caso puede pedir intervencion manual).
- **Verificacion por correo:** Haz clic en la opcion "E-mail". Si estan configurados `IMAP_USER` e `IMAP_PASSWORD`, la funcion `_obtener_codigo_desde_correo` se conecta por IMAP, busca correos recientes de Mercado Libre y extrae el codigo de 4-6 digitos del cuerpo del mensaje (`_extraer_codigo_del_cuerpo`). Luego rellena los campos del codigo en la pagina (varias cajas o un solo input) y confirma. Si no hay IMAP o falla, el script pide al usuario que ingrese el codigo manualmente y pulse Enter.
- **Busqueda y extraccion:** Una vez dentro, localiza la barra de busqueda del home, escribe el termino de busqueda (variable de entorno o valor por defecto), pulsa Enter (o navega al listado si falla). Espera los resultados, usa la misma logica de `_extraer_resultados` que el scraper de busqueda y limita al numero definido de articulos.
- **Exportacion:** Llama a `guardar_csv` y `guardar_json` con nombres fijos (`mercadolibre_resultados.csv` y `mercadolibre_resultados.json`).
- **Cierre:** Intenta abrir el menu de usuario y hacer clic en "Salir" para cerrar sesion antes de cerrar el navegador.

**Para que sirve:** Ejemplo avanzado de automatizacion con login, posibles captchas, integracion con correo (IMAP) y extraccion posterior. Sirve para estudiar flujos multi-paso, escritura “humana”, manejo de timeouts y exportacion a CSV/JSON. Solo debe usarse en el ambito educativo y respetando los terminos de uso del sitio.

---

## Configuracion (variables de entorno)

Crear un archivo `.env` en la raiz de `wscrapper_v1` (y asegurarse de que no se sube a Git). Ejemplo de variables utilizadas por los scrapers de Mercado Libre:

- `MERCADOLIBRE_EMAIL`: Correo de la cuenta de Mercado Libre (necesario para `scraper-mercadolibre.py`).
- `MERCADOLIBRE_BASE_URL`: URL base del sitio (por defecto Mercado Libre Venezuela).
- `MERCADOLIBRE_LISTADO_URL`: URL base del listado de busqueda.
- `MERCADOLIBRE_USAR_CHROMIUM`: Si es `1` o `true`, usa Chromium de Playwright; si no, intenta usar Chrome instalado.
- `MERCADOLIBRE_BUSQUEDA`: Termino de busqueda por defecto en `scraper-mercadolibre.py`.
- `IMAP_SERVER`, `IMAP_USER`, `IMAP_PASSWORD`: Opcionales; para que `scraper-mercadolibre.py` lea el codigo de verificacion desde el correo (por ejemplo Gmail con IMAP y contraseña de aplicacion).

---

## Como ejecutar los scrapers

Desde la raiz del proyecto o desde `src/scrapers`, con el entorno virtual activado y Playwright instalado:

```bash
# Scraper de libros (ejemplo)
python src/scrapers/scraper-v1.py

# Busqueda en Mercado Libre sin login (pide termino y cantidad por consola)
python src/scrapers/scraper-mercadolibre-busqueda.py

# Mercado Libre con login (requiere MERCADOLIBRE_EMAIL en .env)
python src/scrapers/scraper-mercadolibre.py
```

Antes de usar Playwright por primera vez:

```bash
pip install playwright python-dotenv
playwright install
```

---

## Aviso legal y uso responsable

Este proyecto fue realizado bajo investigacion y estudio con fines netamente educacionales. El autor, William Flores, no se hace responsable del uso que terceros den a este codigo. El usuario debe:

- Respetar los terminos de uso y politicas de los sitios que se scrapeen.
- No utilizar los scripts para sobrecargar servidores, extraer datos personales sin consentimiento ni fines ilegales o no autorizados.
- Entender que sitios como Mercado Libre pueden emplear medidas anti-bot (por ejemplo reCAPTCHA) y que evadirlas puede violar sus condiciones de uso.

El proposito del repositorio es exclusivamente el aprendizaje de tecnicas de scraping y automatizacion en un contexto educativo.
