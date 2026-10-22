"""App Streamlit para generar facturas TopRedesValencia / SOSMADERA S.L.

Ejecutar:  streamlit run app.py
"""
import os
import tempfile
from datetime import date

import streamlit as st

import counters_store
import facturas_core as fc

def nombre_descarga(numero, cliente):
    """Nombre de descarga: 26-T0006-CatherineAntequera-TopRedes (sin tildes ni espacios)."""
    import re
    import unicodedata
    sin_tildes = unicodedata.normalize("NFKD", cliente).encode("ascii", "ignore").decode("ascii")
    solo_letras = re.sub(r"[^A-Za-z0-9]", "", sin_tildes)
    return f"{numero}-{solo_letras}-TopRedes"

SALIDA = os.path.join(fc.HERE, "facturas_generadas")
os.makedirs(SALIDA, exist_ok=True)

st.set_page_config(page_title="Facturas Top Redes", page_icon="🐾", layout="centered")
st.markdown(
    "<h2 style='color:#E01B7D;margin-bottom:0'>🐾 Facturas Top Redes Valencia</h2>"
    "<p style='color:#666'>Pega los datos del cliente o rellena el formulario. "
    "El PDF sale con el mismo diseño de la plantilla.</p>",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------ estado inicial
DEFAULTS = {
    "cliente": "", "nif": "", "linea1": "", "cp_ciudad": "",
    "descripcion": "Instalación de red de seguridad para gatos",
    "cantidad": 1, "precio": 0.0, "incl_iva": True,
    "tipo_iva": "R", "forma_pago": "Transferencia", "pagada": True,
    "serie": "M", "fecha": date.today(), "pegado": "",
    "ultimo": None,
}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def aplicar_pegado():
    """Callback: vuelca lo interpretado del texto pegado en el formulario."""
    datos = fc.parse_pegado(st.session_state.pegado)
    if "cliente" in datos: st.session_state.cliente = datos["cliente"]
    if "nif" in datos:
        st.session_state.nif = datos["nif"]
        st.session_state.tipo_iva = fc.tipo_iva_sugerido(datos["nif"])
    if "linea1" in datos: st.session_state.linea1 = datos["linea1"]
    if "cp_ciudad" in datos: st.session_state.cp_ciudad = datos["cp_ciudad"]
    if "descripcion" in datos: st.session_state.descripcion = datos["descripcion"]
    if "precio" in datos:
        st.session_state.precio = float(datos["precio"])
        st.session_state.incl_iva = bool(datos.get("precio_incluye_iva", True))


def sugerir_iva():
    """Callback del NIF: propone el tipo de IVA según sea particular o empresa."""
    st.session_state.tipo_iva = fc.tipo_iva_sugerido(st.session_state.nif)


def nueva_factura():
    for k in ["cliente", "nif", "linea1", "cp_ciudad", "precio"]:
        st.session_state[k] = DEFAULTS[k]
    st.session_state.cantidad = 1
    st.session_state.pegado = ""
    st.session_state.ultimo = None


# ------------------------------------------------------------ 1. pegar datos
with st.expander("📋 Pegar datos del cliente (rellena el formulario)", expanded=True):
    st.text_area(
        "Texto con los datos",
        key="pegado", height=140,
        placeholder="José Argimiro Pujol Espert\nC/ Arquitecto Segura de Lago, 7-1-14\n46014 Valencia\n25401056V\nImporte IVA incluido 120€ (desglosar)",
        label_visibility="collapsed",
    )
    st.button("Rellenar formulario", on_click=aplicar_pegado, use_container_width=True)

# ------------------------------------------------------------ 2. formulario
st.subheader("Datos de la factura")
col1, col2 = st.columns([1, 1])
with col1:
    serie = st.radio("Serie", ["M", "T"], key="serie", horizontal=True,
                     help="M = serie habitual · T = serie de presupuestos/facturas T")
with col2:
    fecha = st.date_input("Fecha", key="fecha", format="DD/MM/YYYY")

numero = fc.next_number(serie)
st.info(f"Número de factura que se va a emitir: **{numero}**  (se asigna automáticamente y es correlativo)")
st.caption(f"Numeración guardada en: {counters_store.backend_name()}")

st.text_input("Nombre / razón social", key="cliente")
c1, c2 = st.columns(2)
with c1:
    st.text_input("NIF / DNI / CIF", key="nif", on_change=sugerir_iva)
with c2:
    st.text_input("Ciudad / CP", key="cp_ciudad", placeholder="46014 Valencia")
st.text_input("Dirección", key="linea1", placeholder="C/ Arquitecto Segura de Lago, 7-1-14")
st.text_area("Descripción (una línea por fila)", key="descripcion", height=90)

c3, c4 = st.columns([1, 1])
with c3:
    st.number_input("Cantidad", key="cantidad", min_value=1, step=1)
with c4:
    st.number_input("Precio (€)", key="precio", min_value=0.0, step=1.0, format="%.2f")

c5, c6 = st.columns(2)
with c5:
    st.checkbox("El precio INCLUYE IVA (desglosar)", key="incl_iva")
    tipo = st.radio(
        "Tipo de IVA", ["R", "N"], key="tipo_iva", horizontal=True,
        format_func=lambda c: f"{c} · IVA {fc.IVA_CODES[c]} %",
        help="Se propone según el NIF: particular → 10 % · empresa (CIF) → 21 %. Puedes cambiarlo.",
    )
    st.caption("Propuesto: " + ("empresa → 21 %" if fc.es_empresa(st.session_state.nif) else "particular → 10 %"))
with c6:
    st.selectbox("Forma de pago", fc.PAYMENT_METHODS, key="forma_pago")
    st.checkbox("Marcar como PAGADA", key="pagada")

# ------------------------------------------------------------ 3. previsualización de importes
precio = st.session_state.precio
if precio > 0:
    imp = fc.calcular(precio, st.session_state.cantidad, tipo, st.session_state.incl_iva)
    st.markdown("##### Desglose")
    st.table({
        "Concepto": ["Total Bruto (base)", f"Total IVA ({imp['tipo_iva']} %)", "Total Factura"],
        "Importe": [fc.fmt(imp["base"]), fc.fmt(imp["iva"]), fc.fmt(imp["total"])],
    })

# ------------------------------------------------------------ 4. generar
errores = []
if not st.session_state.cliente.strip(): errores.append("Falta el nombre del cliente")
if not st.session_state.nif.strip(): errores.append("Falta el NIF")
if not st.session_state.linea1.strip(): errores.append("Falta la dirección")
if not st.session_state.cp_ciudad.strip(): errores.append("Falta el CP y la ciudad")
if not st.session_state.descripcion.strip(): errores.append("Falta la descripción")
if precio <= 0: errores.append("El precio debe ser mayor que 0")
for e in errores:
    st.warning(e)

if st.button("⬇️ Generar factura", type="primary", disabled=bool(errores), use_container_width=True):
    direccion = " - ".join(x for x in [st.session_state.linea1.strip(), st.session_state.cp_ciudad.strip()] if x)
    lineas = [l.strip() for l in st.session_state.descripcion.splitlines() if l.strip()]
    datos = {
        "cliente": st.session_state.cliente.strip(),
        "nif": st.session_state.nif.strip().upper(),
        "direccion": direccion,
        "numero": numero,
        "fecha": fecha.strftime("%d/%m/%Y"),
        "forma_pago": st.session_state.forma_pago,
        "pagada": st.session_state.pagada,
        "descripcion_lineas": lineas,
        "cantidad": int(st.session_state.cantidad),
        "precio": precio,
        "precio_incluye_iva": st.session_state.incl_iva,
        "iva_code": tipo,
    }
    try:
        with st.spinner("Generando PDF..."):
            docx_path, pdf_path, imp = fc.build_invoice(datos, SALIDA)
        fc.commit_number(serie)   # solo se incrementa si todo ha ido bien
        st.session_state.ultimo = {"numero": numero, "pdf": pdf_path, "docx": docx_path,
                                   "total": fc.fmt(imp["total"]),
                                   "nombre": nombre_descarga(numero, datos["cliente"])}
    except Exception as ex:  # noqa: BLE001
        st.error(f"No se pudo generar la factura: {ex}. ¿Está instalado LibreOffice?")

# ------------------------------------------------------------ 5. descargas
ult = st.session_state.ultimo
if ult:
    st.success(f"✅ Factura **{ult['numero']}** generada · Total {ult['total']}")
    d1, d2 = st.columns(2)
    with d1:
        with open(ult["pdf"], "rb") as f:
            st.download_button("📄 Descargar PDF", f, file_name=ult["nombre"] + ".pdf",
                               mime="application/pdf", use_container_width=True)
    with d2:
        with open(ult["docx"], "rb") as f:
            st.download_button("📝 Descargar Word (editable)", f, file_name=ult["nombre"] + ".docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               use_container_width=True)
    st.button("➕ Nueva factura", on_click=nueva_factura)
