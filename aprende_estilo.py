#!/usr/bin/env python3
"""
PASO 1 - Aprender el estilo del noticiario.

Claude (Opus 4.8) lee el PDF del noticiario y deduce su estructura, espiritu,
tono, secciones, temas habituales y posibles fuentes de noticias. Guarda todo
en 'estilo_noticiario.json', que luego usa genera_noticiario.py.

Uso (Windows):
    set ANTHROPIC_API_KEY=sk-ant-...
    py aprende_estilo.py --pdf viernes_OPZGZ.pdf

La API key de Anthropic se saca de console.anthropic.com.
"""

import argparse
import json
import os
import sys

import anthropic

MODEL = "claude-opus-4-8"

# Esquema de la guia de estilo que queremos que Claude rellene.
ESQUEMA = {
    "type": "object",
    "properties": {
        "nombre": {"type": "string", "description": "Nombre del noticiario"},
        "idioma": {"type": "string"},
        "espiritu": {
            "type": "string",
            "description": "El proposito y el 'alma' del noticiario en 2-4 frases",
        },
        "tono": {"type": "string", "description": "Registro y voz (cercano, formal, ironico...)"},
        "audiencia": {"type": "string", "description": "A quien va dirigido"},
        "secciones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "descripcion": {"type": "string"},
                    "num_items": {"type": "integer"},
                },
                "required": ["titulo", "descripcion", "num_items"],
                "additionalProperties": False,
            },
        },
        "longitud_total_palabras": {"type": "integer"},
        "temas": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Temas/areas que cubre el noticiario, para buscar noticias",
        },
        "fuentes_sugeridas": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Medios o webs de donde salen las noticias (dominios o nombres)",
        },
        "instrucciones_estilo": {
            "type": "string",
            "description": "Guia de redaccion: como escribir titulares, entradillas, longitud, despedida...",
        },
        "instrucciones_html": {
            "type": "string",
            "description": "Como debe verse el HTML: colores, cabecera, estructura de bloques, etc.",
        },
    },
    "required": [
        "nombre", "idioma", "espiritu", "tono", "audiencia", "secciones",
        "longitud_total_palabras", "temas", "fuentes_sugeridas",
        "instrucciones_estilo", "instrucciones_html",
    ],
    "additionalProperties": False,
}

PROMPT = (
    "Eres un analista editorial. Te paso el PDF de un noticiario/boletin que se "
    "envia por email. Estudia a fondo su ESTRUCTURA y su ESPIRITU: que secciones "
    "tiene y en que orden, el tono y la voz, a quien se dirige, la longitud tipica, "
    "como redacta titulares y entradillas, que tipo de noticias incluye y de que "
    "temas tratan, y como esta maquetado (colores, cabecera, bloques). "
    "A partir de eso, deduce tambien los TEMAS que cubre y posibles FUENTES de "
    "noticias coherentes con esos temas. Rellena el esquema con todo ello, en el "
    "mismo idioma del noticiario. Se concreto y fiel al original."
)


def main():
    ap = argparse.ArgumentParser(description="Aprende el estilo del noticiario desde un PDF.")
    ap.add_argument("--pdf", required=True, help="Ruta al PDF del noticiario")
    ap.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY"))
    ap.add_argument("--out", default="estilo_noticiario.json")
    args = ap.parse_args()

    if not args.api_key:
        sys.exit("ERROR: falta la API key de Anthropic (--api-key o ANTHROPIC_API_KEY).")
    if not os.path.isfile(args.pdf):
        sys.exit(f"ERROR: no encuentro el PDF: {args.pdf}")

    client = anthropic.Anthropic(api_key=args.api_key)

    print(f"Subiendo PDF a Anthropic: {args.pdf}")
    with open(args.pdf, "rb") as fh:
        uploaded = client.beta.files.upload(
            file=(os.path.basename(args.pdf), fh, "application/pdf"),
        )

    print("Analizando el noticiario con Claude (Opus 4.8)...")
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": ESQUEMA},
        },
        betas=["files-api-2025-04-14"],
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "document", "source": {"type": "file", "file_id": uploaded.id}},
            ],
        }],
    )

    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        estilo = json.loads(text)
    except json.JSONDecodeError:
        sys.exit("ERROR: la respuesta no era JSON valido:\n" + text[:1000])

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(estilo, fh, ensure_ascii=False, indent=2)

    # Limpieza del fichero subido
    try:
        client.beta.files.delete(uploaded.id)
    except Exception:
        pass

    print(f"OK -> {args.out}")
    print(f"  Noticiario: {estilo.get('nombre')}")
    print(f"  Secciones:  {len(estilo.get('secciones', []))}")
    print(f"  Temas:      {', '.join(estilo.get('temas', [])[:8])}")
    print("\nRevisa el JSON y ajusta temas/fuentes si quieres antes de generar.")


if __name__ == "__main__":
    main()
