"""Almacén de la numeración correlativa.

- Con secretos de Google Sheets (Streamlit Cloud): el contador vive en una hoja
  de cálculo, así no se pierde al reiniciar la app.
- Sin secretos (uso en tu PC): usa counters.json local.

Hoja esperada: pestaña "contadores" con cabeceras  serie | siguiente
y dos filas:  M | 40   ·   T | 6
"""
import json
import os

import streamlit as st  # noqa: F401  (se usa para leer st.secrets)

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_FILE = os.path.join(HERE, "counters.json")
SHEET_TAB = "contadores"


def _gsheets_ok():
    try:
        return "sheet_id" in st.secrets and "gcp_service_account" in st.secrets
    except Exception:  # noqa: BLE001
        return False


def backend_name():
    return "Google Sheets" if _gsheets_ok() else "local (no persistente en Streamlit Cloud)"


@st.cache_resource(show_spinner=False)
def _worksheet():
    import gspread
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    return gc.open_by_key(st.secrets["sheet_id"]).worksheet(SHEET_TAB)


def read_counters():
    if _gsheets_ok():
        rows = _worksheet().get_all_records()
        return {str(r["serie"]).strip().upper(): int(r["siguiente"]) for r in rows}
    if not os.path.exists(LOCAL_FILE):
        return {"M": 40, "T": 6}
    with open(LOCAL_FILE, encoding="utf8") as f:
        return json.load(f)


def increment(serie):
    """Suma 1 al contador de la serie. Llamar solo tras generar la factura."""
    if _gsheets_ok():
        ws = _worksheet()
        rows = ws.get_all_records()
        for i, r in enumerate(rows, start=2):        # fila 1 = cabeceras
            if str(r["serie"]).strip().upper() == serie:
                ws.update_cell(i, 2, int(r["siguiente"]) + 1)
                return
        raise RuntimeError(f"No existe la serie {serie} en la hoja")
    c = read_counters()
    c[serie] = c.get(serie, 1) + 1
    with open(LOCAL_FILE, "w", encoding="utf8") as f:
        json.dump(c, f, indent=2)
