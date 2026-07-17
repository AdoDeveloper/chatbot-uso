from __future__ import annotations

"""Plantillas de correo institucional.

Estilo limpio: encabezado azul con el nombre de la institución, tarjeta blanca
con el contenido (título, texto y datos en tabla) y un pie discreto. Un solo
color de marca, sin iconos, sin emojis, sin firma epistolar (son mensajes
automáticos). Compatible con clientes de correo (layout en tabla, estilos
inline, responsive por media query).
"""

import html as _html
from datetime import datetime, timezone

YEAR = datetime.now(timezone.utc).year

PRIMARY = "#1E40AF"          # azul institucional
TEXT_COLOR = "#1f2937"
MUTED_COLOR = "#6b7280"
BORDER_COLOR = "#e5e7eb"
PAGE_BG = "#f3f4f6"
CARD_BG = "#ffffff"
ROW_BG = "#f8fafc"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

BRAND_NAME = "Universidad de Sonsonate"


def render_email(
    *,
    title: str,
    content: str,
    preheader: str = "",
    # Aceptados por compatibilidad; el estilo limpio no los usa.
    severity: str = "neutral",
    eyebrow: str | None = None,
) -> str:
    """Envuelve `content` en la estructura institucional limpia.

    El encabezado muestra el título de la notificación; el nombre de la
    institución se ubica como rótulo superior discreto.
    """
    pre = (
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all">'
        f"{_html.escape(preheader)}</div>"
        if preheader
        else ""
    )
    return f"""\
<!DOCTYPE html>
<html lang="es" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{_html.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; supported-color-schemes: light dark; }}
  body,table,td,p,a{{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
  a{{ color:{PRIMARY}; }}
  @media only screen and (max-width:600px) {{
    .outer   {{ padding:0 !important; }}
    .card    {{ width:100% !important; border-radius:0 !important; border-left:0 !important; border-right:0 !important; border-top:0 !important; }}
    .px      {{ padding-left:20px !important; padding-right:20px !important; }}
  }}
  /* Modo oscuro: aplicado por los clientes que respetan prefers-color-scheme
     (Apple Mail, iOS). Gmail/Outlook usan su propia inversión automática. */
  @media (prefers-color-scheme: dark) {{
    .bg-page  {{ background:#0f1115 !important; }}
    .bg-card  {{ background:#1a1d23 !important; border-color:#2b2f37 !important; }}
    .bg-row   {{ background:#22262e !important; border-color:#2b2f37 !important; }}
    .t-main   {{ color:#e7e9ee !important; }}
    .t-muted  {{ color:#9aa1ad !important; }}
    .bd       {{ border-color:#2b2f37 !important; }}
  }}
</style>
</head>
<body class="bg-page" style="margin:0;padding:0;background:{PAGE_BG};font-family:{FONT};color:{TEXT_COLOR}">
{pre}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="outer bg-page" style="background:{PAGE_BG};padding:24px 12px">
  <tr><td align="center">
    <table role="presentation" width="580" cellpadding="0" cellspacing="0" class="card bg-card bd" style="width:580px;max-width:100%;background:{CARD_BG};border:1px solid {BORDER_COLOR};border-radius:10px;overflow:hidden">

      <!-- Encabezado: título de la notificación -->
      <tr>
        <td class="px" style="background:{PRIMARY};padding:26px 36px">
          <span style="color:#ffffff;font-size:19px;font-weight:700;letter-spacing:.1px;display:block;line-height:1.3">{_html.escape(title)}</span>
        </td>
      </tr>

      <!-- Contenido -->
      <tr>
        <td class="px" style="padding:32px 36px 36px 36px">
          {content}
        </td>
      </tr>

      <!-- Pie -->
      <tr>
        <td class="px bg-row bd" style="padding:22px 36px;border-top:1px solid {BORDER_COLOR};background:{ROW_BG};text-align:center">
          <p class="t-muted" style="margin:0 0 6px;font-size:12px;color:{MUTED_COLOR};line-height:1.6">
            Notificación automática. Por favor no responda a este mensaje.
          </p>
          <p class="t-muted" style="margin:0;font-size:11px;color:{MUTED_COLOR};line-height:1.6">
            &copy; {YEAR} {_html.escape(BRAND_NAME)}. Todos los derechos reservados.
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def heading(text: str) -> str:
    return (
        f'<p class="t-main" style="margin:24px 0 8px;font-size:15px;font-weight:700;color:{TEXT_COLOR}">'
        f"{_html.escape(text)}</p>"
    )


def paragraph(text: str) -> str:
    return (
        f'<p class="t-main" style="margin:0 0 16px;font-size:15px;line-height:1.65;color:{TEXT_COLOR}">'
        f"{_html.escape(text)}</p>"
    )


def greeting(text: str = "") -> str:
    # Sin saludo epistolar en mensajes automáticos.
    return ""


def detail_table(rows: dict[str, object], *, heading_text: str | None = None) -> str:
    """Lista de datos: cada dato como un bloque con la etiqueta arriba (pequeña,
    gris) y el valor debajo. Se ve bien en escritorio y móvil sin depender de
    media queries (clave para Gmail en Android, que las ignora a menudo)."""
    head = ""
    if heading_text:
        head = (
            f'<p class="t-muted" style="margin:24px 0 10px;font-size:13px;font-weight:700;letter-spacing:.03em;'
            f'text-transform:uppercase;color:{MUTED_COLOR}">{_html.escape(heading_text)}</p>'
        )
    items = list(rows.items())
    body = ""
    for i, (k, v) in enumerate(items):
        border = "" if i == len(items) - 1 else f"border-bottom:1px solid {BORDER_COLOR};"
        body += (
            f'<tr><td class="bd" style="padding:12px 16px;{border}">'
            f'<div class="t-muted" style="font-size:12px;color:{MUTED_COLOR};line-height:1.4;margin-bottom:3px">{_html.escape(str(k))}</div>'
            f'<div class="t-main" style="font-size:15px;color:{TEXT_COLOR};line-height:1.5;word-break:break-word">{_html.escape(str(v))}</div>'
            f"</td></tr>"
        )
    return (
        f"{head}"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="bg-row bd" '
        f'style="margin:0 0 8px;border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'border-collapse:separate;border-spacing:0;overflow:hidden;background:{ROW_BG}">{body}</table>'
    )


def button(label: str, url: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 18px">'
        f'<tr><td style="border-radius:8px;background:{PRIMARY}">'
        f'<a href="{_html.escape(url, quote=True)}" '
        f'style="display:inline-block;padding:12px 30px;font-size:15px;font-weight:600;'
        f'color:#ffffff;text-decoration:none;border-radius:8px">{_html.escape(label)}</a>'
        f"</td></tr></table>"
    )


def muted_note(text: str) -> str:
    return (
        f'<p class="t-muted" style="margin:12px 0 0;font-size:13px;line-height:1.55;color:{MUTED_COLOR}">'
        f"{_html.escape(text)}</p>"
    )


def stat_grid(stats: list[tuple[object, str]]) -> str:
    """Cifras destacadas en una rejilla de 2 columnas (se ve bien en móvil y
    escritorio sin media queries: 2x2 con cuatro métricas)."""
    rows_html = ""
    for i in range(0, len(stats), 2):
        pair = stats[i:i + 2]
        cells = ""
        for j, (value, label) in enumerate(pair):
            border_r = f"border-right:1px solid {BORDER_COLOR};" if j == 0 and len(pair) == 2 else ""
            border_b = f"border-bottom:1px solid {BORDER_COLOR};" if i + 2 < len(stats) else ""
            cells += (
                f'<td class="bd" width="50%" valign="top" style="padding:18px 14px;text-align:center;{border_r}{border_b}">'
                f'<div style="font-size:28px;line-height:1;font-weight:800;color:{PRIMARY}">{_html.escape(str(value))}</div>'
                f'<div class="t-muted" style="margin-top:6px;font-size:12px;color:{MUTED_COLOR};line-height:1.4">{_html.escape(label)}</div>'
                f"</td>"
            )
        rows_html += f"<tr>{cells}</tr>"
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="bg-row bd" '
        f'style="margin:0 0 20px;border:1px solid {BORDER_COLOR};border-radius:8px;'
        f'border-collapse:separate;border-spacing:0;overflow:hidden;background:{ROW_BG}">'
        f"{rows_html}</table>"
    )


def topic_list(topics: list[tuple[str, int]]) -> str:
    """Lista de temas con su conteo, en formato de barras simples."""
    if not topics:
        return ""
    max_n = max(n for _, n in topics) or 1
    rows = ""
    for topic, n in topics:
        pct = max(8, round(n / max_n * 100))
        rows += (
            f'<tr><td class="t-main" style="padding:6px 0;font-size:14px;color:{TEXT_COLOR};width:45%;'
            f'vertical-align:middle">{_html.escape(str(topic))}</td>'
            f'<td style="padding:6px 0;vertical-align:middle">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%"><tr>'
            f'<td style="background:{PRIMARY};height:10px;border-radius:5px;width:{pct}%;font-size:0;line-height:0">&nbsp;</td>'
            f'<td class="t-muted" style="padding-left:10px;font-size:13px;color:{MUTED_COLOR};white-space:nowrap;width:1%">{n}</td>'
            f"</tr></table></td></tr>"
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px">'
        f"{rows}</table>"
    )


def quote_list(items: list[str]) -> str:
    """Lista de fragmentos de texto (p. ej. preguntas), cada uno como cita."""
    if not items:
        return ""
    blocks = "".join(
        f'<tr><td style="padding:0 0 10px 0">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td class="bg-row t-main" style="background:{ROW_BG};border-left:3px solid {PRIMARY};border-radius:4px;'
        f'padding:10px 14px;font-size:14px;color:{TEXT_COLOR};line-height:1.5">{_html.escape(str(it))}</td></tr>'
        f"</table></td></tr>"
        for it in items
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 12px">'
        f"{blocks}</table>"
    )
