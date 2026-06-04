#!/usr/bin/env python3
"""
PASO 2 - Generar el noticiario de la semana y dejarlo como BORRADOR en Mailchimp.

Usa la guia de estilo aprendida (estilo_noticiario.json) + busqueda web de Claude
(Opus 4.8) para encontrar las noticias de la ultima semana sobre los temas del
noticiario, montar el HTML en el mismo formato, y crear un BORRADOR de campana en
Mailchimp para la audiencia indicada (por defecto OPZGZ). Tu lo revisas y envias.

Uso (Windows):
    set ANTHROPIC_API_KEY=sk-ant-...
    set MAILCHIMP_API_KEY=xxxxxxxx-usXX
    py genera_noticiario.py --audience OPZGZ

Anade --dry-run para solo generar el HTML en local, sin tocar Mailchimp.
"""

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time

import anthropic
import requests

MODEL = "claude-opus-4-8"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


# --------------------------------------------------------------------------- #
# Mailchimp (solo lo necesario: buscar audiencia, sender, crear borrador)
# --------------------------------------------------------------------------- #
class Mailchimp:
    def __init__(self, api_key):
        if "-" not in api_key:
            sys.exit("ERROR: la API key de Mailchimp no tiene el sufijo -usXX.")
        self.dc = api_key.split("-")[-1]
        self.base = f"https://{self.dc}.api.mailchimp.com/3.0"
        self.s = requests.Session()
        token = base64.b64encode(f"anystring:{api_key}".encode()).decode()
        self.s.headers.update({"Authorization": f"Basic {token}"})

    def _req(self, method, path, **kw):
        r = self.s.request(method, self.base + path, timeout=60, **kw)
        if not r.ok:
            sys.exit(f"ERROR Mailchimp {r.status_code} en {path}: {r.text[:400]}")
        return r.json() if r.text else {}

    def find_list(self, name):
        data = self._req("GET", "/lists", params={"count": 1000, "fields": "lists.id,lists.name"})
        lists = data.get("lists", [])
        nl = name.lower()
        for l in lists:
            if l["name"].lower() == nl:
                return l
        for l in lists:
            if nl in l["name"].lower():
                return l
        sys.exit(f"ERROR: no encuentro la audiencia '{name}'. Hay: "
                 + ", ".join(l["name"] for l in lists))

    def latest_sender(self, list_id):
        """Reutiliza from_name/reply_to de la ultima campana enviada a esa lista."""
        data = self._req("GET", "/campaigns", params={
            "list_id": list_id, "count": 1, "sort_field": "send_time",
            "sort_dir": "DESC",
            "fields": "campaigns.settings.from_name,campaigns.settings.reply_to",
        })
        camps = data.get("campaigns", [])
        if camps:
            s = camps[0].get("settings", {})
            return s.get("from_name"), s.get("reply_to")
        return None, None

    def create_draft(self, list_id, subject, title, from_name, reply_to, html):
        body = {
            "type": "regular",
            "recipients": {"list_id": list_id},
            "settings": {"subject_line": subject, "title": title},
        }
        if from_name:
            body["settings"]["from_name"] = from_name
        if reply_to:
            body["settings"]["reply_to"] = reply_to
        camp = self._req("POST", "/campaigns", json=body)
        cid = camp["id"]
        self._req("PUT", f"/campaigns/{cid}/content", json={"html": html})
        return cid


# --------------------------------------------------------------------------- #
# Generacion con Claude + busqueda web
# --------------------------------------------------------------------------- #
def build_system(estilo):
    return (
        "Eres el redactor del noticiario descrito abajo. Debes producir la edicion "
        "de esta semana respetando FIELMENTE su estructura, secciones, tono y "
        "espiritu. Escribe en el idioma del noticiario.\n\n"
        "GUIA DE ESTILO (JSON):\n" + json.dumps(estilo, ensure_ascii=False, indent=2)
    )


def build_user(estilo, hoy):
    temas = ", ".join(estilo.get("temas", []))
    fuentes = ", ".join(estilo.get("fuentes_sugeridas", []))
    return (
        f"Hoy es {hoy}. Busca en la web las noticias mas relevantes de los ultimos "
        f"7 dias sobre estos temas: {temas}. "
        f"Prioriza estas fuentes si es posible: {fuentes}. "
        "Selecciona y resume las noticias siguiendo las secciones y la longitud del "
        "noticiario. Cada noticia debe incluir un enlace a la fuente.\n\n"
        "Devuelve EXACTAMENTE dos bloques con estos marcadores y nada mas fuera de ellos:\n"
        "<<<SUBJECT>>>\nlinea de asunto del email (sin comillas)\n<<<END_SUBJECT>>>\n"
        "<<<HTML>>>\ndocumento HTML completo del noticiario, autocontenido, con estilos "
        "inline acordes a la guia (instrucciones_html), listo para enviar por email\n"
        "<<<END_HTML>>>"
    )


def generar(client, estilo):
    hoy = dt.date.today().isoformat()
    system = [{"type": "text", "text": build_system(estilo),
               "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": build_user(estilo, hoy)}]

    textos = []
    for _ in range(8):  # permite varias rondas de busqueda (pause_turn)
        with client.messages.stream(
            model=MODEL,
            max_tokens=32000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            tools=[WEB_SEARCH_TOOL],
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()

        textos += [b.text for b in msg.content if b.type == "text"]
        messages.append({"role": "assistant", "content": msg.content})
        if msg.stop_reason == "pause_turn":
            continue  # el servidor reanuda la busqueda
        break

    full = "\n".join(textos)
    subject = _extract(full, "SUBJECT") or estilo.get("nombre", "Noticiario")
    html = _extract(full, "HTML")
    if not html:
        sys.exit("ERROR: Claude no devolvio el HTML esperado.\n" + full[:1500])
    return subject.strip(), html.strip()


def _extract(text, tag):
    m = re.search(rf"<<<{tag}>>>(.*?)<<<END_{tag}>>>", text, re.DOTALL)
    return m.group(1).strip() if m else None


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Genera el noticiario semanal y crea borrador en Mailchimp.")
    ap.add_argument("--estilo", default="estilo_noticiario.json")
    ap.add_argument("--audience", default="OPZGZ")
    ap.add_argument("--anthropic-key", default=os.environ.get("ANTHROPIC_API_KEY"))
    ap.add_argument("--mailchimp-key", default=os.environ.get("MAILCHIMP_API_KEY"))
    ap.add_argument("--dry-run", action="store_true", help="Solo genera HTML local, no toca Mailchimp")
    args = ap.parse_args()

    if not args.anthropic_key:
        sys.exit("ERROR: falta ANTHROPIC_API_KEY.")
    if not os.path.isfile(args.estilo):
        sys.exit(f"ERROR: no encuentro {args.estilo}. Ejecuta antes aprende_estilo.py")

    with open(args.estilo, encoding="utf-8") as fh:
        estilo = json.load(fh)

    client = anthropic.Anthropic(api_key=args.anthropic_key)
    print("Buscando noticias de la semana y montando el noticiario...")
    subject, html = generar(client, estilo)

    fecha = dt.date.today().isoformat()
    out_html = f"noticiario_{fecha}.html"
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"HTML generado -> {out_html}")
    print(f"Asunto: {subject}")

    if args.dry_run:
        print("(dry-run) No se ha creado nada en Mailchimp.")
        return

    if not args.mailchimp_key:
        sys.exit("ERROR: falta MAILCHIMP_API_KEY (o usa --dry-run).")

    mc = Mailchimp(args.mailchimp_key)
    audience = mc.find_list(args.audience)
    print(f"Audiencia: {audience['name']} ({audience['id']})")
    from_name, reply_to = mc.latest_sender(audience["id"])

    title = f"{estilo.get('nombre', 'Noticiario')} - {fecha}"
    cid = mc.create_draft(audience["id"], subject, title, from_name, reply_to, html)
    print(f"OK -> Borrador creado en Mailchimp (campaign id {cid}).")
    print("Entra en Mailchimp, revisalo y dale a enviar cuando quieras.")


if __name__ == "__main__":
    main()
