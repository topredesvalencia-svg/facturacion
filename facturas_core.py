"""Núcleo de generación de facturas TopRedesValencia / SOSMADERA S.L.

Rellena la plantilla .docx (sustituyendo solo los valores, conservando el diseño)
y la convierte a PDF con LibreOffice. Gestiona numeración correlativa por serie.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "plantilla.docx")
COUNTERS = os.path.join(HERE, "counters.json")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# Tipo de IVA: R = 10 %, N = 21 % (criterio de la casa)
IVA_CODES = {"R": 10, "N": 21}
PAYMENT_METHODS = ["Transferencia", "Tarjeta", "Efectivo"]

# Datos fijos de la empresa (ya están en la plantilla; se usan para la forma de pago)
BANK = {
    "beneficiario": "SOSMADERA SL",
    "iban": "ES32 2100 4972 6522 0037 5285",
    "entidad": "CAIXABANK, S.A.",
}


def q(tag):
    return "{%s}%s" % (W, tag)


# ---------------------------------------------------------------- cálculos
def _r2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular(precio, cantidad, iva_code, precio_incluye_iva):
    """Devuelve dict con importes en Decimal.

    precio_incluye_iva=True  -> el precio introducido es el TOTAL con IVA
    precio_incluye_iva=False -> el precio introducido es la BASE (se añade IVA)
    """
    rate = Decimal(IVA_CODES[iva_code]) / 100
    precio = Decimal(str(precio))
    cantidad = Decimal(str(cantidad))
    if precio_incluye_iva:
        total_linea = _r2(precio * cantidad)            # total con IVA
        base = _r2(total_linea / (1 + rate))            # base imponible
        iva = total_linea - base
        precio_unit = _r2(base / cantidad) if cantidad else base
    else:
        base = _r2(precio * cantidad)
        iva = _r2(base * rate)
        total_linea = base + iva
        precio_unit = _r2(precio)
    return {
        "precio_unit": precio_unit,   # columna PRECIO (base unitaria)
        "base": base,                 # Total Bruto
        "iva": iva,                   # Total IVA
        "total": total_linea,         # Total Factura
        "tipo_iva": IVA_CODES[iva_code],
    }


def es_empresa(nif):
    """True si el identificador es un CIF (empresa/autónomo societario).

    CIF: letra + 7 dígitos + dígito/letra de control (p. ej. B97884480).
    NIF particular (8 dígitos + letra) y NIE (X/Y/Z) no son empresa.
    """
    return bool(re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", (nif or "").strip().upper()))


def tipo_iva_sugerido(nif):
    """Particular -> R (10 %) · Empresa -> N (21 %)."""
    return "N" if es_empresa(nif) else "R"


def fmt(x):
    """Formato español: 1234,50 €"""
    s = f"{Decimal(x):,.2f}"  # 1,234.50
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def fmt_pct(p):
    return f"{p:.2f} %".replace(".", ",")


# ---------------------------------------------------------------- numeración
import counters_store


def next_number(series):
    c = counters_store.read_counters()
    return f"26-{series}{c[series]:04d}"


def commit_number(series):
    """Incrementa el contador solo cuando la factura se ha generado con éxito."""
    counters_store.increment(series)


# ---------------------------------------------------------------- XML helpers
def _ptext(p):
    return "".join(t.text or "" for t in p.iter(q("t")))


def _has_graphic(p):
    return any(True for _ in p.iter(q("drawing"))) or any(True for _ in p.iter(q("pict")))


def _set_runs_text_all(p, text):
    """Sustituye todo el texto del párrafo conservando el formato del primer run con texto."""
    runs = [r for r in p.iter(q("r"))]
    template_rpr = None
    for r in runs:
        if r.find(q("t")) is not None:
            rpr = r.find(q("rPr"))
            template_rpr = copy.deepcopy(rpr) if rpr is not None else None
            break
    for r in runs:
        r.getparent().remove(r)
    new_r = etree.SubElement(p, q("r"))
    if template_rpr is not None:
        new_r.append(template_rpr)
    t = etree.SubElement(new_r, q("t"))
    t.text = text
    t.set(XML_SPACE, "preserve")


def _set_value_after_label(p, label, value):
    """En un párrafo 'Etiqueta: valor', sustituye solo el valor conservando la etiqueta."""
    runs = [r for r in p.iter(q("r")) if r.find(q("t")) is not None]
    full = "".join("".join(t.text or "" for t in r.findall(q("t"))) for r in runs)
    if label not in full:
        return False
    cut = full.index(label) + len(label)
    pos = 0
    value_rpr = None
    to_remove = []
    straddle = None
    for r in runs:
        txt = "".join(t.text or "" for t in r.findall(q("t")))
        start, end = pos, pos + len(txt)
        pos = end
        if end <= cut:
            continue                      # run completo de etiqueta
        if start < cut:                   # run a caballo: mantener solo la etiqueta
            keep = txt[: cut - start]
            ts = r.findall(q("t"))
            for t in ts[1:]:
                r.remove(t)
            ts[0].text = keep
            ts[0].set(XML_SPACE, "preserve")
            straddle = r
            rpr = r.find(q("rPr"))
            value_rpr = copy.deepcopy(rpr) if rpr is not None else None
            continue
        if value_rpr is None:
            rpr = r.find(q("rPr"))
            value_rpr = copy.deepcopy(rpr) if rpr is not None else None
        to_remove.append(r)
    for r in to_remove:
        r.getparent().remove(r)
    new_r = etree.Element(q("r"))
    if value_rpr is not None:
        new_r.append(value_rpr)
    t = etree.SubElement(new_r, q("t"))
    t.text = " " + value
    t.set(XML_SPACE, "preserve")
    anchor = straddle if straddle is not None else None
    if anchor is not None:
        anchor.addnext(new_r)
    else:
        p.append(new_r)
    return True


def _replace_cell_paragraphs(cell, lines):
    """Sustituye el contenido de una celda por varias líneas (un párrafo por línea)."""
    paras = cell.findall(q("p"))
    base = paras[0]
    for extra in paras[1:]:
        cell.remove(extra)
    _set_runs_text_all(base, lines[0])
    prev = base
    for line in lines[1:]:
        newp = copy.deepcopy(base)
        _set_runs_text_all(newp, line)
        prev.addnext(newp)
        prev = newp


def _add_bank_lines(anchor):
    """Inserta los datos bancarios debajo de 'Forma de Pago' (solo transferencia)."""
    lines = [
        f"Nombre del beneficiario: {BANK['beneficiario']}",
        f"Número de cuenta (IBAN): {BANK['iban']}",
        f"Entidad: {BANK['entidad']}",
    ]
    prev = anchor
    for line in lines:
        newp = copy.deepcopy(anchor)
        _set_runs_text_all(newp, line)
        prev.addnext(newp)
        prev = newp


# ---------------------------------------------------------------- relleno
def _fill_document(root, d):
    # 1) Cabecera: cliente y factura (cuadros de texto; se aplican a todas las copias)
    client_name_done = False
    for p in root.iter(q("p")):
        if _has_graphic(p):
            continue
        text = _ptext(p)
        if "B26945873" in text:            # NIF de la empresa: no tocar
            continue
        if text.startswith("Nombre:"):
            _set_value_after_label(p, "Nombre:", d["cliente"])
        elif text.startswith("Dirección:"):
            _set_value_after_label(p, "Dirección:", d["direccion"])
        elif text.startswith("NIF:"):
            _set_value_after_label(p, "NIF:", d["nif"])
        elif text.startswith("Número:"):
            _set_value_after_label(p, "Número:", d["numero"])
        elif text.startswith("Fecha:"):
            _set_value_after_label(p, "Fecha:", d["fecha"])
        elif text.startswith("Forma de Pago:"):
            _set_value_after_label(p, "Forma de Pago:", d["forma_pago"])
            if d["forma_pago"] == "Transferencia":
                _add_bank_lines(p)
        elif text.strip() == "Pagada" and not d["pagada"]:
            _set_runs_text_all(p, "")

    # 2) Tablas
    for tbl in root.iter(q("tbl")):
        rows = tbl.findall(q("tr"))
        header = "".join(_ptext(p) for p in rows[0].iter(q("p")))
        if "Código" in header and len(rows) >= 2:
            cells = rows[1].findall(q("tc"))
            _replace_cell_paragraphs(cells[0], [d["codigo"]])
            _replace_cell_paragraphs(cells[1], d["descripcion_lineas"])
            _replace_cell_paragraphs(cells[2], [str(d["cantidad"])])
            _replace_cell_paragraphs(cells[3], [fmt(d["precio_unit"])])
            _replace_cell_paragraphs(cells[4], [fmt(d["base"])])
            # La plantilla tiene una sola línea de producto: el resto de filas se eliminan
            for extra in rows[2:]:
                tbl.remove(extra)
        elif "Total Bruto" in header or "Total Bruto" in "".join(_ptext(p) for p in tbl.iter(q("p"))):
            for tr in rows:
                tcs = tr.findall(q("tc"))
                label = _ptext(tcs[0]) if tcs else ""
                if label.startswith("Total Bruto"):
                    _replace_cell_paragraphs(tcs[1], [fmt(d["base"])])
                elif label.startswith("% IVA"):
                    _replace_cell_paragraphs(tcs[1], [fmt_pct(d["tipo_iva"])])
                elif label.startswith("Total IVA"):
                    _replace_cell_paragraphs(tcs[1], [fmt(d["iva"])])
                elif label.startswith("Total Factura"):
                    _replace_cell_paragraphs(tcs[1], [fmt(d["total"])])


def _render_pdf(docx_path, outdir):
    """Convierte .docx a .pdf con LibreOffice (sin mirar el resultado, solo el fichero)."""
    cmd = ["soffice", "-env:UserInstallation=file:///tmp/lo_profile", "--headless",
           "--convert-to", "pdf", "--outdir", outdir, docx_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    if not os.path.exists(pdf):
        raise RuntimeError("LibreOffice no generó el PDF")
    return pdf


def build_invoice(datos, outdir):
    """datos: dict con cliente, nif, direccion, numero, fecha, forma_pago, pagada,
    codigo, descripcion_lineas (list), cantidad, precio, precio_incluye_iva, iva_code.

    Devuelve (ruta_docx, ruta_pdf, importes).
    """
    imp = calcular(datos["precio"], datos["cantidad"], datos["iva_code"], datos["precio_incluye_iva"])
    d = dict(datos)
    d.update({
        "codigo": datos["iva_code"],
        "base": imp["base"], "iva": imp["iva"], "total": imp["total"],
        "precio_unit": imp["precio_unit"], "tipo_iva": imp["tipo_iva"],
    })
    base_name = d["numero"]
    docx_out = os.path.join(outdir, f"FACTURA_{base_name}.docx")

    with zipfile.ZipFile(TEMPLATE) as zin:
        xml_bytes = zin.read("word/document.xml")
        root = etree.fromstring(xml_bytes)
        _fill_document(root, d)
        new_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        with zipfile.ZipFile(docx_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = new_xml if item.filename == "word/document.xml" else zin.read(item.filename)
                zout.writestr(item, data)

    pdf_out = _render_pdf(docx_out, outdir)
    return docx_out, pdf_out, imp


def parse_pegado(texto):
    """Interpreta un bloque de texto pegado con los datos del cliente.

    Acepta líneas con etiqueta (Nombre:, DNI:, Dirección:, Descripción:, Importe:)
    o sin etiqueta (el lector las reconoce por su forma). Devuelve un dict
    con las claves que haya encontrado.
    """
    out = {}
    lines = [l.strip() for l in texto.splitlines() if l.strip()]
    for l in lines:
        low = l.lower()
        m = re.match(r"^(nombre|cliente)\s*:\s*(.+)$", l, re.I)
        if m:
            out["cliente"] = m.group(2).strip(); continue
        m = re.match(r"^(dni|nif|cif)\s*:?\s*(.+)$", l, re.I)
        if m:
            out["nif"] = m.group(2).strip().upper(); continue
        m = re.match(r"^(dirección|direccion)\s*:\s*(.+)$", l, re.I)
        if m:
            out["linea1"] = m.group(2).strip(); continue
        m = re.match(r"^(descripci[oó]n|servicio)\s*:\s*(.+)$", l, re.I)
        if m:
            out["descripcion"] = m.group(2).strip(); continue
        m = re.match(r"^(importe|precio|total)\s*:\s*(.+)$", l, re.I)
        if m:
            _parse_importe(m.group(2), out); continue
        # ---- sin etiqueta: reconocer por forma
        if re.fullmatch(r"\d{8}[A-Za-z]|[A-Za-z]\d{7}[A-Za-z0-9]|[XYZxyz]\d{7}[A-Za-z]", l):
            out["nif"] = l.upper(); continue
        if re.match(r"^\d{5}\b", l):
            out["cp_ciudad"] = l; continue
        if re.match(r"^(c/|c\.|calle\b|av\b|avda\b|avenida\b|pza\b|plaza\b|paseo\b|carrer\b|cami\b)", low):
            out["linea1"] = l; continue
        if re.search(r"\d", l) and re.search(r"(iva|€|eur|\+|base)", low):
            _parse_importe(l, out); continue
        if "cliente" not in out and re.fullmatch(r"[A-Za-zÀ-ÿ' .\-]{5,}", l):
            out["cliente"] = l
    return out


def _parse_importe(texto, out):
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", texto)
    if not m:
        return
    out["precio"] = float(m.group(1).replace(",", "."))
    low = texto.lower()
    out["precio_incluye_iva"] = not ("base" in low or "+" in texto or "más iva" in low or "mas iva" in low)
