# Noticiario automático (aprende del PDF → busca noticias → borrador en Mailchimp)

Sistema en dos pasos que aprende el estilo de tu noticiario a partir de un PDF y,
cada semana, busca las noticias del momento y monta un **borrador** de campaña en
Mailchimp para que tú lo revises y envíes.

## Requisitos (una vez)

```cmd
py -m pip install anthropic requests
```

Dos claves:
- `ANTHROPIC_API_KEY` — de https://console.anthropic.com (para que Claude redacte y busque noticias).
- `MAILCHIMP_API_KEY` — la tuya de Mailchimp (`...-us15`).

## Paso 1 — Aprender el estilo (una vez, o cuando cambie el formato)

```cmd
set ANTHROPIC_API_KEY=sk-ant-...
py aprende_estilo.py --pdf viernes_OPZGZ.pdf
```

Genera `estilo_noticiario.json` con la estructura, el espíritu, los temas y las
fuentes deducidas del PDF. **Ábrelo y ajusta `temas` / `fuentes_sugeridas` si quieres.**

## Paso 2 — Generar la edición de la semana

```cmd
set ANTHROPIC_API_KEY=sk-ant-...
set MAILCHIMP_API_KEY=tu-clave-mailchimp-usXX
py genera_noticiario.py --audience OPZGZ
```

- Busca noticias de los últimos 7 días sobre tus temas.
- Monta el HTML del noticiario en tu formato → `noticiario_AAAA-MM-DD.html`.
- Crea un **borrador** en Mailchimp para la audiencia OPZGZ (reutiliza el remitente
  de tu última campaña). Tú lo revisas y le das a enviar.

Prueba sin tocar Mailchimp: añade `--dry-run` (solo genera el HTML local).

## Doble clic (Windows)

Edita `noticiario_semanal.bat` y pon tu clave de Anthropic donde indica. Luego
doble clic. La primera vez aprende el estilo; después solo genera y crea el borrador.

## Automatizar cada viernes (opcional)

Programador de tareas de Windows → Crear tarea básica → semanal, viernes →
Acción: iniciar `noticiario_semanal.bat`.

## Notas

- El sistema deja **borradores**, nunca envía solo (decisión tuya).
- Usa Claude Opus 4.8 con búsqueda web y caché de prompts.
