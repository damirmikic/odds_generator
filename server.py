import pandas as pd
import io
import time
import os
import json
from datetime import datetime, timedelta

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

# --- FUNKCIJA ZA PREUZIMANJE I OBRADU PODATAKA POMOĆU SELENIUM-A ---
def fetch_and_save_stats():
    """
    Preuzima sveže podatke sa fbref.com koristeći Selenium i čuva ih u JSON fajl.
    Spaja 'Standard', 'Shooting', i 'Miscellaneous' statistike.
    """
    print("Pokušavam da preuzmem sveže podatke sa fbref.com pomoću Selenium-a...")
    
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
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
            "misc": "https://fbref.com/en/comps/Big5/misc/players/Big-5-European-Leagues-Stats"
        }
        
        dataframes = {}

        def parse_table(driver, table_container_id):
            wait_time = 20
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
                print("Tabela pronađena direktno.")
            else:
                print("Tabela nije pronađena direktno, tražim u komentarima...")
                comments = soup.find_all(string=lambda text: isinstance(text, Comment))
                for comment in comments:
                    if BeautifulSoup(comment, 'lxml').find('table'):
                        table_html_content = comment
                        print("Tabela pronađena u komentaru.")
                        break
            
            if not table_html_content:
                raise Exception(f"Nije moguće pronaći tabelu unutar kontejnera '{table_container_id}'")

            df_list = pd.read_html(io.StringIO(table_html_content))
            if not df_list:
                raise Exception(f"Pandas nije uspeo da pročita tabelu iz HTML-a za '{table_container_id}'")
            
            df = df_list[0]
            
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(0)
            
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
            time.sleep(2)

        # --- AŽURIRANA I POUZDANIJA LOGIKA SPAJANJA ---
        print("\nSpajam preuzete tabele...")
        # Počinjemo sa 'standard' tabelom kao osnovom
        combined_df = dataframes['standard']

        # Spajamo 'shooting' tabelu
        df_shooting_rel = dataframes['shooting'].drop_duplicates(subset=['Player', 'Squad'])
        combined_df = pd.merge(
            combined_df, 
            df_shooting_rel, 
            on=['Player', 'Squad'], 
            how='left',
            suffixes=('', '_shooting')
        )

        # Spajamo 'misc' tabelu
        df_misc_rel = dataframes['misc'].drop_duplicates(subset=['Player', 'Squad'])
        combined_df = pd.merge(
            combined_df,
            df_misc_rel,
            on=['Player', 'Squad'],
            how='left',
            suffixes=('', '_misc')
        )
        print("Tabele uspešno spojene.")

        # Čišćenje dupliranih kolona nakon spajanja
        combined_df = combined_df.loc[:, ~combined_df.columns.str.endswith(('_shooting', '_misc'))]
        combined_df = combined_df.loc[:, ~combined_df.columns.duplicated()]

        # Čišćenje i proračun
        numeric_cols = ['90s', 'Gls', 'Ast', 'Sh', 'SoT', 'Fls']
        for col in numeric_cols:
            if col in combined_df.columns:
                combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce')
        
        combined_df.fillna(0, inplace=True)
        combined_df = combined_df[combined_df['90s'] > 0].copy()

        combined_df['Gls_90'] = (combined_df['Gls'] / combined_df['90s']).round(2)
        combined_df['Ast_90'] = (combined_df['Ast'] / combined_df['90s']).round(2)
        combined_df['Sh_90'] = (combined_df['Sh'] / combined_df['90s']).round(2)
        combined_df['SoT_90'] = (combined_df['SoT'] / combined_df['90s']).round(2)
        combined_df['Fls_90'] = (combined_df['Fls'] / combined_df['90s']).round(2)

        player_data = combined_df.to_dict('records')

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
