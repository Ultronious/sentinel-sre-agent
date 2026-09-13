import concurrent.futures
import time
import requests

URL = "http://sentinel-demo-alb-119522837.us-east-1.elb.amazonaws.com/cpu"

def hit(_):
    start = time.perf_counter()
    try:
        r = requests.get(URL, timeout=30)
        elapsed = time.perf_counter() - start
        return r.status_code, elapsed, r.text
    except Exception as e:
        return "ERROR", None, str(e)

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    results = list(executor.map(hit, range(20)))

for result in results:
    print(result)
