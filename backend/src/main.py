import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dependencies import ApplicationServices
from routers import profile, job, generation

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.services = ApplicationServices()
    yield


app = FastAPI(
    title="Job Application Assistant",
    description="Parse job postings, generate cover letters, tailor resumes, and answer application questions.",
    lifespan=lifespan,
)

app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return HTMLResponse((Path("frontend") / "index.html").read_text())


app.include_router(profile.router)
app.include_router(job.router)
app.include_router(generation.router)


if __name__ == "__main__":
    import uvicorn

    logger.info("Local server starting at http://localhost:7860")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=7860,
        reload=False,
    )