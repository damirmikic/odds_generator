import pandas as pd
import io
import time
import os
import json
from datetime import datetime, timedelta
from functools import reduce

from flask import Flask, jsonify
from flask_cors import CORS

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup, Comment

# --- Inicijalizacija Flask servera ---
app = Flask(__name__)
CORS(app)

# Naziv fajla za keširanje
CACHE_FILE = 'fbref_stats.json'

# --- Osnovna ruta za proveru statusa ---
@app.route('/')
def index():
    return jsonify({"status": "Odds Generator API is running successfully."})

# --- FUNKCIJA ZA PREUZIMANJE I OBRADU PODATAKA POMOĆU SELENIUM-A ---
def fetch_and_save_stats():
    """
    Preuzima sveže podatke sa fbref.com koristeći Selenium i čuva ih u JSON fajl.
    Spaja 'Standard', 'Shooting', 'Passing' i 'Miscellaneous' statistike.
    """
    print("Pokušavam da preuzmem sveže podatke sa fbref.com pomoću Selenium-a...")
    
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = None
    try:
        print("Podešavanje Chrome WebDriver-a...")
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        print("WebDriver je spreman.")

        urls_to_scrape = {
            "standard": "https://fbref.com/en/comps/Big5/stats/players/Big-5-European-Leagues-Stats",
            "shooting": "https://fbref.com/en/comps/Big5/shooting/players/Big-5-European-Leagues-Stats",
            "passing": "https://fbref.com/en/comps/Big5/passing/players/Big-5-European-Leagues-Stats",
            "misc": "https://fbref.com/en/comps/Big5/misc/players/Big-5-European-Leagues-Stats"
        }
        
        dataframes = {}

        def parse_table(driver, table_container_id):
            wait_time = 30
            print(f"Čekam na kontejner tabele: '{table_container_id}'...")
            table_container = WebDriverWait(driver, wait_time).until(
                EC.presence_of_element_located((By.ID, table_container_id))
            )
            print("Kontejner pronađen.")

            container_html = table_container.get_attribute('innerHTML')
            soup = BeautifulSoup(container_html, 'lxml')

            table_html_content = None
            table_element = soup.find('table')
            if table_element:
                table_html_content = str(table_element)
            else:
                comments = soup.find_all(string=lambda text: isinstance(text, Comment))
                for comment in comments:
                    if BeautifulSoup(comment, 'lxml').find('table'):
                        table_html_content = comment
                        break
            
            if not table_html_content:
                raise Exception(f"Nije moguće pronaći tabelu unutar kontejnera '{table_container_id}'")

            df = pd.read_html(io.StringIO(table_html_content))[0]
            
            # AŽURIRANO: Najrobusniji način za čišćenje zaglavlja
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ['_'.join(col).strip() for col in df.columns.values]
            
            df = df.rename(columns=lambda x: x.replace(' ', '_').replace('%', 'Pct'))
            
            if 'Player' in df.columns:
                df = df[df['Player'] != 'Player'].reset_index(drop=True)
            
            return df

        for key, url in urls_to_scrape.items():
            print(f"\nPreuzimam tabelu: '{key}' sa URL: {url}")
            driver.get(url)
            df = parse_table(driver, f'div_stats_{key}')
            if df is not None:
                dataframes[key] = df
                print(f"Tabela '{key}' uspešno preuzeta.")
            else:
                raise Exception(f"DataFrame za '{key}' je None.")
            time.sleep(3)

        # Spajanje tabela
        print("\nSpajam preuzete tabele...")
        df_standard_rel = dataframes['standard'][['Player', 'Squad', 'Age', '90s', 'Gls', 'Ast']]
        df_shooting_rel = dataframes['shooting'][['Player', 'Squad', 'Sh', 'SoT']]
        df_passing_rel = dataframes['passing'][['Player', 'Squad', 'Total_Att']]
        df_misc_rel = dataframes['misc'][['Player', 'Squad', 'Fls', 'Fld']]
        
        dfs_to_merge = [df_standard_rel, df_shooting_rel, df_passing_rel, df_misc_rel]
        df_final = reduce(lambda left, right: pd.merge(left, right, on=['Player', 'Squad'], how='outer'), dfs_to_merge)
        
        df_final.rename(columns={'Total_Att': 'Att'}, inplace=True)
        print("Tabele uspešno spojene.")

        # Čišćenje i proračun
        numeric_cols = ['90s', 'Gls', 'Ast', 'Sh', 'SoT', 'Att', 'Fls', 'Fld']
        for col in numeric_cols:
            if col in df_final.columns:
                df_final[col] = pd.to_numeric(df_final[col], errors='coerce')
        
        df_final.fillna(0, inplace=True)
        df_final = df_final[df_final['90s'] > 0].copy()

        df_final['Gls_90'] = (df_final['Gls'] / df_final['90s']).round(2)
        df_final['Ast_90'] = (df_final['Ast'] / df_final['90s']).round(2)
        df_final['Sh_90'] = (df_final['Sh'] / df_final['90s']).round(2)
        df_final['SoT_90'] = (df_final['SoT'] / df_final['90s']).round(2)
        df_final['Pass_Att_90'] = (df_final['Att'] / df_final['90s']).round(2)
        df_final['Fls_90'] = (df_final['Fls'] / df_final['90s']).round(2)
        df_final['Fld_90'] = (df_final['Fld'] / df_final['90s']).round(2)

        player_data = df_final.to_dict('records')

        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(player_data, f, ensure_ascii=False, indent=4)
        
        print(f"Podaci uspešno preuzeti i sačuvani u '{CACHE_FILE}'.")
        return player_data

    except TimeoutException:
        print(f"Greška: Isteklo je vreme čekanja na elemente stranice.")
        return None
    except Exception as e:
        print(f"Došlo je do neočekivane greške: {e}")
        return None
    finally:
        if driver:
            print("Zatvaram WebDriver.")
            driver.quit()

# --- API RUTA ---
@app.route('/api/stats', methods=['GET'])
def get_stats_api():
    print("Primljen zahtev za /api/stats")
    
    if os.path.exists(CACHE_FILE):
        file_mod_time = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE))
        if datetime.now() - file_mod_time < timedelta(hours=24):
            print(f"Učitavam podatke iz keš fajla '{CACHE_FILE}'.")
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            print(f"Slanje podataka za {len(stats)} igrača.")
            return jsonify(stats)

    stats = fetch_and_save_stats()
    if stats:
        print(f"Slanje sveže preuzetih podataka za {len(stats)} igrača.")
        return jsonify(stats)
    else:
        print("Greška: Nema podataka za slanje.")
        return jsonify({"error": "Nije moguće preuzeti podatke sa Fbref-a."}), 500

# --- POKRETANJE SERVERA ---
if __name__ == "__main__":
    app.run(debug=True, port=5000)
