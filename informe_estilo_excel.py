#!/usr/bin/env python3
"""
Genera el informe Excel de seguimiento en el formato EXACTO de OPERINTER
(6 hojas: Resumen General, Todos los Rebotes, Dados de Baja, Aperturas por
Destinatario, Aperturas por Empresa, Dominios sin Aperturas) para un publico
y un periodo de Mailchimp.

Uso:
    set MAILCHIMP_API_KEY=xxxxxxxx-usXX
    py informe_estilo_excel.py --audience OPZGZ --desde 2026-01-01 --hasta 2026-02-28

Salida: <AUDIENCE>_<desde>_<hasta>.xlsx
"""

import argparse
import base64
import datetime as dt
import os
import sys
import time

import requests
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


class Mailchimp:
    def __init__(self, api_key):
        if "-" not in api_key:
            sys.exit("ERROR: la API key de Mailchimp no tiene el sufijo -usXX.")
        self.dc = api_key.split("-")[-1]
        self.base = f"https://{self.dc}.api.mailchimp.com/3.0"
        self.s = requests.Session()
        token = base64.b64encode(f"anystring:{api_key}".encode()).decode()
        self.s.headers.update({"Authorization": f"Basic {token}"})

    def get(self, path, params=None):
        for attempt in range(6):
            r = self.s.get(self.base + path, params=params, timeout=120)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if not r.ok:
                sys.exit(f"ERROR Mailchimp {r.status_code} en {path}: {r.text[:300]}")
            return r.json()
        sys.exit(f"ERROR: rate limit persistente en {path}")

    def find_list(self, name):
        data = self.get("/lists", {"count": 1000, "fields": "lists.id,lists.name"})
        nl = name.lower()
        for l in data.get("lists", []):
            if l["name"].lower() == nl:
                return l
        for l in data.get("lists", []):
            if nl in l["name"].lower():
                return l
        return None

    def campaigns_in_range(self, list_id, desde, hasta):
        out, offset = [], 0
        hasta_excl = (dt.date.fromisoformat(hasta) + dt.timedelta(days=1)).isoformat()
        while True:
            data = self.get("/campaigns", {
                "list_id": list_id, "status": "sent", "count": 500, "offset": offset,
                "since_send_time": f"{desde}T00:00:00+00:00",
                "before_send_time": f"{hasta_excl}T00:00:00+00:00",
                "sort_field": "send_time", "sort_dir": "ASC",
                "fields": "campaigns.id,campaigns.send_time,"
                          "campaigns.settings.subject_line,total_items",
            })
            batch = data.get("campaigns", [])
            out.extend(batch)
            offset += len(batch)
            if not batch or offset >= data.get("total_items", 0):
                break
        return out

    def report(self, cid):
        return self.get(f"/reports/{cid}", {
            "fields": "emails_sent,unsubscribed,bounces,opens,clicks",
        })

    def email_activity(self, cid):
        """Devuelve (opens_por_email, lista_rebotes, universo_emails).
        Conserva el email TAL CUAL lo devuelve Mailchimp (con sus mayusculas)."""
        opens, rebotes, universo = {}, [], set()
        offset = 0
        while True:
            data = self.get(f"/reports/{cid}/email-activity", {
                "count": 1000, "offset": offset,
                "fields": "emails.email_address,emails.activity.action,"
                          "emails.activity.type,emails.activity.timestamp,total_items",
            })
            emails = data.get("emails", [])
            for e in emails:
                addr = e.get("email_address") or ""
                if not addr:
                    continue
                universo.add(addr)
                n = 0
                for a in e.get("activity", []):
                    if a.get("action") == "open":
                        n += 1
                    elif a.get("action") == "bounce":
                        rebotes.append((addr, a.get("type", ""), a.get("timestamp", "")))
                if n:
                    opens[addr] = opens.get(addr, 0) + n
            offset += len(emails)
            if not emails or offset >= data.get("total_items", 0):
                break
        return opens, rebotes, universo

    def unsubscribed(self, cid):
        out, offset = [], 0
        while True:
            data = self.get(f"/reports/{cid}/unsubscribed", {
                "count": 1000, "offset": offset,
                "fields": "unsubscribes.email_address,unsubscribes.timestamp,"
                          "unsubscribes.reason,total_items",
            })
            batch = data.get("unsubscribes", [])
            out.extend(batch)
            offset += len(batch)
            if not batch or offset >= data.get("total_items", 0):
                break
        return out


def empresa(email):
    """Nombre de empresa a partir del dominio: export@fedinsa.com -> FEDINSA."""
    if "@" not in email:
        return ""
    return email.split("@")[1].split(".")[0].upper()


# --------------------------------------------------------------------------- #
H_FILL = PatternFill("solid", fgColor="1F3864")
H_FONT = Font(bold=True, color="FFFFFF")


def _head(ws, headers):
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.fill = H_FILL; c.font = H_FONT; c.alignment = Alignment(horizontal="center")


def main():
    ap = argparse.ArgumentParser(description="Informe Excel formato OPERINTER por publico.")
    ap.add_argument("--audience", default="OPZGZ")
    ap.add_argument("--desde", default="2026-01-01")
    ap.add_argument("--hasta", default="2026-02-28")
    ap.add_argument("--api-key", default=os.environ.get("MAILCHIMP_API_KEY"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if not args.api_key:
        sys.exit("ERROR: falta MAILCHIMP_API_KEY.")

    mc = Mailchimp(args.api_key)
    lst = mc.find_list(args.audience)
    if not lst:
        sys.exit(f"ERROR: no encuentro la audiencia '{args.audience}'.")
    print(f"Audiencia: {lst['name']} ({lst['id']})")
    camps = mc.campaigns_in_range(lst["id"], args.desde, args.hasta)
    print(f"Campanas {args.desde}..{args.hasta}: {len(camps)}")
    if not camps:
        sys.exit("Sin campanas en el periodo.")

    # Pre-cargar reports y deduplicar: cuando hay varias campanas con el mismo
    # asunto y la misma fecha (reenvio a no-abridores, prueba, etc.) se conserva
    # solo la principal (la de mayor numero de envios).
    info = {}
    for c in camps:
        rep = mc.report(c["id"])
        st = c.get("send_time", "")
        subj = c.get("settings", {}).get("subject_line", "")
        info[c["id"]] = {"c": c, "rep": rep, "subj": subj,
                         "env": rep.get("emails_sent", 0), "fecha": st[:10]}
    mejores = {}
    for cid, d in info.items():
        k = (d["subj"], d["fecha"])
        if k not in mejores or d["env"] > info[mejores[k]]["env"]:
            mejores[k] = cid
    keep = set(mejores.values())
    descartadas = [d for cid, d in info.items() if cid not in keep]
    for d in descartadas:
        print(f"  (reenvio/prueba: fuera del Resumen, dentro de detalle) "
              f"{d['fecha']} env={d['env']} {d['subj'][:40]}")
    # Todas las campanas, ordenadas por fecha de envio
    camps_all = sorted(info.values(), key=lambda d: d["c"].get("send_time", ""))

    resumen = []                 # filas de Resumen General (solo campanas principales)
    rebotes_all = []             # (campana, email, tipo, fecha)  -> TODAS las campanas
    bajas_all = []               # (campana, email, fecha, razon) -> TODAS las campanas
    opens_acum = {}              # email(min) -> total aperturas    -> TODAS las campanas
    disp = {}                    # email(min) -> email original (con sus mayusculas)
    universo = set()             # todos los destinatarios del periodo
    tot = {"baja": 0, "hard": 0, "soft": 0, "tot_reb": 0}

    for d in camps_all:
        c = d["c"]; cid = c["id"]; rep = d["rep"]; subj = d["subj"]
        st = c.get("send_time", "")
        try:
            dd = dt.datetime.fromisoformat(st.replace("Z", "+00:00"))
            fecha, dia = dd.strftime("%Y-%m-%d"), DIAS[dd.weekday()]
        except Exception:
            fecha, dia = st[:10], ""

        # --- Resumen General: solo la campana principal de cada (asunto, fecha) ---
        if cid in keep:
            env = rep.get("emails_sent", 0)
            uo = rep.get("opens", {}).get("unique_opens", 0)
            orate = rep.get("opens", {}).get("open_rate", 0) or 0
            ct = rep.get("clicks", {}).get("clicks_total", 0)
            crate = rep.get("clicks", {}).get("click_rate", 0) or 0
            baja = rep.get("unsubscribed", 0)
            hard = rep.get("bounces", {}).get("hard_bounces", 0)
            soft = rep.get("bounces", {}).get("soft_bounces", 0)
            treb = hard + soft
            resumen.append([subj, fecha, dia, env, uo, orate, ct, crate, baja, hard, soft, treb])
            tot["baja"] += baja; tot["hard"] += hard
            tot["soft"] += soft; tot["tot_reb"] += treb

        # --- Detalle y agregados: TODAS las campanas (incluye reenvios/pruebas) ---
        op, reb, uni = mc.email_activity(cid)
        for a in uni:
            lo = a.lower(); disp.setdefault(lo, a); universo.add(lo)
        for addr, n in op.items():
            lo = addr.lower(); disp.setdefault(lo, addr)
            opens_acum[lo] = opens_acum.get(lo, 0) + n
        for addr, tp, ts in reb:
            rebotes_all.append([subj, addr, tp, ts])
        for u in mc.unsubscribed(cid):
            ts = u.get("timestamp", "")
            try:
                ts = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            bajas_all.append([subj, u.get("email_address", ""), ts, u.get("reason", "")])
        print(f"  - {fecha} {subj[:40]}  env={d['env']}")

    # Totales del Resumen: tasa de apertura global de las campanas principales
    tot_env = sum(r[3] for r in resumen)
    tot_uo = sum(r[4] for r in resumen)

    # ---------- construir Excel ----------
    wb = Workbook()

    ws = wb.active; ws.title = "Resumen General"
    _head(ws, ["Asunto", "Fecha de envío", "Día", "Enviados", "Aperturas únicas",
               "Tasa de apertura", "Clics únicos", "Tasa de clics", "Dados de baja",
               "Rebotes duros", "Rebotes suaves", "Total rebotes"])
    for i, fila in enumerate(resumen, 2):
        for j, v in enumerate(fila, 1):
            cell = ws.cell(row=i, column=j, value=v)
            if j in (6, 8):
                cell.number_format = "0.00%"
    r = len(resumen) + 2
    orate_tot = (tot_uo / tot_env) if tot_env else 0
    ws.cell(row=r, column=6, value=orate_tot).number_format = "0.00%"
    ws.cell(row=r, column=9, value=tot["baja"])
    ws.cell(row=r, column=10, value=tot["hard"])
    ws.cell(row=r, column=11, value=tot["soft"])
    ws.cell(row=r, column=12, value=tot["tot_reb"])
    for col, w in zip("ABCDEFGHIJKL", [46, 14, 11, 10, 14, 14, 11, 12, 12, 12, 13, 12]):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("Todos los Rebotes")
    _head(ws, ["Campaña", "Email", "Tipo de Rebote", "Fecha"])
    for i, fila in enumerate(sorted(rebotes_all, key=lambda x: (x[0], x[1])), 2):
        for j, v in enumerate(fila, 1):
            ws.cell(row=i, column=j, value=v)
    for col, w in zip("ABCD", [46, 34, 14, 26]):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("Dados de Baja")
    _head(ws, ["Campaña", "Email", "Fecha", "Razón"])
    for i, fila in enumerate(sorted(bajas_all, key=lambda x: x[2]), 2):
        for j, v in enumerate(fila, 1):
            ws.cell(row=i, column=j, value=v)
    for col, w in zip("ABCD", [46, 34, 18, 24]):
        ws.column_dimensions[col].width = w

    # aperturas por destinatario
    ws = wb.create_sheet("Aperturas por Destinatario")
    _head(ws, ["Email", "Empresa", "Total Aperturas"])
    dest = sorted(((disp.get(a, a), empresa(a), n) for a, n in opens_acum.items()),
                  key=lambda x: x[2], reverse=True)
    for i, (a, emp, n) in enumerate(dest, 2):
        ws.cell(row=i, column=1, value=a)
        ws.cell(row=i, column=2, value=emp)
        ws.cell(row=i, column=3, value=n)
    for col, w in zip("ABC", [38, 24, 16]):
        ws.column_dimensions[col].width = w

    # aperturas por empresa
    emp_opens = {}
    for a, n in opens_acum.items():
        e = empresa(a)
        if e:
            emp_opens[e] = emp_opens.get(e, 0) + n
    ws = wb.create_sheet("Aperturas por Empresa")
    _head(ws, ["Empresa", "Total Aperturas"])
    for i, (e, n) in enumerate(sorted(emp_opens.items(), key=lambda x: x[1], reverse=True), 2):
        ws.cell(row=i, column=1, value=e)
        ws.cell(row=i, column=2, value=n)
    ws.column_dimensions["A"].width = 30; ws.column_dimensions["B"].width = 16

    # dominios (empresas) sin aperturas
    emp_universo = {empresa(a) for a in universo if "@" in a}
    emp_con = set(emp_opens.keys())
    sin = sorted(e for e in (emp_universo - emp_con) if e)
    ws = wb.create_sheet("Dominios sin Aperturas")
    ws.cell(row=1, column=1, value="Empresas sin Aperturas").fill = H_FILL
    ws.cell(row=1, column=1).font = H_FONT
    for i, e in enumerate(sin, 2):
        ws.cell(row=i, column=1, value=e)
    ws.column_dimensions["A"].width = 32

    out = args.out or f"{args.audience}_{args.desde}_{args.hasta}.xlsx"
    wb.save(out)
    print(f"OK -> {out}")
    print(f"  campanas={len(resumen)} destinatarios={len(dest)} "
          f"empresas={len(emp_opens)} sin_aperturas={len(sin)} "
          f"rebotes={len(rebotes_all)} bajas={len(bajas_all)}")


if __name__ == "__main__":
    main()
