# Facturas Top Redes Valencia — app para Streamlit Cloud

## 1. Preparar la numeración (Google Sheets)
En Streamlit Cloud el disco es temporal, así que el contador se guarda en una hoja de Google:

1. Crea una hoja de cálculo. Renombra la pestaña a **contadores** y escribe:

   | serie | siguiente |
   |-------|-----------|
   | M     | 40        |
   | T     | 6         |

2. En Google Cloud Console crea un proyecto, activa **Google Sheets API** y **Google Drive API**,
   crea una **cuenta de servicio** y genera una clave JSON.
3. Abre la hoja, pulsa **Compartir** y añade el email de la cuenta de servicio (`client_email`) como **Editor**.
4. Copia el ID de la hoja (la parte larga de la URL entre `/d/` y `/edit`).

## 2. Subir la app a GitHub
Sube esta carpeta a un repositorio. **No subas** `.streamlit/secrets.toml` (está en `.gitignore`).
Incluye: `app.py`, `facturas_core.py`, `counters_store.py`, `plantilla.docx`,
`requirements.txt`, `packages.txt`.

## 3. Desplegar en Streamlit Cloud
1. share.streamlit.io → **New app** → elige el repositorio, rama y `app.py` como archivo principal.
2. **Advanced settings → Secrets**: pega el contenido de `.streamlit/secrets.toml.example` con tus datos reales
   (`sheet_id` y `[gcp_service_account]`).
3. Deploy. La primera vez tarda unos minutos porque instala LibreOffice (`packages.txt`).

Cuando la app muestra *"Numeración guardada en: Google Sheets"*, todo está bien.

## Uso
1. Pega los datos del cliente y pulsa **Rellenar formulario**.
2. Revisa datos y desglose.
3. **Generar factura** → descarga PDF y Word. Descarga siempre los archivos: en Streamlit Cloud no se guardan en el servidor.

## Reglas
- R = IVA 10 % (particulares) · N = IVA 21 % (empresas, CIF)
- El tipo de IVA se propone según el NIF: CIF → 21 %, DNI/NIE → 10 %. Se puede cambiar a mano.
- "Precio incluye IVA": el importe introducido es el total y se desglosa hacia atrás.
- El número solo avanza si la factura se genera correctamente.

## Ejecutar en tu PC (opcional)
`pip install -r requirements.txt`, instala LibreOffice y ejecuta `streamlit run app.py`.
Sin secretos, la numeración se guarda en `counters.json` local.
