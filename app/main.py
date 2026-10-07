import requests
import json
import math
import os
from pathlib import Path
import re
from secrets import token_hex
from datetime import datetime, timezone
from html import escape
from typing import Tuple, Union, List

import logging
import pandas
import textstat
from fastapi import FastAPI, Request, File, Form, UploadFile, HTTPException
from fastapi.middleware import Middleware
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response
from rq import Queue, get_current_job
from rq.decorators import job
from rq.exceptions import NoSuchJobError
import rq
import pikepdf

import formfyxer
from formfyxer import lit_explorer
from worker import conn
from limits import UploadLimitMiddleware, MAX_UPLOAD_BYTES, JOB_TIMEOUT

# Configure the logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

queue = Queue(connection=conn)

app = FastAPI()
app.add_middleware(UploadLimitMiddleware)


async def set_url_scheme(request: Request, call_next):
    app.url_scheme = request.url.scheme
    response = await call_next(request)
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith(("/view/", "/download/", "/job-status/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


app.middleware("http")(set_url_scheme)


def format_number(number: Union[float, str]):
    return "{:,.2f}".format(float(number))


templates = Jinja2Templates(directory="templates")
templates.env.filters["format_number"] = format_number

SITE_ROOT = os.path.realpath(os.path.dirname(__file__))
if os.getenv("IN_DOCKER", "False").lower() == "true":
    UPLOAD_FOLDER = "/pdf-files"
else:
    UPLOAD_FOLDER = "/tmp"
TERMS_VERSION = "2026-10-07"
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx"}

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/healthz")
async def healthz():
    """Simple health endpoint for container healthchecks."""
    return {"status": "ok"}


def allowed_file(filename: str) -> bool:
    """Check if the given file has an allowed extension.

    Args:
        filename (str): The name of the file.

    Returns:
        bool: True if the file is allowed, False otherwise.
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def valid_hash(hash: str) -> bool:
    """Check if the given hash is valid.

    Args:
        hash (str): The hash string.

    Returns:
        bool: True if the hash is valid, False otherwise.
    """
    return bool(re.match(r"^[A-Fa-f0-9]{64}$", hash))


def highlight_text(
    text: str, ranges: List[Tuple[int, int]], class_name="highlight"
) -> str:
    """Highlight the text in the given ranges using the specified CSS class name.

    Args:
        text (str): The input text.
        ranges (List[Tuple[int, int]]): A list of tuples representing the start and end positions to highlight.
        class_name (str, optional): The CSS class name to apply to the highlighted text. Defaults to "highlight".

    Returns:
        str: The text with the specified ranges highlighted using a an HTML `<span>`
    """
    output = []
    prev_end = 0

    for start, end in sorted(ranges):
        start = max(prev_end, min(len(text), start))
        end = max(start, min(len(text), end))
        output.append(escape(text[prev_end:start]))
        output.append(f'<span class="{escape(class_name, quote=True)}">')
        output.append(escape(text[start:end]))
        output.append("</span>")
        prev_end = end

    output.append(escape(text[prev_end:]))
    return "".join(output)


def get_pdf_from_dir(file_hash):
    path_to_dir = os.path.join(UPLOAD_FOLDER, file_hash)
    if not os.path.isdir(path_to_dir):
        return None
    for f in os.listdir(path_to_dir):
        if f.endswith(".pdf"):
            return f
    return None


def get_pdf_title_from_hash(file_hash: str) -> str:
    filename = get_pdf_from_dir(file_hash)
    if not filename:
        return ""
    try:
        with pikepdf.open(os.path.join(UPLOAD_FOLDER, file_hash, filename)) as pdf:
            title = pdf.docinfo.get("/Title")
            if title:
                return str(title)
    except (pikepdf.PdfError, OSError):
        pass
    return Path(filename).stem.replace("-", " ").replace("_", " ")


def has_fields(pdf_file: str) -> bool:
    """
    Check if a PDF has at least one form field using PikePDF.

    Args:
        pdf_file (str): The path to the PDF file.

    Returns:
        bool: True if the PDF has at least one form field, False otherwise.
    """
    with pikepdf.open(pdf_file) as pdf:
        for page in pdf.pages:
            annotations = page.get("/Annots", [])
            if not isinstance(annotations, (pikepdf.Array, list)):
                continue
            for annot in annotations:
                # /Type is optional. Ignore malformed entries and non-widget annotations.
                if isinstance(annot, pikepdf.Dictionary) and annot.get("/Subtype") == "/Widget":
                    return True
    return False


def convert_word_to_pdf(input_file: str, output_file: str, gotenberg_url: str):
    """
    Convert a Word document to a PDF using the Gotenberg API.

    Args:
        input_file (str): The path to the input Word document.
        output_file (str): The path to the output PDF file.
        gotenberg_url (str): The base URL of the Gotenberg service.

    Raises:
        Exception: If the conversion fails and returns a non-200 status code.
    """
    gotenberg_url = gotenberg_url + "/forms/libreoffice/convert"
    with open(input_file, "rb") as file:
        response = requests.post(
            gotenberg_url, files={"files": (Path(input_file).name, file)},
            timeout=(5, 60), stream=True
        )

    if response.status_code == 200:
        with open(output_file, "wb") as file:
            size = 0
            try:
                for chunk in response.iter_content(64 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ValueError("Converted PDF exceeds the upload limit")
                    file.write(chunk)
            finally:
                response.close()
    else:
        raise Exception(f"Conversion failed with status code: {response.status_code}")


@app.get("/", response_class=HTMLResponse)
async def upload_file(request: Request):
    return templates.TemplateResponse(request=request, name="ratemypdf.html", context={"request": request, "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024), "terms_version": TERMS_VERSION})


@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse(request=request,
        name="terms.html", context={"request": request, "title": "Terms of use and privacy", "terms_version": TERMS_VERSION}
    )


@job("default", connection=conn, timeout=JOB_TIMEOUT)
def parse_form_job(
    to_path: str,
    filename: str,
    openai_creds=None,
    spot_token=None,
    tools_token=None,
    debug=False,
):
    """
    Run formfyxer.parse_form as a background job using RQ.

    Args:
        to_path (str): The path to the directory where the uploaded PDF file is stored.
        filename (str): The name of the uploaded PDF file.
        openai_creds (str): The OpenAI API credentials.
        spot_token (str): The Spot API token.
        tools_token (str): The Tools API token.
        debug (bool): Controls whether the resulting stats will contain detailed information about each field
    Saves:
        stats.json: A JSON file containing the parsed form statistics, saved in the same directory as the PDF file.
    """
    # Resolve secrets in the worker; new jobs do not serialize credentials into Redis.
    if openai_creds is None and os.getenv("OPEN_AI__key"):
        openai_creds = {"org": os.getenv("OPEN_AI__org"), "key": os.environ["OPEN_AI__key"]}
    spot_token = spot_token or os.getenv("SPOT_TOKEN")
    tools_token = tools_token or os.getenv("TOOLS_TOKEN")
    was_docx = False
    current_job = get_current_job()
    # Check for DOCX uploads. Convert them to PDF
    if filename.lower().endswith(".doc") or filename.lower().endswith(".docx"):
        was_docx = True
        current_job.meta["status"] = "converting_word_to_pdf"
        current_job.save_meta()
        path_without_extension = Path(filename).stem
        convert_word_to_pdf(
            os.path.join(to_path, filename),
            os.path.join(to_path, path_without_extension + ".pdf"),
            os.environ.get("GOTENBERG_URL", "http://localhost:3000"),
        )
        filename = path_without_extension + ".pdf"

    # Check for PDF fields
    if was_docx or not has_fields(os.path.join(to_path, filename)):
        current_job.meta["status"] = "detecting_pdf_fields"
        current_job.save_meta()
        formfyxer.auto_add_fields(
            os.path.join(to_path, filename), os.path.join(to_path, filename)
        )

    current_job.meta["status"] = "analyzing_pdf"
    current_job.save_meta()
    stats = formfyxer.parse_form(
        os.path.join(to_path, filename),
        normalize=True,
        debug=debug,
        openai_creds=openai_creds,
        spot_token=spot_token,
        tools_token=tools_token,
    )

    with open(os.path.join(to_path, "stats.json"), "w") as stats_file:
        stats_file.write(json.dumps(stats))


@app.post("/")
async def process_file(
    file: UploadFile = File(...), terms_version: str = Form("")
) -> RedirectResponse:
    """Upload a file and process it, then redirect to the view_stats endpoint.

    Args:
        file (UploadFile, optional): The file to be uploaded. Defaults to File(...).

    Returns:
        RedirectResponse: A response redirecting to the view_stats endpoint with the file_hash as a parameter.
    """
    if terms_version != TERMS_VERSION:
        raise HTTPException(status_code=400, detail="Please accept the current terms and privacy notice before uploading.")
    if file.filename == "":
        raise HTTPException(status_code=400, detail="No file selected")
    if file and file.filename and allowed_file(file.filename):
        filename = Path(file.filename.replace("\\", "/")).name
        if filename in {"", ".", ".."}:
            raise HTTPException(status_code=400, detail="Invalid filename")
        file_content = await file.read(MAX_UPLOAD_BYTES + 1)
        await file.close()
        if len(file_content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds the upload limit")
        if not file_content:
            raise HTTPException(status_code=400, detail="The file is empty")
        # A fresh unguessable link prevents cross-user cache reuse and content-hash lookups.
        intermediate_dir = token_hex(32)
        to_path = os.path.join(UPLOAD_FOLDER, intermediate_dir)
        os.mkdir(to_path)
        with open(os.path.join(to_path, "consent.json"), "w") as consent_file:
            json.dump({"terms_version": TERMS_VERSION, "accepted_at": datetime.now(timezone.utc).isoformat()}, consent_file)
        full_path = os.path.join(to_path, filename)
        with open(full_path, "wb") as write_file:
            write_file.write(file_content)

        logger.info("Accepted upload %s", intermediate_dir)

        # Generate a unique identifier for the job
        job = queue.enqueue(
            parse_form_job,
            to_path,
            filename,
            debug=os.environ.get("RATEMYPDF_DEBUG", "false").lower() == "true",
            job_id=intermediate_dir,
            job_timeout=JOB_TIMEOUT,
            result_ttl=3600,
            failure_ttl=3600,
        )

        logger.info(f"Started job {job.id}")

        return RedirectResponse(url=f"/view/{intermediate_dir}", status_code=303)
    raise HTTPException(status_code=400, detail="Invalid file type")


@app.get("/download/{file_hash}")
async def download_file(file_hash: str) -> Response:
    """Serve the uploaded PDF file for download.

    Args:
        file_hash (str): The hash of the file to be downloaded.

    Returns:
        Union[FileResponse, RedirectResponse]: If the file exists, return a FileResponse with the file;
        otherwise, return a RedirectResponse to the root endpoint.
    """
    if not (file_hash and valid_hash(file_hash)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    f = get_pdf_from_dir(file_hash)
    if f:
        return FileResponse(
            path=os.path.join(UPLOAD_FOLDER, file_hash, f),
            filename=f,
            media_type="application/pdf",
        )
    raise HTTPException(status_code=404, detail="No file uploaded here")


@app.get("/view/{file_hash}", response_class=HTMLResponse)
async def view_stats(request: Request, file_hash: str) -> Response:
    """Display the statistics of a previously uploaded and processed file.

    Args:
        file_hash (str): The hash of the file to display statistics for.

    Returns:
        TemplateResponse: A response containing the statistics as an HTML page.
    """
    if not (file_hash and valid_hash(file_hash)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        job = rq.job.Job.fetch(file_hash, connection=conn)
    except NoSuchJobError:
        stats_path = os.path.join(UPLOAD_FOLDER, file_hash)
        if not os.path.isdir(stats_path) or not os.path.isfile(
            os.path.join(stats_path, "stats.json")
        ):
            logger.warning(f"No job or existing cache found for {file_hash}")
            return RedirectResponse("/")

    variables = {
        "request": request,
        "title": get_pdf_title_from_hash(file_hash),
        "file_hash": file_hash,
    }

    return templates.TemplateResponse(request=request, name="ratemypdf_stats.html", context=variables)


@app.get("/job-status/{job_id}")
async def get_job_status(request: Request, job_id: str):
    if not valid_hash(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID")
    try:
        job = rq.job.Job.fetch(job_id, connection=conn)

        if job.is_failed:
            if job.meta.get("status") == "converting_word_to_pdf":
                message = (
                    "We couldn't convert your Word document to PDF. "
                    "Please try uploading it again, or save it as a PDF and upload the PDF instead."
                )
            else:
                message = (
                    "We couldn't process your document. Please try uploading it again. "
                    "If the problem continues, try a smaller document."
                )
            return {"status": "failed", "status_message": message}

        if not job.is_finished:
            if job.meta.get("status") == "converting_word_to_pdf":
                return {"status": "pending", "status_message": "Converting Word to PDF"}
            if job.meta.get("status") == "detecting_pdf_fields":
                return {"status": "pending", "status_message": "Detecting PDF fields"}
            if job.meta.get("status") == "analyzing_pdf":
                return {"status": "pending", "status_message": "Analyzing PDF"}

            return {"status": "pending", "status_message": "Analyzing PDF"}
    except NoSuchJobError:
        pass

    # We end up here if the job finished processing OR
    # if there is a previously cached file
    file_hash = job_id
    stats_path = os.path.join(UPLOAD_FOLDER, file_hash)
    stats_file_path = os.path.join(stats_path, "stats.json")
    if os.path.isdir(stats_path):
        if not os.path.isfile(stats_file_path):
            return {"status": "failed", "status_message": "Results are unavailable. Please upload again."}
    else:
        return {"status": "failed", "status_message": "Results are unavailable. Please upload again."}

    with open(stats_file_path, "r") as stats_file:
        stats = json.loads(stats_file.read())

    metric_means = {
        "complexity score": 18.25398487,
        "time to answer": 49.266632,
        "reading grade level": 7.180685,
        "pages": 2.2601246,
        "total fields": 38.38878,
        "avg fields per page": 20.98784,
        "number of sentences": 71.4894,
        "difficult word count": 75.675389408,
        "difficult word percent": 0.127301677,
        "number of passive voice sentences": 8.11557632,
        "sentences per page": 31.25462694,
        "citation count": 1.098442367,
    }
    metric_stddev = {
        "complexity score": 5.86058205587,
        "time to answer": 82.79478559926,
        "reading grade level": 1.561731,
        "pages": 1.97868674,
        "total fields": 47.211886658,
        "avg fields per page": 20.96440214,
        "number of sentences": 83.419848187,
        "difficult word count": 75.67538940809969,
        "difficult word percent": 0.03873129,
        "sentences per page": 14.38664529,
        "number of passive voice sentences": 10.843292156557,
        "citation count": 4.122761536011,
    }

    def percent_of_2_stddev(score, mean, stddev):
        max = mean + (2 * stddev)
        return score / max * 100

    word_count = len(stats.get("text").split(" "))
    if stats.get("number of passive voice sentences") and stats.get(
        "number of sentences"
    ):
        passive_percent = (
            int(stats["number of passive voice sentences"])
            / stats["number of sentences"]
        )
    else:
        passive_percent = 0

    vars = {
        "request": request,
        "stats": stats,
        "passive_percent": passive_percent,
        "title": stats.get("title", file_hash),
        "complexity_score": formfyxer.form_complexity(stats),
        "word_count": word_count,
        "word_count_per_page": word_count / float(stats.get("pages") or 1.0),
        "difficult_word_count": textstat.difficult_words(stats.get("text")),
        "metric_means": metric_means,
        "metric_stddev": metric_stddev,
        "percent_of_2_stddev": percent_of_2_stddev,
        "highlight_text": highlight_text,
        "file_hash": file_hash,
        "int": int,
        "float": float,
        "floor": math.floor,
        "round": round,
        "pandas": pandas,
        "lit_explorer": lit_explorer,
    }

    # Render the partial template with the stats
    rendered_stats = templates.TemplateResponse(request=request,
        name="_stats_partial.html", context=vars, media_type="text/html"
    )

    # Return the rendered HTML as a string
    return {"status": "finished", "rendered_stats": rendered_stats.body.decode()}


@app.get("/loading_animation", response_class=HTMLResponse)
async def loading_animation(request: Request):
    return templates.TemplateResponse(request=request, name="loading_animation.html", context={"request": request})


@app.get("/example_forms.html", response_class=HTMLResponse)
async def view_examples(request: Request) -> Response:
    """Shows examples of highly rated forms.

    Returns:
        TemplateResponse: A response containing the highly rated example forms as an HTML page.
    """
    examples = [
        {
            "title": "Courts and Lawyers",
            "description": "Motion to Continue (VT)",
            "image": "img/thumb1.png",
            "image_alt": "Thumbnail of Example Court Form #1",
            "download_link": "https://www.courtformsonline.org/forms/4250d72f88521a1e36cf4de12c839cb6.pdf",
        },
        {
            "title": "Estates, Wills, and Guardianships",
            "description": "REQUEST TO BE APPOINTED AS CO-PERSONAL REPRESENTATIVE (AK)",
            "image": "img/thumb2.png",
            "image_alt": "Thumbnail of Example Court Form #2",
            "download_link": "https://www.courtformsonline.org/forms/e21e8c015228bf50f945ad623dec1116.pdf",
        },
        {
            "title": "Estates, Wills, and Guardianships #2",
            "description": "APPLICATION FOR APPOINTMENT AS TEMPORARY PROPERTY CUSTODIAN (AK)",
            "image": "img/thumb3.png",
            "image_alt": "Thumbnail of Example Court Form #3",
            "download_link": "https://www.courtformsonline.org/forms/a0a5bf50b2c7420975ed922631beadcf.pdf",
        },
        {
            "title": "Name Change of a Child",
            "description": "PUBLICATION NOTICE OF COURT DATE FOR REQUEST FOR NAME CHANGE (MINOR CHILDREN) (IL)",
            "image": "img/thumb4.png",
            "image_alt": "Thumbnail of Example Court Form #4",
            "download_link": "https://www.courtformsonline.org/forms/c4e028ca6967bab9268255de6ad08ab2.pdf",
        }
    ]
    return templates.TemplateResponse(request=request,
        name="example_forms.html", context={"request": request, "examples": examples}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
