#!/usr/bin/env python3
"""
Exporta a PDF (legible y respetando el formato) todas las campañas de Mailchimp
enviadas un VIERNES a una audiencia/público concreto (por defecto "OPZGZ").

Uso:
    export MAILCHIMP_API_KEY="xxxxxxxx-usXX"
    python3 mailchimp_friday_export.py --audience OPZGZ --out viernes_OPZGZ.pdf

La API key también se puede pasar con --api-key.
El sufijo de la key (-usXX) indica el datacenter y se usa automáticamente.

Renderizado HTML -> PDF: usa el primer motor disponible de:
    1. Playwright (Chromium)  -> mejor fidelidad con HTML de email
    2. wkhtmltopdf (pdfkit)
    3. WeasyPrint
Y combina todas las campañas en un único PDF (una sección por campaña).
"""

import argparse
import base64
import datetime as dt
import os
import re
import sys
import tempfile
import time
from typing import Dict, List, Optional

import requests

API_BASE_TMPL = "https://{dc}.api.mailchimp.com/3.0"


# --------------------------------------------------------------------------- #
# Cliente Mailchimp
# --------------------------------------------------------------------------- #
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
            if r.status_code == 429:  # rate limit
                time.sleep(2 ** attempt)
                continue
            if not r.ok:
                sys.exit(f"ERROR {r.status_code} en {path}: {r.text[:500]}")
            return r.json()
        sys.exit(f"ERROR: rate limit persistente en {path}")

    def find_list(self, name: str) -> dict:
        """Busca la audiencia por nombre exacto (case-insensitive) o por substring."""
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
        """Devuelve todas las campañas enviadas a esa audiencia."""
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


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def is_friday(send_time: str) -> bool:
    if not send_time:
        return False
    # send_time viene en ISO 8601 con timezone, p.ej. 2024-05-17T10:00:00+00:00
    try:
        d = dt.datetime.fromisoformat(send_time.replace("Z", "+00:00"))
    except ValueError:
        return False
    return d.weekday() == 4  # 0=lunes ... 4=viernes


def fmt_date(send_time: str) -> str:
    try:
        d = dt.datetime.fromisoformat(send_time.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return send_time


def header_html(subject: str, title: str, when: str) -> str:
    subject = subject or "(sin asunto)"
    title = title or ""
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; border-bottom:2px solid #333;
                padding:8px 12px; margin:0 0 4px 0; background:#f4f4f4;">
      <div style="font-size:15px; font-weight:bold; color:#111;">{subject}</div>
      <div style="font-size:11px; color:#666;">Viernes · {when}{(' · ' + title) if title else ''}</div>
    </div>"""


# --------------------------------------------------------------------------- #
# Renderizado HTML -> PDF
# --------------------------------------------------------------------------- #
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
        print(f"  Playwright falló: {e}", file=sys.stderr)
        return False


def render_with_pdfkit(htmls: List[str], out_path: str) -> bool:
    try:
        import pdfkit  # requiere binario wkhtmltopdf
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
        print(f"  pdfkit/wkhtmltopdf falló: {e}", file=sys.stderr)
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
        print(f"  WeasyPrint falló: {e}", file=sys.stderr)
        return False


def merge_pdfs(parts: List[str], out_path: str) -> None:
    from pypdf import PdfWriter
    writer = PdfWriter()
    for f in parts:
        writer.append(f)
    with open(out_path, "wb") as fh:
        writer.write(fh)


def inject_header(html: str, header: str) -> str:
    """Inserta la cabecera justo después de <body> (o al principio)."""
    if re.search(r"<body[^>]*>", html, re.IGNORECASE):
        return re.sub(r"(<body[^>]*>)", r"\1" + header, html, count=1,
                      flags=re.IGNORECASE)
    return header + html


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Exporta a PDF las campañas de "
                                 "Mailchimp enviadas en viernes a una audiencia.")
    ap.add_argument("--audience", default="OPZGZ",
                    help="Nombre de la audiencia/público (def: OPZGZ)")
    ap.add_argument("--api-key", default=os.environ.get("MAILCHIMP_API_KEY"),
                    help="API key (o variable de entorno MAILCHIMP_API_KEY)")
    ap.add_argument("--out", default="viernes_OPZGZ.pdf", help="PDF de salida")
    ap.add_argument("--save-html", action="store_true",
                    help="Guarda también el HTML de cada campaña")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("ERROR: falta la API key (--api-key o MAILCHIMP_API_KEY).")

    mc = Mailchimp(args.api_key)
    print(f"Datacenter: {mc.dc}")

    audience = mc.find_list(args.audience)
    print(f"Audiencia: '{audience['name']}' (id {audience['id']})")

    campaigns = mc.sent_campaigns(audience["id"])
    print(f"Campañas enviadas a esa audiencia: {len(campaigns)}")

    fridays = [c for c in campaigns if is_friday(c.get("send_time", ""))]
    fridays.sort(key=lambda c: c.get("send_time", ""))
    print(f"Enviadas en VIERNES: {len(fridays)}")

    if not fridays:
        sys.exit("No hay campañas enviadas en viernes para esa audiencia.")

    htmls = []
    for i, c in enumerate(fridays, 1):
        subj = c.get("settings", {}).get("subject_line", "")
        title = c.get("settings", {}).get("title", "")
        when = fmt_date(c.get("send_time", ""))
        print(f"  [{i}/{len(fridays)}] {when} · {subj}")
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
            print(f"OK -> {args.out} ({len(fridays)} campañas)")
            return
    sys.exit("ERROR: ningún motor de PDF disponible. Instala uno:\n"
             "  pip install playwright pypdf && python -m playwright install chromium\n"
             "  o  pip install pdfkit pypdf  (+ apt install wkhtmltopdf)\n"
             "  o  pip install weasyprint pypdf")


if __name__ == "__main__":
    main()
