import json
import time
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
from scraper.working_email_extractor import WorkingEmailExtractor

class PMC(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)
    ]

_pmc_func = ctypes.windll.psapi.GetProcessMemoryInfo
_pmc_func.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
_pmc_func.restype = wintypes.BOOL

def get_ram_mb() -> float:
    p = PMC()
    p.cb = ctypes.sizeof(PMC)
    if _pmc_func(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(p), p.cb):
        return round(p.WorkingSetSize / (1024 * 1024), 2)
    return 0.0

def run_benchmark(sample_size=12, label="BASELINE"):
    with open('data/progress/search_runs.json', 'r', encoding='utf-8') as f:
        runs = json.load(f)
    
    # Pick a sample of 12 jobs from the latest run
    sample_jobs = []
    for r in runs.values():
        jobs = r.get("jobs", [])
        if len(jobs) >= sample_size:
            sample_jobs = [dict(j) for j in jobs[:sample_size]]
            break
            
    if not sample_jobs:
        print("No sample jobs found.")
        return

    ram_start = get_ram_mb()
    t0 = time.time()
    
    extractor = WorkingEmailExtractor(
        captcha_userid="",
        captcha_apikey="",
        headless=True,
        worker_id=1,
    )
    results = []
    try:
        for idx, job in enumerate(sample_jobs):
            res = extractor.process_job(job, profession_keyword="Koch")
            results.append(res)
    finally:
        extractor.close()
        
    t1 = time.time()
    ram_end = get_ram_mb()
    total_time = t1 - t0
    jobs_count = len(results)
    avg_time = round(total_time / max(1, jobs_count), 2)
    throughput = round(jobs_count / (total_time / 60), 2) if total_time > 0 else 0
    
    fast_http_count = sum(1 for r in results if r.get("extraction_method") == "fast_http" or r.get("extraction_method") == "cache")
    selenium_count = sum(1 for r in results if r.get("extraction_method") == "selenium" or not r.get("extraction_method"))
    emails_count = sum(1 for r in results if r.get("email") and "@" in r.get("email"))
    forms_count = sum(1 for r in results if r.get("has_form") or r.get("direct_application_url"))
    
    print(f"=== BENCHMARK RESULT: {label} ===")
    print(f"Processed: {jobs_count} jobs in {total_time:.2f}s")
    print(f"Avg time per job: {avg_time}s")
    print(f"Throughput: {throughput} jobs/min")
    print(f"Fast-HTTP / Cache hits: {fast_http_count} ({round(fast_http_count/jobs_count*100, 1)}%)")
    print(f"Selenium fallbacks: {selenium_count} ({round(selenium_count/jobs_count*100, 1)}%)")
    print(f"Emails extracted: {emails_count}")
    print(f"Forms discovered: {forms_count}")
    print(f"RAM Start: {ram_start} MB | RAM End: {ram_end} MB | Delta: {round(ram_end - ram_start, 2)} MB")
    print("==================================")
    
    metrics = {
        "label": label,
        "jobs": jobs_count,
        "total_time_sec": round(total_time, 2),
        "avg_time_sec": avg_time,
        "jobs_per_min": throughput,
        "fast_http_count": fast_http_count,
        "selenium_count": selenium_count,
        "emails_count": emails_count,
        "forms_count": forms_count,
        "ram_start_mb": ram_start,
        "ram_end_mb": ram_end,
    }
    with open(f"benchmark_{label.lower()}.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

if __name__ == "__main__":
    run_benchmark(sample_size=10, label="OPTIMIZED")
