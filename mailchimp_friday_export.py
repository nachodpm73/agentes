#!/usr/bin/env python3
"""
Exporta a PDF (legible y respetando el formato) todas las campanas de Mailchimp
enviadas un VIERNES a una audiencia/publico concreto (por defecto "OPZGZ").

Uso (Windows):
    set MAILCHIMP_API_KEY=xxxxxxxx-usXX
    py mailchimp_friday_export.py --audience OPZGZ --out viernes_OPZGZ.pdf
"""

import argparse
import base64
import datetime as dt
import os
import re
import sys
import tempfile
import time
from typing import List, Optional

import requests

API_BASE_TMPL = "https://{dc}.api.mailchimp.com/3.0"


class Mailchimp:
    def __init__(self, api_key: str):
        if "-" not in api_key:
            sys.exit("ERROR: la API key no tiene el sufijo de datacenter (-usXX).")
        self.api_key = api_key
        self.dc = api_key.split("-")[-1]
        self.base = API_BASE_TMPL.format(dc=self.dc)
        self.session = requests.Session()
        token = base64.b64encode(f"anystring:{api_key}".encode()).decode()
        self.session.headers.update({"Authorization": f"Basic {token}"})

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        for attempt in range(5):
            r = self.session.get(self.base + path, params=params, timeout=60)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if not r.ok:
                sys.exit(f"ERROR {r.status_code} en {path}: {r.text[:500]}")
            return r.json()
        sys.exit(f"ERROR: rate limit persistente en {path}")

    def find_list(self, name: str) -> dict:
        data = self._get("/lists", {"count": 1000, "fields": "lists.id,lists.name"})
        lists = data.get("lists", [])
        if not lists:
            sys.exit("ERROR: la cuenta no tiene audiencias.")
        name_l = name.lower()
        for l in lists:
            if l["name"].lower() == name_l:
                return l
        for l in lists:
            if name_l in l["name"].lower():
                return l
        nombres = ", ".join(l["name"] for l in lists)
        sys.exit(f"ERROR: no encuentro la audiencia '{name}'. Disponibles: {nombres}")

    def sent_campaigns(self, list_id: str) -> List[dict]:
        out, offset = [], 0
        while True:
            data = self._get(
                "/campaigns",
                {
                    "list_id": list_id,
                    "status": "sent",
                    "count": 1000,
                    "offset": offset,
                    "sort_field": "send_time",
                    "sort_dir": "ASC",
                    "fields": "campaigns.id,campaigns.send_time,"
                    "campaigns.settings.subject_line,campaigns.settings.title,"
                    "total_items",
                },
            )
            batch = data.get("campaigns", [])
            out.extend(batch)
            offset += len(batch)
            if not batch or offset >= data.get("total_items", 0):
                break
        return out

    def campaign_html(self, campaign_id: str) -> str:
        data = self._get(f"/campaigns/{campaign_id}/content")
        return data.get("html") or data.get("archive_html") or ""


def is_friday(send_time: str) -> bool:
    if not send_time:
        return False
    try:
        d = dt.datetime.fromisoformat(send_time.replace("Z", "+00:00"))
    except ValueError:
        return False
    return d.weekday() == 4


def fmt_date(send_time: str) -> str:
    try:
        d = dt.datetime.fromisoformat(send_time.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return send_time


def header_html(subject: str, title: str, when: str) -> str:
    subject = subject or "(sin asunto)"
    title = title or ""
    extra = (" - " + title) if title else ""
    return (
        '<div style="font-family: Arial, Helvetica, sans-serif; '
        'border-bottom:2px solid #333; padding:8px 12px; margin:0 0 4px 0; '
        'background:#f4f4f4;">'
        f'<div style="font-size:15px; font-weight:bold; color:#111;">{subject}</div>'
        f'<div style="font-size:11px; color:#666;">Viernes - {when}{extra}</div>'
        "</div>"
    )


def render_with_playwright(htmls: List[str], out_path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        pdf_parts = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            for html in htmls:
                page.set_content(html, wait_until="networkidle")
                tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                tmp.close()
                page.pdf(
                    path=tmp.name,
                    format="A4",
                    print_background=True,
                    margin={"top": "10mm", "bottom": "10mm",
                            "left": "8mm", "right": "8mm"},
                )
                pdf_parts.append(tmp.name)
            browser.close()
        merge_pdfs(pdf_parts, out_path)
        for f in pdf_parts:
            os.unlink(f)
        return True
    except Exception as e:
        print(f"  Playwright fallo: {e}", file=sys.stderr)
        return False


def render_with_pdfkit(htmls: List[str], out_path: str) -> bool:
    try:
        import pdfkit
    except ImportError:
        return False
    try:
        pdf_parts = []
        opts = {"enable-local-file-access": None, "encoding": "UTF-8",
                "quiet": "", "load-error-handling": "ignore",
                "load-media-error-handling": "ignore"}
        for html in htmls:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.close()
            pdfkit.from_string(html, tmp.name, options=opts)
            pdf_parts.append(tmp.name)
        merge_pdfs(pdf_parts, out_path)
        for f in pdf_parts:
            os.unlink(f)
        return True
    except Exception as e:
        print(f"  pdfkit/wkhtmltopdf fallo: {e}", file=sys.stderr)
        return False


def render_with_weasyprint(htmls: List[str], out_path: str) -> bool:
    try:
        from weasyprint import HTML
    except ImportError:
        return False
    try:
        pdf_parts = []
        for html in htmls:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.close()
            HTML(string=html).write_pdf(tmp.name)
            pdf_parts.append(tmp.name)
        merge_pdfs(pdf_parts, out_path)
        for f in pdf_parts:
            os.unlink(f)
        return True
    except Exception as e:
        print(f"  WeasyPrint fallo: {e}", file=sys.stderr)
        return False


def merge_pdfs(parts: List[str], out_path: str) -> None:
    from pypdf import PdfWriter
    writer = PdfWriter()
    for f in parts:
        writer.append(f)
    with open(out_path, "wb") as fh:
        writer.write(fh)


def inject_header(html: str, header: str) -> str:
    if re.search(r"<body[^>]*>", html, re.IGNORECASE):
        return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + header,
                      html, count=1, flags=re.IGNORECASE)
    return header + html


def main():
    ap = argparse.ArgumentParser(
        description="Exporta a PDF las campanas de Mailchimp enviadas en viernes.")
    ap.add_argument("--audience", default="OPZGZ")
    ap.add_argument("--api-key", default=os.environ.get("MAILCHIMP_API_KEY"))
    ap.add_argument("--out", default="viernes_OPZGZ.pdf")
    ap.add_argument("--save-html", action="store_true")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("ERROR: falta la API key (--api-key o MAILCHIMP_API_KEY).")

    mc = Mailchimp(args.api_key)
    print(f"Datacenter: {mc.dc}")

    audience = mc.find_list(args.audience)
    print(f"Audiencia: '{audience['name']}' (id {audience['id']})")

    campaigns = mc.sent_campaigns(audience["id"])
    print(f"Campanas enviadas a esa audiencia: {len(campaigns)}")

    fridays = [c for c in campaigns if is_friday(c.get("send_time", ""))]
    fridays.sort(key=lambda c: c.get("send_time", ""))
    print(f"Enviadas en VIERNES: {len(fridays)}")

    if not fridays:
        sys.exit("No hay campanas enviadas en viernes para esa audiencia.")

    htmls = []
    for i, c in enumerate(fridays, 1):
        subj = c.get("settings", {}).get("subject_line", "")
        title = c.get("settings", {}).get("title", "")
        when = fmt_date(c.get("send_time", ""))
        print(f"  [{i}/{len(fridays)}] {when} - {subj}")
        html = mc.campaign_html(c["id"])
        if not html:
            html = "<html><body><p>(sin contenido HTML)</p></body></html>"
        html = inject_header(html, header_html(subj, title, when))
        htmls.append(html)
        if args.save_html:
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", f"{when}_{subj}")[:80]
            with open(f"{safe}.html", "w", encoding="utf-8") as fh:
                fh.write(html)

    print("Renderizando PDF...")
    for engine in (render_with_playwright, render_with_pdfkit, render_with_weasyprint):
        if engine(htmls, args.out):
            print(f"OK -> {args.out} ({len(fridays)} campanas)")
            return
    sys.exit("ERROR: ningun motor de PDF disponible. Instala uno:\n"
             "  py -m pip install playwright pypdf\n"
             "  py -m playwright install chromium")


if __name__ == "__main__":
    main()
