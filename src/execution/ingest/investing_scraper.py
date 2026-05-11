from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from datetime import datetime



def test_chromedriver(path="driver/chromedriver.exe"):
    print("🔧 Verificando ChromeDriver...")

    options = Options()
    ##options.add_argument("--headless")
    options.add_argument("--disable-gpu")

    service = Service(executable_path=path)

    try:
        driver = webdriver.Chrome(service=service, options=options)
        driver.get("https://www.google.com")
        try:
            close_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "popupCloseIcon"))
            )
            close_button.click()
            print("🧹 Popup cerrado.")
        except:
            print("ℹ️ No apareció popup.")
        title = driver.title
        driver.quit()
        if "Google" in title:
            print("✅ ChromeDriver funciona correctamente.")
            return True
        else:
            print("⚠️ ChromeDriver se ejecutó pero no cargó correctamente.")
            return False
    except Exception as e:
        print(f"❌ Error al iniciar ChromeDriver: {e}")
        return False
    
#if not test_chromedriver("driver/chromedriver.exe"):
#    print("🚫 No se puede continuar con Selenium. Verificá el driver.")
#    exit()    
# Mapeo actualizado
ticker_map = {
    "GGAL.BA": "gp-fin-galicia",
    "YPFD.BA": "ypf",
    "PAMP.BA": "pampa-energia",
    "BMA.BA": "banco-macro",
    "TXAR.BA": "ternium",
    "CEPU.BA": "central-puerto",
    "AAPL.BA": "apple-inc-cedear",
    "TSLA.BA": "tesla-inc-cedear",
    "GOOGL.BA": "alphabet-inc-cedear",
    "MSFT.BA": "microsoft-corp-cedear"
}

def fetch_from_investing(ticker):
    print(f"🧭 Scraping con Selenium: {ticker}")

    if ticker not in ticker_map:
        print(f"⚠️ Ticker {ticker} no está mapeado para Investing.com")
        return None

    slug = ticker_map[ticker]
    url = f"https://www.investing.com/equities/{slug}-historical-data"

    # Configuración del navegador
    options = Options()
    ##options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=es-ES")
    options.add_argument("--no-sandbox")

    service = Service(executable_path="driver/chromedriver.exe")
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(url)

        # Esperar a que la tabla se cargue
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "curr_table"))
        )

        table = driver.find_element(By.ID, "curr_table")
        rows = table.find_elements(By.TAG_NAME, "tr")[1:]

        data = []
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 6:
                continue
            try:
                date = datetime.strptime(cols[0].text.strip(), "%d.%m.%Y")
                close = float(cols[1].text.replace(",", "").replace("-", ""))
                open_ = float(cols[2].text.replace(",", "").replace("-", ""))
                high = float(cols[3].text.replace(",", "").replace("-", ""))
                low = float(cols[4].text.replace(",", "").replace("-", ""))
                volume = cols[5].text.replace(",", "").replace("-", "0")
                volume = int(volume) if volume.isdigit() else 0
                data.append([date, open_, high, low, close, volume])
            except:
                continue

        driver.quit()

        df = pd.DataFrame(data, columns=["date", "open", "high", "low", "close", "volume"])
        df.set_index("date", inplace=True)
        df = df.sort_index()
        return df

    except Exception as e:
        driver.quit()
        print(f"❌ Error con Selenium para {ticker}: {e}")
        return None