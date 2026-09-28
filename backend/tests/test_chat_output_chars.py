from app.api.v1.chat.router import _OUTPUT_CHARS


def test_typographic_spaces_and_hyphens_become_plain():
    raw = "Duración: **3 semanas**, costo $30, pre‑universitario"
    assert raw.translate(_OUTPUT_CHARS) == "Duración: **3 semanas**, costo $30, pre-universitario"
