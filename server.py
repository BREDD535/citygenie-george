from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/")
async def root():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>CityGenie Test</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
    </head>
    <body>
        <h1>George Municipality</h1>
        <p>If you see this, the server works!</p>
        <p>Garden Route Dam: 67%</p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
