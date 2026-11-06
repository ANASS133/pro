import time
import json
from pathlib import Path
from services.employer_cache import EmployerDomainCache
from services.debounced_writer import DebouncedAtomicWriter
from scraper.browser_driver import get_installed_driver_path


def test_employer_domain_cache_normalization_and_retrieval():
    cache = EmployerDomainCache()
    assert cache.normalize_domain("https://www.example.com/karriere/jobs?id=123") == "example.com"
    assert cache.normalize_domain("http://sub.domain.de:8080/path") == "sub.domain.de"

    # Put and get by domain
    cache.put(
        company="Muster GmbH",
        city="Köln",
        url_or_domain="https://www.muster-gmbh.de/jobs",
        data={
            "email": "bewerbung@muster-gmbh.de",
            "phone": "+49 221 123456",
            "has_form": True,
            "direct_application_url": "https://www.muster-gmbh.de/apply",
        },
    )

    # Retrieval by company name
    res1 = cache.get(company="Muster GmbH", city="Köln")
    assert res1 is not None
    assert res1["email"] == "bewerbung@muster-gmbh.de"
    assert res1["phone"] == "+49 221 123456"
    assert res1["has_form"] is True

    # Retrieval by domain
    res2 = cache.get(url_or_domain="muster-gmbh.de")
    assert res2 is not None
    assert res2["email"] == "bewerbung@muster-gmbh.de"

    # Miss
    assert cache.get(company="NonExistent AG") is None
    assert cache.hits == 2
    assert cache.misses == 1


def test_debounced_atomic_writer(tmp_path):
    target = tmp_path / "progress.json"
    writer = DebouncedAtomicWriter(target, min_interval_seconds=0.2)

    # First write: immediate write because last write was never
    writer.schedule_write({"status": "first", "val": 1})
    assert target.exists()
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["val"] == 1

    # Rapid writes within debounce window
    writer.schedule_write({"status": "second", "val": 2})
    writer.schedule_write({"status": "third", "val": 3})

    # Immediate flush
    writer.flush()
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["val"] == 3


def test_driver_path_caching():
    # Cache lookup should return string or None consistently without repeated downloads
    p1 = get_installed_driver_path("chrome")
    p2 = get_installed_driver_path("chrome")
    assert p1 == p2
