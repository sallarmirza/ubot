# main.py 
from fastapi import FastAPI
from router import google_oauth_router as oauth_router

app=FastAPI(title="Fastapi Backend")
app.include_router(oauth_router,prefix='auth')

@app.get('/')
def get_heath():
    return "Backend is up and running"
