from fastapi import FastAPI

app = FastAPI(title="AutoPublisher")


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the service is running."""
    return {"status": "ok"}
