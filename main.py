from fastapi import FastAPI, Request, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil
from pathlib import Path
from io import BytesIO

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def get_upload(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/api/preprocess", response_class=JSONResponse)
async def api_preprocess_pdf(file: UploadFile = File(...)):
    try:
        content = file.read()
        filename = file.filename

        # Simulate checking for form fields in the PDF
        import random
        has_form_fields = random.choice([True, False])

        return {"filename": filename, "has_form_fields": has_form_fields}
    except Exception as e:
        raise HTTPException(status_code=400, detail="An error occurred while preprocessing the PDF.")


@app.post("/api/upload", response_class=JSONResponse)
async def api_upload_file(request: Request, file: UploadFile = File(...)):
    try:
        content = await file.read()
        filename = file.filename
        size = len(content)

        # Simulate the stats generation taking a long time
        import time
        time.sleep(5)

        return {"filename": filename, "size": size}
    except Exception as e:
        raise HTTPException(status_code=400, detail="An error occurred while processing the file.")


@app.post("/upload/", response_class=HTMLResponse)
async def upload(request: Request, file: UploadFile = File(...)):
    content = file.file.read()
    size = len(content)
    
    return templates.TemplateResponse(
        "info.html",
        {
            "request": request,
            "filename": file.filename,
            "size": size,
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
