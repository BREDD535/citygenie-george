from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
from functools import lru_cache
import os

app = FastAPI(title="CityGenie George")

CACHE_MINUTES = 15

# VERIFY YEARLY: https://www.george.gov.za/refuse-removal/
REFUSE_SCHEDULE = {
    "Monday": ["Heatherlands", "Denneoord", "Fernridge"],
    "Tuesday": ["Blanco", "Heather Park", "Camphersdrift"],
    "Wednesday": ["George Central", "Dormehlsdrift", "Glen Barrie"],
    "Thursday": ["Thembalethu", "Lawaaikamp", "Borcherds"],
    "Friday": ["Pacaltsdorp", "Delville Park", "Andersonville"],
    "Saturday": ["Leisure Isle", "Wilderness"]
}

# SAFE: Generic contacts. For ward-specific names, check https://www.george.gov.za/council/ward-councillors
COUNCILLORS = {
    "General": {"name": "George Municipality", "phone": "044 801 9111", "area": "Switchboard - ask for your ward councillor"},
    "WhatsApp": {"name": "Municipal WhatsApp", "phone": "044 803 5555", "area": "Report service issues 24/7"},
    "After Hours": {"name": "Emergency Standby", "phone": "044 801 6300", "area": "Water & electricity emergencies only"},
}

def cache_expired(cached_time):
    return datetime.now() - cached_time > timedelta(minutes=CACHE_MINUTES)

@lru_cache(maxsize=1)
def get_cached_data():
    return {
        "time": datetime.now(),
        "dam": fetch_dam_level(),
        "notices": fetch_notices(),
        "disruptions": fetch_live_disruptions(),
        "weather": fetch_weather_alerts(),
        "events": fetch_live_events(),
        "bus_alerts": fetch_bus_alerts(),
        "water_restrictions": fetch_water_restrictions(),
        "refuse": REFUSE_SCHEDULE
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
    twenty_four_hours_ago = datetime.now() - timedelta(hours=24)
    
    fb_rss = os.getenv("FB_RSS_URL", "")
    if fb_rss:
        try:
            r = requests.get(fb_rss, timeout=5)
            soup = BeautifulSoup(r.content, 'xml')
            for item in soup.find_all('item'):
                title = item.title.text if item.title else ""
                desc = item.description.text if item.description else ""
                pub_date_str = item.pubDate.text
                pub_date = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z").replace(tzinfo=None)
                
                combined = (title + " " + desc).lower()
                power_words = ['unplanned outage','power outage','electricity','no power','substation','krag','onderbreking','load','tripped','fault','outage','beurtkrag']
                water_words = ['burst pipe','water outage','no water','reservoir','supply interruption','water','pyp','gebars','lek']
                traffic_words = ['road closure','accident','n2','n12','traffic','collision','closure','pad','botsing']
                
                if pub_date > twenty_four_hours_ago:
                    if any(x in combined for x in power_words):
                        disruptions.append({"type": "Power", "msg": title[:120], "time": pub_date.strftime("%H:%M")})
                    elif any(x in combined for x in water_words):
                        disruptions.append({"type": "Water", "msg": title[:120], "time": pub_date.strftime("%H:%M")})
                    elif any(x in combined for x in traffic_words):
                        disruptions.append({"type": "Traffic", "msg": title[:120], "time": pub_date.strftime("%H:%M")})
        except Exception as e:
            print(f"FB RSS error: {e}")
    
    try:
        r = requests.get("https://www.vumatel.co.za/network-status", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('.outage-item, .alert'):
            text = item.get_text(strip=True).lower()
            if 'unplanned' in text and 'george' in text:
                disruptions.append({"type": "Fibre", "msg": item.get_text(strip=True)[:120], "time": "Ongoing"})
    except:
        pass
    
    manual_outage = os.getenv("MANUAL_OUTAGE", "")
    if manual_outage:
        try:
            o_type, o_msg, o_time = manual_outage.split("|")
            disruptions.insert(0, {"type": o_type, "msg": o_msg, "time": o_time})
        except:
            pass
    
    seen = set()
    unique = []
    for d in sorted(disruptions, key=lambda x: x['time'], reverse=True):
        key = d['msg'][:40]
        if key not in seen:
            seen.add(key)
            unique.append(d)
    
    if not unique:
        unique = [{"type": "Status", "msg": "No unplanned disruptions reported in last 24 hours", "time": ""}]
    
    return unique[:8]

def fetch_bus_alerts():
    alerts = []
    try:
        r = requests.get("https://www.gogeorge.org.za/service-alerts/", timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('.alert-item, .notice, .entry-content p')[:4]:
            text = item.get_text(strip=True)
            if len(text) > 15:
                alerts.append(text[:150])
    except:
        pass
    return alerts if alerts else ["No Go George service alerts currently"]

def fetch_water_restrictions():
    try:
        r = requests.get("https://www.george.gov.za/", timeout=5)
        text = r.text
        match = re.search(r'Water Restrictions.*?Level\s*(\d)', text, re.IGNORECASE | re.DOTALL)
        if match:
            level = match.group(1)
            details = {
                "1": "No watering 10am-4pm. Handheld hosepipes allowed.",
                "2": "No hosepipes. Buckets only 6-9am & 6-9pm.",
                "3": "No outdoor water use. Drinking/essential only.",
                "4": "Severe restrictions. Municipal supply points only."
            }
            return {"level": f"Level {level}", "detail": details.get(level, "Check municipality site")}
        return {"level": "No restrictions", "detail": "Normal water use permitted"}
    except:
        return {"level": "Unknown", "detail": "Check george.gov.za"}

def fetch_weather_alerts():
    try:
        r = requests.get("https://www.weathersa.co.za/rss/AlertsRSS.xml", timeout=5)
        if any(x in r.text for x in ["George", "Eden", "Garden Route"]):
            return "Active SAWS weather warning for region"
        return "No current warnings"
    except:
        return "Weather data unavailable"

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
                <div class="md-typescale-body-medium" style="hyphens:auto;">{item['msg']}</div>
                <div class="md-typescale-label-small" style="opacity:0.8">{item['time']}</div>
            </div>
        </div>"""
    
    events_html = "".join([f"""
        <md-list-item type="link" href="{e['link']}" target="_blank" style="--md-list-item-container-shape: 20px;">
            <div slot="headline">{e['title']}</div>
            <div slot="supporting-text">{e['date']} • {e['source']}</div>
            <md-icon slot="start">celebration</md-icon>
        </md-list-item>""" if e['link'] else f"<md-list-item><div slot='headline'>{e['title']}</div></md-list-item>" for e in d["events"][:4]])
    
    bus_html = "".join([f"""
        <md-list-item style="--md-list-item-container-shape: 20px;">
            <div slot="headline">{alert}</div>
            <md-icon slot="start">directions_bus</md-icon>
        </md-list-item>""" for alert in d["bus_alerts"][:3]])
    
    refuse_html = ""
    today = datetime.now().strftime("%A")
    for day, suburbs in d["refuse"].items():
        is_today = " (Today)" if day == today else ""
        refuse_html += f"""
        <md-list-item style="--md-list-item-container-shape: 20px;">
            <div slot="headline">{day}{is_today}</div>
            <div slot="supporting-text">{', '.join(suburbs[:3])}{'...' if len(suburbs) > 3 else ''}</div>
            <md-icon slot="start">delete</md-icon>
        </md-list-item>"""
    
    councillor_html = "".join([f"""
        <md-list-item href="tel:{c['phone'].replace(' ', '')}" style="--md-list-item-container-shape: 20px;">
            <div slot="headline">{c['name']}</div>
            <div slot="supporting-text">{c['area']}</div>
            <md-icon slot="start">phone</md-icon>
            <md-icon slot="end">call</md-icon>
        </md-list-item>""" for c in COUNCILLORS.values()])
    
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
                --md-sys-color-surface-container-lowest: #FFFFFF;
                --md-sys-color-surface-container-low: #F2F9FD;
                --md-sys-color-surface-container: #ECF3F8;
                --md-sys-color-surface-container-high: #E6EDF2;
                --md-sys-color-surface-container-highest: #E0E7EC;
                --md-sys-color-on-surface: #191C1E;
                --md-sys-color-on-surface-variant: #41484D;
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
                    --md-sys-color-surface-container-lowest: #0B0F12;
                    --md-sys-color-surface-container-low: #191C1E;
                    --md-sys-color-surface-container: #1D2023;
                    --md-sys-color-surface-container-high: #272A2D;
                    --md-sys-color-surface-container-highest: #323538;
                    --md-sys-color-on-surface: #E1E2E5;
                    --md-sys-color-on-surface-variant: #C0C8CD;
                    --md-sys-color-outline: #8A9297;
                    --md-sys-color-outline-variant: #40484C;
                }}
            }}
            * {{ box-sizing: border-box; }}
            body {{ 
                font-family: 'Roboto', system-ui, sans-serif; 
                margin: 0; 
                background: var(--md-sys-color-surface);
                color: var(--md-sys-color-on-surface);
                line-height: 1.5; 
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
                padding: 24px 28px;
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
                font-size: clamp(48px, 15vw, 64px); 
                line-height: 1.1;
                font-weight: 400;
                letter-spacing: -0.5px;
                word-break: break-word;
            }}
          .expressive-card {{
                background: var(--md-sys-color-surface-container);
                border-radius: var(--md-sys-shape-corner-large);
                overflow: hidden;
            }}
         .card-header {{
                padding: 20px 20px 8px 20px;
                display: flex;
                align-items: center;
                gap: 16px;
            }}
          .section-icon {{
                font-family: 'Material Symbols Rounded';
                font-size: 28px;
                font-variation-settings: 'FILL' 1;
                color: var(--md-sys-color-primary);
                flex-shrink: 0;
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
         .expressive-item md-icon {{
                flex-shrink: 0;
                margin-top: 2px;
            }}
         .expressive-item > div {{
                flex: 1;
                min-width: 0;
            }}
         .expressive-item .md-typescale-body-medium {{
                word-wrap: break-word;
                overflow-wrap: break-word;
                white-space: normal;
                line-height: 1.4;
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
                --md-list-item-label-text-line-height: 1.4;
                --md-list-item-supporting-text-line-height: 1.4;
                margin-bottom: 4px;
                min-height: 56px;
            }}
            md-list-item [slot="headline"] {{
                white-space: normal !important;
                word-wrap: break-word;
                overflow-wrap: break-word;
            }}
            md-list-item [slot="supporting-text"] {{
                white-space: normal !important;
                word-wrap: break-word;
                color: var(--md-sys-color-on-surface-variant);
            }}
          .fab-container {{
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 10;
            }}
            md-fab {{
                --md-fab-container-shape: 16px;
            }}
            @media (max-width: 360px) {{
              .content {{ padding: 0 12px 100px 12px; }}
              .hero {{ padding: 20px; }}
             .card-header {{ padding: 16px 16px 8px 16px; }}
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
                        <span class="section-icon">directions_bus</span>
                        <div class="md-typescale-title-large">Go George Alerts</div>
                    </div>
                    <md-list>{bus_html}</md-list>
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">water_drop</span>
                        <div class="md-typescale-title-large">Water Restrictions</div>
                    </div>
                    <md-list>
                        <md-list-item>
                            <div slot="headline">{d["water_restrictions"]["level"]}</div>
                            <div slot="supporting-text">{d["water_restrictions"]["detail"]}</div>
                            <md-icon slot="start">info</md-icon>
                        </md-list-item>
                    </md-list>
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">delete</span>
                        <div class="md-typescale-title-large">Refuse Collection</div>
                    </div>
                    <md-list>{refuse_html}</md-list>
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
                        <span class="section-icon">cloud</span>
                        <div class="md-typescale-title-large">Weather</div>
                    </div>
                    <md-list>
                        <md-list-item>
                            <div slot="headline">{d["weather"]}</div>
                            <md-icon slot="start">warning</md-icon>
                        </md-list-item>
                    </md-list>
                </div>
                
                <div class="expressive-card">
                    <div class="card-header">
                        <span class="section-icon">contact_phone</span>
                        <div class="md-typescale-title-large">Municipal Contacts</div>
                    </div>
                    <md-list>{councillor_html}</md-list>
                </div>
                
                <div class="md-typescale-body-small" style="text-align:center; padding:32px 16px; color:var(--md-sys-color-outline);">
                    For emergencies dial 10111<br>
                    Data cached 15min • Not affiliated with George Municipality<br>
                    Refuse schedule: Verify at george.gov.za
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
        "weather_alert": d["weather"],
        "live_events": d["events"],
        "bus_alerts": d["bus_alerts"],
        "water_restrictions": d["water_restrictions"],
        "refuse_schedule": d["refuse"],
        "councillors": COUNCILLORS,
        "updated": d["time"].isoformat(),
        "disclaimer": "For emergencies dial 10111"
    })

@app.get("/health")
async def health():
    return {"status": "ok"}
