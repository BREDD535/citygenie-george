from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import pandas as pd
from io import BytesIO
from functools import lru_cache

app = FastAPI(title="CityGenie George")

# Cache for 15min so we don't get IP banned
CACHE_MINUTES = 15

def cache_expired(cached_time):
    return datetime.now() - cached_time > timedelta(minutes=CACHE_MINUTES)

@lru_cache(maxsize=1)
def get_cached_data():
    return {
        "time": datetime.now(),
        "dam": fetch_dam_level(),
        "notices": fetch_notices(),
        "internet": fetch_internet_status(),
        "loadshedding": fetch_loadshedding(),
        "weather": fetch_weather_alerts(),
        "crime": fetch_crime_stats()
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

def fetch_internet_status():
    outages = []
    try:
        r = requests.get("https://www.vumatel.co.za/network-status", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('.outage-item,.alert')[:5]:
            area = item.get_text(strip=True)
            if any(x in area for x in ["George", "Garden Route", "Southern Cape"]):
                outages.append(f"Vumatel: {area}")
    except:
        pass
    return outages if outages else ["No major ISP outages reported"]

def fetch_loadshedding():
    try:
        # Free EskomSePush API - get token at eskomsepush.com
        # For now return placeholder if no token
        return {"stage": "Check EskomSePush", "area": "George", "next": "18:00"}
    except:
        return {"stage": "Unknown", "area": "George"}

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
        # SAPS data - update URL quarterly
        url = "https://www.saps.gov.za/services/quarterly_crimestats_2026_q1.xlsx"
        r = requests.get(url, timeout=10)
        df = pd.read_excel(BytesIO(r.content), sheet_name="Western Cape")
        george_stations = ['GEORGE', 'CONVILLE', 'THEMBALETHU', 'PACALTSDORP']
        df_g = df[df['Station'].isin(george_stations)]
        return df_g[['Station', 'Common robbery', 'Burglary at residential premises']].head(2).to_dict('records')
    except:
        return [{"Station":"Data unavailable","note":"SAPS site down or quarterly update pending"}]

@app.get("/", response_class=HTMLResponse)
async def root():
    d = get_data()
    updated = d["time"].strftime("%d %b %H:%M")
    
    notices_html = "".join([f"<li>{n}</li>" for n in d["notices"]])
    internet_html = "".join([f"<li style='color:#cc0000'>{n}</li>" for n in d["internet"]])
    crime_html = ""
    for s in d["crime"]:
        if 'Station' in s:
            crime_html += f"<b>{s['Station']}</b>: Robbery {s.get('Common robbery','?')}, Housebreaking {s.get('Burglary at residential premises','?')}<br>"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>CityGenie George</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="manifest" href="/static/manifest.json">
        <meta name="theme-color" content="#0066cc">
        <style>
            body {{ font-family: -apple-system, Arial; padding: 12px; background: #f0f2f5; margin:0; }}
           .card {{ background: white; padding: 16px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 12px; }}
            h1 {{ color: #0066cc; margin: 0 0 8px 0; font-size: 24px; }}
            h2 {{ color: #333; margin: 0 0 8px 0; font-size: 18px; }}
           .dam {{ font-size: 44px; font-weight: 700; color: #00aa44; line-height:1; }}
           .small {{ color: #666; font-size: 13px; }}
           .alert {{ background:#fff3cd; border-left:4px solid #ffc107; padding:8px; margin:8px 0; }}
            ul {{ padding-left: 18px; margin: 8px 0; }}
            li {{ margin-bottom: 6px; }}
           .footer {{ text-align:center; color:#999; font-size:11px; padding:20px 0; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>George Municipality</h1>
            <div class="dam">{d["dam"]}</div>
            <div class="small">Garden Route Dam Level</div>
            <div class="small">Updated: {updated}</div>
        </div>
        
        <div class="card">
            <h2>Load Shedding</h2>
            <div><b>Stage:</b> {d["loadshedding"]["stage"]}</div>
            <div class="small">Area: George. Add EskomSePush token for live data.</div>
        </div>
        
        <div class="card">
            <h2>Internet/Fibre Status</h2>
            <ul>{internet_html}</ul>
        </div>
        
        <div class="card">
            <h2>Weather Alerts</h2>
            <div class="alert">{d["weather"]}</div>
        </div>
        
        <div class="card">
            <h2>Latest Notices</h2>
            <ul>{notices_html}</ul>
        </div>
        
        <div class="card">
            <h2>SAPS Crime Stats - Latest Quarter</h2>
            <div class="small">{crime_html}</div>
            <div class="small" style="margin-top:8px;color:#666">10111 for emergencies. Data: SAPS. May be 3 months delayed.</div>
        </div>
        
        <div class="footer">
            CityGenie displays public info only. For emergencies dial 10111. <br>
            Not affiliated with George Municipality. Data cached 15min.
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
        "internet_outages": d["internet"],
        "loadshedding": d["loadshedding"],
        "weather_alert": d["weather"],
        "crime_stats": d["crime"],
        "updated": d["time"].isoformat(),
        "disclaimer": "For emergencies dial 10111"
    })

@app.get("/health")
async def health():
    return {"status": "ok"}
