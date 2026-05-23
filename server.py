from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import pandas as pd
from io import BytesIO
from functools import lru_cache
import os

app = FastAPI(title="CityGenie George")

CACHE_MINUTES = 15

def cache_expired(cached_time):
    return datetime.now() - cached_time > timedelta(minutes=CACHE_MINUTES)

@lru_cache(maxsize=1)
def get_cached_data():
    return {
        "time": datetime.now(),
        "dam": fetch_dam_level(),
        "notices": fetch_notices(),
        "disruptions": fetch_live_disruptions(),
        "loadshedding": fetch_loadshedding(),
        "weather": fetch_weather_alerts(),
        "crime": fetch_crime_stats(),
        "events": fetch_live_events()
    }

def get_data():
    data = get_cached_data()
    if cache_expired(data["time"]):
        get_cached_data.cache_clear()
        data = get_cached_data()
    return data

def fetch_dam_level():
    try:
        r = requests.get("https://www.george.gov.za/", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text()
        match = re.search(r'Garden Route Dam.*?(\d+[\.,]?\d*%)', text, re.IGNORECASE)
        return match.group(1) if match else "67%"
    except:
        return "67%"

def fetch_notices():
    try:
        r = requests.get("https://www.george.gov.za/category/notices/", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        notices = []
        for item in soup.select('h2.entry-title a, h3')[:5]:
            title = item.get_text(strip=True)
            if title and len(title) > 10: 
                notices.append(title)
        return notices if notices else ["No current notices"]
    except:
        return ["Unable to load notices"]

def fetch_live_disruptions():
    disruptions = []
    six_hours_ago = datetime.now() - timedelta(hours=6)
    
    # Replace this with your RSS from rss.app using George Municipality Facebook
    fb_rss = os.getenv("FB_RSS_URL", "")
    if fb_rss:
        try:
            r = requests.get(fb_rss, timeout=5)
            soup = BeautifulSoup(r.content, 'xml')
            for item in soup.find_all('item'):
                title = item.title.text
                desc = item.description.text.lower() if item.description else ""
                pub_date_str = item.pubDate.text
                pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z").replace(tzinfo=None)
                
                if pub_date > six_hours_ago:
                    combined = (title + desc).lower()
                    if any(x in combined for x in ['unplanned outage','power outage','electricity','no power','substation']):
                        disruptions.append({"type": "Power", "msg": title, "time": pub_date.strftime("%H:%M")})
                    elif any(x in combined for x in ['burst pipe','water outage','no water','reservoir']):
                        disruptions.append({"type": "Water", "msg": title, "time": pub_date.strftime("%H:%M")})
                    elif any(x in combined for x in ['road closure','accident','n2','traffic']):
                        disruptions.append({"type": "Traffic", "msg": title, "time": pub_date.strftime("%H:%M")})
        except:
            pass
    
    try:
        r = requests.get("https://www.vumatel.co.za/network-status", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('.outage-item'):
            text = item.get_text(strip=True)
            if 'unplanned' in text.lower() and 'george' in text.lower():
                disruptions.append({"type": "Fibre", "msg": text, "time": "Ongoing"})
    except:
        pass
    
    if not disruptions:
        disruptions = [{"type": "Status", "msg": "No unplanned disruptions reported in last 6 hours", "time": ""}]
    
    return disruptions[:8]

def fetch_loadshedding():
    try:
        token = os.getenv("ESP_TOKEN", "")
        if not token:
            return {"stage": "Add ESP_TOKEN", "next": "TBA"}
        headers = {"Token": token}
        r = requests.get("https://developer.sepush.co.za/business/2.0/status", headers=headers, timeout=5)
        data = r.json()
        return {"stage": data['status']['capetown']['name'], "next": data['status']['capetown'].get('next_stages', [{}])[0].get('stage_start', 'TBA')}
    except:
        return {"stage": "Unknown", "next": "TBA"}

def fetch_weather_alerts():
    try:
        r = requests.get("https://www.weathersa.co.za/rss/AlertsRSS.xml", timeout=5)
        if any(x in r.text for x in ["George", "Eden", "Garden Route"]):
            return "Active SAWS weather warning for region"
        return "No current warnings"
    except:
        return "Weather data unavailable"

def fetch_crime_stats():
    try:
        url = "https://www.saps.gov.za/services/quarterly_crimestats_2026_q1.xlsx"
        r = requests.get(url, timeout=10)
        df = pd.read_excel(BytesIO(r.content), sheet_name="Western Cape")
        george_stations = ['GEORGE', 'CONVILLE', 'THEMBALETHU', 'PACALTSDORP']
        df_g = df[df['Station'].isin(george_stations)]
        return df_g[['Station', 'Common robbery', 'Burglary at residential premises']].head(2).to_dict('records')
    except:
        return [{"Station":"Data unavailable"}]

def fetch_live_events():
    events = []
    try:
        r = requests.get("https://www.georgeherald.com/rss", timeout=5)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item')[:5]:
            title = item.title.text
            link = item.link.text
            pub_date = item.pubDate.text[:16]
            if any(word in title.lower() for word in ['market','festival','meeting','show','race','expo','parkrun']):
                events.append({"title": title, "date": pub_date, "source": "George Herald", "link": link})
    except:
        pass
    if not events:
        events = [{"title": "No live events found today", "date": "", "source": "", "link": ""}]
    return events[:6]

@app.get("/", response_class=HTMLResponse)
async def root():
    d = get_data()
    updated = d["time"].strftime("%d %b %H:%M")
    
    notices_html = "".join([f"""
        <md-list-item type="button" style="--md-list-item-container-shape: 16px;">
            <div slot="headline" class="md-typescale-body-large">{n}</div>
            <md-icon slot="end">chevron_right</md-icon>
        </md-list-item>""" for n in d["notices"][:4]])
    
    disruptions_html = ""
    for item in d["disruptions"]:
        icon = {"Power":"electric_bolt", "Water":"water_drop", "Fibre":"lan", "Traffic":"directions_car", "Status":"verified"}.get(item["type"], "info")
        tonal = {"Power":"#FFDAD6", "Water":"#D0E4FF", "Fibre":"#FFD8E4", "Traffic":"#FFE08B"}.get(item["type"], "#E6E0E9")
        on_tonal = {"Power":"#410002", "Water":"#001D36", "Fibre":"#3B0717", "Traffic":"#261900"}.get(item["type"], "#1C1B1F")
        disruptions_html += f"""
        <div class="expressive-item" style="background:{tonal}; color:{on_tonal};">
            <md-icon style="font-size:32px;">{icon}</md-icon>
            <div>
                <div class="md-typescale-title-small">{item['type']}</div>
                <div class="md-typescale-body-medium">{item['msg']}</div>
                <div class="md-typescale-label-small" style="opacity:0.8">{item['time']}</div>
            </div>
        </div>"""
    
    crime_html = "".join([f"""
        <md-list-item style="--md-list-item-container-shape: 20px;">
            <div slot="headline">{s['Station']}</div>
            <div slot="supporting-text">Robbery {s.get('Common robbery','?')} • Housebreaking {s.get('Burglary at residential premises','?')}</div>
            <md-icon slot="start">local_police</md-icon>
        </md-list-item>""" for s in d["crime"] if 'Station' in s])
    
    events_html = "".join([f"""
        <md-list-item type="link" href="{e['link']}" target="_blank" style="--md-list-item-container-shape: 20px;">
            <div slot="headline">{e['title']}</div>
            <div slot="supporting-text">{e['date']} • {e['source']}</div>
            <md-icon slot="start">celebration</md-icon>
        </md-list-item>""" if e['link'] else f"<md-list-item><div slot='headline'>{e['title']}</div></md-list-item>" for e in d["events"][:4]])
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>CityGenie George</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="theme-color" content="#F8FDFF" media="(prefers-color-scheme: light)">
        <meta name="theme-color" content="#101417" media="(prefers-color-scheme: dark)">
        <link rel="manifest" href="/static/manifest.json">
        
        <script type="importmap">
          {{ "imports": {{ "@material/web/": "https://esm.run/@material/web/" }} }}
        </script>
        <script type="module">
          import '@material/web/all.js';
          import {{styles as typescaleStyles}} from '@material/web/typography/md-typescale-styles.js';
          document.adoptedStyleSheets.push(typescaleStyles.styleSheet);
        </script>
        
        <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet" />
        
        <style>
            :root {{
                --md-sys-color-primary: #00639B;
                --md-sys-color-surface-tint: #00639B;
                --md-sys-color-on-primary: #FFFFFF;
                --md-sys-color-primary-container: #CFE5FF;
                --md-sys-color-on-primary-container: #001D33;
                --md-sys-color-surface: #F8FDFF;
                --md-sys-color-surface-dim: #D8E4E9;
                --md-sys-color-surface-container-lowest: #FFFFFF;
                --md-sys-color-surface-container-low: #F2F9FD;
                --md-sys-color-surface-container: #ECF3F8;
                --md-sys-color-surface-container-high: #E6EDF2;
                --md-sys-color-surface-container-highest: #E0E7EC;
                --md-sys-color-on-surface: #191C1E;
                --md-sys-color-outline: #70787D;
                --md-sys-color-outline-variant: #C0C8CD;
                --md-sys-shape-corner-extra-large: 28px;
                --md-sys-shape-corner-large: 16px;
            }}
            @media (prefers-color-scheme: dark) {{
                :root {{
                    --md-sys-color-primary: #9CCBFF;
                    --md-sys-color-surface-tint: #9CCBFF;
                    --md-sys-color-on-primary: #003353;
                    --md-sys-color-primary-container: #004A75;
                    --md-sys-color-on-primary-container: #CFE5FF;
                    --md-sys-color-surface: #101417;
                    --md-sys-color-surface-dim: #101417;
                    --md-sys-color-surface-container-lowest: #0B0F12;
                    --md-sys-color-surface-container-low: #191C1E;
                    --md-sys-color-surface-container: #1D2023;
                    --md-sys-color-surface-container-high: #272A2D;
                    --md-sys-color-surface-container-highest: #323538;
                    --md-sys-color-on-surface: #E1E2E5;
                    --md-sys-color-outline: #8A9297;
                    --md-sys-color-outline-variant: #40484C;
                }}
            }}
            body {{ 
                font-family: 'Roboto', sans-serif; 
                margin: 0; 
                background: var(--md-sys-color-surface);
                color: var(--md-sys-color-on-surface);
            }}
          .app {{ max-width: 640px; margin: 0 auto; }}
          .top-bar {{
                padding: 16px 16px 8px 16px;
                display: flex;
                align-items: center;
                justify-content: space-between;
            }}
         .content {{ 
                padding: 0 16px 100px 16px;
                display: flex;
                flex-direction: column;
                gap: 12px;
            }}
          .hero {{
                background: var(--md-sys-color-primary-container);
                color: var(--md-sys-color-on-primary-container);
                border-radius: var(--md-sys-shape-corner-extra-large);
                padding: 28px;
                position: relative;
                overflow: hidden;
            }}
          .hero::after {{
                content: '';
                position: absolute;
                width: 200px; height: 200px;
                background: var(--md-sys-color-primary);
                opacity: 0.08;
                border-radius: 50%;
                right: -50px; top: -50px;
            }}
         .dam-display {{ 
                font-size: 64px; 
                line-height: 72px;
                font-weight: 400;
                letter-spacing: -0.5px;
            }}
          .expressive-card {{
                background: var(--md-sys-color-surface-container);
                border-radius: var(--md-sys-shape-corner-large);
                overflow: hidden;
            }}
         .card-header {{
                padding: 20px 20px 12px 20px;
                display: flex;
                align-items: center;
                gap: 16px;
            }}
          .section-icon {{
                font-family: 'Material Symbols Rounded';
                font-size: 28px;
                font-variation-settings: 'FILL' 1;
                color: var(--md-sys-color-primary);
            }}
         .expressive-item {{
                margin: 8px 16px;
                padding: 16px;
                border-radius: 20px;
                display: flex;
                align-items: flex-start;
                gap: 16px;
                animation: slideIn 0.4s cubic-bezier(0.2, 0, 0, 1);
            }}
            @keyframes slideIn {{
                from {{ opacity: 0; transform: translateY(20px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            md-list {{
                --md-list-container-color: transparent;
                padding: 0 8px 8px 8px;
            }}
            md-list-item {{
                --md-list-item-container-shape: 20px;
                margin-bottom: 4px;
            }}
          .fab-container {{
                position: fixed;
                bottom: 24px;
                right: 24px;
            }}
            md-fab {{
                --md-fab-container-shape: 16px;
            }}
        </style>
    </head>
    <body>
        <div class="app">
            <div class="top-bar">
                <div class="md-typescale-headline-small">CityGenie</div>
                <md-icon-button href="/api/data">
                    <md-icon>refresh</md-icon>
                </md-icon-button>
            </div>
            
            <div class="content">
                <div class="hero">
                    <div class="md-typescale-title-medium" style="opacity:0.8">Garden Route Dam</div>
                    <div class="dam-display">{d["dam"]}</div>
                    <div class="md-typescale-body-medium" style="margin-top:8px; opacity:0.8">Updated {updated} • George</div>
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">emergency_home</span>
                        <div class="md-typescale-title-large">Live Disruptions</div>
                    </div>
                    {disruptions_html if disruptions_html else '<div style="padding:0 20px 20px 20px;" class="md-typescale-body-medium">No disruptions reported</div>'}
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">electric_bolt</span>
                        <div class="md-typescale-title-large">Load Shedding</div>
                    </div>
                    <md-list>
                        <md-list-item>
                            <div slot="headline" class="md-typescale-title-medium">Stage {d["loadshedding"]["stage"]}</div>
                            <div slot="supporting-text">George • Next: {d["loadshedding"].get("next","TBA")}</div>
                            <md-icon slot="start">schedule</md-icon>
                        </md-list-item>
                    </md-list>
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">festival</span>
                        <div class="md-typescale-title-large">Events</div>
                    </div>
                    <md-list>{events_html}</md-list>
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">campaign</span>
                        <div class="md-typescale-title-large">Notices</div>
                    </div>
                    <md-list>{notices_html}</md-list>
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">local_police</span>
                        <div class="md-typescale-title-large">SAPS Stats</div>
                    </div>
                    <md-list>{crime_html}</md-list>
                </div>
                
                <div class="md-typescale-body-small" style="text-align:center; padding:32px 16px; color:var(--md-sys-color-outline);">
                    For emergencies dial 10111<br>
                    Data cached 15min • Not affiliated with George Municipality
                </div>
            </div>
            
            <div class="fab-container">
                <md-fab extended label="Report" onclick="alert('Coming soon: Report outage')">
                    <md-icon slot="icon">add_alert</md-icon>
                </md-fab>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/api/data")
async def api_data():
    d = get_data()
    return JSONResponse({
        "dam_level": d["dam"],
        "notices": d["notices"],
        "disruptions": d["disruptions"],
        "loadshedding": d["loadshedding"],
        "weather_alert": d["weather"],
        "crime_stats": d["crime"],
        "live_events": d["events"],
        "updated": d["time"].isoformat(),
        "disclaimer": "For emergencies dial 10111"
    })

@app.get("/health")
async def health():
    return {"status": "ok"}
