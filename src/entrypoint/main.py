from fastapi import FastAPI, UploadFile, File
import shutil
import os
from core import ingestor

app = FastAPI(title="RiskFlow API")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    try:
        headers = ingestor.get_headers(temp_path)
        return {"filename": file.filename, "headers": headers}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)