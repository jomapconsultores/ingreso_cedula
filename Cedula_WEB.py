import streamlit as st
import pandas as pd
import base64
import requests
import json
import re
import io
import time
from PIL import Image, ImageOps, ImageEnhance

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Sistema Cédulas Web", layout="wide")

API_KEY = st.secrets["MISTRAL_KEY"] # Usaremos Secretos de Streamlit para seguridad
API_URL = "https://api.mistral.ai/v1/chat/completions"
MODEL_ID = "pixtral-12b-2409"

# --- 2. GESTIÓN DE ESTADO ---
if 'step' not in st.session_state: st.session_state.step = 1
if 'data' not in st.session_state: st.session_state.data = {}
if 'proc_front' not in st.session_state: st.session_state.proc_front = None
if 'proc_back' not in st.session_state: st.session_state.proc_back = None

# --- 3. BASE DE DATOS GEOGRÁFICA ---
CIUDADES_PROVINCIAS = {
    "AZOGUES": "CAÑAR", "CUENCA": "AZUAY", "GUALACEO": "AZUAY", "SIGSIG": "AZUAY", "GIRON": "AZUAY", "PAUTE": "AZUAY",
    "MACHALA": "EL ORO", "PASAJE": "EL ORO", "SANTA ROSA": "EL ORO", "HUAQUILLAS": "EL ORO", "PIÑAS": "EL ORO",
    "QUITO": "PICHINCHA", "GUAYAQUIL": "GUAYAS", "SAMBORONDON": "GUAYAS", "DAULE": "GUAYAS", "DURAN": "GUAYAS",
    "LOJA": "LOJA", "AMBATO": "TUNGURAHUA", "RIOBAMBA": "CHIMBORAZO",
    "IBARRA": "IMBABURA", "TULCAN": "CARCHI", "ESMERALDAS": "ESMERALDAS",
    "PORTOVIEJO": "MANABI", "MANTA": "MANABI", "SANTO DOMINGO": "SANTO DOMINGO",
    "LATACUNGA": "COTOPAXI", "GUARANDA": "BOLIVAR", "BABAHOYO": "LOS RIOS", "QUEVEDO": "LOS RIOS",
    "MACAS": "MORONA SANTIAGO", "PUYO": "PASTAZA", "TENA": "NAPO",
    "ZAMORA": "ZAMORA CHINCHIPE", "NUEVA LOJA": "SUCUMBIOS", "ORELLANA": "ORELLANA", "COCA": "ORELLANA",
    "SANTA CRUZ": "GALAPAGOS", "SAN CRISTOBAL": "GALAPAGOS", "IQUIQUE": "EXTRANJERO"
}

# --- 4. PROCESAMIENTO DE IMAGEN ---
def process_image_upload(uploaded_file):
    try:
        image = Image.open(uploaded_file)
        image = ImageOps.exif_transpose(image)
        w, h = image.size
        if h > w: image = image.rotate(90, expand=True)
        if image.mode != "RGB": image = image.convert("RGB")
        
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.8)
        enhancer_sharp = ImageEnhance.Sharpness(image)
        image = enhancer_sharp.enhance(2.5)
        
        image.thumbnail((1400, 1400))
        return image
    except Exception as e:
        st.error(f"Error imagen: {e}")
        return None

def encode_image(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=95)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# --- 5. LÓGICA DE EXTRACCIÓN ---
def clean_text(text):
    if not text: return ""
    text = str(text).strip().upper().replace('"', '').replace("'", "")
    if "CEDULA" in text or "CIUDADANIA" in text or "REPUBLICA" in text: return ""
    if text in ["MUJER", "HOMBRE", "DONANTE", "SEXO", "SOLTERO", "CASADO"]: return ""
    return text

def correct_dactilar_ocr(text_raw):
    if not text_raw: return ""
    clean = text_raw.upper().replace(" ", "").replace("-", "").replace(".", "").replace(",", "")
    if len(clean) != 10:
        match = re.search(r'[A-Z0-9]{10}', clean)
        if match: clean = match.group(0)
        else: return text_raw 
    num_to_let = {'0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B', 'H': 'I'} 
    let_to_num = {'O': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'B': '8'}
    corrected = list(clean)
    for i in range(10):
        char = corrected[i]
        if i in [0, 5]: 
            if char.isdigit(): corrected[i] = num_to_let.get(char, char)
            elif char == 'H': corrected[i] = 'I'
        else: 
            if char.isalpha(): corrected[i] = let_to_num.get(char, char)
    return "".join(corrected)

def call_mistral(front_img, back_img):
    try:
        f_b64 = encode_image(front_img)
        b_b64 = encode_image(back_img)
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        prompt = """
        Eres un experto en identificación. Analiza las cédulas de Ecuador.
        INSTRUCCIONES ESPECÍFICAS:
        1. EXTRANJEROS: Si dice "CHILENA", "COLOMBIANA", etc -> es_extranjero = "SI". SOLO si dice "ECUATORIANA" -> "NO".
        2. CÉDULA ANTIGUA: Busca "APELLIDOS Y NOMBRES". Primera línea debajo son APELLIDOS, segunda son NOMBRES.
        3. CÉDULA NUEVA: Busca "APELLIDOS" y "NOMBRES" y el texto al lado.
        4. DACTILAR: Formato Letra, 4 números, Letra, 4 números.
        5. UBICACIÓN: Extranjeros usa "Lugar de Emisión", Ecuatorianos "Lugar de Nacimiento".
        Responde JSON: {"cedula": "...", "codigo_dactilar": "...", "apellidos": "...", "nombres": "...", "provincia": "...", "ciudad": "...", "es_extranjero": "..."}
        """
        payload = {
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": f"data:image/jpeg;base64,{f_b64}"}, {"type": "image_url", "image_url": f"data:image/jpeg;base64,{b_b64}"}]}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0
        }
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content']
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                loc_txt = (str(data.get("ciudad")) + str(data.get("provincia"))).upper()
                if "IQUIQUE" in loc_txt or "CHILE" in loc_txt: data["es_extranjero"] = "SI"
                raw_ciudad = clean_text(data.get("ciudad", ""))
                raw_ciudad = re.sub(r'\d{2}\s+[A-Z]{3}\s+\d{4}', '', raw_ciudad).strip()
                raw_prov = clean_text(data.get("provincia", ""))
                if raw_prov in CIUDADES_PROVINCIAS:
                    raw_ciudad = raw_prov; raw_prov = CIUDADES_PROVINCIAS[raw_prov]
                elif raw_ciudad in CIUDADES_PROVINCIAS:
                    raw_prov = CIUDADES_PROVINCIAS[raw_ciudad]
                data["ciudad"] = raw_ciudad
                data["provincia"] = raw_prov
                dac_raw = str(data.get("codigo_dactilar", ""))
                if len(dac_raw) > 15:
                      match_inner = re.search(r'[A-Z0-9]{10}', str(content))
                      dac_raw = match_inner.group(0) if match_inner else ""
                data["codigo_dactilar"] = correct_dactilar_ocr(dac_raw)
                ced_raw = str(data.get("cedula", "")).replace("-", "").strip()
                if not ced_raw or len(ced_raw) < 9:
                    match_ced = re.search(r'\b\d{9,10}\b', str(content))
                    if match_ced: ced_raw = match_ced.group(0)
                data["cedula"] = ced_raw
                ape = str(data.get("apellidos", "")).upper()
                if "CIUDADANIA" in ape: 
                    ape = ape.replace("CEDULA", "").replace("DE", "").replace("CIUDADANIA", "").strip()
                data["apellidos"] = ape
                return data
            return None
        return None
    except Exception as e:
        st.error(f"Error de conexión: {str(e)}")
        return None

# --- FUNCIONES DE DESCARGA EN MEMORIA (WEB) ---
def convert_df_to_excel(data):
    # Crea un Excel en memoria RAM, no en disco
    output = io.BytesIO()
    df = pd.DataFrame([data])
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Datos')
    return output.getvalue()

def convert_img_to_bytes(img):
    # Convierte imagen a bytes para descarga
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

# --- 6. INTERFAZ ---
st.title("🆔 Sistema de Firmas (Web Cloud)")
st.caption("Los archivos se descargarán a la carpeta que tú elijas en tu navegador.")

col1, col2 = st.columns(2)
with col1:
    f_in = st.file_uploader("Anverso", type=['jpg','png','jpeg'], key="f")
    if f_in: 
        st.session_state.proc_front = process_image_upload(f_in)
        if st.session_state.proc_front: st.image(st.session_state.proc_front, width=250, caption="Anverso")

with col2:
    b_in = st.file_uploader("Reverso", type=['jpg','png','jpeg'], key="b")
    if b_in: 
        st.session_state.proc_back = process_image_upload(b_in)
        if st.session_state.proc_back: st.image(st.session_state.proc_back, width=250, caption="Reverso")

st.markdown("---")
c_dat1, c_dat2, c_dat3 = st.columns(3)
email = c_dat1.text_input("Correo", key="mail")
phone = c_dat2.text_input("Celular", key="phone")
vig = c_dat3.selectbox("Vigencia", ["15 días", "30 días", "1 año", "2 años", "3 años", "4 años", "5 años"])

if st.session_state.step == 1:
    if st.button("🚀 PROCESAR DATOS", type="primary"):
        if st.session_state.proc_front and st.session_state.proc_back and email:
            with st.spinner("Conectando con IA..."):
                res = call_mistral(st.session_state.proc_front, st.session_state.proc_back)
                if res:
                    st.session_state.data = {
                        "Cédula": clean_text(res.get("cedula")),
                        "Código Dactilar": clean_text(res.get("codigo_dactilar")),
                        "Apellidos": clean_text(res.get("apellidos")),
                        "Nombres": clean_text(res.get("nombres")),
                        "Provincia": clean_text(res.get("provincia")),
                        "Ciudad": clean_text(res.get("ciudad")),
                        "Es Extranjero": clean_text(res.get("es_extranjero")),
                        "Correo Electrónico": email,
                        "Celular": phone,
                        "Tiempo Vigencia": vig
                    }
                    st.session_state.step = 2
                    st.rerun()
        else:
            st.warning("Faltan imágenes o correo.")

elif st.session_state.step == 2:
    st.subheader("✅ Verificación")
    d = st.session_state.data
    with st.form("val_form"):
        colA, colB = st.columns(2)
        v_ced = colA.text_input("Cédula", d['Cédula'])
        v_dac = colB.text_input("Código Dactilar", d['Código Dactilar'])
        
        colC, colD = st.columns(2)
        v_ape = colC.text_input("Apellidos", d['Apellidos'])
        v_nom = colD.text_input("Nombres", d['Nombres'])
        
        colE, colF, colG = st.columns(3)
        v_prov = colE.text_input("Provincia", d['Provincia'])
        v_ciu = colF.text_input("Ciudad", d['Ciudad'])
        idx_ext = 0 if "SI" in str(d['Es Extranjero']).upper() else 1
        v_ext = colG.selectbox("Es Extranjero", ["SI", "NO"], index=idx_ext)
        
        colH, colI, colJ = st.columns(3)
        v_mail = colH.text_input("Correo", d['Correo Electrónico'])
        v_cel = colI.text_input("Celular", d['Celular'])
        try: idx = ["15 días", "30 días", "1 año", "2 años", "3 años", "4 años", "5 años"].index(d['Tiempo Vigencia'])
        except: idx = 2
        v_vig = colJ.selectbox("Vigencia", ["15 días", "30 días", "1 año", "2 años", "3 años", "4 años", "5 años"], index=idx)
        
        saved = st.form_submit_button("✅ CONFIRMAR DATOS")
        if saved:
            st.session_state.data.update({
                "Cédula": v_ced, "Código Dactilar": v_dac, "Apellidos": v_ape.upper(), "Nombres": v_nom.upper(),
                "Provincia": v_prov.upper(), "Ciudad": v_ciu.upper(), "Es Extranjero": v_ext,
                "Correo Electrónico": v_mail, "Celular": v_cel, "Tiempo Vigencia": v_vig
            })
            st.success("Datos Confirmados. Descarga tus archivos abajo 👇")

    # --- SECCIÓN DE DESCARGA (SIN ZIP) ---
    if st.session_state.data:
        st.markdown("### 📥 Descargar Archivos")
        st.info("💡 Tip: Para elegir la carpeta, configura tu navegador para 'Preguntar dónde guardar cada archivo antes de descargar'.")
        
        safe_name = re.sub(r'[^A-Z0-9_]', '', f"{st.session_state.data['Apellidos']}_{st.session_state.data['Nombres']}".replace(" ", "_"))
        
        # 1. Preparar Excel
        excel_data = convert_df_to_excel(st.session_state.data)
        
        # 2. Preparar Imágenes
        img_front_bytes = convert_img_to_bytes(st.session_state.proc_front)
        img_back_bytes = convert_img_to_bytes(st.session_state.proc_back)
        
        c_down1, c_down2, c_down3 = st.columns(3)
        
        with c_down1:
            st.download_button(
                label="📄 Descargar Excel",
                data=excel_data,
                file_name=f"Datos_{safe_name}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="down_excel"
            )
        
        with c_down2:
            st.download_button(
                label="📷 Descargar Anverso",
                data=img_front_bytes,
                file_name=f"Anverso_{safe_name}.jpg",
                mime="image/jpeg",
                key="down_front"
            )
            
        with c_down3:
            st.download_button(
                label="📷 Descargar Reverso",
                data=img_back_bytes,
                file_name=f"Reverso_{safe_name}.jpg",
                mime="image/jpeg",
                key="down_back"
            )

    if st.button("🔄 Reiniciar Proceso"):
        st.session_state.clear()
        st.rerun()