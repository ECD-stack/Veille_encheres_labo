#!/usr/bin/env python3
"""
Scraper generique de pages d'encheres -> flux RSS unique.

Lit la configuration des sites depuis sites.yaml, extrait les annonces de
chaque site selon les selecteurs CSS fournis, deduplique par rapport aux
annonces deja vues (data/seen.json), et regenere feed.xml (RSS 2.0).

Ce script est concu pour tourner via la tache planifiee GitHub Actions
(.github/workflows/update-feed.yml), mais peut aussi etre lance a la main :
    pip install -r requirements.txt
    playwright install --with-deps chromium   # seulement si un site a js: true
    python scraper.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from xml.sax.saxutils import escape

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
SITES_FILE = ROOT / "sites.yaml"
SEEN_FILE = ROOT / "data" / "seen.json"
FEED_FILE = ROOT / "feed.xml"

MAX_ITEMS_IN_FEED = 150
MAX_SEEN_STORED = 3000
REQUEST_TIMEOUT = 25
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; VeilleEncheresLabo/1.0)"
}


def load_sites():
    with open(SITES_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return [s for s in config.get("sites", []) if s.get("enabled", True)]


def load_seen():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if len(seen) > MAX_SEEN_STORED:
        ordered = sorted(seen.items(), key=lambda kv: kv[1]["first_seen"], reverse=True)
        seen = dict(ordered[:MAX_SEEN_STORED])
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def fetch_static(url):
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_js(url, wait_selector=None, wait_ms=3000):
    # Import local : playwright n'est necessaire que si un site l'utilise.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, timeout=REQUEST_TIMEOUT * 1000)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=REQUEST_TIMEOUT * 1000)
            except Exception:
                pass
        else:
            page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
        return html


def extract_items(html, base_url, site_cfg):
    """
    Extrait les annonces d'une page.

    Mode normal : chaque annonce doit avoir un lien individuel (href) -> celui-ci
    sert de cle de deduplication et de lien cliquable dans le flux.

    Mode degrade (site_cfg["no_item_links"] = true) : le site ne fournit aucun
    lien individuel par annonce (application type Bubble sans URL par fiche, par
    exemple). Dans ce cas on garde uniquement le titre ; le lien du flux pointera
    vers la page de recherche generale du site, et la deduplication se fait sur
    le texte du titre plutot que sur un lien.
    """
    soup = BeautifulSoup(html, "lxml")
    containers = soup.select(site_cfg["item_selector"])
    no_item_links = site_cfg.get("no_item_links", False)
    items = []
    for c in containers:
        title_el = c.select_one(site_cfg["title_selector"]) if site_cfg.get("title_selector") else c
        title = title_el.get_text(" ", strip=True) if title_el else None
        if not title:
            continue

        if no_item_links:
            link = base_url  # pas de fiche individuelle disponible sur ce site
        else:
            link_el = c.select_one(site_cfg["link_selector"]) if site_cfg.get("link_selector") else c
            href = link_el.get("href") if link_el else None
            if not href:
                continue
            link = urljoin(base_url, href)

        items.append({"title": title, "link": link})
    return items


def process_site(site_cfg, seen, now_iso):
    name = site_cfg["name"]
    url = site_cfg["url"]
    print(f"[{name}] fetching {url}")
    try:
        if site_cfg.get("js"):
            html = fetch_js(url, wait_selector=site_cfg.get("wait_selector"))
        else:
            html = fetch_static(url)
    except Exception as exc:
        print(f"[{name}] ERREUR de recuperation de la page : {exc}", file=sys.stderr)
        return []

    items = extract_items(html, url, site_cfg)
    print(f"[{name}] {len(items)} annonce(s) trouvee(s) sur la page")

    no_item_links = site_cfg.get("no_item_links", False)
    keywords = [k.lower() for k in site_cfg.get("keywords", [])]
    new_entries = []
    for item in items:
        if keywords and not any(k in item["title"].lower() for k in keywords):
            continue
        # Mode degrade : pas de lien individuel -> on deduplique sur le titre
        # (prefixe par le nom du site pour eviter les collisions entre sites).
        key = f"{name}::{item['title']}" if no_item_links else item["link"]
        if key in seen:
            continue
        seen[key] = {
            "title": item["title"],
            "link": item["link"],
            "source": name,
            "first_seen": now_iso,
            "guid": key,
            "is_permalink": not no_item_links,
        }
        new_entries.append(seen[key])
    return new_entries


def build_feed(seen):
    entries = sorted(seen.values(), key=lambda e: e["first_seen"], reverse=True)[:MAX_ITEMS_IN_FEED]
    now_rfc822 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items_xml = []
    for e in entries:
        try:
            pub_dt = datetime.fromisoformat(e["first_seen"])
            pub_rfc822 = pub_dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except ValueError:
            pub_rfc822 = now_rfc822
        guid = e.get("guid", e["link"])
        is_permalink = "true" if e.get("is_permalink", True) else "false"
        items_xml.append(
            "    <item>\n"
            f"      <title>{escape(e['title'])}</title>\n"
            f"      <link>{escape(e['link'])}</link>\n"
            f"      <guid isPermaLink=\"{is_permalink}\">{escape(guid)}</guid>\n"
            f"      <description>{escape('Source : ' + e['source'])}</description>\n"
            f"      <pubDate>{pub_rfc822}</pubDate>\n"
            "    </item>"
        )

    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        "    <title>Veille encheres materiel de laboratoire</title>\n"
        "    <link>https://TON-COMPTE.github.io/TON-DEPOT/</link>\n"
        "    <description>Flux agrege des nouvelles annonces d'encheres de materiel de laboratoire</description>\n"
        f"    <lastBuildDate>{now_rfc822}</lastBuildDate>\n"
        + "\n".join(items_xml) + "\n"
        "  </channel>\n"
        "</rss>\n"
    )
    FEED_FILE.write_text(feed, encoding="utf-8")


def main():
    sites = load_sites()
    if not sites:
        print("Aucun site actif dans sites.yaml (enabled: true). Rien a faire.")
    seen = load_seen()
    now_iso = datetime.now(timezone.utc).isoformat()

    total_new = 0
    for site_cfg in sites:
        total_new += len(process_site(site_cfg, seen, now_iso))

    save_seen(seen)
    build_feed(seen)
    print(f"Termine. {total_new} nouvelle(s) annonce(s). {len(seen)} annonce(s) au total en memoire.")


if __name__ == "__main__":
    main()
