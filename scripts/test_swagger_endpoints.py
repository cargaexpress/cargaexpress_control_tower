import urllib.request
import urllib.error
import json
import time

BASE_URL = "http://cargaexpress-staging-alb-353383531.us-east-2.elb.amazonaws.com"

# Keys
SYSTEM_KEY = "CHANGE_ME_API_KEY_32_CHARS_MINIMUM"
ADMIN_TOKEN = "CHANGE_ME_ADMIN_KEY_32_CHARS_MINIMUM"
BRAND_KEY = "brand_alpha"
CARRIER_KEY = "carrier_alpha"

real_endpoints = [
    # Health & System
    ("GET", "/api/v1/health", {}, "Health check probe"),
    ("GET", "/api/v1/ready", {}, "Readiness probe"),
    ("GET", "/docs/api/openapi.json", {}, "OpenAPI schema contract"),

    # Carriers
    ("GET", "/api/v1/carriers", {"X-API-Key": SYSTEM_KEY}, "List 12 active carriers"),
    ("GET", "/api/v1/carriers/1", {"X-API-Key": SYSTEM_KEY}, "Get carrier #1 details"),
    ("GET", "/api/v1/carriers/me", {"X-API-Key": CARRIER_KEY}, "Carrier self-profile"),

    # Admin State Mapping (Requires X-Admin-Token + X-API-Key)
    ("GET", "/api/v1/admin/state-mappings", {"X-API-Key": SYSTEM_KEY, "X-Admin-Token": ADMIN_TOKEN}, "List 101 canonical state mappings"),
    ("GET", "/api/v1/admin/state-mappings/resolve?carrier_id=1&raw_status=DELIVERED", {"X-API-Key": SYSTEM_KEY, "X-Admin-Token": ADMIN_TOKEN}, "Resolve raw carrier state"),
    ("GET", "/api/v1/admin/carrier-state-mappings/1", {"X-API-Key": SYSTEM_KEY, "X-Admin-Token": ADMIN_TOKEN}, "Get state mappings for carrier 1"),

    # Orders (Brand scoped)
    ("GET", "/api/v1/orders", {"X-API-Key": BRAND_KEY}, "List brand orders"),

    # SLA Tracking & Metrics
    ("GET", "/api/v1/sla/at-risk", {"X-API-Key": SYSTEM_KEY}, "Query at-risk shipments"),
    ("GET", "/api/v1/sla/brand/metrics", {"X-API-Key": BRAND_KEY}, "Brand SLA compliance rate"),
    ("GET", "/api/v1/sla/brand/history", {"X-API-Key": BRAND_KEY}, "Brand SLA historical metrics"),
    ("GET", "/api/v1/sla/carrier/metrics", {"X-API-Key": CARRIER_KEY}, "Carrier SLA performance"),
    ("GET", "/api/v1/sla/carrier/history", {"X-API-Key": CARRIER_KEY}, "Carrier SLA historical performance"),

    # Alerts
    ("GET", "/api/v1/alerts", {"X-API-Key": SYSTEM_KEY}, "Operational alerts"),

    # Financial Engine
    ("GET", "/api/v1/financial/penalties", {"X-API-Key": BRAND_KEY}, "Brand freight penalties"),
    ("GET", "/api/v1/financial/carrier/1/penalties", {"X-API-Key": SYSTEM_KEY}, "Carrier freight penalties"),
    ("GET", "/api/v1/financial/config/penalty-scales", {"X-API-Key": SYSTEM_KEY}, "Penalty scales configuration"),

    # Analytics & DW
    ("GET", "/api/v1/analytics/kpis", {"X-API-Key": SYSTEM_KEY}, "High-level KPI metrics"),
    ("GET", "/api/v1/analytics/facts/shipments-sla", {"X-API-Key": SYSTEM_KEY}, "Kimball fact_shipments_sla query"),
    ("GET", "/api/v1/analytics/facts/penalties", {"X-API-Key": SYSTEM_KEY}, "Kimball fact_financial_penalties query"),
    ("GET", "/api/v1/analytics/etl/batches", {"X-API-Key": SYSTEM_KEY}, "ETL lineage batch history"),
]

print("================================================================================")
print("             CARGAEXPRESS STAGING - REAL ENDPOINTS TEST SUITE                   ")
print(f"Target ALB: {BASE_URL}")
print("================================================================================\n")

results = []

for method, path, headers, desc in real_endpoints:
    url = f"{BASE_URL}{path}"
    req_headers = {"User-Agent": "CargaExpress-Audit/1.0", "Accept": "application/json"}
    req_headers.update(headers)
    
    req = urllib.request.Request(url, headers=req_headers, method=method)
    
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            elapsed = (time.time() - t0) * 1000
            content = resp.read().decode("utf-8")
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    info = f"Array(len={len(parsed)})"
                elif isinstance(parsed, dict):
                    info = f"Object(keys={list(parsed.keys())[:4]})"
                else:
                    info = str(parsed)
            except Exception:
                info = content[:30]
                
            print(f"[PASS {resp.status}] {method:4} {path:45} {elapsed:5.1f}ms | {desc:30} -> {info}")
            results.append({"path": path, "status": resp.status, "desc": desc, "ok": True, "info": info})
    except urllib.error.HTTPError as e:
        elapsed = (time.time() - t0) * 1000
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[FAIL {e.code}] {method:4} {path:45} {elapsed:5.1f}ms | {desc:30} -> Err: {err_body[:80]}")
        results.append({"path": path, "status": e.code, "desc": desc, "ok": False, "err": err_body})
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        print(f"[FAIL 000] {method:4} {path:45} {elapsed:5.1f}ms | {desc:30} -> Exc: {str(e)[:80]}")
        results.append({"path": path, "status": 0, "desc": desc, "ok": False, "err": str(e)})

passed = sum(1 for r in results if r["ok"])
total = len(results)
print("\n--------------------------------------------------------------------------------")
print(f"TOTAL: {passed}/{total} ENDPOINTS PASSED ({(passed/total)*100:.1f}%)")
print("--------------------------------------------------------------------------------")
