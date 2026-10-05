# main.py 
from fastapi import FastAPI

app=FastAPI(title="Fastapi Backend")

@app.get('/')
def get_heath():
    return "Backend is up and running"
