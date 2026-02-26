from playwright.sync_api import sync_playwright
import time
import csv
import json

def scrape_books():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        todos_los_libros = []
        pagina_actual = 1

        while True: 
            if pagina_actual == 1:
                url = "https://books.toscrape.com/"
            else: 
                url = f"https://books.toscrape.com/catalogue/page-{pagina_actual}.html"
            print (f"Scraping pagina {pagina_actual}")
            page.goto(url)

            if page.query_selector(".product_pod") is None:
                print("No hay más paginas")
                break

            libros = page.evaluate("""
            () => {
                const productos = document.querySelectorAll(".product_pod");
                return Array.from(productos).map(libro => ({
                    titulo: libro.querySelector("h3 a").getAttribute("title"),
                    precio: libro.querySelector(".price_color").innerText,
                    disponible: libro.querySelector(".instock") ? true : false,
                    rating: libro.querySelector(".star-rating").classList[1]
                }));
            }
            """)
            todos_los_libros.extend(libros)
            pagina_actual += 1
            time.sleep(0.5)
        browser.close()
        return todos_los_libros
    
libros = scrape_books()
print(f'Total de libros extraidos: {len(libros)}')


def guardar_en_csv(libros, nombre_archivo = 'libros.csv'):
    with open (nombre_archivo, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames= ['titulo', 'precio', 'disponible', 'rating'])
        writer.writeheader()
        writer.writerows(libros)
    print(f'Datos guardados en {nombre_archivo}') 

def guardar_en_json(libros, nombre_archivo ='libros.json'):
    with open (nombre_archivo, 'w', encoding='utf-8') as f:
        json.dump(libros, f, indent = 2, ensure_ascii=False)
    print(f'Datos guardados en {nombre_archivo}') 

guardar_en_csv(libros)
guardar_en_json(libros)

