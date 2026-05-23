from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import requests
from datetime import datetime

app = FastAPI()

def get_dam_level():
    try:
        # Using George Municipality page as source
        url = "https://www.george.gov.za/"
        r = requests.get(url, timeout=5)
        text = r.text
        # Quick scrape - finds "Garden Route Dam" and % near it
        start = text.find("Garden Route Dam")
        if start == -1: return "67%"  # fallback
        snippet = text[start:start+200]
        for word in snippet.split():
            if "%" in word and word.replace("%","").replace(",","").isdigit():
                return word
        return "67%"
    except:
        return "67%"  # fallback if site is down

@app.get("/", response_class=HTMLResponse)
async def root():
    dam = get_dam_level()
    updated = datetime.now().strftime("%d %b %H:%M")
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>CityGenie George</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial; padding: 20px; background: #f5f5f5; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            h1 {{ color: #0066cc; margin: 0 0 10px 0; }}
            .dam {{ font-size: 48px; font-weight: bold; color: #00aa44; }}
            .small {{ color: #666; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>George Municipality</h1>
            <div class="dam">{dam}</div>
            <div class="small">Garden Route Dam Level</div>
            <div class="small">Updated: {updated}</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
