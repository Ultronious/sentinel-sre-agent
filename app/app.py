from fastapi import FastAPI, Request
import time
import random
import logging

app = FastAPI(title="Sentinel Demo Service")

logger = logging.getLogger("sentinel")
logging.basicConfig(level=logging.INFO)


@app.middleware("http")
async def request_timing(request: Request, call_next):
    start = time.perf_counter()

    response = await call_next(request)

    duration_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "REQUEST_TELEMETRY "
        "method=%s "
        "path=%s "
        "status=%s "
        "duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )

    return response


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/api")
def api():
    return {
        "message": "Sentinel's victim is alive"
    }


@app.get("/metrics-demo")
def metrics_demo():
    return {
        "request_id": random.randint(1000, 9999),
        "timestamp": time.time()
    }


@app.get("/admin/inject-latency")
def inject_latency(seconds: int = 5):
    time.sleep(seconds)

    return {
        "status": "latency injected",
        "seconds": seconds
    }


@app.get("/admin/inject-errors")
def inject_errors():
    raise RuntimeError("Deliberate Sentinel test failure")


@app.get("/slow")
def slow():
    time.sleep(2)

    return {
        "status": "slow"
    }


@app.get("/cpu")
def cpu():
    end = time.perf_counter() + 5

    while time.perf_counter() < end:
        pass

    return {
        "status": "cpu-busy"
    }