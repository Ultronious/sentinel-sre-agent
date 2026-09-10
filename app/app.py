from fastapi import FastAPI
import time
import random

app = FastAPI(title="Sentinel Demo Service")


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