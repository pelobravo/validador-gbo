# app.py - Con campos para saldos iniciales manuales - VERSIÓN COMPLETA CON CIERRE DIARIO Y VISUALIZACIÓN DE ARCHIVOS
# 🔥 MODIFICADO: Identificación y visualización de OT Nuevas en Cuentas por Pagar
# 🤖 INTEGRACIÓN CON DEEPSEEK API

import streamlit as st
import pandas as pd
from datetime import datetime
import os
import base64
from PIL import Image
import io
import numpy as np
import re
import matplotlib.pyplot as plt
import sqlite3
import warnings
from openai import OpenAI  # <--- NUEVO: Para DeepSeek API

# Importar módulos del sistema
from config import USUARIOS, validar_carpetas
from database import Database
from logger import Logger
from procesadores import ProcesadorArchivos
from api_bcv import obtener_tasa_bcv
from motor_auditoria import ejecutar_auditoria_inteligente, registrar_excepcion, cargar_ultimo_cierre

# ============================================================
# 🤖 FUNCIÓN PARA CONSULTAR DEEPSEEK API (NUEVO)
# ============================================================
def consultar_deepseek(pregunta, contexto=""):
    """
    Consulta la API de DeepSeek usando la clave desde Secrets de Streamlit Cloud.
    """
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        
        if not api_key:
            return "❌ Error: La clave API no está configurada en Secrets de Streamlit Cloud."
        
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": f"Eres un asistente experto en validación de trazabilidad financiera y contabilidad. Contexto: {contexto}"},
                {"role": "user", "content": pregunta}
            ],
            temperature=0.3
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        return f"❌ Error al consultar DeepSeek: {str(e)}"

# ============================================================
# FIN FUNCIÓN DEEPSEEK
# ============================================================

# ============================================================
# 🔥 FUNCIÓN PARA BUSCAR CANDIDATOS POR MONTO (NUEVA)
# ============================================================
def buscar_candidatos_por_monto(df, monto_buscar, origen):
    """
    Busca en un DataFrame filas que tengan un monto cercano al valor buscado.
    Retorna una lista de strings con la descripción de cada candidato.
    """
    candidatos = []
    if df is None or df.empty:
        return candidatos
    
    monto_buscar = abs(monto_buscar)  # Usamos el valor absoluto para la búsqueda
    
    try:
        # Identificar columnas numéricas que podrían contener montos
        columnas_numericas = df.select_dtypes(include=['number']).columns.tolist()
        
        # Si no hay columnas numéricas, intentar convertir algunas columnas
        if not columnas_numericas:
            for col in df.columns:
                try:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    if df[col].notna().sum() > 0:
                        columnas_numericas.append(col)
                except:
                    pass
        
        # Buscar en cada columna numérica
        for col in columnas_numericas:
            # Buscar valores cercanos al monto (con un margen del 5%)
            margen = max(0.01, abs(monto_buscar) * 0.05)
            mascara = (df[col] >= monto_buscar - margen) & (df[col] <= monto_buscar + margen)
            filas_encontradas = df[mascara]
            
            if not filas_encontradas.empty:
                for idx, row in filas_encontradas.iterrows():
                    # Construir una descripción de la fila
                    desc = f"[{origen}] "
                    # Tomar las primeras 3 columnas no numéricas como identificadores
                    cols_no_numericas = df.select_dtypes(exclude=['number']).columns.tolist()
                    for c in cols_no_numericas[:3]:
                        if c in row and pd.notna(row[c]):
                            desc += f"{c}: {str(row[c])} | "
                    desc += f"Monto: {formato_venezolano(row[col])}"
                    candidatos.append(desc)
                    
                    # Limitar a 3 candidatos por columna para no saturar
                    if len(candidatos) >= 5:
                        return candidatos[:5]
        
        # Si no se encontraron candidatos, buscar por cualquier columna que parezca tener montos
        if not candidatos:
            for col in df.columns:
                col_lower = str(col).lower()
                if any(palabra in col_lower for palabra in ['monto', 'total', 'importe', 'saldo', 'valor', 'neto', 'precio']):
                    try:
                        valores = df[col].dropna()
                        if not valores.empty:
                            # Buscar el valor más cercano
                            mejor_match = None
                            mejor_diff = float('inf')
                            for val in valores:
                                try:
                                    val_num = float(val)
                                    diff = abs(abs(val_num) - monto_buscar)
                                    if diff < mejor_diff and diff < max(0.01, monto_buscar * 0.05):
                                        mejor_diff = diff
                                        mejor_match = val_num
                                except:
                                    pass
                            if mejor_match is not None:
                                # Encontrar la fila con ese valor
                                fila = df[df[col] == mejor_match]
                                if not fila.empty:
                                    row = fila.iloc[0]
                                    desc = f"[{origen}] "
                                    cols_no_numericas = df.select_dtypes(exclude=['number']).columns.tolist()
                                    for c in cols_no_numericas[:2]:
                                        if c in row and pd.notna(row[c]):
                                            desc += f"{c}: {str(row[c])} | "
                                    desc += f"Monto: {formato_venezolano(mejor_match)} (aprox.)"
                                    candidatos.append(desc)
                    except:
                        pass
                    
    except Exception as e:
        print(f"Error en buscar_candidatos_por_monto: {e}")
    
    return candidatos[:5]  # Máximo 5 candidatos

# ============================================================
# FIN FUNCIÓN BUSCAR CANDIDATOS
# ============================================================

# Inicializar componentes
validar_carpetas()
db = Database()
logger = Logger()

# Inicializar variables de archivos en None para evitar NameError
archivo_facturacion = None
archivo_cobranzas = None
archivo_egresos = None
archivo_estado_cuenta = None
archivo_recepciones = None
archivo_notas_credito_cliente = None
archivo_notas_credito_proveedor = None
archivo_costo_facturacion = None
archivo_cxc_reportado = None
archivo_cxp_reportado = None
archivo_cxp_anterior = None
archivo_inventario_reportado = None
archivo_inventario_anterior = None
archivo_tb = None
fecha_procesar = datetime.now()

# 🔥 TEMPORAL: Botón para LIMPIAR TODOS los saldos
if st.button("🗑️ LIMPIAR SALDOS"):
    db.limpiar_saldos()
    st.success("✅ Tabla saldos_diarios limpiada correctamente")

st.set_page_config(
    page_title="Validador de Trazabilidad Diaria",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# FUNCIÓN DE INTEGRACIÓN DE AUDITORÍA (MÓDULO VISUAL)
# ============================================================
def renderizar_modulo_auditoria(fallas_detectadas, df_consolidado, hay_errores, fecha_cierre_str, analista_default="Analista"):
    st.markdown(f"### 🤖 Conciliación de Trazabilidad y Aprendizaje ({fecha_cierre_str})")
    
    # KPIs Financieros
    from motor_auditoria import calcular_kpis
    kpis = calcular_kpis(df_consolidado)
    m1, m2, m3 = st.columns(3)
    m1.metric("💵 Tasa BCV", f"{kpis['tasa_bcv']:.2f} Bs/$")
    m2.metric("📊 Total Balance (Bs)", f"{kpis['total_ves']:,.2f} VES")
    m3.metric("📈 Consolidado (USD)", f"${kpis['total_usd']:,.2f}")
    
    # Separar alertas
    fallas_activas = [f for f in fallas_detectadas if f['tipo'] in ['ROJA', 'AMARILLA', 'NARANJA']]
    fallas_corregidas = [f for f in fallas_detectadas if f['tipo'] == 'VERDE_CORREGIDO']
    
    if not hay_errores:
        st.success("✅ ¡Auditoría al día! No se registran inconsistencias activas en el balance.")
        if fallas_corregidas:
            st.info(f"💡 Se aplicaron {len(fallas_corregidas)} auto-correcciones basadas en el historial.")
    else:
        st.error(f"⚠️ Balance descuadrado: {len(fallas_activas)} discrepancias activas requieren conciliación.")

    # Campo de analista para registrar excepciones
    analista_activo = st.text_input(
        "👤 Analista Operador actual (para autorizar excepciones):", 
        value=st.session_state.get("analista_operador", analista_default),
        key=f"analista_op_input_{fecha_cierre_str.replace(' ', '_').replace(':', '_')}"
    )
    st.session_state["analista_operador"] = analista_activo

    # Ordenar y renderizar cada alerta
    alertas_ordenadas = sorted(
        fallas_detectadas, 
        key=lambda x: {'ROJA': 0, 'NARANJA': 1, 'AMARILLA': 2, 'VERDE_CORREGIDO': 3}.get(x['tipo'], 4)
    )
    
    for falla in alertas_ordenadas:
        tipo = falla['tipo']
        ref = falla['referencia']
        
        if tipo == 'ROJA':
            st.error(f"🔴 **ALERTA ROJA (Falta en Sistema)** | Ref: {ref}")
        elif tipo == 'NARANJA':
            st.warning(f"🟠 **ALERTA NARANJA (Diferencia de Monto)** | Ref: {ref} (Dif: {falla['diferencia']:.2f})")
        elif tipo == 'AMARILLA':
            st.warning(f"🟡 **ALERTA AMARILLA (Transacción en Tránsito)** | Ref: {ref}")
        elif tipo == 'VERDE_CORREGIDO':
            st.success(f"🟢 **Movimiento AUTO-CORREGIDO** | Ref: {ref}")
            
        with st.expander(f"Detalle de Auditoría - Ref {ref}", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Módulo Origen:** {falla['origen']}")
                st.markdown(f"**Monto Banco:** {falla['monto_banco']:.2f}")
            with col2:
                st.markdown(f"**Monto Sistema:** {falla['monto_sistema']:.2f}")
                st.markdown(f"**Fecha Banco:** {falla['fecha_banco']}")
            
            st.markdown(f"💡 **Diagnóstico:** {falla['causa']}")
            
            if tipo in ['ROJA', 'AMARILLA', 'NARANJA']:
                st.markdown("---")
                monto_a_guardar = falla['monto_banco'] if tipo in ['ROJA', 'NARANJA'] else falla['monto_sistema']
                modulo_banco = falla['origen']
                
                if st.button("💾 Validar y Recordar esta Regla", key=f"btn_exc_{ref}_{monto_a_guardar}_{modulo_banco}_{fecha_cierre_str.replace(' ', '_').replace(':', '_')}"):
                    if not analista_activo or analista_activo == "Analista":
                        st.warning("⚠️ Escriba su nombre de Analista arriba antes de validar la regla.")
                    else:
                        exito = registrar_excepcion(
                            referencia=ref, monto=monto_a_guardar, banco=modulo_banco,
                            tipo_excepcion=tipo, usuario_analista=analista_activo
                        )
                        if exito:
                            st.toast(f"✅ Excepción registrada. Recargando...")
                            import time
                            time.sleep(0.6)
                            st.rerun()
            else:
                st.markdown(f"🛠️ **Acción Recomendada:** *{falla['accion']}*")

    st.markdown("### 📊 Reporte Consolidado de Discrepancias")
    columnas_visibles = ['referencia', 'fecha_banco', 'monto_banco', 'fecha_sistema', 'monto_sistema', 'origen_sistema', 'estatus', 'alerta', 'diferencia']
    columnas_render = [c for c in columnas_visibles if c in df_consolidado.columns]
    
    st.dataframe(
        df_consolidado[columnas_render].style.map(
            lambda val: 'background-color: #ffcccc' if val == 'ROJA' else 
                        ('background-color: #ffe6cc' if val == 'NARANJA' else 
                         ('background-color: #fffae6' if val == 'AMARILLA' else 
                          ('background-color: #e6ffec' if val == 'VERDE_CORREGIDO' else ''))),
            subset=['alerta']
        ),
        use_container_width=True
    )

# ============================================================
# FUNCIÓN PARA FORMATEAR NÚMEROS EN FORMATO VENEZOLANO
# ============================================================
def formato_venezolano(valor):
    """
    Formatea un número en formato venezolano:
    - Separador de miles: .
    - Separador decimal: ,
    
    Ejemplo: 129922542.79 → 129.922.542,79
    """
    if valor is None:
        return "0,00"
    try:
        if isinstance(valor, str):
            valor = float(valor.replace(',', '').replace('.', '').replace(' ', ''))
        return f"{float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return "0,00"

def formato_venezolano_desde_str(valor_str):
    """
    Convierte un string con formato venezolano a número para cálculos
    """
    if valor_str is None or valor_str == "-" or valor_str == "":
        return 0
    try:
        if isinstance(valor_str, str):
            limpio = valor_str.replace('.', '').replace(',', '.')
            return float(limpio)
        return float(valor_str)
    except (ValueError, TypeError):
        return 0

# ============================================================
# FUNCIÓN PARA MOSTRAR ARCHIVO CON FORMATO
# ============================================================
def mostrar_archivo_con_formato(df, nombre_archivo, titulo):
    """
    Muestra un DataFrame con formato mejorado y estadísticas básicas
    """
    if df is None or df.empty:
        st.warning(f"⚠️ El archivo {nombre_archivo} está vacío")
        return
    
    # 🔥 CONVERTIR TODAS LAS FECHAS A STRING PARA EVITAR ERRORES DE PYARROW
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        elif df[col].dtype == 'object':
            try:
                df[col] = df[col].apply(lambda x: str(x) if not pd.isna(x) else x)
            except:
                pass
    
    with st.expander(f"📄 {titulo} - {nombre_archivo}", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📊 Filas", len(df))
        with col2:
            st.metric("📋 Columnas", len(df.columns))
        with col3:
            columnas_numericas = df.select_dtypes(include=['number']).columns
            if len(columnas_numericas) > 0:
                total = df[columnas_numericas[0]].sum()
                st.metric("💰 Total", formato_venezolano(total))
        
        st.dataframe(
            df.style.background_gradient(subset=columnas_numericas, cmap='Blues', low=0.1, high=0.9),
            width='stretch',
            height=400
        )
        
        st.caption(f"📌 Columnas: {', '.join(df.columns)}")

# ============================================================
# FUNCIÓN HELPER PARA VALORES SEGUROS
# ============================================================
def safe_number(value, default=0):
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_string(value, default=""):
    if value is None:
        return default
    return str(value)

# ============================================================
# CSS PERSONALIZADO - DISEÑO CORPORATIVO MODERNO
# ============================================================
st.markdown("""
<style>
    /* ==================== IMPORTAR FUENTES ==================== */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    @import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css');
    
    /* ==================== RESET Y BASE ==================== */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background: #f0f4f8;
    }
    
    /* ==================== HEADER CORPORATIVO ==================== */
    .corporate-header {
        background: linear-gradient(135deg, #0a1628 0%, #1a3a5c 50%, #2a4a6c 100%);
        padding: 20px 30px;
        border-radius: 16px;
        margin-bottom: 25px;
        box-shadow: 0 8px 32px rgba(10, 22, 40, 0.3);
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        border: 1px solid rgba(201, 168, 76, 0.15);
    }
    
    .corporate-header .brand {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    
    .corporate-header .brand .logo {
        width: 48px;
        height: 48px;
        background: linear-gradient(135deg, #c9a84c, #e8c86a);
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        font-weight: 900;
        color: #0a1628;
        box-shadow: 0 4px 12px rgba(201, 168, 76, 0.4);
    }
    
    .corporate-header .brand .title {
        color: white;
        font-size: 1.4rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    
    .corporate-header .brand .subtitle {
        color: rgba(255,255,255,0.6);
        font-size: 0.75rem;
        font-weight: 400;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }
    
    .corporate-header .status-bar {
        display: flex;
        align-items: center;
        gap: 20px;
        color: rgba(255,255,255,0.8);
        font-size: 0.85rem;
    }
    
    .corporate-header .status-bar .status-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 6px;
    }
    
    .corporate-header .status-bar .status-dot.online {
        background: #2ecc71;
        box-shadow: 0 0 12px rgba(46, 204, 113, 0.5);
        animation: pulse-dot 2s infinite;
    }
    
    @keyframes pulse-dot {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.6; transform: scale(0.9); }
    }
    
    .corporate-header .status-bar .user-info {
        background: rgba(255,255,255,0.08);
        padding: 6px 16px;
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,0.06);
        font-size: 0.8rem;
    }
    
    .corporate-header .status-bar .user-info i {
        color: #c9a84c;
        margin-right: 6px;
    }
    
    /* ==================== SIDEBAR CORPORATIVA ==================== */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a1628 0%, #162a44 50%, #1a3a5c 100%);
        border-right: 1px solid rgba(201, 168, 76, 0.1);
    }
    
    [data-testid="stSidebar"] * {
        color: #e8edf2 !important;
    }
    
    [data-testid="stSidebar"] .stMarkdown h1,
    [data-testid="stSidebar"] .stMarkdown h2,
    [data-testid="stSidebar"] .stMarkdown h3 {
        color: white !important;
    }
    
    [data-testid="stSidebar"] .stMarkdown h3 {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        opacity: 0.6;
        margin-top: 20px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        padding-bottom: 8px;
    }
    
    [data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #c9a84c, #e8c86a);
        color: #0a1628 !important;
        font-weight: 600;
        border: none;
        border-radius: 10px;
        padding: 10px 16px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(201, 168, 76, 0.2);
    }
    
    [data-testid="stSidebar"] .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(201, 168, 76, 0.35);
        background: linear-gradient(135deg, #d4b85a, #f0d878);
    }
    
    /* ============================================================
       🔥 FILE UPLOADER - VISIBILIDAD MEJORADA
       ============================================================ */
    
    /* Forzar color blanco en TODOS los textos del file uploader */
    .stFileUploader label,
    .stFileUploader label span,
    .stFileUploader label div,
    .stFileUploader label p,
    .stFileUploader .stMarkdown,
    .stFileUploader .stMarkdown p,
    .stFileUploader .stMarkdown small,
    .stFileUploader .stMarkdown span,
    .stFileUploader [data-testid="stFileUploaderDropzone"] p,
    .stFileUploader [data-testid="stFileUploaderDropzone"] span,
    .stFileUploader [data-testid="stFileUploaderDropzone"] div {
        color: #ffffff !important;
        opacity: 1 !important;
    }
    
    /* Contenedor del file uploader */
    .stFileUploader {
        background: rgba(255, 255, 255, 0.06) !important;
        border-radius: 10px !important;
        padding: 8px 12px !important;
        margin-bottom: 4px !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        transition: all 0.3s ease !important;
    }
    
    .stFileUploader:hover {
        background: rgba(255, 255, 255, 0.10) !important;
        border-color: rgba(201, 168, 76, 0.2) !important;
    }
    
    /* Label del file uploader - TEXTO BLANCO VISIBLE */
    .stFileUploader > label {
        color: #ffffff !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        opacity: 1 !important;
        display: block !important;
        margin-bottom: 4px !important;
    }
    
    .stFileUploader > label .stMarkdown {
        color: #ffffff !important;
    }
    
    .stFileUploader > label span {
        color: #ffffff !important;
    }
    
    /* Texto de ayuda del file uploader */
    .stFileUploader .stMarkdown p {
        color: rgba(255, 255, 255, 0.6) !important;
        font-size: 0.7rem !important;
    }
    
    .stFileUploader .stMarkdown small {
        color: rgba(255, 255, 255, 0.4) !important;
    }
    
    /* Área de drop del file uploader */
    .stFileUploader [data-testid="stFileUploaderDropzone"] {
        background: rgba(255, 255, 255, 0.04) !important;
        border: 1px dashed rgba(255, 255, 255, 0.12) !important;
        border-radius: 8px !important;
        padding: 10px !important;
    }
    
    .stFileUploader [data-testid="stFileUploaderDropzone"]:hover {
        background: rgba(255, 255, 255, 0.08) !important;
        border-color: rgba(201, 168, 76, 0.25) !important;
    }
    
    /* Texto dentro del área de drop */
    .stFileUploader [data-testid="stFileUploaderDropzone"] p {
        color: rgba(255, 255, 255, 0.5) !important;
        font-size: 0.8rem !important;
    }
    
    .stFileUploader [data-testid="stFileUploaderDropzone"] .stMarkdown {
        color: rgba(255, 255, 255, 0.5) !important;
    }
    
    /* Badge de archivos cargados */
    .stFileUploader [data-testid="stFileUploaderFile"] {
        background: rgba(46, 204, 113, 0.12) !important;
        border: 1px solid rgba(46, 204, 113, 0.2) !important;
        border-radius: 6px !important;
        padding: 6px 10px !important;
    }
    
    .stFileUploader [data-testid="stFileUploaderFile"] .stMarkdown {
        color: #2ecc71 !important;
    }
    
    .stFileUploader [data-testid="stFileUploaderFile"] button {
        color: #e74c3c !important;
    }
    
    /* Forzar en todos los elementos del uploader */
    .stFileUploader * {
        color: #ffffff !important;
    }
    
    .stFileUploader .stMarkdown * {
        color: #ffffff !important;
    }
    
    /* ============================================================
       FIN FILE UPLOADER
       ============================================================ */
    
    [data-testid="stSidebar"] .stDateInput label {
        color: rgba(255,255,255,0.7) !important;
    }
    
    /* ==================== KPIS CORPORATIVOS ==================== */
    .kpi-card {
        border-radius: 16px;
        padding: 22px 18px;
        text-align: center;
        color: white;
        box-shadow: 0 8px 25px -5px rgba(0,0,0,0.15);
        border: 1px solid rgba(255,255,255,0.08);
        cursor: pointer;
        transition: all 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    
    .kpi-card::before {
        content: '';
        position: absolute;
        top: -50%;
        right: -50%;
        width: 100%;
        height: 100%;
        background: rgba(255,255,255,0.03);
        border-radius: 50%;
        transform: rotate(25deg);
        pointer-events: none;
    }
    
    .kpi-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 12px 35px -5px rgba(0,0,0,0.25);
    }
    
    .kpi-card .label {
        font-size: 0.75rem;
        opacity: 0.85;
        letter-spacing: 1px;
        font-weight: 600;
        text-transform: uppercase;
    }
    
    .kpi-card .value {
        font-size: 2rem;
        font-weight: 800;
        margin-top: 8px;
        letter-spacing: -0.5px;
        font-family: 'Inter', monospace;
    }
    
    .kpi-card .sub-label {
        font-size: 0.65rem;
        opacity: 0.6;
        margin-top: 6px;
        font-weight: 400;
    }
    
    .kpi-card .icon-bg {
        position: absolute;
        right: 12px;
        bottom: 12px;
        font-size: 3rem;
        opacity: 0.08;
        pointer-events: none;
    }
    
    /* KPI - Activos (Verde) */
    .kpi-activos {
        background: linear-gradient(135deg, #0f3d2e 0%, #1a6b4a 100%);
        border: 1px solid rgba(46, 204, 113, 0.2);
    }
    .kpi-activos .value { color: #2ecc71; }
    
    /* KPI - Pasivos (Rojo) */
    .kpi-pasivos {
        background: linear-gradient(135deg, #3d1a1a 0%, #6b2a2a 100%);
        border: 1px solid rgba(231, 76, 60, 0.2);
    }
    .kpi-pasivos .value { color: #e74c3c; }
    
    /* KPI - Capital (Dorado) */
    .kpi-capital {
        background: linear-gradient(135deg, #2a1f0a 0%, #4a3a1a 100%);
        border: 1px solid rgba(201, 168, 76, 0.2);
    }
    .kpi-capital .value { color: #c9a84c; }
    
    /* KPI - Capital Positivo */
    .kpi-capital-positivo {
        background: linear-gradient(135deg, #0f3d2e 0%, #1a6b4a 100%);
        border: 1px solid rgba(46, 204, 113, 0.3);
    }
    .kpi-capital-positivo .value { color: #2ecc71; }
    
    /* KPI - Capital Negativo */
    .kpi-capital-negativo {
        background: linear-gradient(135deg, #3d1a1a 0%, #6b2a2a 100%);
        border: 1px solid rgba(231, 76, 60, 0.3);
    }
    .kpi-capital-negativo .value { color: #e74c3c; }
    
    /* KPI - Iniciales (Saldos del día anterior) */
    .kpi-inicial {
        border-radius: 14px;
        padding: 16px 12px;
        text-align: center;
        color: white;
        box-shadow: 0 4px 15px -3px rgba(0,0,0,0.12);
        border: 1px solid rgba(255,255,255,0.06);
        transition: all 0.3s ease;
        height: 100%;
        min-height: 100px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    
    .kpi-inicial:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px -3px rgba(0,0,0,0.2);
    }
    
    .kpi-inicial .icon {
        font-size: 1.2rem;
        margin-bottom: 4px;
    }
    
    .kpi-inicial .label {
        font-size: 0.7rem;
        opacity: 0.8;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .kpi-inicial .value {
        font-size: 1.3rem;
        font-weight: 700;
        margin-top: 4px;
        font-family: 'Inter', monospace;
    }
    
    .kpi-inicial-verde {
        background: linear-gradient(135deg, #0f3d2e 0%, #1a6b4a 100%);
        border: 1px solid rgba(46, 204, 113, 0.15);
    }
    .kpi-inicial-verde .value { color: #2ecc71; }
    
    .kpi-inicial-azul {
        background: linear-gradient(135deg, #0a1a3a 0%, #1a3a6b 100%);
        border: 1px solid rgba(52, 152, 219, 0.15);
    }
    .kpi-inicial-azul .value { color: #3498db; }
    
    .kpi-inicial-naranja {
        background: linear-gradient(135deg, #3d2a0a 0%, #6b4a1a 100%);
        border: 1px solid rgba(243, 156, 18, 0.15);
    }
    .kpi-inicial-naranja .value { color: #f39c12; }
    
    .kpi-inicial-rojo {
        background: linear-gradient(135deg, #3d1a1a 0%, #6b2a2a 100%);
        border: 1px solid rgba(231, 76, 60, 0.15);
    }
    .kpi-inicial-rojo .value { color: #e74c3c; }
    
    .kpi-inicial-morado {
        background: linear-gradient(135deg, #2a0a3a 0%, #4a1a6b 100%);
        border: 1px solid rgba(155, 89, 182, 0.15);
    }
    .kpi-inicial-morado .value { color: #af7ac5; }
    
    /* ==================== BOTONES CORPORATIVOS ==================== */
    .stButton > button {
        border-radius: 10px !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
        font-size: 0.85rem !important;
        padding: 10px 20px !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 25px rgba(0,0,0,0.15) !important;
    }
    
    /* ==================== TABLAS ==================== */
    .dataframe {
        border-radius: 12px !important;
        overflow: hidden !important;
        box-shadow: 0 4px 20px rgba(0,0,0,0.04) !important;
    }
    
    .dataframe th {
        background: linear-gradient(135deg, #0a1628 0%, #1a3a5c 100%) !important;
        color: white !important;
        font-weight: 600 !important;
        padding: 14px !important;
        font-size: 0.8rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* ==================== EXPANDERS ==================== */
    .streamlit-expanderHeader {
        font-weight: 600 !important;
        color: #1a3a5c !important;
        background: rgba(26, 58, 92, 0.04) !important;
        border-radius: 10px !important;
        border: 1px solid rgba(26, 58, 92, 0.06) !important;
    }
    
    .streamlit-expanderHeader:hover {
        background: rgba(26, 58, 92, 0.08) !important;
    }
    
    /* ==================== POPOVERS ==================== */
    div[data-testid="stPopover"] {
        background: #ffffff !important;
        border-radius: 16px !important;
        border: 1px solid rgba(26, 58, 92, 0.1) !important;
        box-shadow: 0 20px 60px rgba(0,0,0,0.1) !important;
        padding: 20px !important;
    }
    
    /* ==================== MÉTRICAS ==================== */
    [data-testid="stMetric"] {
        background: rgba(255,255,255,0.05) !important;
        border-radius: 12px !important;
        padding: 16px !important;
        border: 1px solid rgba(255,255,255,0.04) !important;
    }
    
    [data-testid="stMetric"] label {
        color: rgba(255,255,255,0.7) !important;
        font-weight: 500 !important;
    }
    
    [data-testid="stMetric"] .stMetricValue {
        color: white !important;
        font-weight: 700 !important;
    }
    
    /* ==================== SIDEBAR SECTION TITLES ==================== */
    .sidebar-section-title {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: rgba(255,255,255,0.4);
        font-weight: 600;
        margin-top: 25px;
        margin-bottom: 10px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        padding-bottom: 8px;
    }
    
    /* ==================== DIVISORES ==================== */
    .divider-light {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(201, 168, 76, 0.15), transparent);
        margin: 20px 0;
    }
    
    /* ==================== TOOLTIP ==================== */
    .tooltip-hint {
        font-size: 0.7rem;
        color: rgba(255,255,255,0.3);
        font-style: italic;
        text-align: center;
        margin-top: 4px;
    }

    /* ==================== KPIs DASHBOARD GENERAL ==================== */
    .dashboard-kpi-card {
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        border: 1px solid rgba(0,0,0,0.05);
        margin-bottom: 20px;
        transition: all 0.3s ease;
    }
    .dashboard-kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.08);
    }
    .dashboard-kpi-title {
        font-size: 0.8rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    .dashboard-kpi-value {
        font-size: 1.8rem;
        font-weight: 800;
    }
    .dashboard-kpi-desc {
        font-size: 0.75rem;
        opacity: 0.7;
        margin-top: 4px;
    }
    
    /* Variantes de colores suaves pero fuertes */
    .kpi-variant-blue {
        background-color: #f0f7ff;
        border-left: 5px solid #0056b3;
    }
    .kpi-variant-blue .dashboard-kpi-title,
    .kpi-variant-blue .dashboard-kpi-value {
        color: #0056b3;
    }
    
    .kpi-variant-green {
        background-color: #f0fff4;
        border-left: 5px solid #1e7e34;
    }
    .kpi-variant-green .dashboard-kpi-title,
    .kpi-variant-green .dashboard-kpi-value {
        color: #1e7e34;
    }
    
    .kpi-variant-red {
        background-color: #fff5f5;
        border-left: 5px solid #c82333;
    }
    .kpi-variant-red .dashboard-kpi-title,
    .kpi-variant-red .dashboard-kpi-value {
        color: #c82333;
    }
    
    .kpi-variant-orange {
        background-color: #fff9db;
        border-left: 5px solid #d97706;
    }
    .kpi-variant-orange .dashboard-kpi-title,
    .kpi-variant-orange .dashboard-kpi-value {
        color: #d97706;
    }
    
    .kpi-variant-purple {
        background-color: #fcf0ff;
        border-left: 5px solid #85144b;
    }
    .kpi-variant-purple .dashboard-kpi-title,
    .kpi-variant-purple .dashboard-kpi-value {
        color: #85144b;
    }
    
    /* ============================================================
       CORRECCIÓN DE CONTRASTE EN SIDEBAR (CHAT INPUT Y EXPANDERS)
       ============================================================ */
    /* Corregir texto escrito dentro del chat input e inputs del sidebar */
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] [data-testid="stChatInput"] textarea,
    [data-testid="stSidebar"] [data-testid="stChatInput"] p {
        color: #0f172a !important;
        background-color: #ffffff !important;
        -webkit-text-fill-color: #0f172a !important;
    }
    
    /* Asegurar visibilidad del placeholder en el chat input */
    [data-testid="stSidebar"] textarea::placeholder,
    [data-testid="stSidebar"] input::placeholder {
        color: #64748b !important;
        opacity: 0.8 !important;
    }

    /* Estilo para los expanders dentro del sidebar (Asistente Virtual) */
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 10px !important;
    }
    
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        background-color: #0a1628 !important; /* Fondo azul oscuro del sidebar */
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
        justify-content: center !important; /* Centrado */
        display: flex !important;
        padding: 10px !important;
    }
    
    [data-testid="stSidebar"] [data-testid="stExpander"] summary * {
        color: #e8c86a !important; /* Color dorado */
        font-weight: 700 !important;
        text-align: center !important;
    }
    
    [data-testid="stSidebar"] [data-testid="stExpander"] summary svg {
        fill: #e8c86a !important;
        color: #e8c86a !important;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# SESION STATE
# ============================================================
if 'empresa_activa' not in st.session_state:
    st.session_state.empresa_activa = "Bodeguita Guayana"

# Función para inicializar saldos y ajustes de una empresa y fecha
def inicializar_saldos_empresa(empresa, fecha_str):
    """
    Inicializa los saldos para una empresa y fecha específica.
    Si existe un saldo guardado del día anterior, lo carga automáticamente.
    """
    ultimo = db.obtener_ultimo_saldo(empresa)
    
    if ultimo:
        # ✅ Hay saldo guardado → lo cargamos automáticamente
        st.session_state.saldos = {
            'fecha_actual': ultimo['fecha'],
            'inventario': safe_number(ultimo['inventario']),
            'cx_c': safe_number(ultimo['cx_c']),
            'bancos': safe_number(ultimo['bancos']),
            'cx_p': safe_number(ultimo['cx_p']),
            'transito': safe_number(ultimo['transito']),
            'capital_anterior': safe_number(ultimo['capital']),
            'historico': []
        }
        st.success(f"✅ Saldos del día anterior ({ultimo['fecha']}) cargados automáticamente para {empresa}.")
    else:
        # ❌ No hay saldo guardado → inicializar en 0
        st.session_state.saldos = {
            'fecha_actual': None,
            'inventario': 0.0,
            'cx_c': 0.0,
            'bancos': 0.0,
            'cx_p': 0.0,
            'transito': 0.0,
            'capital_anterior': 0.0,
            'historico': []
        }
        st.info(f"ℹ️ No hay saldos previos para {empresa}. Comenzando desde 0.")
    
    # Cargar ajustes guardados para esta fecha/empresa
    st.session_state.ajustes = db.obtener_ajustes(fecha_str, empresa)

if 'saldos' not in st.session_state:
    st.session_state.saldos = {
        'fecha_actual': None,
        'inventario': 0,
        'cx_c': 0,
        'bancos': 0,
        'cx_p': 0,
        'transito': 0,
        'capital_anterior': 0,
        'historico': []
    }

if 'saldos_reportados' not in st.session_state:
    st.session_state.saldos_reportados = {
        'inventario': None,
        'cx_c': None,
        'cx_p': None,
        'bancos': None,
        'transito': None
    }

if 'usuario_actual' not in st.session_state:
    st.session_state.usuario_actual = None

# ============================================================
# INICIALIZAR FILTRO DE FECHAS Y FLAGS
# ============================================================
if 'fecha_desde' not in st.session_state:
    st.session_state.fecha_desde = datetime.now() - pd.Timedelta(days=7)
if 'fecha_hasta' not in st.session_state:
    st.session_state.fecha_hasta = datetime.now()
if 'mostrar_historial' not in st.session_state:
    st.session_state.mostrar_historial = False
if 'historial_data' not in st.session_state:
    st.session_state.historial_data = None
if 'archivos_cargados' not in st.session_state:
    st.session_state.archivos_cargados = {}

# ============================================================
# FUNCIONES AUXILIARES
# ============================================================
def cargar_ultimo_saldo_automatico(empresa='General'):
    ultimo = db.obtener_ultimo_saldo(empresa)
    if ultimo:
        st.session_state.saldos['inventario'] = safe_number(ultimo['inventario'])
        st.session_state.saldos['cx_c'] = safe_number(ultimo['cx_c'])
        st.session_state.saldos['bancos'] = safe_number(ultimo['bancos'])
        st.session_state.saldos['cx_p'] = safe_number(ultimo['cx_p'])
        st.session_state.saldos['transito'] = safe_number(ultimo['transito'])
        st.session_state.saldos['capital_anterior'] = safe_number(ultimo['capital'])
        return True
    return False

def formatear_diferencia(valor_calculado, valor_reportado):
    """
    Formatea la diferencia entre dos valores con emojis y colores.
    - Si la diferencia es 0 → ✅ 0,00 (verde)
    - Si es positiva → 📈 +X.XXX,XX
    - Si es negativa → 📉 -X.XXX,XX
    - Si no hay valor reportado → N/A
    """
    # Si no hay valor de referencia, mostrar "N/A"
    if valor_reportado is None:
        return "N/A"
    
    # Calcular la diferencia
    diferencia = safe_number(valor_calculado) - safe_number(valor_reportado)
    
    # Si la diferencia es 0 (dentro de un margen de 0.01)
    if abs(diferencia) < 0.01:
        return "✅ 0,00"
    elif diferencia > 0:
        return f"📈 +{formato_venezolano(diferencia)}"
    else:
        return f"📉 {formato_venezolano(diferencia)}"

def mostrar_tabla_activos_pasivos(inventario, cx_c, bancos, cx_p, transito, capital):
    inventario = safe_number(inventario)
    cx_c = safe_number(cx_c)
    bancos = safe_number(bancos)
    cx_p = safe_number(cx_p)
    transito = safe_number(transito)
    capital = safe_number(capital)
    
    total_activos = inventario + cx_c + bancos
    total_pasivos = cx_p + transito
    
    html = f"""
    <style>
        .activos-pasivos-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-family: 'Inter', sans-serif;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.04);
        }}
        .activos-pasivos-table th {{
            background: linear-gradient(135deg, #0a1628 0%, #1a3a5c 100%);
            color: white;
            padding: 15px;
            text-align: center;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .activos-pasivos-table td {{
            padding: 12px 16px;
            border-bottom: 1px solid #e8edf2;
        }}
        .activos-pasivos-table .activos-col {{
            background: linear-gradient(135deg, #e8f8f0 0%, #d0f0e0 100%);
            vertical-align: top;
            width: 50%;
        }}
        .activos-pasivos-table .pasivos-col {{
            background: linear-gradient(135deg, #fdf0ed 0%, #f8e0da 100%);
            vertical-align: top;
            width: 50%;
        }}
        .activos-pasivos-table .capital-row {{
            background: linear-gradient(135deg, #0a1628 0%, #1a3a5c 100%);
            font-weight: bold;
            font-size: 1.1rem;
            color: white;
        }}
        .activos-pasivos-table .capital-row td {{
            padding: 16px;
            text-align: center;
        }}
        .valor {{
            font-weight: 700;
            text-align: right;
            font-family: 'Inter', monospace;
        }}
        .titulo-cuenta {{
            font-weight: 500;
            color: #1a3a5c;
        }}
        .total-label {{
            font-weight: 700;
            color: #0a1628;
        }}
        .total-valor {{
            font-weight: 800;
            color: #0a1628;
            font-size: 1.1rem;
        }}
    </style>
    
    <table class="activos-pasivos-table">
        <tr><th colspan="2">📊 ACTIVOS</th><th colspan="2">📋 PASIVOS</th></tr>
        <tr>
            <td class="activos-col" style="width: 50%;">
                <table style="width: 100%; border: none;">
                    <tr><td class="titulo-cuenta">📦 Inventario</td><td class="valor">{formato_venezolano(inventario)}</td></tr>
                    <tr><td class="titulo-cuenta">💰 Cuentas por cobrar</td><td class="valor">{formato_venezolano(cx_c)}</td></tr>
                    <tr><td class="titulo-cuenta">🏦 Bancos</td><td class="valor">{formato_venezolano(bancos)}</td></tr>
                    <tr style="border-top: 2px solid #2ecc71;">
                        <td class="total-label">📌 TOTAL ACTIVOS</td>
                        <td class="total-valor">{formato_venezolano(total_activos)}</td>
                    </tr>
                </table>
            </td>
            <td class="pasivos-col" style="width: 50%;">
                <table style="width: 100%; border: none;">
                    <tr><td class="titulo-cuenta">📋 Cuentas por pagar</td><td class="valor">{formato_venezolano(cx_p)}</td></tr>
                    <tr><td class="titulo-cuenta">🔄 Transferencias en tránsito</td><td class="valor">{formato_venezolano(transito)}</td></tr>
                    <tr style="border-top: 2px solid #e74c3c;">
                        <td class="total-label">📌 TOTAL PASIVOS</td>
                        <td class="total-valor">{formato_venezolano(total_pasivos)}</td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr class="capital-row">
            <td colspan="4">
                🏁 CAPITAL DE TRABAJO NETO = {formato_venezolano(capital)}
            </td>
        </tr>
    </table>
    """
    return html

def extraer_transito_reportado(df, transito_inicial):
    try:
        if df is None or df.empty:
            return None

        for idx, row in df.iterrows():
            row_str = ' '.join(
                [str(x) for x in row.values if pd.notna(x)]
            ).lower()

            if 'total tb' in row_str:
                for val in row.values:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num) and num > 0:
                        return float(num)

        return None
    except Exception:
        return None
        
def mostrar_recepciones_rezagadas(df_recepciones, fecha_actual, empresa):
    """
    Analiza si el archivo de recepciones contiene registros con fechas anteriores
    y si coinciden con inconsistencias históricas de Cuentas por Pagar.
    """
    if df_recepciones is None or df_recepciones.empty:
        return
        
    try:
        import re
        import sqlite3
        from datetime import datetime
        
        # 1. Limpiar columnas como lo hace el procesador
        df_limpio = ProcesadorArchivos._limpiar_columnas(df_recepciones)
        
        idx_inicio = 0
        for idx, row in df_limpio.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'compra' in row_str and 'proveedor' in row_str and 'f. recepción' in row_str:
                idx_inicio = idx + 1
                break
        
        if idx_inicio == 0:
            patrones = ['compra', 'proveedor', 'f. recepción']
            idx_inicio = ProcesadorArchivos._encontrar_fila_datos(df_limpio, patrones) + 1
            
        if idx_inicio > 0 and idx_inicio < len(df_limpio):
            df_datos = df_limpio.iloc[idx_inicio:].reset_index(drop=True)
            if len(df_datos) > 0:
                header_row = df_datos.iloc[0]
                new_columns = []
                for col in header_row:
                    if pd.notna(col):
                        new_columns.append(str(col).strip())
                    else:
                        new_columns.append(f'col_{len(new_columns)}')
                df_datos.columns = new_columns
                df_limpio = df_datos.iloc[1:].reset_index(drop=True)
                
        # 2. Buscar columnas de fecha y monto
        col_fecha = None
        for col in df_limpio.columns:
            if 'recep' in str(col).lower() or 'fecha' in str(col).lower():
                col_fecha = col
                break
                
        col_neto = None
        for col in df_limpio.columns:
            clean_col = re.sub(r'[^a-z0-9]', '', str(col).lower())
            if 'neto' in clean_col and 'iva' in clean_col:
                col_neto = col
                break
        if col_neto is None:
            for col in df_limpio.columns:
                clean_col = re.sub(r'[^a-z0-9]', '', str(col).lower())
                if 'neto' in clean_col:
                    col_neto = col
                    break
                    
        if not col_fecha or not col_neto:
            return
            
        # 3. Extraer los registros
        registros_por_fecha = {}
        fecha_actual_dt = pd.to_datetime(fecha_actual).date()
        
        for idx, row in df_limpio.iterrows():
            val_fecha = row[col_fecha]
            val_monto = row[col_neto]
            
            if pd.isna(val_fecha) or pd.isna(val_monto):
                continue
                
            # Intentar convertir fecha
            try:
                if isinstance(val_fecha, (pd.Timestamp, datetime)):
                    fecha_dt = val_fecha.date()
                else:
                    fecha_dt = pd.to_datetime(str(val_fecha).strip(), errors='coerce', dayfirst=True).date()
            except:
                continue
                
            if pd.isna(fecha_dt):
                continue
                
            # Solo nos interesan fechas estrictamente anteriores a la actual
            if fecha_dt < fecha_actual_dt:
                monto = ProcesadorArchivos._convertir_numero_europeo(val_monto)
                if monto and monto > 0:
                    registros_por_fecha.setdefault(fecha_dt, []).append(monto)
                    
        # 4. Si hay registros de fechas anteriores, buscar inconsistencias en la BD
        if registros_por_fecha:
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            
            for f_dt, montos in registros_por_fecha.items():
                f_str = f_dt.strftime('%Y-%m-%d')
                total_rezagado = sum(montos)
                
                # Consultar inconsistencias históricas en CxP para ese día
                cursor.execute("""
                    SELECT diferencia, descripcion 
                    FROM inconsistencias 
                    WHERE fecha = ? AND empresa = ? AND cuenta = 'Cuentas por pagar'
                """, (f_str, empresa))
                
                row_incons = cursor.fetchone()
                if row_incons:
                    diff_historica = abs(float(row_incons[0]))
                    # Si el total rezagado es cercano a la diferencia (margen de 1.0)
                    if abs(total_rezagado - diff_historica) < 1.0:
                        st.info(
                            f"💡 **Recepciones Rezagadas Detectadas:** El archivo de hoy contiene "
                            f"{len(montos)} recepción(es) con fecha **{f_dt.strftime('%d/%m/%Y')}** por un total de "
                            f"**{formato_venezolano(total_rezagado)}**.\n\n"
                            f"Esto coincide perfectamente y explica la diferencia de **{formato_venezolano(diff_historica)}** "
                            f"que fue reportada en esa fecha para Cuentas por Pagar."
                        )
            conn.close()
    except Exception as e:
        print(f"Error en análisis de recepciones rezagadas: {e}")

# ============================================================
# FUNCIÓN CORREGIDA: COTEJO AUTOMÁTICO DE DOCUMENTOS (NE / OT)
# 🔥 MODIFICADO: Identificación y visualización de OT Nuevas
# ============================================================
def mostrar_cotejo_recepciones_cxp(df_recepciones, df_cxp_rep, fecha_actual, empresa, diferencia_cxp=0.0):
    """
    Compara las recepciones del día contra el reporte de Cuentas por Pagar (CxP)
    de hoy y de ayer para identificar documentos conciliados, faltantes o sobrantes.
    
    🔥 REGLAS DE NEGOCIO:
    - NE = Nota de Entrega (Recepción de mercancía) → DEBE estar en Recepciones
    - OT = Orden de Trabajo (Carga manual) → NO debe estar en Recepciones
    - Si una NE está en Recepciones pero NO en CxP → POSIBLE PAGO AL CONTADO
    - Si una OT está en CxP pero NO en Recepciones → CARGA MANUAL
    - Si una OT está en CxP de HOY pero NO en CxP de AYER → OT NUEVA ⭐
    """
    if df_recepciones is None or df_recepciones.empty or df_cxp_rep is None or df_cxp_rep.empty:
        return
        
    try:
        import re
        import os
        import pandas as pd
        from datetime import timedelta
        from config import RUTA_ARCHIVOS
        
        # ============================================================
        # 1. LIMPIAR Y ESTRUCTURAR RECEPCIONES
        # ============================================================
        df_rec_clean = ProcesadorArchivos._limpiar_columnas(df_recepciones)
        idx_rec = None
        for idx, row in df_rec_clean.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'compra' in row_str and 'proveedor' in row_str and 'recep' in row_str:
                idx_rec = idx
                break
        if idx_rec is None:
            idx_rec = ProcesadorArchivos._encontrar_fila_datos(df_rec_clean, ['compra', 'proveedor', 'recep'])
        if idx_rec is not None and idx_rec >= 0 and idx_rec < len(df_rec_clean):
            df_datos = df_rec_clean.iloc[idx_rec:].reset_index(drop=True)
            if len(df_datos) > 0:
                header_row = df_datos.iloc[0]
                new_cols = [str(col).strip() if pd.notna(col) else f'col_{i}' for i, col in enumerate(header_row)]
                df_datos.columns = new_cols
                df_rec_clean = df_datos.iloc[1:].reset_index(drop=True)
        
        # ============================================================
        # 2. LIMPIAR Y ESTRUCTURAR CxP DE HOY
        # ============================================================
        df_cxp_clean = ProcesadorArchivos._limpiar_columnas(df_cxp_rep)
        idx_cxp = None
        for idx, row in df_cxp_clean.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'documento' in row_str and any(k in row_str for k in ['saldo', 'pendt', 'pendiente']):
                idx_cxp = idx
                break
        if idx_cxp is None:
            idx_cxp = ProcesadorArchivos._encontrar_fila_datos(df_cxp_clean, ['proveedor', 'documento', 'saldo'])
        if idx_cxp is not None and idx_cxp >= 0 and idx_cxp < len(df_cxp_clean):
            df_datos = df_cxp_clean.iloc[idx_cxp:].reset_index(drop=True)
            if len(df_datos) > 0:
                header_row = df_datos.iloc[0]
                new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                df_datos.columns = new_cols
                df_cxp_clean = df_datos.iloc[1:].reset_index(drop=True)

        # ============================================================
        # 3. BUSCAR CxP DEL DÍA ANTERIOR (DESDE ARCHIVO SUBIDO O HISTÓRICO)
        # ============================================================
        df_cxp_ant_clean = None
        fecha_ant_encontrada = ""
        
        # 🔥 PRIMERO: Buscar en archivo subido manualmente (archivo_cxp_anterior)
        if 'archivo_cxp_anterior' in globals() and archivo_cxp_anterior is not None:
            try:
                df_ant_raw = pd.read_excel(archivo_cxp_anterior)
                df_cxp_ant_clean = ProcesadorArchivos._limpiar_columnas(df_ant_raw)
                idx_ant = None
                for idx, row in df_cxp_ant_clean.iterrows():
                    row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                    if 'documento' in row_str and any(k in row_str for k in ['saldo', 'pendt', 'pendiente']):
                        idx_ant = idx
                        break
                if idx_ant is None:
                    idx_ant = ProcesadorArchivos._encontrar_fila_datos(df_cxp_ant_clean, ['proveedor', 'documento', 'saldo'])
                if idx_ant is not None and idx_ant >= 0 and idx_ant < len(df_cxp_ant_clean):
                    df_datos = df_cxp_ant_clean.iloc[idx_ant:].reset_index(drop=True)
                    if len(df_datos) > 0:
                        header_row = df_datos.iloc[0]
                        new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                        df_datos.columns = new_cols
                        df_cxp_ant_clean = df_datos.iloc[1:].reset_index(drop=True)
                fecha_ant_encontrada = "Archivo Subido (23-Jun-2026)"
            except Exception as e:
                print(f"Error al leer archivo_cxp_anterior subido: {e}")
                
        # 🔥 SEGUNDO: Si no hay archivo subido, buscar en histórico
        if df_cxp_ant_clean is None:
            empresa_clean = re.sub(r'[^\w\-_]', '_', empresa)
            for i in range(1, 6):
                fecha_ant_dt = pd.to_datetime(fecha_actual) - timedelta(days=i)
                fecha_ant_str = fecha_ant_dt.strftime('%Y-%m-%d')
                filename_ant = f"cxp_reportado_{empresa_clean}_{fecha_ant_str}.xlsx"
                filepath_ant = os.path.join(RUTA_ARCHIVOS, filename_ant)
                
                if os.path.exists(filepath_ant):
                    try:
                        df_ant_raw = pd.read_excel(filepath_ant)
                        df_cxp_ant_clean = ProcesadorArchivos._limpiar_columnas(df_ant_raw)
                        idx_ant = None
                        for idx, row in df_cxp_ant_clean.iterrows():
                            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                            if 'documento' in row_str and any(k in row_str for k in ['saldo', 'pendt', 'pendiente']):
                                idx_ant = idx
                                break
                        if idx_ant is None:
                            idx_ant = ProcesadorArchivos._encontrar_fila_datos(df_cxp_ant_clean, ['proveedor', 'documento', 'saldo'])
                        if idx_ant is not None and idx_ant >= 0 and idx_ant < len(df_cxp_ant_clean):
                            df_datos = df_cxp_ant_clean.iloc[idx_ant:].reset_index(drop=True)
                            if len(df_datos) > 0:
                                header_row = df_datos.iloc[0]
                                new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                                df_datos.columns = new_cols
                                df_cxp_ant_clean = df_datos.iloc[1:].reset_index(drop=True)
                        fecha_ant_encontrada = fecha_ant_dt.strftime('%d/%m/%Y')
                        break
                    except Exception as e:
                        print(f"Error cargando CxP anterior del {fecha_ant_str}: {e}")

        # ============================================================
        # 4. BUSCAR COLUMNAS CLAVE
        # ============================================================
        # Columnas de Recepciones
        cols_doc_rec = []
        for col in df_rec_clean.columns:
            col_l = str(col).lower()
            if 'fact' in col_l:
                cols_doc_rec.append(col)
        for col in df_rec_clean.columns:
            col_l = str(col).lower()
            if any(k in col_l for k in ['compra', 'documento', 'nro_doc', 'referencia', 'nro', 'ref']):
                if not any(k in col_l for k in ['proveedor', 'prov', 'rif', 'nombre', 'fecha', 'monto', 'total', 'neto', 'iva', 'cod']):
                    if col not in cols_doc_rec:
                        cols_doc_rec.append(col)
                
        col_rec_monto = None
        for col in df_rec_clean.columns:
            clean_col = re.sub(r'[^a-z0-9]', '', str(col).lower())
            if 'neto' in clean_col and 'iva' in clean_col:
                col_rec_monto = col
                break
        if col_rec_monto is None:
            for col in df_rec_clean.columns:
                clean_col = re.sub(r'[^a-z0-9]', '', str(col).lower())
                if 'neto' in clean_col or 'total' in clean_col:
                    col_rec_monto = col
                    break
                
        # Columnas de CxP - FORZAR COLUMNA C (índice 2) para Saldo Pendt.
        col_cxp_doc = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'documento', 'doc', 'factura', 'nro_doc', 'referencia')
        col_cxp_monto = None
        if len(df_cxp_clean.columns) > 2:
            col_cxp_monto = df_cxp_clean.columns[2]  # Columna C = Saldo Pendt.
        else:
            col_cxp_monto = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'saldo', 'saldo pendt', 'pendiente', 'monto')
        
        # 🔥 Buscar columna de fecha de vencimiento en CxP
        col_cxp_fecha = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'fecha venc', 'fecha vencimiento', 'vencimiento', 'fecha')

        # Columnas de CxP Anterior
        col_cxp_ant_doc = None
        col_cxp_ant_monto = None
        if df_cxp_ant_clean is not None:
            col_cxp_ant_doc = ProcesadorArchivos._buscar_columna(df_cxp_ant_clean, 'documento', 'doc', 'factura', 'nro_doc', 'referencia')
            if len(df_cxp_ant_clean.columns) > 2:
                col_cxp_ant_monto = df_cxp_ant_clean.columns[2]
            else:
                col_cxp_ant_monto = ProcesadorArchivos._buscar_columna(df_cxp_ant_clean, 'saldo', 'saldo pendt', 'pendiente', 'monto')

        if not cols_doc_rec or not col_cxp_doc or not col_rec_monto or not col_cxp_monto:
            st.warning("⚠️ **Cotejo de documentos deshabilitado**: No se pudieron identificar las columnas requeridas.")
            return

        # ============================================================
        # 5. EXTRAER DOCUMENTOS DE RECEPCIONES CON CLASIFICACIÓN NE/OT
        # ============================================================
        rec_dict = {}
        for idx, row in df_rec_clean.iterrows():
            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_rec_monto])
            if not monto:
                continue
            for col_doc in cols_doc_rec:
                doc = str(row[col_doc]).strip()
                if doc and doc != 'nan' and doc != 'None':
                    doc_norm = re.sub(r'[^0-9]', '', doc)
                    doc_norm = re.sub(r'^0+', '', doc_norm)
                    if doc_norm:
                        doc_upper = doc.upper()
                        if 'NE' in doc_upper or 'NE ' in doc_upper:
                            tipo = 'NE'
                        elif 'OT' in doc_upper or 'OT ' in doc_upper:
                            tipo = 'OT'
                        else:
                            tipo = 'DESCONOCIDO'
                        rec_dict[doc_norm] = {
                            'original': doc,
                            'monto': float(monto),
                            'tipo': tipo
                        }

        # ============================================================
        # 6. EXTRAER DOCUMENTOS DE CxP DE HOY CON CLASIFICACIÓN NE/OT
        # ============================================================
        cxp_dict = {}
        for idx, row in df_cxp_clean.iterrows():
            doc = str(row[col_cxp_doc]).strip()
            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_cxp_monto])
            if doc and doc != 'nan' and doc != 'None' and monto:
                doc_norm = re.sub(r'[^0-9]', '', doc)
                doc_norm = re.sub(r'^0+', '', doc_norm)
                if doc_norm:
                    doc_upper = doc.upper()
                    if 'NE' in doc_upper or 'NE ' in doc_upper:
                        tipo = 'NE'
                    elif 'OT' in doc_upper or 'OT ' in doc_upper:
                        tipo = 'OT'
                    else:
                        tipo = 'DESCONOCIDO'
                    
                    # 🔥 Obtener la fecha de vencimiento si está disponible
                    fecha_venc = None
                    if col_cxp_fecha:
                        try:
                            fecha_val = row[col_cxp_fecha]
                            if pd.notna(fecha_val):
                                if isinstance(fecha_val, pd.Timestamp):
                                    fecha_venc = fecha_val.strftime('%d/%m/%Y')
                                else:
                                    fecha_venc = str(fecha_val).strip()
                        except:
                            pass
                    
                    # 🔥 Obtener el proveedor (RIF y nombre) desde el archivo de CxP
                    proveedor = "No identificado"
                    # Buscar en la misma fila si hay una columna con el proveedor
                    for col in df_cxp_clean.columns:
                        col_lower = str(col).lower()
                        if 'proveedor' in col_lower or 'rif' in col_lower or 'nombre' in col_lower:
                            try:
                                prov_val = str(row[col]).strip()
                                if prov_val and prov_val != 'nan' and prov_val != 'None':
                                    proveedor = prov_val
                                    break
                            except:
                                pass
                    
                    cxp_dict[doc_norm] = {
                        'original': doc,
                        'monto': float(monto),
                        'tipo': tipo,
                        'fecha_vencimiento': fecha_venc,
                        'proveedor': proveedor
                    }

        # ============================================================
        # 7. EXTRAER DOCUMENTOS DE CxP DEL DÍA ANTERIOR
        # ============================================================
        cxp_ant_dict = {}
        if df_cxp_ant_clean is not None and col_cxp_ant_doc and col_cxp_ant_monto:
            for idx, row in df_cxp_ant_clean.iterrows():
                doc = str(row[col_cxp_ant_doc]).strip()
                monto = ProcesadorArchivos._convertir_numero_europeo(row[col_cxp_ant_monto])
                if doc and doc != 'nan' and doc != 'None' and monto:
                    doc_norm = re.sub(r'[^0-9]', '', doc)
                    doc_norm = re.sub(r'^0+', '', doc_norm)
                    if doc_norm:
                        doc_upper = doc.upper()
                        if 'NE' in doc_upper or 'NE ' in doc_upper:
                            tipo = 'NE'
                        elif 'OT' in doc_upper or 'OT ' in doc_upper:
                            tipo = 'OT'
                        else:
                            tipo = 'DESCONOCIDO'
                        cxp_ant_dict[doc_norm] = {
                            'original': doc,
                            'monto': float(monto),
                            'tipo': tipo
                        }

        # ============================================================
        # 8. CRUZAR DOCUMENTOS POR TIPO (NE y OT por separado)
        # ============================================================
        # NE - Notas de Entrega (Recepción de mercancía)
        ne_en_cxp = []      # NE en Recepciones y en CxP
        ne_faltantes = []   # NE en Recepciones pero NO en CxP (Pago al contado)
        
        # OT - Ordenes de Trabajo (Carga manual)
        ot_no_rec = []      # OT en CxP pero NO en Recepciones (Carga manual)
        ot_nuevas = []      # 🔥 OT nuevas respecto al día anterior (ESTÁN EN HOY, NO EN AYER) ⭐
        ot_eliminadas = []  # 🔥 OT que estaban en el día anterior y ya no están (SALIERON DEL CxP)
        
        # 🔥 8a. ANALIZAR NE (Notas de Entrega)
        for doc_norm, info in rec_dict.items():
            if info['tipo'] == 'NE':
                if doc_norm in cxp_dict:
                    ne_en_cxp.append({
                        'documento': info['original'],
                        'monto_rec': info['monto'],
                        'monto_cxp': cxp_dict[doc_norm]['monto'],
                        'estado': '✅ Conciliado'
                    })
                else:
                    ne_faltantes.append({
                        'documento': info['original'],
                        'monto': info['monto'],
                        'estado': '⚠️ Pago al Contado (No está en CxP)'
                    })

        # 🔥 8b. ANALIZAR OT (Ordenes de Trabajo) - ¡ESTA ES LA PARTE CLAVE!
        for doc_norm, info in cxp_dict.items():
            if info['tipo'] == 'OT':
                # 🔥 Verificar si es NUEVA (no estaba en el día anterior)
                es_nueva = doc_norm not in cxp_ant_dict
                
                # Verificar si está en Recepciones
                if doc_norm not in rec_dict:
                    ot_no_rec.append({
                        'documento': info['original'],
                        'monto': info['monto'],
                        'estado': '🟡 Carga Manual (OT no está en Recepciones)',
                        'es_nueva': es_nueva
                    })
                
                # 🔥⭐ SI ES NUEVA, la agregamos a la lista de OT nuevas con TODO el detalle
                if es_nueva:
                    ot_nuevas.append({
                        'documento': info['original'],
                        'monto': info['monto'],
                        'fecha_vencimiento': info.get('fecha_vencimiento', 'No disponible'),
                        'proveedor': info.get('proveedor', 'No identificado'),
                        'estado': '🆕 NUEVA OT en CxP (No estaba en día anterior)'
                    })

        # 🔥 8c. ANALIZAR OT ELIMINADAS (estaban en CxP de ayer y ya no están hoy)
        for doc_norm, info in cxp_ant_dict.items():
            if info['tipo'] == 'OT':
                if doc_norm not in cxp_dict:
                    ot_eliminadas.append({
                        'documento': info['original'],
                        'monto': info['monto'],
                        'estado': '🗑️ OT Eliminada del CxP (Ya no está en el día actual)'
                    })

        # ============================================================
        # 9. CALCULAR DIFERENCIA EXPLICADA
        # ============================================================
        total_ne_faltantes = sum([x['monto'] for x in ne_faltantes])
        total_ot_no_rec = sum([x['monto'] for x in ot_no_rec])
        total_ot_nuevas = sum([x['monto'] for x in ot_nuevas])
        total_ot_eliminadas = sum([x['monto'] for x in ot_eliminadas])
        diferencia_explicada = total_ne_faltantes + total_ot_no_rec

        # ============================================================
        # 10. MOSTRAR RESULTADOS EN STREAMLIT - VERSIÓN MEJORADA
        # ============================================================
        st.markdown("---")
        st.markdown("#### 🔍 Cotejo Automático de Documentos (NE / OT)")
        st.caption("Cruce automático por número de documento entre las Recepciones del día y el balance de Cuentas por Pagar")

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("📄 NE en Recepciones", len([x for x in rec_dict.values() if x['tipo'] == 'NE']))
        with col2:
            st.metric("✅ NE en CxP", len(ne_en_cxp))
        with col3:
            st.metric("⚠️ NE No en CxP", len(ne_faltantes))
        with col4:
            st.metric("🟡 OT en CxP (Carga Manual)", len(ot_no_rec))
        with col5:
            st.metric("🆕 OT Nuevas ⭐", len(ot_nuevas))
        with col6:
            st.metric("🗑️ OT Eliminadas", len(ot_eliminadas))

        # ============================================================
        # 🔥⭐ SECCIÓN PRINCIPAL: OT NUEVAS - ¡ESTA ES LA QUE NECESITAS!
        # ============================================================
        st.markdown("---")
        st.markdown("### ⭐ OT NUEVAS EN CUENTAS POR PAGAR")
        st.caption(f"Órdenes de Trabajo que están en el CxP del día actual ({fecha_actual.strftime('%d/%m/%Y')}) pero NO estaban en el día anterior ({fecha_ant_encontrada})")
        
        if ot_nuevas:
            st.warning(f"🔍 Se encontraron **{len(ot_nuevas)} OT NUEVAS** que NO estaban en el día anterior.")
            st.info("💡 Estas órdenes de trabajo se agregaron administrativamente entre el día anterior y hoy.")
            
            # 🔥 Mostrar tabla con el detalle COMPLETO incluyendo proveedor
            df_ot_nuevas = pd.DataFrame(ot_nuevas)
            if 'monto' in df_ot_nuevas.columns:
                df_ot_nuevas['Monto (Bs.)'] = df_ot_nuevas['monto'].apply(formato_venezolano)
            
            # Renombrar columnas para mejor visualización
            df_ot_nuevas_display = df_ot_nuevas.rename(columns={
                'documento': 'N° Documento',
                'fecha_vencimiento': 'Fecha Vencimiento',
                'proveedor': 'Proveedor',
                'estado': 'Estado'
            })
            
            # Mostrar la tabla con las columnas relevantes
            columnas_mostrar = ['N° Documento', 'Monto (Bs.)', 'Fecha Vencimiento', 'Proveedor', 'Estado']
            st.dataframe(df_ot_nuevas_display[columnas_mostrar], width='stretch')
            
            # 🔥 Mostrar el total de las OT nuevas de forma destacada
            st.success(f"💰 **Total de OT Nuevas: {formato_venezolano(total_ot_nuevas)} Bs.**")
            
            # 🔥 Generar mensaje resumen con el ejemplo específico
            st.markdown("#### 📋 Detalle de las OT Nuevas Encontradas")
            for item in ot_nuevas:
                st.markdown(f"""
                - **📄 {item['documento']}** → Monto: **{formato_venezolano(item['monto'])}** 
                  (Vencimiento: {item.get('fecha_vencimiento', 'No disponible')} | Proveedor: {item.get('proveedor', 'No identificado')})
                """)
            
            # 🔥 Explicación del incremento en CxP
            st.markdown("#### 📈 Impacto en Cuentas por Pagar")
            st.markdown(f"""
            | Concepto | Monto |
            |----------|-------|
            | **OT Nuevas (No estaban en día anterior)** | {formato_venezolano(total_ot_nuevas)} |
            | **OT Eliminadas (Salieron del CxP)** | {formato_venezolano(total_ot_eliminadas)} |
            | **Incremento Neto por OT** | {formato_venezolano(total_ot_nuevas - total_ot_eliminadas)} |
            """)
            
            # 🔥 Si solo hay 1 OT nueva, mostrarla de forma especial
            if len(ot_nuevas) == 1:
                item = ot_nuevas[0]
                st.markdown("---")
                st.markdown(f"""
                ### 🎯 Única OT Nueva Detectada
                
                | Campo | Valor |
                |-------|-------|
                | **Documento** | {item['documento']} |
                | **Monto** | {formato_venezolano(item['monto'])} Bs. |
                | **Fecha Vencimiento** | {item.get('fecha_vencimiento', 'No disponible')} |
                | **Proveedor** | {item.get('proveedor', 'No identificado')} |
                | **Estado** | 🆕 NUEVA OT en CxP (No estaba en día anterior) |
                """)
                st.info(f"✅ Esta OT de **{formato_venezolano(item['monto'])} Bs.** explica exactamente la diferencia en Cuentas por Pagar entre el {fecha_ant_encontrada} y el día actual.")
        else:
            st.success(f"✅ No hay OT nuevas en el día actual que no estuvieran en el día anterior ({fecha_ant_encontrada}).")

        # ============================================================
        # SECCIONES ADICIONALES (OT Eliminadas, NE, etc.)
        # ============================================================
        
        # Tabla de OT Eliminadas
        with st.expander("🗑️ OT Eliminadas del CxP (Ya no están en el día actual)", expanded=False):
            if ot_eliminadas:
                st.warning(f"🔍 Se encontraron **{len(ot_eliminadas)} OT ELIMINADAS** que estaban en el día anterior y ya no aparecen en el CxP del día actual.")
                df_ot_elim = pd.DataFrame(ot_eliminadas)
                if 'monto' in df_ot_elim.columns:
                    df_ot_elim['Monto'] = df_ot_elim['monto'].apply(formato_venezolano)
                st.dataframe(df_ot_elim[['documento', 'Monto', 'estado']], width='stretch')
                st.metric("💰 Total OT Eliminadas", formato_venezolano(total_ot_eliminadas))
            else:
                st.info("No hay OT que hayan sido eliminadas del CxP entre el día anterior y hoy.")

        # Tabla de NE Conciliados
        with st.expander("✅ NE Conciliados (Están en Recepciones y en CxP)", expanded=False):
            if ne_en_cxp:
                df_ne_conc = pd.DataFrame(ne_en_cxp)
                st.dataframe(df_ne_conc, width='stretch')
            else:
                st.info("No hay NE conciliados en este período.")

        # Tabla de NE Faltantes (Pago al Contado)
        with st.expander("⚠️ NE en Recepciones pero NO en CxP (Posible Pago al Contado)", expanded=False):
            if ne_faltantes:
                st.warning(f"🔍 Se encontraron {len(ne_faltantes)} NE que están en Recepciones pero NO en Cuentas por Pagar.")
                st.info("💡 Esto indica que la recepción fue pagada al contado y no generó deuda en CxP.")
                df_ne_falt = pd.DataFrame(ne_faltantes)
                st.dataframe(df_ne_falt, width='stretch')
                st.metric("💰 Total NE Faltantes (Pago al Contado)", formato_venezolano(total_ne_faltantes))
            else:
                st.success("✅ Todas las NE de Recepciones están en CxP.")

        # Tabla de OT (Carga Manual)
        with st.expander("🟡 OT en CxP pero NO en Recepciones (Carga Manual)", expanded=False):
            if ot_no_rec:
                st.warning(f"🔍 Se encontraron {len(ot_no_rec)} OT que están en Cuentas por Pagar pero NO en Recepciones.")
                st.info("💡 Esto indica que son cargas manuales o ajustes administrativos.")
                df_ot = pd.DataFrame(ot_no_rec)
                df_ot['Monto'] = df_ot['monto'].apply(formato_venezolano)
                st.dataframe(df_ot[['documento', 'Monto', 'estado']], width='stretch')
                st.metric("💰 Total OT (Carga Manual)", formato_venezolano(total_ot_no_rec))
            else:
                st.success("✅ No hay OT en CxP que no estén en Recepciones.")

        # ============================================================
        # 11. RESUMEN DE LA DIFERENCIA
        # ============================================================
        st.markdown("---")
        st.markdown("### 📊 Resumen de la Diferencia en Cuentas por Pagar")
        
        st.markdown(f"""
        | Concepto | Monto | Explicación |
        |----------|-------|-------------|
        | **NE Faltantes (Pago al Contado)** | {formato_venezolano(total_ne_faltantes)} | Recepciones pagadas al contado, no generan deuda en CxP |
        | **OT en CxP (Carga Manual)** | {formato_venezolano(total_ot_no_rec)} | Cargas manuales o ajustes administrativos |
        | **🆕 OT Nuevas ⭐** | **{formato_venezolano(total_ot_nuevas)}** | Nuevas órdenes de trabajo agregadas hoy |
        | **🗑️ OT Eliminadas** | {formato_venezolano(total_ot_eliminadas)} | Órdenes de trabajo que ya no están en CxP |
        | **Diferencia Explicada** | **{formato_venezolano(diferencia_explicada)}** | Suma de las diferencias identificadas |
        | **Diferencia Total Reportada** | **{formato_venezolano(abs(diferencia_cxp))}** | Diferencia original en Cuentas por Pagar |
        """)
        
        # ============================================================
        # 12. ANÁLISIS DETALLADO POR DOCUMENTO
        # ============================================================
        st.markdown("---")
        st.markdown("### 📋 Documentos que Explican la Diferencia")
        
        # Unir todos los documentos que generan diferencia
        docs_diferencia = []
        for item in ne_faltantes:
            docs_diferencia.append({
                'Documento': item['documento'],
                'Tipo': 'NE',
                'Monto': item['monto'],
                'Explicación': 'Pago al Contado (No está en CxP)'
            })
        for item in ot_no_rec:
            docs_diferencia.append({
                'Documento': item['documento'],
                'Tipo': 'OT',
                'Monto': item['monto'],
                'Explicación': 'Carga Manual (OT no está en Recepciones)'
            })
        for item in ot_nuevas:
            docs_diferencia.append({
                'Documento': item['documento'],
                'Tipo': 'OT',
                'Monto': item['monto'],
                'Explicación': f'🆕 NUEVA OT (No estaba en {fecha_ant_encontrada})'
            })
        
        if docs_diferencia:
            df_docs = pd.DataFrame(docs_diferencia)
            df_docs['Monto'] = df_docs['Monto'].apply(formato_venezolano)
            st.dataframe(df_docs, width='stretch')
        else:
            st.info("No se identificaron documentos que expliquen la diferencia.")
                    
    except Exception as e:
        st.error(f"Error al comparar recepciones con CxP: {e}")
        import traceback
        traceback.print_exc()

# ============================================================
# FUNCIÓN PARA MOSTRAR KPI INICIAL CON DISEÑO CORPORATIVO
# ============================================================
def mostrar_kpi_inicial(col, titulo, valor, color, icono):
    if color == "verde":
        clase = "kpi-inicial-verde"
    elif color == "azul":
        clase = "kpi-inicial-azul"
    elif color == "naranja":
        clase = "kpi-inicial-naranja"
    elif color == "rojo":
        clase = "kpi-inicial-rojo"
    elif color == "morado":
        clase = "kpi-inicial-morado"
    else:
        clase = "kpi-inicial-default"
    
    valor_formateado = formato_venezolano(valor)
    
    html = f"""
    <div class="kpi-inicial {clase}">
        <div class="icon">{icono}</div>
        <div class="label">{titulo}</div>
        <div class="value">{valor_formateado}</div>
    </div>
    """
    with col:
        st.markdown(html, unsafe_allow_html=True)

# ============================================================
# FUNCIONES PARA EL DASHBOARD DEL GERENTE (AUDITOR1)
# ============================================================
def obtener_saldos_consolidados():
    empresas = [
        "Bodeguita Guayana",
        "Bodeguita Monagas",
        "Bodeguita Corporación",
        "Bodeguita Anzoátegui",
        "Bodeguita Nororiental",
        "Bodeguita Carúpano",
        "Nexo Comercial"
    ]
    datos = []
    for emp in empresas:
        ultimo = db.obtener_ultimo_saldo(emp)
        if ultimo:
            datos.append({
                'Empresa': emp,
                'Inventario': safe_number(ultimo['inventario']),
                'CxC': safe_number(ultimo['cx_c']),
                'Bancos': safe_number(ultimo['bancos']),
                'CxP': safe_number(ultimo['cx_p']),
                'Tránsito': safe_number(ultimo['transito']),
                'Capital Neto': safe_number(ultimo['capital']),
                'Fecha': ultimo['fecha']
            })
        else:
            datos.append({
                'Empresa': emp,
                'Inventario': 0.0,
                'CxC': 0.0,
                'Bancos': 0.0,
                'CxP': 0.0,
                'Tránsito': 0.0,
                'Capital Neto': 0.0,
                'Fecha': '-'
            })
    return pd.DataFrame(datos)

def mostrar_dashboard_general_consolidado():
    st.markdown("""
    <div style="margin-bottom: 25px;">
        <h2 style="text-align: left; font-size: 1.8rem; font-weight: 800; color: #0a1628; margin-bottom: 5px;">📊 Panel de Control Consolidado</h2>
        <p style="color: #6a8aac; font-size: 0.95rem;">Grupo Bodeguita Oriente · Resumen de Capital de Trabajo Neto Operativo</p>
    </div>
    """, unsafe_allow_html=True)
    
    df_consolidado = obtener_saldos_consolidados()
    
    # Calcular KPIs
    total_capital = df_consolidado['Capital Neto'].sum()
    emp_max = df_consolidado.loc[df_consolidado['Capital Neto'].idxmax()] if not df_consolidado.empty else {'Capital Neto': 0.0, 'Empresa': '-'}
    emp_min = df_consolidado.loc[df_consolidado['Capital Neto'].idxmin()] if not df_consolidado.empty else {'Capital Neto': 0.0, 'Empresa': '-'}
    
    col_g1, col_g2, col_g3 = st.columns(3)
    
    with col_g1:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-blue">
            <div class="dashboard-kpi-title">🏁 Capital Consolidado</div>
            <div class="dashboard-kpi-value">{formato_venezolano(total_capital)} Bs.</div>
            <div class="dashboard-kpi-desc">Suma neta de todas las empresas</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_g2:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-green">
            <div class="dashboard-kpi-title">📈 Mayor Capital de Trabajo</div>
            <div class="dashboard-kpi-value">{formato_venezolano(emp_max['Capital Neto'])} Bs.</div>
            <div class="dashboard-kpi-desc">{emp_max['Empresa']}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_g3:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-red">
            <div class="dashboard-kpi-title">📉 Menor Capital de Trabajo</div>
            <div class="dashboard-kpi-value">{formato_venezolano(emp_min['Capital Neto'])} Bs.</div>
            <div class="dashboard-kpi-desc">{emp_min['Empresa']}</div>
        </div>
        """, unsafe_allow_html=True)
        
    # Gráficos
    st.markdown("### 📊 Comparación de Capital Neto por Empresa")
    
    chart_df = df_consolidado[['Empresa', 'Capital Neto']].copy()
    chart_df = chart_df.set_index('Empresa')
    st.bar_chart(chart_df, color="#1a73e8", height=300)
    
    # Tabla detallada
    st.markdown("### 📋 Detalle de Saldos por Empresa")
    
    df_formatted = df_consolidado.copy()
    for col in ['Inventario', 'CxC', 'Bancos', 'CxP', 'Tránsito', 'Capital Neto']:
        df_formatted[col] = df_formatted[col].apply(formato_venezolano)
        
    st.dataframe(df_formatted, width='stretch', hide_index=True)
    
    # Evolución Consolidada Histórica
    st.markdown("### 📈 Evolución Histórica Comparativa")
    
    conn = sqlite3.connect(db.db_path)
    df_hist_all = pd.read_sql_query(
        "SELECT fecha, empresa, capital FROM saldos_diarios ORDER BY fecha ASC",
        conn
    )
    conn.close()
    
    if not df_hist_all.empty:
        try:
            df_pivot = df_hist_all.pivot(index='fecha', columns='empresa', values='capital')
            df_pivot = df_pivot.ffill().fillna(0)
            st.line_chart(df_pivot, height=350)
        except Exception as e:
            st.info("ℹ️ Cargando gráfico histórico comparativo...")
            try:
                fig, ax = plt.subplots(figsize=(10, 4))
                for emp in df_hist_all['empresa'].unique():
                    df_emp = df_hist_all[df_hist_all['empresa'] == emp]
                    ax.plot(df_emp['fecha'], df_emp['capital'], label=emp, marker='o', alpha=0.7)
                ax.set_title('Evolución por Empresa', fontsize=12, fontweight='bold')
                ax.grid(True, alpha=0.3)
                ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
                plt.xticks(rotation=45)
                st.pyplot(fig)
            except:
                pass
    else:
        st.info("ℹ️ No hay suficiente historial de cierres diarios para mostrar el gráfico de evolución.")

def mostrar_dashboard_historico_empresa(empresa):
    st.markdown(f"""
    <div style="margin-bottom: 25px;">
        <h2 style="text-align: left; font-size: 1.8rem; font-weight: 800; color: #0a1628; margin-bottom: 5px;">🏢 {empresa}</h2>
        <p style="color: #6a8aac; font-size: 0.95rem;">Panel de Historial y Trazabilidad Operativa</p>
    </div>
    """, unsafe_allow_html=True)
    
    ultimo = db.obtener_ultimo_saldo(empresa)
    
    if not ultimo:
        st.warning(f"⚠️ No hay cierres diarios registrados aún para {empresa}.")
        st.info("Para comenzar, puede cargar los archivos obligatorios del día en el menú de la izquierda para realizar una validación y registrar el primer cierre.")
        return
        
    # KPIs
    capital_trabajo = safe_number(ultimo['capital'])
    inventario = safe_number(ultimo['inventario'])
    cxc = safe_number(ultimo['cx_c'])
    bancos = safe_number(ultimo['bancos'])
    cxp = safe_number(ultimo['cx_p'])
    transito = safe_number(ultimo['transito'])
    
    activos = inventario + cxc
    pasivos = cxp + transito
    
    col_e1, col_e2, col_e3, col_e4 = st.columns(4)
    
    with col_e1:
        color_kpi = "kpi-variant-green" if capital_trabajo >= 0 else "kpi-variant-red"
        st.markdown(f"""
        <div class="dashboard-kpi-card {color_kpi}">
            <div class="dashboard-kpi-title">🏁 Capital de Trabajo</div>
            <div class="dashboard-kpi-value">{formato_venezolano(capital_trabajo)} Bs.</div>
            <div class="dashboard-kpi-desc">Cierre al {ultimo['fecha']}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_e2:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-blue">
            <div class="dashboard-kpi-title">🏦 Saldo Bancos</div>
            <div class="dashboard-kpi-value">{formato_venezolano(bancos)} Bs.</div>
            <div class="dashboard-kpi-desc">Cierre al {ultimo['fecha']}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_e3:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-purple">
            <div class="dashboard-kpi-title">📦 Activos Operativos</div>
            <div class="dashboard-kpi-value">{formato_venezolano(activos)} Bs.</div>
            <div class="dashboard-kpi-desc">Inventario + CxC</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_e4:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-orange">
            <div class="dashboard-kpi-title">📋 Pasivos Operativos</div>
            <div class="dashboard-kpi-value">{formato_venezolano(pasivos)} Bs.</div>
            <div class="dashboard-kpi-desc">CxP + En Tránsito</div>
        </div>
        """, unsafe_allow_html=True)
        
    # Obtener historial filtrado por fechas
    desde = st.session_state.fecha_desde
    hasta = st.session_state.fecha_hasta
    
    historial = db.obtener_historial_por_fechas(
        desde.strftime('%Y-%m-%d'),
        hasta.strftime('%Y-%m-%d'),
        empresa=empresa
    )
    
    st.markdown("### 📈 Evolución del Capital de Trabajo Neto")
    if not historial.empty and len(historial) > 1:
        chart_data = historial[['fecha', 'capital']].copy()
        chart_data = chart_data.set_index('fecha')
        st.line_chart(chart_data, color="#c9a84c", height=250)
        
        st.markdown("### 📊 Evolución de Componentes")
        comp_data = historial[['fecha', 'inventario', 'cx_c', 'bancos', 'cx_p', 'transito']].copy()
        comp_data = comp_data.set_index('fecha')
        st.line_chart(comp_data, height=300)
    else:
        st.info("ℹ️ No hay suficientes registros en el rango de fechas seleccionado para mostrar los gráficos de evolución.")
        
    # Tabla histórica
    st.markdown("### 📋 Historial de Cierres Diarios")
    if not historial.empty:
        df_mostrar = historial.copy()
        df_mostrar = df_mostrar.drop(columns=['id', 'created_at', 'empresa'], errors='ignore')
        for col in ['inventario', 'cx_c', 'bancos', 'cx_p', 'transito', 'capital']:
            if col in df_mostrar.columns:
                df_mostrar[col] = df_mostrar[col].apply(formato_venezolano)
        st.dataframe(df_mostrar, width='stretch', hide_index=True)
    else:
        st.info("No hay registros en el rango de fechas seleccionado.")

    # Tabla de inconsistencias
    st.markdown("### ⚠️ Inconsistencias Detectadas")
    incons = db.obtener_inconsistencias(empresa=empresa)
    if not incons.empty:
        df_incons = incons.copy()
        df_incons = df_incons.drop(columns=['id', 'created_at', 'empresa'], errors='ignore')
        for col in ['valor_calculado', 'valor_reportado', 'diferencia']:
            if col in df_incons.columns:
                df_incons[col] = df_incons[col].apply(formato_venezolano)
        st.dataframe(df_incons, width='stretch', hide_index=True)
    else:
        st.success("✅ No se han detectado inconsistencias para esta empresa.")

# ============================================================
# LOGIN CON DISEÑO CORPORATIVO
# ============================================================
def mostrar_login():
    with st.container():
        st.markdown("<br><br>", unsafe_allow_html=True)
        
        try:
            img = Image.open("auditoria.jpeg")
            img.thumbnail((120, 120))
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            st.markdown(
                f"""
                <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                    <img src="data:image/jpeg;base64,{img_str}" style="width: 100px; height: auto; border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.15);">
                </div>
                """, 
                unsafe_allow_html=True
            )
        except:
            pass
        
        st.markdown("""
        <div style="text-align: center;">
            <h1 style="font-size: 2.5rem; font-weight: 800; background: linear-gradient(135deg, #c9a84c 0%, #e8c86a 100%); 
                       -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                SISTEMA CONTABLE
            </h1>
            <h2 style="color: #1a3a5c; font-weight: 400; font-size: 1.2rem; margin-top: -5px;">
                Validador de Trazabilidad Diaria
            </h2>
            <p style="color: #6a8aac; font-size: 0.85rem; margin-top: 5px;">
                Grupo Bodeguita Oriente
            </p>
            <hr style="margin: 20px auto; width: 60px; height: 3px; background: linear-gradient(90deg, #c9a84c, #e8c86a); border: none; border-radius: 2px;">
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.markdown("""
            <div style="background: white; border-radius: 20px; padding: 35px; box-shadow: 0 20px 60px rgba(10,22,40,0.08); border: 1px solid rgba(26,58,92,0.06);">
                <h3 style="text-align: center; color: #1a3a5c; margin-bottom: 25px; font-weight: 600;">🔐 Acceso al Sistema</h3>
            </div>
            """, unsafe_allow_html=True)
            
            with st.container():
                usuario_id = st.text_input("👤 Usuario", key="login_usuario", placeholder="Ingrese su usuario")
                password = st.text_input("🔑 Contraseña", type="password", key="login_password", placeholder="Ingrese su contraseña")
                
                if st.button("🚀 Ingresar", width='stretch'):
                    if usuario_id in USUARIOS and USUARIOS[usuario_id]["password"] == password:
                        st.session_state.usuario_actual = usuario_id
                        if 'primer_login_ejecutado' in st.session_state:
                            del st.session_state['primer_login_ejecutado']
                        st.rerun()
                    else:
                        st.error("❌ Usuario o contraseña incorrectos")
        
        st.markdown("<br><br>", unsafe_allow_html=True)

if st.session_state.usuario_actual is None:
    mostrar_login()
    st.stop()

# ============================================================
# HEADER CORPORATIVO
# ============================================================
st.markdown(f"""
<div class="corporate-header">
    <div class="brand">
        <div class="logo">GB</div>
        <div>
            <div class="title">Validador de Trazabilidad</div>
            <div class="subtitle">Grupo Bodeguita Oriente · Sistema Contable</div>
        </div>
    </div>
    <div class="status-bar">
        <span>
            <span class="status-dot online"></span>
            Sistema en línea
        </span>
        <span class="user-info">
            <i class="fas fa-user"></i> {USUARIOS[st.session_state.usuario_actual]['nombre']}
            <span style="opacity:0.4;margin:0 6px;">|</span>
            <i class="fas fa-briefcase"></i> {USUARIOS[st.session_state.usuario_actual]['rol']}
        </span>
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# DETERMINAR ROL DE USUARIO
# ============================================================
usuario_info = USUARIOS.get(st.session_state.usuario_actual, {})
es_gerente = usuario_info.get('rol') == 'auditor'

# Inicializar empresa activa según el rol y usuario
if es_gerente and st.session_state.empresa_activa not in ["📊 Dashboard General", "Bodeguita Guayana", "Bodeguita Monagas", "Bodeguita Corporación", "Bodeguita Anzoátegui", "Bodeguita Nororiental", "Bodeguita Carúpano", "Nexo Comercial"]:
    st.session_state.empresa_activa = "📊 Dashboard General"
elif not es_gerente:
    # Si la empresa activa es el Dashboard General (que no es permitido para analistas)
    # o si se acaba de iniciar sesión, asignamos la empresa por defecto del analista
    if st.session_state.empresa_activa == "📊 Dashboard General" or st.session_state.get('primer_login_ejecutado') is None:
        st.session_state.primer_login_ejecutado = True
        user_key = st.session_state.get("usuario_actual")
        MAP_DEFAULT_EMPRESAS = {
            "analista1": "Bodeguita Guayana",
            "analista2": "Bodeguita Monagas",
            "analista3": "Bodeguita Anzoátegui",
            "analista4": "Bodeguita Nororiental",
            "analista5": "Nexo Comercial",
            "analista6": "Bodeguita Corporación",
            "supervisor1": "Bodeguita Guayana"
        }
        st.session_state.empresa_activa = MAP_DEFAULT_EMPRESAS.get(user_key, "Bodeguita Guayana")

# ============================================================
# CARGAR AUTOMÁTICAMENTE EL ÚLTIMO SALDO GUARDADO (Solo Analistas o si Gerente selecciona Empresa específica)
# ============================================================
if st.session_state.empresa_activa != "📊 Dashboard General":
    # Si cambió la empresa cargada, recargar saldos para esa empresa
    if st.session_state.get('saldos_empresa_cargada') != st.session_state.empresa_activa:
        # Cargar los saldos correspondientes a esta empresa
        inicializar_saldos_empresa(st.session_state.empresa_activa, datetime.now().strftime("%Y-%m-%d"))
        st.session_state.saldos_empresa_cargada = st.session_state.empresa_activa
else:
    # Para el Dashboard General Consolidado, no cargamos saldos de una sola empresa
    pass

# Cambiar automáticamente a Ficha de Validación si todos los archivos obligatorios están presentes
# Debe hacerse antes de que se dibuje el widget en la barra lateral
if (st.session_state.get("fact") is not None and 
    st.session_state.get("cob") is not None and 
    st.session_state.get("egr") is not None and 
    st.session_state.get("estado") is not None):
    st.session_state.modo_vista = "🔍 Ficha de Validación"

# ============================================================
# SIDEBAR CORPORATIVA (SEGÚN ROL)
# ============================================================
with st.sidebar:
    st.markdown("""
    <div style="text-align: center; margin: 10px 0 20px 0; padding-bottom: 15px; border-bottom: 1px solid rgba(255,255,255,0.05);">
        <div style="font-size: 1.6rem; font-weight: 700; background: linear-gradient(135deg, #c9a84c, #e8c86a); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
            VALIDADOR
        </div>
        <div style="font-size: 0.6rem; opacity: 0.4; letter-spacing: 2px; text-transform: uppercase; margin-top: 2px;">
            Trazabilidad Diaria
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # SECCIÓN: USUARIO
    st.markdown('<div class="sidebar-section-title">👤 Usuario</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div style="background: rgba(255,255,255,0.04); border-radius: 10px; padding: 12px 16px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.04);">
        <div style="font-size: 0.85rem; font-weight: 600; color: white;">{usuario_info.get('nombre', 'Usuario')}</div>
        <div style="font-size: 0.7rem; opacity: 0.5; display: flex; justify-content: space-between;">
            <span>{usuario_info.get('rol', 'analista')}</span>
            <span>● Activo</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🚪 Cerrar Sesión", width='stretch'):
        st.session_state.usuario_actual = None
        st.rerun()
    
    st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
    
    # LÓGICA DE BARRA LATERAL PARA EL GERENTE (Navegación entre empresas)
    if es_gerente:
        st.markdown('<div class="sidebar-section-title">🏢 Empresas</div>', unsafe_allow_html=True)
        
        opciones_menu = [
            "📊 Dashboard General",
            "Bodeguita Guayana",
            "Bodeguita Monagas",
            "Bodeguita Corporación",
            "Bodeguita Anzoátegui",
            "Bodeguita Nororiental",
            "Bodeguita Carúpano",
            "Nexo Comercial"
        ]
        
        for opcion in opciones_menu:
            is_selected = st.session_state.empresa_activa == opcion
            label = opcion
            
            if is_selected:
                st.button(label, key=f"menu_{opcion}", type="primary", width='stretch')
            else:
                if st.button(label, key=f"menu_{opcion}", type="secondary", width='stretch'):
                    st.session_state.empresa_activa = opcion
                    st.rerun()
                    
        st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
        
        # Filtro de fecha para el gerente si no está en el consolidado
        if st.session_state.empresa_activa != "📊 Dashboard General":
            st.markdown('<div class="sidebar-section-title">🔍 Vista Principal</div>', unsafe_allow_html=True)
            modo_vista = st.radio("Seleccionar Vista", ["📊 Dashboard Histórico", "🔍 Ficha de Validación"], key="modo_vista")
            st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
            
            st.markdown('<div class="sidebar-section-title">📅 Historial</div>', unsafe_allow_html=True)
            col_fecha1, col_fecha2 = st.columns(2)
            with col_fecha1:
                fecha_desde = st.date_input("📅 Desde", st.session_state.fecha_desde, key="gerente_desde")
            with col_fecha2:
                fecha_hasta = st.date_input("📅 Hasta", st.session_state.fecha_hasta, key="gerente_hasta")
                
            if st.button("🔍 Filtrar", key="btn_filtrar_gerente", width='stretch'):
                st.session_state.fecha_desde = fecha_desde
                st.session_state.fecha_hasta = fecha_hasta
                st.rerun()
                
            st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
            
            # Expander de subida opcional de archivos para el gerente
            with st.expander("📥 Carga Dinámica de Archivos"):
                archivo_facturacion = st.file_uploader("📊 Facturación", type=["xlsx", "xls"], key="fact")
                archivo_cobranzas = st.file_uploader("💰 Cobranzas", type=["xlsx", "xls"], key="cob")
                archivo_egresos = st.file_uploader("💳 Egresos iPago", type=["xlsx", "xls"], key="egr")
                archivo_estado_cuenta = st.file_uploader("🏦 Estado de Cuenta", type=["xlsx", "xls"], key="estado")
                
                st.markdown('<div style="font-size:0.65rem;opacity:0.25;text-transform:uppercase;letter-spacing:1px;margin-top:12px;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.03);padding-bottom:4px;">Opcionales</div>', unsafe_allow_html=True)
                archivo_recepciones = st.file_uploader("📦 Recepciones", type=["xlsx", "xls"], key="rec")
                archivo_notas_credito_cliente = st.file_uploader("📝 NC Clientes", type=["xlsx", "xls"], key="notas_cliente")
                archivo_notas_credito_proveedor = st.file_uploader("📝 NC Proveedores", type=["xlsx", "xls"], key="notas_proveedor")
                
                st.markdown('<div style="font-size:0.65rem;opacity:0.25;text-transform:uppercase;letter-spacing:1px;margin-top:12px;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.03);padding-bottom:4px;">Costos</div>', unsafe_allow_html=True)
                archivo_costo_facturacion = st.file_uploader("📈 Costo Facturación", type=["xlsx", "xls"], key="costo_fact")
                
                st.markdown('<div style="font-size:0.65rem;opacity:0.25;text-transform:uppercase;letter-spacing:1px;margin-top:12px;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.03);padding-bottom:4px;">Verificación</div>', unsafe_allow_html=True)
                archivo_cxc_reportado = st.file_uploader("📄 CxC Reportado", type=["xlsx", "xls"], key="cxc_rep")
                archivo_cxp_reportado = st.file_uploader("📄 CxP Reportado", type=["xlsx", "xls"], key="cxp_rep")
                archivo_cxp_anterior = st.file_uploader("📄 CxP Día Anterior (opcional)", type=["xlsx", "xls"], key="cxp_ant")
                archivo_inventario_reportado = st.file_uploader("📄 Inventario Reportado", type=["xlsx", "xls"], key="inv_rep")
                archivo_inventario_anterior = st.file_uploader("📄 Inventario Día Anterior (para desglose a profundidad)", type=["xlsx", "xls"], key="inv_ant")
                archivo_tb = st.file_uploader("🔄 TB.xlsx", type=["xlsx", "xls"], key="tb")
            
            fecha_procesar = st.date_input("📅 Fecha a procesar", datetime.now(), key="gerente_fecha_proc")
            fecha_str = fecha_procesar.strftime("%Y-%m-%d")
            tasa_guardada = db.obtener_tasa_bcv(fecha_str)
            tasa_bcv = st.number_input("💵 Tasa BCV", value=float(tasa_guardada or 1), step=0.0001, format="%.4f", key="gerente_tasa_bcv")
            db.guardar_tasa_bcv(fecha_str, tasa_bcv)
        else:
            archivo_facturacion = None
            archivo_cobranzas = None
            archivo_egresos = None
            archivo_estado_cuenta = None
            
    # LÓGICA DE BARRA LATERAL PARA EL ANALISTA (EXISTENTE MÁS SELECTOR DE EMPRESA)
    else:
        st.markdown('<div class="sidebar-section-title">🏢 Empresa</div>', unsafe_allow_html=True)
        st.session_state.empresa_activa = st.selectbox(
            "Empresa a procesar",
            ["Bodeguita Guayana", "Bodeguita Monagas", "Bodeguita Corporación", "Bodeguita Anzoátegui", "Bodeguita Nororiental", "Bodeguita Carúpano", "Nexo Comercial"],
            key="analista_empresa"
        )
        
        st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">🔍 Vista Principal</div>', unsafe_allow_html=True)
        modo_vista = st.radio("Seleccionar Vista", ["📊 Dashboard Histórico", "🔍 Ficha de Validación"], key="modo_vista")
        
        st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">📅 Configuración</div>', unsafe_allow_html=True)
        
        fecha_procesar = st.date_input("📅 Fecha a procesar", datetime.now())
        fecha_str = fecha_procesar.strftime("%Y-%m-%d")
        tasa_guardada = db.obtener_tasa_bcv(fecha_str)
        tasa_bcv = st.number_input("💵 Tasa BCV", value=float(tasa_guardada or 1), step=0.0001, format="%.4f")
        db.guardar_tasa_bcv(fecha_str, tasa_bcv)
        
        if tasa_guardada is None:
            st.caption("⚠️ No hay tasa BCV registrada para esta fecha")
            
        st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">📌 Saldos Iniciales</div>', unsafe_allow_html=True)
        st.caption("Ingrese los saldos del día anterior")
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            inventario_manual = st.number_input("📦 Inventario", value=float(st.session_state.saldos['inventario']), step=100.0, format="%.2f", key="inv_manual")
            cx_c_manual = st.number_input("💰 CxC", value=float(st.session_state.saldos['cx_c']), step=100.0, format="%.2f", key="cxc_manual")
        with col_s2:
            bancos_manual = st.number_input("🏦 Bancos", value=float(st.session_state.saldos['bancos']), step=100.0, format="%.2f", key="ban_manual")
            cx_p_manual = st.number_input("📋 CxP", value=float(st.session_state.saldos['cx_p']), step=100.0, format="%.2f", key="cxp_manual")
            
        transito_manual = st.number_input("🔄 Tránsito", value=float(st.session_state.saldos['transito']), step=100.0, format="%.2f", key="tran_manual")
        
        if st.button("💾 Actualizar Saldos", width='stretch'):
            st.session_state.saldos['inventario'] = inventario_manual
            st.session_state.saldos['cx_c'] = cx_c_manual
            st.session_state.saldos['bancos'] = bancos_manual
            st.session_state.saldos['cx_p'] = cx_p_manual
            st.session_state.saldos['transito'] = transito_manual
            st.success("✅ Saldos actualizados")
            st.rerun()
            
        st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">📅 Historial</div>', unsafe_allow_html=True)
        
        col_fecha1, col_fecha2 = st.columns(2)
        with col_fecha1:
            fecha_desde = st.date_input("📅 Desde", st.session_state.fecha_desde, key="filtro_desde")
        with col_fecha2:
            fecha_hasta = st.date_input("📅 Hasta", st.session_state.fecha_hasta, key="filtro_hasta")
            
        col_btn_f1, col_btn_f2 = st.columns(2)
        with col_btn_f1:
            if st.button("🔍 Aplicar", width='stretch'):
                st.session_state.fecha_desde = fecha_desde
                st.session_state.fecha_hasta = fecha_hasta
                st.session_state.mostrar_historial = True
                st.rerun()
        with col_btn_f2:
            if st.button("🔄 Reset", width='stretch'):
                st.session_state.fecha_desde = datetime.now() - pd.Timedelta(days=7)
                st.session_state.fecha_hasta = datetime.now()
                st.session_state.mostrar_historial = False
                st.session_state.historial_data = None
                st.rerun()
                
        if st.session_state.get('mostrar_historial', False):
            desde = st.session_state.fecha_desde
            hasta = st.session_state.fecha_hasta
            historial = db.obtener_historial_por_fechas(desde.strftime('%Y-%m-%d'), hasta.strftime('%Y-%m-%d'), empresa=st.session_state.empresa_activa)
            
            if not historial.empty:
                st.session_state.historial_data = historial.copy()
                df_mostrar = historial.copy()
                columnas_numericas = ['inventario', 'cx_c', 'bancos', 'cx_p', 'transito', 'capital']
                for col in columnas_numericas:
                    if col in df_mostrar.columns:
                        df_mostrar[col] = df_mostrar[col].apply(formato_venezolano)
                st.dataframe(df_mostrar, width='stretch')
                st.caption(f"📊 {len(historial)} registros")
                
                col_res1, col_res2 = st.columns(2)
                with col_res1:
                    if 'capital' in historial.columns and len(historial) > 0:
                        cap_ini = safe_number(historial.iloc[0]['capital'])
                        cap_fin = safe_number(historial.iloc[-1]['capital'])
                        st.metric("📈 Variación", formato_venezolano(cap_fin - cap_ini))
                with col_res2:
                    if 'capital' in historial.columns and len(historial) > 0:
                        st.metric("🏁 Capital final", formato_venezolano(safe_number(historial.iloc[-1]['capital'])))
            else:
                st.info("No hay registros")
                
        st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">📂 Archivos del Día</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.65rem; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:1px; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.03); padding-bottom:4px;">📌 Obligatorios</div>', unsafe_allow_html=True)
        
        archivo_facturacion = st.file_uploader("📊 Facturación", type=["xlsx", "xls"], key="fact")
        archivo_cobranzas = st.file_uploader("💰 Cobranzas", type=["xlsx", "xls"], key="cob")
        archivo_egresos = st.file_uploader("💳 Egresos iPago", type=["xlsx", "xls"], key="egr")
        archivo_estado_cuenta = st.file_uploader("🏦 Estado de Cuenta", type=["xlsx", "xls"], key="estado")
        
        st.markdown('<div style="font-size:0.65rem; color:rgba(255,255,255,0.25); text-transform:uppercase; letter-spacing:1px; margin-top:12px; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.03); padding-bottom:4px;">📎 Opcionales</div>', unsafe_allow_html=True)
        archivo_recepciones = st.file_uploader("📦 Recepciones", type=["xlsx", "xls"], key="rec")
        archivo_notas_credito_cliente = st.file_uploader("📝 NC Clientes", type=["xlsx", "xls"], key="notas_cliente")
        archivo_notas_credito_proveedor = st.file_uploader("📝 NC Proveedores", type=["xlsx", "xls"], key="notas_proveedor")
        
        st.markdown('<div style="font-size:0.65rem; color:rgba(255,255,255,0.25); text-transform:uppercase; letter-spacing:1px; margin-top:12px; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.03); padding-bottom:4px;">📊 Costos</div>', unsafe_allow_html=True)
        archivo_costo_facturacion = st.file_uploader("📈 Costo Facturación", type=["xlsx", "xls"], key="costo_fact")
        
        st.markdown('<div style="font-size:0.65rem; color:rgba(255,255,255,0.25); text-transform:uppercase; letter-spacing:1px; margin-top:12px; margin-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.03); padding-bottom:4px;">🔍 Verificación</div>', unsafe_allow_html=True)
        archivo_cxc_reportado = st.file_uploader("📄 CxC Reportado", type=["xlsx", "xls"], key="cxc_rep")
        archivo_cxp_reportado = st.file_uploader("📄 CxP Reportado", type=["xlsx", "xls"], key="cxp_rep")
        archivo_cxp_anterior = st.file_uploader("📄 CxP Día Anterior (opcional)", type=["xlsx", "xls"], key="cxp_ant")
        archivo_inventario_reportado = st.file_uploader("📄 Inventario Reportado", type=["xlsx", "xls"], key="inv_rep")
        archivo_inventario_anterior = st.file_uploader("📄 Inventario Día Anterior (para desglose a profundidad)", type=["xlsx", "xls"], key="inv_ant")
        archivo_tb = st.file_uploader("🔄 TB.xlsx", type=["xlsx", "xls"], key="tb")
        
        st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">⚡ Acciones Rápidas</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Cargar Día Anterior", width='stretch'):
                ultimo = db.obtener_ultimo_saldo(st.session_state.empresa_activa)
                if ultimo:
                    st.session_state.saldos['inventario'] = safe_number(ultimo['inventario'])
                    st.session_state.saldos['cx_c'] = safe_number(ultimo['cx_c'])
                    st.session_state.saldos['bancos'] = safe_number(ultimo['bancos'])
                    st.session_state.saldos['cx_p'] = safe_number(ultimo['cx_p'])
                    st.session_state.saldos['transito'] = safe_number(ultimo['transito'])
                    st.success("✅ Saldos cargados")
                    st.rerun()
                else:
                    st.warning("No hay historial")
        with col2:
            if st.button("🧹 Resetear", width='stretch'):
                st.session_state.saldos['inventario'] = 0
                st.session_state.saldos['cx_c'] = 0
                st.session_state.saldos['bancos'] = 0
                st.session_state.saldos['cx_p'] = 0
                st.session_state.saldos['transito'] = 0
                st.success("✅ Saldos reseteados")
                st.rerun()

    # ==============================================================================
    # 👩‍💼 ASISTENTE VIRTUAL DE AUDITORÍA (Barra Lateral)
    # ==============================================================================
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant", 
                "content": "👩‍💼 ¡Hola! Soy tu IA de Auditoría. Puedes darme órdenes escribiendo:\n\n"
                           "- **ejecutar auditoría**\n"
                           "- **ver alertas auto-corregidas**\n"
                           "- **ver excepciones**\n"
                           "- **ultimo cierre**\n"
                           "- **limpiar cache**"
            }
        ]

    st.markdown('<hr class="divider-light">', unsafe_allow_html=True)
    with st.sidebar.expander("👩‍💼 ASISTENTE VIRTUAL DE AUDITORÍA", expanded=True):
        chat_container = st.container(height=380)
        with chat_container:
            for msg in st.session_state.messages:
                avatar = "👩‍💼" if msg["role"] == "assistant" else None
                with st.chat_message(msg["role"], avatar=avatar):
                    st.write(msg["content"])
                
        if user_prompt := st.chat_input("Escribe un comando...", key="chat_input"):
            st.session_state.messages.append({"role": "user", "content": user_prompt})
            
            cmd = user_prompt.strip().lower()
            response = ""
            
            from motor_auditoria import calcular_kpis
            import sqlite3
            from motor_auditoria import DB_PATH
            
            if "ejecutar" in cmd or "auditor" in cmd:
                archivos_cargados = (
                    'archivo_facturacion' in globals() and archivo_facturacion is not None and
                    'archivo_cobranzas' in globals() and archivo_cobranzas is not None and
                    'archivo_egresos' in globals() and archivo_egresos is not None and
                    'archivo_estado_cuenta' in globals() and archivo_estado_cuenta is not None
                )
                
                if archivos_cargados:
                    hay_err, fallas, df_c = ejecutar_auditoria_inteligente(
                        archivo_facturacion, archivo_cobranzas, archivo_egresos, archivo_estado_cuenta
                    )
                    st.session_state['fallas_detectadas'] = fallas
                    st.session_state['df_consolidado'] = df_c
                    st.session_state['hay_errores'] = hay_err
                    st.session_state['cierre_kpis'] = calcular_kpis(df_c)
                    st.session_state['fecha_ultimo_cierre'] = "Manual (En tiempo real)"
                    
                    fallas_activas = [f for f in fallas if f['tipo'] in ['ROJA', 'AMARILLA', 'NARANJA']]
                    response = f"⏳ Auditoría manual ejecutada con éxito. Se detectaron {len(fallas_activas)} discrepancias activas. La pantalla principal ha sido actualizada."
                else:
                    def local_buscar_archivo(patrones):
                        base_dir = os.path.dirname(os.path.abspath(__file__))
                        input_dir = os.path.join(base_dir, "datos_servidor")
                        if not os.path.exists(input_dir):
                            os.makedirs(input_dir)
                            return None
                        import glob
                        for patron in patrones:
                            archivos = glob.glob(os.path.join(input_dir, patron))
                            if archivos:
                                return sorted(archivos, key=os.path.getmtime, reverse=True)[0]
                        return None
                        
                    fb = local_buscar_archivo(["*Banesco*.xlsx", "*BNC*.xlsx", "*Banco*.xlsx", "*banco*.xlsx", "*estado_cuenta*.xlsx"])
                    fi = local_buscar_archivo(["*iPago*.xlsx", "*ipago*.xlsx", "*egresos*.xlsx", "*Egresos*.xlsx"])
                    fc = local_buscar_archivo(["*Cobranzas*.xlsx", "*cobranzas*.xlsx", "*ingresos*.xlsx"])
                    ff = local_buscar_archivo(["*Facturacion*.xlsx", "*facturacion*.xlsx", "*facturas*.xlsx"])
                    
                    if not fb and not fi:
                        response = "❌ No encontré archivos cargados ni archivos válidos en 'datos_servidor/'. Suba archivos en el panel central."
                    else:
                        hay_err, fallas, df_c = ejecutar_auditoria_inteligente(ff, fc, fi, fb)
                        st.session_state['fallas_detectadas'] = fallas
                        st.session_state['df_consolidado'] = df_c
                        st.session_state['hay_errores'] = hay_err
                        st.session_state['cierre_kpis'] = calcular_kpis(df_c)
                        st.session_state['fecha_ultimo_cierre'] = "Ejecutado por el Asistente (Servidor)"
                        
                        fallas_activas = [f for f in fallas if f['tipo'] in ['ROJA', 'AMARILLA', 'NARANJA']]
                        response = f"✅ Auditoría del servidor completada. Se detectaron {len(fallas_activas)} discrepancias activas. Visualización actualizada en pantalla principal."
                        
            elif "auto-corregid" in cmd or "corregid" in cmd:
                fallas = st.session_state.get('fallas_detectadas', [])
                corregidas = [f for f in fallas if f['tipo'] == 'VERDE_CORREGIDO']
                if not corregidas:
                    response = "No hay transacciones auto-corregidas en la corrida actual."
                else:
                    response = f"🟢 **Movimientos Auto-Corregidos en la corrida actual ({len(corregidas)}):**\n"
                    for idx, f in enumerate(corregidas[:10], 1):
                        analista_nombre = "Historial"
                        if "Causa: Excepción histórica aprobada previamente por el analista" in f['causa']:
                            parts = f['causa'].split("el analista ")
                            if len(parts) > 1:
                                analista_nombre = parts[1].replace(".", "")
                        response += f"{idx}. Ref: {f['referencia']} | Monto: {f['monto_banco'] if f['monto_banco'] > 0 else f['monto_sistema']} | Aprobado por: {analista_nombre}\n"
                    if len(corregidas) > 10:
                        response += f"... y {len(corregidas) - 10} más."
                        
            elif "excepcion" in cmd:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT referencia, monto, banco, usuario_analista FROM excepciones_conciliacion")
                    rows = cursor.fetchall()
                    conn.close()
                    if not rows:
                        response = "📭 No hay excepciones registradas en la base de datos de aprendizaje."
                    else:
                        response = f"💾 **Memoria de Aprendizaje ({len(rows)} excepciones guardadas):**\n"
                        for idx, r in enumerate(rows[:10], 1):
                            response += f"{idx}. Ref: {r[0]} | Monto: {r[1]:.2f} | Módulo: {r[2]} | Analista: {r[3]}\n"
                        if len(rows) > 10:
                            response += f"... y {len(rows) - 10} más."
                except Exception as e:
                    conn.close()
                    response = f"❌ Error al consultar excepciones: {e}"
                    
            elif "ultimo cierre" in cmd or "cierre" in cmd:
                existe, fecha, hay_err, fallas, df_c, kpis = cargar_ultimo_cierre()
                if not existe:
                    response = "📭 No se ha registrado ningún cierre automático del bot en la base de datos."
                else:
                    response = (
                        f"📅 **Último Cierre de Bot:** {fecha}\n"
                        f"💵 Tasa Oficial BCV: {kpis.get('tasa_bcv', 36.50):.2f} VES/USD\n"
                        f"📊 Total VES: {kpis.get('total_ves', 0.0):,.2f} Bs.\n"
                        f"📊 Total USD: ${kpis.get('total_usd', 0.0):,.2f}\n"
                        f"🚨 Alertas Activas: {kpis.get('total_alertas', 0)} (Rojas: {kpis.get('alertas_rojas', 0)}, Naranjas: {kpis.get('alertas_naranjas', 0)}, Amarillas: {kpis.get('alertas_amarillas', 0)})"
                    )
                    
            elif "limpiar" in cmd:
                st.cache_data.clear()
                response = "🧹 Caché de datos purgada. La próxima auditoría leerá directamente los archivos de origen y base de datos fresca."
                
            else:
                response = (
                    "🤖 **Comandos Disponibles:**\n\n"
                    "- **ejecutar auditoría**: Corre la conciliación perimetral sobre los archivos actuales.\n"
                    "- **ver alertas auto-corregidas**: Muestra los movimientos omitidos por historial en la corrida actual.\n"
                    "- **ver excepciones**: Muestra todas las excepciones guardadas en SQLite.\n"
                    "- **ultimo cierre**: Muestra los KPIs de la última corrida nocturna automática.\n"
                    "- **limpiar cache**: Borra la memoria intermedia de Streamlit."
                )
                
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()

# ============================================================
# RESOLUCIÓN Y PERSISTENCIA DE ARCHIVOS
# ============================================================
class LocalFileWrapper(str):
    @property
    def name(self):
        return os.path.basename(self)

def obtener_archivo_historico_o_subido(archivo_subido, prefijo_tipo):
    from config import RUTA_ARCHIVOS
    empresa_clean = re.sub(r'[^\w\-_]', '_', st.session_state.get('empresa_activa', 'General'))
    fecha_str = fecha_procesar.strftime('%Y-%m-%d')
    filename = f"{prefijo_tipo}_{empresa_clean}_{fecha_str}.xlsx"
    filepath = os.path.join(RUTA_ARCHIVOS, filename)

    try:
        with open(r'C:\Users\Ccom\Desktop\Validador Motor de Auditoria\log_guardado.txt', 'a', encoding='utf-8') as log_f:
            log_f.write(f"Call for {prefijo_tipo} | subido={archivo_subido is not None} | path={filepath}\n")
    except:
        pass

    if archivo_subido is not None:
        try:
            os.makedirs(RUTA_ARCHIVOS, exist_ok=True)
            archivo_subido.seek(0)
            bytes_data = archivo_subido.read()
            with open(filepath, 'wb') as f:
                f.write(bytes_data)
            archivo_subido.seek(0)
            try:
                with open(r'C:\Users\Ccom\Desktop\Validador Motor de Auditoria\log_guardado.txt', 'a', encoding='utf-8') as log_f:
                    log_f.write(f"  Successfully wrote {filepath}\n")
            except:
                pass
        except Exception as e:
            try:
                with open(r'C:\Users\Ccom\Desktop\Validador Motor de Auditoria\log_guardado.txt', 'a', encoding='utf-8') as log_f:
                    log_f.write(f"  FAILED to write: {e}\n")
            except:
                pass
            st.error(f"❌ Error al autoguardar {prefijo_tipo} en historial: {e} (Ruta: {filepath})")
        return archivo_subido
    else:
        if os.path.exists(filepath):
            return LocalFileWrapper(filepath)
    return None

# Resolve all file variables using the helper
archivo_facturacion = obtener_archivo_historico_o_subido(archivo_facturacion, "facturacion")
archivo_cobranzas = obtener_archivo_historico_o_subido(archivo_cobranzas, "cobranzas")
archivo_egresos = obtener_archivo_historico_o_subido(archivo_egresos, "egresos")
archivo_estado_cuenta = obtener_archivo_historico_o_subido(archivo_estado_cuenta, "estado_cuenta")
archivo_recepciones = obtener_archivo_historico_o_subido(archivo_recepciones, "recepciones")
archivo_notas_credito_cliente = obtener_archivo_historico_o_subido(archivo_notas_credito_cliente, "notas_cliente")
archivo_notas_credito_proveedor = obtener_archivo_historico_o_subido(archivo_notas_credito_proveedor, "notas_proveedor")
archivo_costo_facturacion = obtener_archivo_historico_o_subido(archivo_costo_facturacion, "costo_facturacion")
archivo_cxc_reportado = obtener_archivo_historico_o_subido(archivo_cxc_reportado, "cxc_reportado")
archivo_cxp_reportado = obtener_archivo_historico_o_subido(archivo_cxp_reportado, "cxp_reportado")
archivo_cxp_anterior = obtener_archivo_historico_o_subido(archivo_cxp_anterior, "cxp_anterior")
archivo_inventario_reportado = obtener_archivo_historico_o_subido(archivo_inventario_reportado, "inventario_reportado")
archivo_inventario_anterior = obtener_archivo_historico_o_subido(archivo_inventario_anterior, "inventario_anterior")
archivo_tb = obtener_archivo_historico_o_subido(archivo_tb, "tb")

# ============================================================
# INTERFAZ PRINCIPAL
# ============================================================
# Lógica de renderizado en la pantalla principal
if es_gerente and st.session_state.empresa_activa == "📊 Dashboard General":
    mostrar_dashboard_general_consolidado()
    st.stop()


# Si se selecciona el Dashboard Histórico o faltan archivos obligatorios
modo_vista = st.session_state.get("modo_vista", "📊 Dashboard Histórico")
if modo_vista == "📊 Dashboard Histórico" or not (archivo_facturacion and archivo_cobranzas and archivo_egresos and archivo_estado_cuenta):
    if st.session_state.empresa_activa != "📊 Dashboard General":
        if not (archivo_facturacion and archivo_cobranzas and archivo_egresos and archivo_estado_cuenta) and modo_vista == "🔍 Ficha de Validación":
            st.warning("⚠️ No se encontraron archivos cargados ni respaldos históricos para esta fecha. Suba los archivos obligatorios del día para realizar la validación.")
            st.info("Mientras tanto, se muestra el Panel de Historial:")
        mostrar_dashboard_historico_empresa(st.session_state.empresa_activa)
        st.stop()

# Título de la interfaz principal (dinámico según validación en vivo o estándar)
title_text = f"📊 Validación En Vivo: {st.session_state.empresa_activa}" if (archivo_facturacion and archivo_cobranzas and archivo_egresos and archivo_estado_cuenta) else "📊 Validador de Trazabilidad Diaria"
st.markdown(f"""
<div style="text-align: center; margin-bottom: 25px;">
    <h1 style="font-size: 1.6rem; font-weight: 700; color: #0a1628;">{title_text}</h1>
    <p style="color: #6a8aac; font-size: 0.9rem;">Capital de Trabajo Neto Operativo</p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# MOSTRAR HISTORIAL FILTRADO
# ============================================================
if st.session_state.get('mostrar_historial', False) and st.session_state.get('historial_data') is not None:
    with st.expander("📊 Historial Filtrado", expanded=True):
        historial = st.session_state.historial_data
        df_mostrar = historial.copy()
        columnas_numericas = ['inventario', 'cx_c', 'bancos', 'cx_p', 'transito', 'capital']
        for col in columnas_numericas:
            if col in df_mostrar.columns:
                df_mostrar[col] = df_mostrar[col].apply(formato_venezolano)
        
        st.dataframe(df_mostrar, width='stretch')
        
        if 'capital' in historial.columns and len(historial) > 1:
            try:
                fig, ax = plt.subplots(figsize=(10, 4))
                historial_ordenado = historial.sort_values('fecha')
                ax.plot(historial_ordenado['fecha'], historial_ordenado['capital'], marker='o', linewidth=2, color='#c9a84c')
                ax.set_title('Evolución del Capital de Trabajo Neto', fontsize=14, fontweight='bold', color='#0a1628')
                ax.set_xlabel('Fecha', color='#6a8aac')
                ax.set_ylabel('Capital (Bs.)', color='#6a8aac')
                ax.grid(True, alpha=0.3)
                ax.set_facecolor('#f8fafc')
                plt.xticks(rotation=45, color='#6a8aac')
                plt.tight_layout()
                st.pyplot(fig)
            except:
                pass

# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================
if archivo_facturacion and archivo_cobranzas and archivo_egresos and archivo_estado_cuenta:
    
    st.markdown(f"### 📈 Resultados de la Validación")
    
    # --- MÓDULO VISUAL DE AUDITORÍA INTEGRADO (MANUAL) ---
    st.markdown("---")
    st.markdown("#### 🔍 Motor de Auditoría y Trazabilidad de Errores")
    if st.button("🔍 Ejecutar Auditoría de Trazabilidad Manual", width='stretch', key="btn_auditoria_manual_principal"):
        hay_err_m, fallas_m, df_c_m = ejecutar_auditoria_inteligente(
            archivo_facturacion, archivo_cobranzas, archivo_egresos, archivo_estado_cuenta
        )
        st.session_state['fallas_detectadas'] = fallas_m
        st.session_state['df_consolidado'] = df_c_m
        st.session_state['hay_errores'] = hay_err_m
        st.session_state['fecha_ultimo_cierre'] = "Manual (En tiempo real)"
        
    if 'fallas_detectadas' in st.session_state and st.session_state.get('fecha_ultimo_cierre') == "Manual (En tiempo real)":
        renderizar_modulo_auditoria(
            st.session_state['fallas_detectadas'],
            st.session_state['df_consolidado'],
            st.session_state['hay_errores'],
            "Manual (En tiempo real)",
            usuario_info.get('nombre', 'Analista')
        )
    st.markdown("---")
    st.markdown(f"**📅 Fecha procesada:** {fecha_procesar.strftime('%Y-%m-%d')}")
    
    # ============================================================
    # SALDOS INICIALES - DESPLEGABLE
    # ============================================================
    with st.expander("📌 Saldos Iniciales - Ver detalle de origen", expanded=False):
        origen_saldos = {}
        
        if cargar_ultimo_saldo_automatico():
            origen_saldos['inventario'] = "📂 Cargado automáticamente del día anterior"
            origen_saldos['cx_c'] = "📂 Cargado automáticamente del día anterior"
            origen_saldos['bancos'] = "📂 Cargado automáticamente del día anterior"
            origen_saldos['cx_p'] = "📂 Cargado automáticamente del día anterior"
            origen_saldos['transito'] = "📂 Cargado automáticamente del día anterior"
        else:
            origen_saldos['inventario'] = "✏️ Ingresado manualmente"
            origen_saldos['cx_c'] = "✏️ Ingresado manualmente"
            origen_saldos['bancos'] = "✏️ Ingresado manualmente"
            origen_saldos['cx_p'] = "✏️ Ingresado manualmente"
            origen_saldos['transito'] = "✏️ Ingresado manualmente"
        
        st.markdown("""
        ### 📂 Origen de los Saldos Iniciales
        
        | Concepto | Valor | Origen |
        |----------|-------|--------|
        """)
        
        st.markdown(f"""
        | 📦 Inventario | {formato_venezolano(st.session_state.saldos['inventario'])} | {origen_saldos['inventario']} |
        | 💰 Cuentas por cobrar | {formato_venezolano(st.session_state.saldos['cx_c'])} | {origen_saldos['cx_c']} |
        | 🏦 Bancos | {formato_venezolano(st.session_state.saldos['bancos'])} | {origen_saldos['bancos']} |
        | 📋 Cuentas por pagar | {formato_venezolano(st.session_state.saldos['cx_p'])} | {origen_saldos['cx_p']} |
        | 🔄 Transferencias en tránsito | {formato_venezolano(st.session_state.saldos['transito'])} | {origen_saldos['transito']} |
        """)
        
        if st.session_state.saldos.get('capital_anterior', 0) > 0:
            st.markdown(f"""
            | 🏁 Capital anterior | {formato_venezolano(st.session_state.saldos['capital_anterior'])} | 📂 Calculado del día anterior |
            """)
    
    # ============================================================
    # SALDOS INICIALES - KPIs
    # ============================================================
    st.markdown("#### 📌 Saldos Iniciales (Día Anterior)")
    st.caption("💡 Estos son los saldos que vienen del día anterior")

    col_kpi_inv, col_kpi_cxc, col_kpi_ban, col_kpi_cxp, col_kpi_tran = st.columns(5)

    with col_kpi_inv:
        mostrar_kpi_inicial(col_kpi_inv, "Inventario", st.session_state.saldos['inventario'], "verde", "📦")
    with col_kpi_cxc:
        mostrar_kpi_inicial(col_kpi_cxc, "Cuentas por Cobrar", st.session_state.saldos['cx_c'], "azul", "💰")
    with col_kpi_ban:
        mostrar_kpi_inicial(col_kpi_ban, "Bancos", st.session_state.saldos['bancos'], "naranja", "🏦")
    with col_kpi_cxp:
        mostrar_kpi_inicial(col_kpi_cxp, "Cuentas por Pagar", st.session_state.saldos['cx_p'], "rojo", "📋")
    with col_kpi_tran:
        mostrar_kpi_inicial(col_kpi_tran, "Tránsito", st.session_state.saldos['transito'], "morado", "🔄")

    st.markdown("---")
    
    # ============================================================
    # LECTURA DE ARCHIVOS
    # ============================================================
    try:
        df_facturacion = pd.read_excel(archivo_facturacion)
        mostrar_archivo_con_formato(df_facturacion, archivo_facturacion.name, "Facturación Diaria")
        
        df_cobranzas = pd.read_excel(archivo_cobranzas)
        mostrar_archivo_con_formato(df_cobranzas, archivo_cobranzas.name, "Cobranzas Procesadas")
        
        df_egresos = pd.read_excel(archivo_egresos)
        mostrar_archivo_con_formato(df_egresos, archivo_egresos.name, "Egresos iPago")
        
        df_estado_cuenta = pd.read_excel(archivo_estado_cuenta)
        mostrar_archivo_con_formato(df_estado_cuenta, archivo_estado_cuenta.name, "Estado de Cuenta Bancario")
    except Exception as e:
        st.error(f"❌ Error al leer archivos Excel: {str(e)}")
        st.stop()
    
    # ============================================================
    # RECEPCIONES (OPCIONAL)
    # ============================================================
    recepcion_total = 0.0
    compras_credito = 0.0
    
    if archivo_recepciones:
        try:
            df_recepciones = pd.read_excel(archivo_recepciones)
            mostrar_archivo_con_formato(df_recepciones, archivo_recepciones.name, "Recepción de Mercancía")
            recepcion_total, compras_credito, _, _ = ProcesadorArchivos.procesar_recepciones(df_recepciones)
            st.info(f"✅ Recepción de mercancía procesada: {formato_venezolano(recepcion_total)}")
            
            # Análisis de recepciones rezagadas de días anteriores
            mostrar_recepciones_rezagadas(df_recepciones, fecha_procesar, st.session_state.empresa_activa)
        except Exception as e:
            st.warning(f"⚠️ Error procesando Recepción: {str(e)}")
            recepcion_total = 0.0
            compras_credito = 0.0
    else:
        st.info("ℹ️ No se cargó archivo de Recepción. Se usará valor 0,00 para inventario.")
    
    # ============================================================
    # COSTO DE FACTURACIÓN - DEBE EXTRAER DE COLUMNA E
    # ============================================================
    costo_facturacion = 0.0
    if archivo_costo_facturacion:
        try:
            df_costo = pd.read_excel(archivo_costo_facturacion)
            mostrar_archivo_con_formato(df_costo, archivo_costo_facturacion.name, "Costo de Facturación (Reporte Utilidad)")
            costo_facturacion = ProcesadorArchivos.procesar_costo_facturacion(df_costo)
            st.success(f"✅ Costo de facturación cargado: {formato_venezolano(costo_facturacion)}")
        except Exception as e:
            st.warning(f"⚠️ Error al leer costo de facturación: {str(e)}")
    else:
        st.info("ℹ️ No se cargó archivo de costo de facturación. El costo se mantendrá en 0.")
    
    # ============================================================
    # ARCHIVOS DE VERIFICACIÓN
    # ============================================================
    saldos_reportados = {}
    archivos_cargados = {}
    
    if archivo_cxc_reportado:
        try:
            df_cxc_rep = pd.read_excel(archivo_cxc_reportado)
            saldos_reportados['Cuentas por cobrar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxc_rep, 'cxc')
            archivos_cargados['CxC'] = df_cxc_rep
            mostrar_archivo_con_formato(df_cxc_rep, archivo_cxc_reportado.name, "Cuentas por Cobrar")
        except Exception as e:
            st.warning(f"⚠️ Error al leer CxC reportado: {str(e)}")
    
    if archivo_cxp_reportado:
        try:
            df_cxp_rep = pd.read_excel(archivo_cxp_reportado)
            saldos_reportados['Cuentas por pagar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxp_rep, 'cxp')
            archivos_cargados['CxP'] = df_cxp_rep
            mostrar_archivo_con_formato(df_cxp_rep, archivo_cxp_reportado.name, "Cuentas por Pagar")
        except Exception as e:
            st.warning(f"⚠️ Error al leer CxP reportado: {str(e)}")
    
    df_inv_ant = None
    if archivo_inventario_reportado:
        try:
            df_inv_rep = pd.read_excel(archivo_inventario_reportado)
            saldos_reportados['Inventario'] = ProcesadorArchivos.extraer_saldo_reportado(df_inv_rep, 'inventario')
            archivos_cargados['Inventario'] = df_inv_rep
            mostrar_archivo_con_formato(df_inv_rep, archivo_inventario_reportado.name, "Inventario")
            
            # Guardar el archivo en RUTA_ARCHIVOS para histórico
            try:
                from config import RUTA_ARCHIVOS
                os.makedirs(RUTA_ARCHIVOS, exist_ok=True)
                file_dest = os.path.join(RUTA_ARCHIVOS, f"inventario_{st.session_state.empresa_activa}_{fecha_procesar.strftime('%Y-%m-%d')}.xlsx")
                df_inv_rep.to_excel(file_dest, index=False)
            except Exception as save_err:
                print(f"Error al guardar inventario en histórico: {save_err}")
        except Exception as e:
            st.warning(f"⚠️ Error al leer Inventario reportado: {str(e)}")
            
    # Intentar cargar inventario anterior (1. desde upload, 2. desde histórico)
    if 'archivo_inventario_anterior' in locals() and archivo_inventario_anterior:
        try:
            df_inv_ant = pd.read_excel(archivo_inventario_anterior)
            st.info("📄 Carga exitosa del Inventario del Día Anterior (desde archivo subido).")
        except Exception as e:
            st.warning(f"⚠️ Error al leer Inventario del Día Anterior subido: {str(e)}")
    else:
        # Intentar cargar desde el histórico guardado
        try:
            from config import RUTA_ARCHIVOS
            fecha_ant_str = (pd.Timestamp(fecha_procesar) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            file_ant_path = os.path.join(RUTA_ARCHIVOS, f"inventario_{st.session_state.empresa_activa}_{fecha_ant_str}.xlsx")
            if os.path.exists(file_ant_path):
                df_inv_ant = pd.read_excel(file_ant_path)
                st.info(f"📄 Se cargó automáticamente el Inventario del Día Anterior ({fecha_ant_str}) desde el histórico.")
        except Exception as cache_err:
            print(f"Error al buscar inventario anterior en histórico: {cache_err}")
    
    if archivo_tb:
        try:
            df_tb = pd.read_excel(archivo_tb)
            transito_reportado = extraer_transito_reportado(df_tb, st.session_state.saldos['transito'])
            if transito_reportado is not None:
                saldos_reportados['Transferencias en tránsito'] = transito_reportado
                archivos_cargados['Tránsito'] = df_tb
                mostrar_archivo_con_formato(df_tb, archivo_tb.name, "Transferencias en Tránsito")
        except Exception as e:
            st.warning(f"⚠️ Error al leer TB.xlsx: {str(e)}")
    
    # ============================================================
    # NOTAS DE CRÉDITO
    # ============================================================
    notas_credito_cliente = 0
    if archivo_notas_credito_cliente:
        try:
            df_notas_cliente = pd.read_excel(archivo_notas_credito_cliente)
            mostrar_archivo_con_formato(df_notas_cliente, archivo_notas_credito_cliente.name, "Notas de Crédito Clientes")
            notas_credito_cliente, _, _ = ProcesadorArchivos.procesar_notas_credito(df_notas_cliente)
        except Exception as e:
            st.warning(f"⚠️ Error al procesar notas de crédito clientes: {str(e)}")
    
    notas_credito_proveedor = 0
    if archivo_notas_credito_proveedor:
        try:
            df_notas_proveedor = pd.read_excel(archivo_notas_credito_proveedor)
            mostrar_archivo_con_formato(df_notas_proveedor, archivo_notas_credito_proveedor.name, "Notas de Crédito Proveedores")
            notas_credito_proveedor, _, _ = ProcesadorArchivos.procesar_notas_credito(df_notas_proveedor)
        except Exception as e:
            st.warning(f"⚠️ Error al procesar notas de crédito proveedores: {str(e)}")
    
    # ============================================================
    # PROCESAMIENTO DE MOVIMIENTOS
    # ============================================================
    try:
        facturacion, _, _, _ = ProcesadorArchivos.procesar_facturacion(df_facturacion)
        cobranzas, _, _ = ProcesadorArchivos.procesar_cobranzas(df_cobranzas)
        
        pagos_proveedores, pagos_gastos, total_egresos, df_proveedores = ProcesadorArchivos.procesar_egresos(df_egresos)
        
        if not df_proveedores.empty:
            with st.expander("📋 Detalle de PROVEEDORES DE MERCANCIA (filtrados)", expanded=False):
                st.success(f"✅ Se encontraron {len(df_proveedores)} registros de PROVEEDORES DE MERCANCIA")
                st.dataframe(df_proveedores, width='stretch')
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("💰 Pagos a Proveedores de Mercancía", formato_venezolano(pagos_proveedores))
                with col2:
                    st.metric("📦 Otros Gastos", formato_venezolano(pagos_gastos))
        else:
            st.warning("⚠️ No se encontraron registros de PROVEEDORES DE MERCANCIA en el archivo de egresos")
            st.info("ℹ️ Asegúrate de que la columna 'Tipo de Pago' tenga 'PROVEEDORES DE MERCANCIA'")
            
            if len(df_egresos.columns) >= 4:
                col_tipo_pago = df_egresos.columns[3]
                tipos_unicos = df_egresos[col_tipo_pago].unique()
                st.write("📌 Tipos de Pago encontrados en el archivo:")
                st.write(tipos_unicos)
        
        saldo_inicial_bancos, ingresos_id, ingresos_no_id, egresos_bancarios, saldo_final, total_ingresos, total_egresos_banco = ProcesadorArchivos.procesar_estado_cuenta(
            df_estado_cuenta, st.session_state.saldos['bancos']
        )
        
    except Exception as e:
        st.error(f"❌ Error al procesar movimientos: {str(e)}")
        st.stop()
    
    # VALIDAR Y ASEGURAR VALORES NUMÉRICOS
    facturacion = safe_number(facturacion)
    costo_facturacion = safe_number(costo_facturacion)
    cobranzas = safe_number(cobranzas)
    notas_credito_cliente = safe_number(notas_credito_cliente)
    recepcion_total = safe_number(recepcion_total)
    compras_credito = safe_number(compras_credito)
    pagos_proveedores = safe_number(pagos_proveedores)
    pagos_gastos = safe_number(pagos_gastos)
    total_egresos = safe_number(total_egresos)
    notas_credito_proveedor = safe_number(notas_credito_proveedor)
    ingresos_id = safe_number(ingresos_id)
    ingresos_no_id = safe_number(ingresos_no_id)
    saldo_final = safe_number(saldo_final)
    saldo_inicial_bancos = safe_number(saldo_inicial_bancos)
    total_ingresos = safe_number(total_ingresos)
    total_egresos_banco = safe_number(total_egresos_banco)
    
    ingresos_totales = ingresos_id + ingresos_no_id
    
    # ============================================================
    # TABLA MOVIMIENTOS DEL DÍA
    # ============================================================
    st.markdown("#### 📋 Movimientos del día procesados")
    
    mov_data = {
        "Concepto": [
            "Facturación",
            "Costo de Facturación",
            "Cobranzas",
            "Recepción de Mercancía",
            "Pagos a Proveedores de Mercancía",
            "Otros Gastos",
            "Total Egresos iPago",
            "Ingresos (Estado de Cuenta)",
            "Estado de Cuenta - Saldo Final",
            "Transferencias en Tránsito"
        ],
        "Monto": [
            formato_venezolano(facturacion),
            formato_venezolano(costo_facturacion),
            formato_venezolano(cobranzas),
            formato_venezolano(recepcion_total),
            formato_venezolano(pagos_proveedores),
            formato_venezolano(pagos_gastos),
            formato_venezolano(total_egresos),
            formato_venezolano(total_ingresos),
            formato_venezolano(saldo_final),
            formato_venezolano(saldos_reportados.get('Transferencias en tránsito', 0))
        ]
    }
    st.dataframe(pd.DataFrame(mov_data), width='stretch', hide_index=True)
    
    st.info(f"""
    📊 **Resumen de Egresos iPago:**
    - 🏪 Proveedores de Mercancía: {formato_venezolano(pagos_proveedores)}
    - 📦 Otros Gastos: {formato_venezolano(pagos_gastos)}
    - 📌 Total Egresos: {formato_venezolano(total_egresos)}
    
    📊 **Resumen del Estado de Cuenta:**
    - 💰 Saldo Inicial: {formato_venezolano(saldo_inicial_bancos)}
    - 📈 Ingresos (Créditos): {formato_venezolano(total_ingresos)}
    - 📉 Egresos (Débitos): {formato_venezolano(total_egresos_banco)}
    - 🏁 Saldo Final: {formato_venezolano(saldo_final)}
    """)
    
    st.markdown("---")
    
    # ============================================================
    # 🔥 SALDO DEL ESTADO DE CUENTA
    # ============================================================
    st.markdown("#### 📊 Saldo del Estado de Cuenta")
    st.caption("💡 Este es el saldo que viene del archivo de estado de cuenta")

    col_ec1, col_ec2, col_ec3, col_ec4 = st.columns(4)
    with col_ec1:
        st.metric("🏦 Saldo Inicial", formato_venezolano(saldo_inicial_bancos))
    with col_ec2:
        st.metric("📈 Ingresos", formato_venezolano(total_ingresos))
    with col_ec3:
        st.metric("📉 Egresos", formato_venezolano(total_egresos_banco))
    with col_ec4:
        st.metric("🏁 Saldo Final", formato_venezolano(saldo_final))

    st.markdown("---")
    
    # ============================================================
    # CÁLCULOS Y VALIDACIONES
    # ============================================================
    
    inventario_calculado = safe_number(st.session_state.saldos['inventario']) + recepcion_total - costo_facturacion
    cx_c_calculado = safe_number(st.session_state.saldos['cx_c']) + facturacion - cobranzas - notas_credito_cliente
    
    # 🔥 Bancos = Saldo Inicial del estado de cuenta + Ingresos - Egresos
    bancos_calculado = safe_number(saldo_inicial_bancos) + total_ingresos - total_egresos_banco
    
    cx_p_calculado = safe_number(st.session_state.saldos['cx_p']) + recepcion_total - pagos_proveedores
    transito_calculado = safe_number(st.session_state.saldos['transito']) + ingresos_totales - cobranzas
    capital_calculado = (inventario_calculado + cx_c_calculado + bancos_calculado) - (cx_p_calculado + transito_calculado)
    
    # ============================================================
    # 🔥 CALCULAR DIFERENCIAS - ¡ESTA ES LA PARTE QUE FALTABA!
    # ============================================================
    inventario_reportado = saldos_reportados.get('Inventario')
    cx_c_reportado = saldos_reportados.get('Cuentas por cobrar')
    cx_p_reportado = saldos_reportados.get('Cuentas por pagar')
    transito_reportado = saldos_reportados.get('Transferencias en tránsito')
    
    # Calcular diferencias
    diff_inv = safe_number(inventario_calculado) - safe_number(inventario_reportado) if inventario_reportado is not None else 0
    diff_cxc = safe_number(cx_c_calculado) - safe_number(cx_c_reportado) if cx_c_reportado is not None else 0
    diff_cxp = safe_number(cx_p_calculado) - safe_number(cx_p_reportado) if cx_p_reportado is not None else 0
    diff_transito = safe_number(transito_calculado) - safe_number(transito_reportado) if transito_reportado is not None else 0
    diferencia_bancos = bancos_calculado - saldo_final
    
    # ============================================================
    # Mostrar información detallada del cálculo de Bancos
    # ============================================================
    st.markdown("#### 📊 Detalle del cálculo de Bancos")
    
    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    with col_b1:
        st.metric("🏦 Saldo Inicial (estado de cuenta)", formato_venezolano(saldo_inicial_bancos))
    with col_b2:
        st.metric("📈 Ingresos (estado de cuenta)", formato_venezolano(total_ingresos))
    with col_b3:
        st.metric("📉 Egresos (estado de cuenta)", formato_venezolano(total_egresos_banco))
    with col_b4:
        st.metric("🏁 Bancos calculado", formato_venezolano(bancos_calculado))
    
    # Verificar contra el saldo final del estado de cuenta
    st.markdown("#### ✅ Verificación con Estado de Cuenta")
    
    col_v1, col_v2, col_v3 = st.columns(3)
    with col_v1:
        st.metric("📋 Saldo Final (Estado de Cuenta)", formato_venezolano(saldo_final))
    with col_v2:
        st.metric("📊 Bancos Calculado", formato_venezolano(bancos_calculado))
    with col_v3:
        diferencia_bancos = bancos_calculado - saldo_final
        if abs(diferencia_bancos) < 0.01:
            st.metric("✅ Diferencia", "0,00", delta="✅ Coincide")
        else:
            st.metric("⚠️ Diferencia", formato_venezolano(diferencia_bancos), delta=f"{'📈' if diferencia_bancos > 0 else '📉'} {formato_venezolano(abs(diferencia_bancos))}")
            st.warning(f"⚠️ Hay una diferencia de {formato_venezolano(diferencia_bancos)} entre el Bancos calculado y el saldo final del estado de cuenta.")
    
    st.info(f"ℹ️ **Saldo Inicial Bancario (desde estado de cuenta):** {formato_venezolano(saldo_inicial_bancos)} Bs.")
    
    st.markdown("---")
    
    # ============================================================
    # ACTIVOS vs PASIVOS
    # ============================================================
    st.markdown("#### 📊 Estructura del Capital de Trabajo")
    html_table = mostrar_tabla_activos_pasivos(
        inventario_calculado, cx_c_calculado, bancos_calculado, 
        cx_p_calculado, transito_calculado, capital_calculado
    )
    st.markdown(html_table, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ============================================================
    # 🔥 COMPARACIÓN VS VALORES REPORTADOS - VERSIÓN FINAL CORREGIDA
    # ============================================================
    st.markdown("#### 📋 Comparación vs Valores Reportados")

    # Obtener valores reportados
    inventario_reportado = saldos_reportados.get('Inventario')
    cx_c_reportado = saldos_reportados.get('Cuentas por cobrar')
    cx_p_reportado = saldos_reportados.get('Cuentas por pagar')
    transito_reportado = saldos_reportados.get('Transferencias en tránsito')

    # Obtener valores del día anterior desde la sesión
    inventario_anterior = safe_number(st.session_state.saldos.get('inventario', 0))
    cx_c_anterior = safe_number(st.session_state.saldos.get('cx_c', 0))
    bancos_anterior = safe_number(st.session_state.saldos.get('bancos', 0))
    cx_p_anterior = safe_number(st.session_state.saldos.get('cx_p', 0))
    transito_anterior = safe_number(st.session_state.saldos.get('transito', 0))
    
    # 💡 CORRECCIÓN MÁGICA: Calcular el capital anterior directo de los saldos base existentes
    capital_anterior = (inventario_anterior + cx_c_anterior + bancos_anterior) - (cx_p_anterior + transito_anterior)

    # Calcular diferencias
    diff_inv_real = safe_number(inventario_calculado) - safe_number(inventario_reportado) if inventario_reportado is not None else 0
    diff_cxc_real = safe_number(cx_c_calculado) - safe_number(cx_c_reportado) if cx_c_reportado is not None else 0
    diff_cxp_real = safe_number(cx_p_calculado) - safe_number(cx_p_reportado) if cx_p_reportado is not None else 0
    diff_transito_real = safe_number(transito_calculado) - safe_number(transito_reportado) if transito_reportado is not None else 0
    diff_capital = capital_calculado - capital_anterior

    # Función para formatear diferencia
    def formatear_diff(valor_calculado, valor_reportado):
        if valor_reportado is None or valor_reportado == 0:
            return "-"
        diff = safe_number(valor_calculado) - safe_number(valor_reportado)
        if abs(diff) < 0.01:
            return "✅ 0,00"
        elif diff > 0:
            return f"📈 +{formato_venezolano(diff)}"
        else:
            return f"📉 {formato_venezolano(diff)}"

    # Crear lista para la tabla
    comparacion_data = []

    # 1. INVENTARIO
    diff_inv_display = formatear_diff(inventario_calculado, inventario_reportado)
    comparacion_data.append({
        "Cuenta": "Inventario",
        "Fórmula": "Inv. inicial + Recepción - Costo facturación",
        "Día Anterior": formato_venezolano(inventario_anterior),
        "Calculado": formato_venezolano(inventario_calculado),
        "Reportado": formato_venezolano(inventario_reportado) if inventario_reportado is not None and inventario_reportado > 0 else "0,00",
        "Diferencia": diff_inv_display
    })

    # 2. CUENTAS POR COBRAR
    diff_cxc_display = formatear_diff(cx_c_calculado, cx_c_reportado)
    comparacion_data.append({
        "Cuenta": "Cuentas por cobrar",
        "Fórmula": "CxC inicial + Facturación - Cobranzas - NC Clientes",
        "Día Anterior": formato_venezolano(cx_c_anterior),
        "Calculado": formato_venezolano(cx_c_calculado),
        "Reportado": formato_venezolano(cx_c_reportado) if cx_c_reportado is not None and cx_c_reportado > 0 else "0,00",
        "Diferencia": diff_cxc_display
    })

    # 3. BANCOS
    diff_bancos_display = formatear_diff(bancos_calculado, bancos_anterior) if bancos_anterior != 0 else "-"
    comparacion_data.append({
        "Cuenta": "Bancos",
        "Fórmula": "Saldo Inicial (E/C) + Ingresos - Egresos",
        "Día Anterior": formato_venezolano(bancos_anterior),
        "Calculado": formato_venezolano(bancos_calculado),
        "Reportado": formato_venezolano(saldo_final) if saldo_final > 0 else "0,00",
        "Diferencia": diff_bancos_display
    })

    # 4. CUENTAS POR PAGAR
    diff_cxp_display = formatear_diff(cx_p_calculado, cx_p_reportado)
    comparacion_data.append({
        "Cuenta": "Cuentas por pagar",
        "Fórmula": "CxP inicial + Recepciones - Pagos proveedores",
        "Día Anterior": formato_venezolano(cx_p_anterior),
        "Calculado": formato_venezolano(cx_p_calculado),
        "Reportado": formato_venezolano(cx_p_reportado) if cx_p_reportado is not None and cx_p_reportado > 0 else "0,00",
        "Diferencia": diff_cxp_display
    })

    # 5. TRANSFERENCIAS EN TRÁNSITO
    diff_transito_display = formatear_diff(transito_calculado, transito_reportado)
    comparacion_data.append({
        "Cuenta": "Transferencias en tránsito",
        "Fórmula": "Tránsito inicial + Ingresos del día - Cobranzas",
        "Día Anterior": formato_venezolano(transito_anterior),
        "Calculado": formato_venezolano(transito_calculado),
        "Reportado": formato_venezolano(transito_reportado) if transito_reportado is not None and transito_reportado > 0 else "0,00",
        "Diferencia": diff_transito_display
    })

    # 6. CAPITAL DE TRABAJO NETO
    if abs(diff_capital) < 0.01:
        diff_capital_display = "✅ 0,00"
    elif diff_capital > 0:
        diff_capital_display = f"📈 +{formato_venezolano(diff_capital)}"
    else:
        diff_capital_display = f"📉 {formato_venezolano(diff_capital)}"
    
    comparacion_data.append({
        "Cuenta": "Capital de Trabajo Neto",
        "Fórmula": "(Inv + CxC + Bancos) - (CxP + Tránsito)",
        "Día Anterior": formato_venezolano(capital_anterior),
        "Calculado": formato_venezolano(capital_calculado),
        "Reportado": formato_venezolano(capital_calculado),
        "Diferencia": diff_capital_display
    })

    # Crear DataFrame
    df_comparacion = pd.DataFrame(comparacion_data)
    columnas_mostrar = ['Cuenta', 'Fórmula', 'Día Anterior', 'Calculado', 'Reportado', 'Diferencia']
    
    # Aplicar estilos a la tabla
    def colorear_filas(row):
        diff_text = str(row['Diferencia'])
        if diff_text != "-" and "✅" not in diff_text:
            if "📈" in diff_text:
                return ['background-color: #d4edda;'] * len(row)
            elif "📉" in diff_text:
                return ['background-color: #f8d7da;'] * len(row)
        if row['Cuenta'] == 'Capital de Trabajo Neto':
            if "📈" in diff_text:
                return ['background-color: #0f3d2e; color: white; font-weight: bold;'] * len(row)
            elif "📉" in diff_text:
                return ['background-color: #3d1a1a; color: white; font-weight: bold;'] * len(row)
            else:
                return ['background-color: #1a3a5c; color: white; font-weight: bold;'] * len(row)
        return [''] * len(row)
    
    # 💡 SOLUCCIÓN MÁGICA: Se remueve el height estático para adaptar la cuadrícula de forma perfecta
    st.dataframe(
        df_comparacion[columnas_mostrar].style.apply(colorear_filas, axis=1).hide(axis='index'),
        use_container_width=True
    )
    # ============================================================
    # 📦 TRAZABILIDAD DE INVENTARIO - PRODUCTO POR PRODUCTO
    # ============================================================
    st.markdown("### 📦 Trazabilidad de Inventario - Producto por Producto")
    st.caption("Análisis detallado: Inventario Inicial - Ventas (Costo) = Inventario Esperado vs Inventario Reportado")
    
    # --- ANÁLISIS DE INVENTARIO (PRODUCTO POR PRODUCTO) ---
    if 'df_inv_ant' in locals() and df_inv_ant is not None and 'df_inv_rep' in locals() and df_inv_rep is not None:
        try:
            # Cargar detalle de inventario anterior y actual
            inv_prev = ProcesadorArchivos.cargar_detalle_inventario(df_inv_ant)
            inv_curr = ProcesadorArchivos.cargar_detalle_inventario(df_inv_rep)
            
            if inv_prev is not None and inv_curr is not None:
                # Cargar utilidades (costo de facturación) si está disponible
                util_df = None
                if 'df_costo' in locals() and df_costo is not None:
                    util_df = ProcesadorArchivos.cargar_detalle_utilidad(df_costo)
                
                # Diccionarios para búsqueda rápida
                inv_prev_dict = inv_prev.set_index('Producto').to_dict('index')
                inv_curr_dict = inv_curr.set_index('Producto').to_dict('index')
                util_dict = util_df.set_index('Cod_Producto').to_dict('index') if util_df is not None else {}
                
                # Obtener todos los productos
                all_prods = set(inv_prev_dict.keys()).union(set(inv_curr_dict.keys()))
                
                # Listas para almacenar resultados
                diferencias = []
                total_inicial = 0
                total_ventas = 0
                total_esperado_valor = 0
                total_reportado_valor = 0
                
                for p in all_prods:
                    p_prev = inv_prev_dict.get(p, {'Cantidad': 0.0, 'Precio/Unidad': 0.0, 'Total(*)': 0.0, 'Descrip_Clean': 'N/A'})
                    p_curr = inv_curr_dict.get(p, {'Cantidad': 0.0, 'Precio/Unidad': 0.0, 'Total(*)': 0.0, 'Descrip_Clean': 'N/A'})
                    u_row = util_dict.get(p, {'Cantidad': 0.0, 'Costo_Total': 0.0, 'Producto_Original': 'N/A'})
                    
                    # Datos del inventario anterior
                    qty_prev = p_prev['Cantidad']
                    price_prev = p_prev['Precio/Unidad']
                    val_prev = p_prev['Total(*)']
                    desc = p_curr['Descrip_Clean'] if p_curr['Descrip_Clean'] != 'N/A' else (p_prev['Descrip_Clean'] if p_prev['Descrip_Clean'] != 'N/A' else u_row['Producto_Original'])
                    
                    # Datos del inventario actual
                    qty_curr = p_curr['Cantidad']
                    price_curr = p_curr['Precio/Unidad']
                    val_curr = p_curr['Total(*)']
                    
                    # Datos de ventas
                    qty_sold = u_row['Cantidad']
                    cost_sold = u_row['Costo_Total']
                    
                    # Cálculos de trazabilidad
                    expected_qty = qty_prev - qty_sold
                    expected_val = val_prev - cost_sold
                    qty_diff = qty_curr - expected_qty
                    val_diff = val_curr - expected_val
                    
                    # Acumular totales
                    total_inicial += val_prev
                    total_ventas += cost_sold
                    total_esperado_valor += expected_val
                    total_reportado_valor += val_curr
                    
                    # Determinar el estado del producto
                    estado = "✅ OK"
                    if abs(qty_diff) > 0.01 and abs(val_diff) > 0.01:
                        estado = "🔴 FALTANTE" if qty_diff < 0 else "🟢 SOBRANTE"
                    elif abs(qty_diff) > 0.01:
                        estado = "🟡 DIF. CANTIDAD"
                    elif abs(val_diff) > 0.01:
                        estado = "🟠 DIF. PRECIO"
                    
                    # Mostrar productos con diferencias o movimientos
                    if abs(qty_sold) > 0.01 or abs(qty_diff) > 0.01 or abs(val_diff) > 0.01 or abs(price_curr - price_prev) > 0.01:
                        efecto_precio = (price_curr - price_prev) * qty_curr if qty_curr > 0 else 0
                        
                        diferencias.append({
                            'Código': p,
                            'Descripción': desc[:40],
                            'Estado': estado,
                            'Q. Anterior': qty_prev,
                            'Vendido': qty_sold,
                            'Q. Esperada': expected_qty,
                            'Q. Reportada': qty_curr,
                            'Dif. Cantidad': qty_diff,
                            'Precio Ant.': price_prev,
                            'Precio Nuevo': price_curr,
                            'Efecto Precio': efecto_precio,
                            'Dif. Valor': val_diff
                        })
                
                # --- MOSTRAR RESULTADOS DE INVENTARIO ---
                st.info(f"""
                **📊 RESUMEN DE TOTALES DE INVENTARIO:**
                - **Inventario Inicial:** {formato_venezolano(total_inicial)} Bs.
                - **Costo de Ventas:** {formato_venezolano(total_ventas)} Bs.
                - **Inventario Esperado:** {formato_venezolano(total_esperado_valor)} Bs.
                - **Inventario Reportado:** {formato_venezolano(total_reportado_valor)} Bs.
                - **Diferencia Total:** {formato_venezolano(total_reportado_valor - total_esperado_valor)} Bs.
                """)
                
                # KPIs de trazabilidad
                col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
                with col_kpi1:
                    st.metric("📦 Productos Analizados", len(diferencias))
                with col_kpi2:
                    st.metric("📊 Total Ventas (Unid.)", f"{total_ventas:,.0f}")
                with col_kpi3:
                    st.metric("✅ Productos OK", len([d for d in diferencias if d['Estado'] == '✅ OK']))
                with col_kpi4:
                    st.metric("⚠️ Con Diferencias", len([d for d in diferencias if d['Estado'] != '✅ OK']))
                
                # Tabla de diferencias de inventario
                if diferencias:
                    df_diferencias = pd.DataFrame(diferencias)
                    
                    # Formatear columnas
                    for col in ['Precio Ant.', 'Precio Nuevo', 'Efecto Precio', 'Dif. Valor']:
                        if col in df_diferencias.columns:
                            df_diferencias[col] = df_diferencias[col].apply(formato_venezolano)
                    
                    df_diferencias['Dif. Cantidad'] = df_diferencias['Dif. Cantidad'].apply(lambda x: f"{x:.2f}")
                    df_diferencias['Q. Anterior'] = df_diferencias['Q. Anterior'].apply(lambda x: f"{x:.2f}")
                    df_diferencias['Vendido'] = df_diferencias['Vendido'].apply(lambda x: f"{x:.2f}")
                    df_diferencias['Q. Esperada'] = df_diferencias['Q. Esperada'].apply(lambda x: f"{x:.2f}")
                    df_diferencias['Q. Reportada'] = df_diferencias['Q. Reportada'].apply(lambda x: f"{x:.2f}")
                    
                    # Mostrar tabla con colores
                    columnas_mostrar = ['Código', 'Descripción', 'Estado', 'Q. Anterior', 'Vendido', 'Q. Esperada', 'Q. Reportada', 'Dif. Cantidad', 'Precio Ant.', 'Precio Nuevo', 'Efecto Precio', 'Dif. Valor']
                    st.dataframe(
                        df_diferencias[columnas_mostrar].style.apply(
                            lambda row: ['background-color: #ffcccc' if row['Estado'] == '🔴 FALTANTE' else
                                        ('background-color: #ccffcc' if row['Estado'] == '🟢 SOBRANTE' else
                                        ('background-color: #fff3cd' if row['Estado'] == '🟠 DIF. PRECIO' else
                                        ('background-color: #fff3cd' if row['Estado'] == '🟡 DIF. CANTIDAD' else ''))) for _ in row],
                            axis=1
                        ),
                        width='stretch',
                        height=400
                    )
                    
                    # Resumen de diferencias de inventario
                    total_faltante = sum([d['Dif. Cantidad'] for d in diferencias if 'FALTANTE' in d['Estado']])
                    total_sobrante = sum([d['Dif. Cantidad'] for d in diferencias if 'SOBRANTE' in d['Estado']])
                    total_efecto_precio = sum([d['Efecto Precio'] for d in diferencias if d['Efecto Precio'] != 0])
                    
                    st.info(f"""
                    **📊 RESUMEN DE DIFERENCIAS DE INVENTARIO:**
                    - **Faltante de inventario:** {abs(total_faltante):.2f} unidades
                    - **Sobrante de inventario:** {total_sobrante:.2f} unidades
                    - **Efecto total por cambio de precio:** {formato_venezolano(total_efecto_precio)} Bs.
                    """)
                    
                    # Detalle de cambios de precio
                    cambios_precio = [d for d in diferencias if abs(d['Efecto Precio']) > 0.01]
                    if cambios_precio:
                        st.markdown("#### 💰 Productos con Cambio de Precio")
                        df_precio = pd.DataFrame(cambios_precio)
                        df_precio['Efecto Precio'] = df_precio['Efecto Precio'].apply(formato_venezolano)
                        df_precio['Precio Ant.'] = df_precio['Precio Ant.'].apply(formato_venezolano)
                        df_precio['Precio Nuevo'] = df_precio['Precio Nuevo'].apply(formato_venezolano)
                        st.dataframe(
                            df_precio[['Código', 'Descripción', 'Precio Ant.', 'Precio Nuevo', 'Efecto Precio']],
                            width='stretch'
                        )
                else:
                    st.success("✅ No se detectaron diferencias en ningún producto de inventario.")
            else:
                st.warning("⚠️ No se pudieron cargar los detalles de inventario. Verifica el formato de los archivos.")
        except Exception as e:
            st.error(f"❌ Error en el análisis de trazabilidad de inventario: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
    else:
        st.info("📄 **Carga los archivos de Inventario (día anterior y actual) y Costo de Facturación para ver el análisis detallado de inventario.**")
    
    st.markdown("---")
    
    # ============================================================
    # 🔍 ANÁLISIS DE OTRAS CUENTAS (CxC, CxP, TRANSITO) - CORREGIDO
    # ============================================================
    st.markdown("### 🔍 Análisis de Diferencias en Otras Cuentas")
    
    # --- CUENTAS POR COBRAR ---
    if abs(diff_cxc) > 0.01:
        with st.expander(f"👤 Cuentas por Cobrar (Diferencia: {formatear_diferencia(cx_c_calculado, cx_c_reportado)})", expanded=True):
            st.markdown(f"**Fórmula**: `CxC Calculado ({formato_venezolano(cx_c_calculado)})` vs `CxC Reportado ({formato_venezolano(cx_c_reportado)})`")
            st.markdown(f"La diferencia de **{formato_venezolano(diff_cxc)} Bs/USD** en Cuentas por Cobrar puede explicarse por:")
            
            # Buscar transacciones coincidentes en los archivos
            cands_cxc = []
            if 'df_facturacion' in locals() and df_facturacion is not None:
                cands_cxc.extend(buscar_candidatos_por_monto(df_facturacion, diff_cxc, "Facturación Semanal"))
            if 'df_cobranzas' in locals() and df_cobranzas is not None:
                cands_cxc.extend(buscar_candidatos_por_monto(df_cobranzas, diff_cxc, "Cobranzas Diarias"))
            if 'df_notas_cliente' in locals() and df_notas_cliente is not None:
                cands_cxc.extend(buscar_candidatos_por_monto(df_notas_cliente, diff_cxc, "Notas de Crédito Clientes"))
            if 'df_cxc_rep' in locals() and df_cxc_rep is not None:
                cands_cxc.extend(buscar_candidatos_por_monto(df_cxc_rep, diff_cxc, "Reporte CxC"))
                
            if cands_cxc:
                st.info("🔍 **Transacciones con importe coincidente encontradas en los archivos:**")
                for c in cands_cxc[:5]:
                    st.markdown(f"- {c}")
            else:
                st.write("No se encontraron transacciones individuales con este importe exacto.")
                
            st.markdown("""
            **💡 Puntos clave a revisar:**
            - **Facturación vs Notas de Crédito**: Valide si hay facturas de crédito anuladas en el sistema mediante notas de crédito que no se hayan descontado correctamente en la sumatoria del día.
            - **Cobranzas Cruzadas**: Revise si se reportaron cobros que no corresponden a facturas de este cliente, afectando el saldo de Cuentas por Cobrar reportado.
            """)
    
    # --- CUENTAS POR PAGAR ---
    if abs(diff_cxp) > 0.01:
        with st.expander(f"🤝 Cuentas por Pagar (Diferencia: {formatear_diferencia(cx_p_calculado, cx_p_reportado)})", expanded=True):
            st.markdown(f"**Fórmula**: `CxP Calculado ({formato_venezolano(cx_p_calculado)})` vs `CxP Reportado ({formato_venezolano(cx_p_reportado)})`")
            st.markdown(f"La diferencia de **{formato_venezolano(diff_cxp)} Bs/USD** en Cuentas por Pagar puede explicarse por:")
            
            # Buscar transacciones coincidentes
            cands_cxp = []
            if 'df_recepciones' in locals() and df_recepciones is not None:
                cands_cxp.extend(buscar_candidatos_por_monto(df_recepciones, diff_cxp, "Recepciones de Mercancía"))
            if 'df_proveedores' in locals() and df_proveedores is not None:
                cands_cxp.extend(buscar_candidatos_por_monto(df_proveedores, diff_cxp, "Proveedores de Mercancía"))
            if 'df_notas_proveedor' in locals() and df_notas_proveedor is not None:
                cands_cxp.extend(buscar_candidatos_por_monto(df_notas_proveedor, diff_cxp, "Notas de Crédito Proveedores"))
            if 'df_cxp_rep' in locals() and df_cxp_rep is not None:
                cands_cxp.extend(buscar_candidatos_por_monto(df_cxp_rep, diff_cxp, "Reporte CxP"))
                
            if cands_cxp:
                st.info("🔍 **Transacciones con importe coincidente encontradas en los archivos:**")
                for c in cands_cxp[:5]:
                    st.markdown(f"- {c}")
            else:
                st.write("No se encontraron transacciones individuales con este importe exacto.")
                    
            # Mostrar cotejo automático de recepciones contra CxP
            df_recepciones_ok = 'df_recepciones' in locals() and df_recepciones is not None
            df_cxp_rep_ok = 'df_cxp_rep' in locals() and df_cxp_rep is not None
            
            if df_recepciones_ok and df_cxp_rep_ok:
                mostrar_cotejo_recepciones_cxp(df_recepciones, df_cxp_rep, fecha_procesar, st.session_state.empresa_activa, diff_cxp)
            else:
                st.info("ℹ️ *Sube el archivo de **Recepciones** para ver el cotejo automático de documentos (NE / OT) contra Cuentas por Pagar.*")
                
            st.markdown("""
            **💡 Puntos clave a revisar:**
            - **Pagos a Proveedores**: Valide si hay egresos ejecutados en iPago que no correspondan a facturas de proveedores de mercancía (p.ej., gastos de administración o servicios) que se clasificaron erróneamente.
            - **Notas de Crédito Recibidas**: Confirme si hay descuentos otorgados por proveedores que no se reflejaron en el balance de compras.
            """)
    
    # --- TRANSFERENCIAS EN TRÁNSITO ---
    if abs(diff_transito) > 0.01:
        with st.expander(f"✈️ Transferencias en Tránsito (Diferencia: {formatear_diferencia(transito_calculado, transito_reportado)})", expanded=True):
            st.markdown(f"**Fórmula**: `Tránsito Calculado ({formato_venezolano(transito_calculado)})` vs `Tránsito Reportado ({formato_venezolano(transito_reportado)})`")
            st.markdown(f"La diferencia de **{formato_venezolano(diff_transito)} Bs/USD** en Transferencias en Tránsito puede explicarse por:")
            
            # Buscar transacciones coincidentes
            cands_transito = []
            if 'df_cobranzas' in locals() and df_cobranzas is not None:
                cands_transito.extend(buscar_candidatos_por_monto(df_cobranzas, diff_transito, "Cobranzas Diarias"))
            if 'df_estado_cuenta' in locals() and df_estado_cuenta is not None:
                cands_transito.extend(buscar_candidatos_por_monto(df_estado_cuenta, diff_transito, "Estado de Cuenta Bancario"))
            if 'df_tb' in locals() and df_tb is not None:
                cands_transito.extend(buscar_candidatos_por_monto(df_tb, diff_transito, "Balanza / Tránsito"))
                
            if cands_transito:
                st.info("🔍 **Transacciones con importe coincidente encontradas en los archivos:**")
                for c in cands_transito[:5]:
                    st.markdown(f"- {c}")
            else:
                st.write("No se encontraron transacciones individuales con este importe exacto.")
                
            st.markdown("""
            **💡 Puntos clave a revisar:**
            - **Depósitos en Tránsito**: Cobranzas que fueron registradas en el sistema administrativo del día pero que ingresaron efectivamente al banco al día siguiente hábil.
            - **Egresos no debitados**: Pagos emitidos a proveedores mediante transferencia que aún no han sido cobrados o debitados por la entidad bancaria.
            """)
    
    # --- BANCOS ---
    if abs(diferencia_bancos) > 0.01:
        with st.expander(f"🏦 Bancos (Diferencia: {formatear_diferencia(bancos_calculado, saldo_final)})", expanded=True):
            st.markdown(f"**Fórmula**: `Bancos Calculado ({formato_venezolano(bancos_calculado)})` vs `Saldo Final Estado de Cuenta ({formato_venezolano(saldo_final)})`")
            st.markdown(f"La diferencia de **{formato_venezolano(diferencia_bancos)} Bs/USD** en Bancos puede explicarse por:")
            
            # Buscar transacciones coincidentes
            cands_bancos = []
            if 'df_estado_cuenta' in locals() and df_estado_cuenta is not None:
                cands_bancos.extend(buscar_candidatos_por_monto(df_estado_cuenta, diferencia_bancos, "Estado de Cuenta"))
            if 'df_cobranzas' in locals() and df_cobranzas is not None:
                cands_bancos.extend(buscar_candidatos_por_monto(df_cobranzas, diferencia_bancos, "Cobranzas Diarias"))
            if 'df_egresos' in locals() and df_egresos is not None:
                cands_bancos.extend(buscar_candidatos_por_monto(df_egresos, diferencia_bancos, "Egresos iPago"))
                
            if cands_bancos:
                st.info("🔍 **Transacciones con importe coincidente encontradas en los archivos:**")
                for c in cands_bancos[:5]:
                    st.markdown(f"- {c}")
            else:
                st.write("No se encontraron transacciones individuales con este importe exacto.")
                
            st.markdown("""
            **💡 Puntos clave a revisar:**
            - **Comisiones o Impuestos Bancarios (IGTF/IDB)**: Verifique si existen cobros de comisiones o impuestos en el estado de cuenta que no estén registrados en el sistema administrativo.
            - **Depósitos o Transferencias no identificados**: Revise si hay ingresos en el banco que no tengan soporte o no hayan sido notificados por ventas/cobranzas.
            - **Cheques o transferencias emitidas no cobradas**: Confirme si hay egresos del sistema que aún no han sido debitados por el banco.
            """)
            
    st.markdown("---")
    # ============================================================
    # 🔥 TRAZABILIDAD DE CUENTAS POR PAGAR - RUTA DE AUDITORÍA
    # ============================================================
    st.markdown("### 🔍 Trazabilidad de Cuentas por Pagar")
    st.caption("Análisis detallado: CxP Anterior + Recepciones - Pagos Proveedores = CxP Calculado vs CxP Reportado")
    
    # Mostrar el cálculo paso a paso
    st.markdown("#### 📊 Paso a paso del cálculo")
    
    col_p1, col_p2, col_p3, col_p4, col_p5 = st.columns(5)
    
    with col_p1:
        st.metric("📋 CxP Anterior", formato_venezolano(cx_p_anterior))
    with col_p2:
        st.metric("📦 Recepciones", formato_venezolano(recepcion_total))
    with col_p3:
        st.metric("💰 Pagos Proveedores", formato_venezolano(pagos_proveedores))
    with col_p4:
        st.metric("📊 CxP Calculado", formato_venezolano(cx_p_calculado))
    with col_p5:
        st.metric("📄 CxP Reportado", formato_venezolano(cx_p_reportado) if cx_p_reportado is not None else "N/A")
    
    # Verificar si hay diferencia
    diff_cxp = safe_number(cx_p_calculado) - safe_number(cx_p_reportado) if cx_p_reportado is not None else 0
    
    if abs(diff_cxp) < 0.01:
        st.success("✅ **¡CONCILIACIÓN PERFECTA!** El CxP Calculado coincide con el CxP Reportado.")
    else:
        st.error(f"⚠️ **DIFERENCIA DETECTADA:** {formato_venezolano(abs(diff_cxp))} Bs. de diferencia entre Calculado y Reportado")
        
        # ============================================================
        # 🔥 ANÁLISIS PROFUNDO DE DOCUMENTOS (NE / OT / FA)
        # ============================================================
        st.markdown("---")
        st.markdown("#### 🔍 Análisis de Documentos (NE / OT / FA)")
        
        # Verificar si tenemos los archivos necesarios
        tiene_recepciones = 'df_recepciones' in locals() and df_recepciones is not None
        tiene_cxp_rep = 'df_cxp_rep' in locals() and df_cxp_rep is not None
        tiene_cxp_ant = 'archivo_cxp_anterior' in globals() and archivo_cxp_anterior is not None
        
        if not tiene_recepciones and not tiene_cxp_rep:
            st.warning("⚠️ **Faltan archivos para el análisis profundo.** Sube el archivo de Recepciones y/o CxP Reportado para continuar.")
        else:
            try:
                import re
                import os
                from datetime import timedelta
                
                # ============================================================
                # 1. EXTRAER DOCUMENTOS DEL CxP ACTUAL
                # ============================================================
                st.markdown("##### 📋 Documentos en CxP Reportado (Día Actual)")
                
                cxp_actual_docs = {}
                if tiene_cxp_rep:
                    df_cxp_clean = ProcesadorArchivos._limpiar_columnas(df_cxp_rep)
                    # Buscar cabecera
                    idx_cxp = None
                    for idx, row in df_cxp_clean.iterrows():
                        row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                        if 'documento' in row_str and any(k in row_str for k in ['saldo', 'pendt', 'pendiente']):
                            idx_cxp = idx
                            break
                    if idx_cxp is None:
                        idx_cxp = ProcesadorArchivos._encontrar_fila_datos(df_cxp_clean, ['proveedor', 'documento', 'saldo'])
                    
                    if idx_cxp is not None and idx_cxp >= 0 and idx_cxp < len(df_cxp_clean):
                        df_datos = df_cxp_clean.iloc[idx_cxp:].reset_index(drop=True)
                        if len(df_datos) > 0:
                            header_row = df_datos.iloc[0]
                            new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                            df_datos.columns = new_cols
                            df_cxp_clean = df_datos.iloc[1:].reset_index(drop=True)
                    
                    # Buscar columnas
                    col_doc = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'documento', 'doc', 'factura', 'nro_doc', 'referencia')
                    col_monto = None
                    if len(df_cxp_clean.columns) > 2:
                        col_monto = df_cxp_clean.columns[2]
                    else:
                        col_monto = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'saldo', 'saldo pendt', 'pendiente', 'monto')
                    
                    # Buscar columna de proveedor
                    col_proveedor = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'proveedor', 'rif', 'nombre', 'razon social')
                    
                    if col_doc and col_monto:
                        for idx, row in df_cxp_clean.iterrows():
                            doc = str(row[col_doc]).strip()
                            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto])
                            if doc and doc != 'nan' and doc != 'None' and monto:
                                doc_norm = re.sub(r'[^0-9]', '', doc)
                                doc_norm = re.sub(r'^0+', '', doc_norm)
                                if doc_norm:
                                    doc_upper = doc.upper()
                                    # 🔥 CLASIFICACIÓN CORRECTA DE DOCUMENTOS
                                    if 'NE' in doc_upper:
                                        tipo = 'NE'
                                    elif 'OT' in doc_upper:
                                        tipo = 'OT'
                                    elif 'FA' in doc_upper or 'FACT' in doc_upper:
                                        tipo = 'FA'
                                    else:
                                        tipo = 'DESCONOCIDO'
                                    
                                    # Obtener proveedor
                                    proveedor = 'No identificado'
                                    if col_proveedor:
                                        try:
                                            prov_val = str(row[col_proveedor]).strip()
                                            if prov_val and prov_val != 'nan' and prov_val != 'None':
                                                proveedor = prov_val
                                        except:
                                            pass
                                    
                                    cxp_actual_docs[doc_norm] = {
                                        'original': doc,
                                        'monto': float(monto),
                                        'tipo': tipo,
                                        'proveedor': proveedor
                                    }
                
                st.info(f"📄 **{len(cxp_actual_docs)}** documentos encontrados en CxP Reportado")
                
                # Mostrar resumen por tipo
                tipos_actual = {}
                for doc in cxp_actual_docs.values():
                    tipos_actual[doc['tipo']] = tipos_actual.get(doc['tipo'], 0) + 1
                if tipos_actual:
                    st.write("**Clasificación:** " + ", ".join([f"{k}: {v}" for k, v in tipos_actual.items()]))
                
                # ============================================================
                # 2. EXTRAER DOCUMENTOS DEL CxP ANTERIOR
                # ============================================================
                st.markdown("##### 📋 Documentos en CxP Día Anterior")
                
                cxp_anterior_docs = {}
                if tiene_cxp_ant:
                    try:
                        df_cxp_ant = pd.read_excel(archivo_cxp_anterior)
                        df_cxp_ant_clean = ProcesadorArchivos._limpiar_columnas(df_cxp_ant)
                        
                        idx_ant = None
                        for idx, row in df_cxp_ant_clean.iterrows():
                            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                            if 'documento' in row_str and any(k in row_str for k in ['saldo', 'pendt', 'pendiente']):
                                idx_ant = idx
                                break
                        if idx_ant is None:
                            idx_ant = ProcesadorArchivos._encontrar_fila_datos(df_cxp_ant_clean, ['proveedor', 'documento', 'saldo'])
                        
                        if idx_ant is not None and idx_ant >= 0 and idx_ant < len(df_cxp_ant_clean):
                            df_datos = df_cxp_ant_clean.iloc[idx_ant:].reset_index(drop=True)
                            if len(df_datos) > 0:
                                header_row = df_datos.iloc[0]
                                new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                                df_datos.columns = new_cols
                                df_cxp_ant_clean = df_datos.iloc[1:].reset_index(drop=True)
                        
                        col_doc_ant = ProcesadorArchivos._buscar_columna(df_cxp_ant_clean, 'documento', 'doc', 'factura', 'nro_doc', 'referencia')
                        col_monto_ant = None
                        if len(df_cxp_ant_clean.columns) > 2:
                            col_monto_ant = df_cxp_ant_clean.columns[2]
                        else:
                            col_monto_ant = ProcesadorArchivos._buscar_columna(df_cxp_ant_clean, 'saldo', 'saldo pendt', 'pendiente', 'monto')
                        
                        if col_doc_ant and col_monto_ant:
                            for idx, row in df_cxp_ant_clean.iterrows():
                                doc = str(row[col_doc_ant]).strip()
                                monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_ant])
                                if doc and doc != 'nan' and doc != 'None' and monto:
                                    doc_norm = re.sub(r'[^0-9]', '', doc)
                                    doc_norm = re.sub(r'^0+', '', doc_norm)
                                    if doc_norm:
                                        doc_upper = doc.upper()
                                        if 'NE' in doc_upper:
                                            tipo = 'NE'
                                        elif 'OT' in doc_upper:
                                            tipo = 'OT'
                                        elif 'FA' in doc_upper or 'FACT' in doc_upper:
                                            tipo = 'FA'
                                        else:
                                            tipo = 'DESCONOCIDO'
                                        cxp_anterior_docs[doc_norm] = {
                                            'original': doc,
                                            'monto': float(monto),
                                            'tipo': tipo
                                        }
                    except Exception as e:
                        st.warning(f"⚠️ Error al leer CxP Anterior: {str(e)}")
                
                st.info(f"📄 **{len(cxp_anterior_docs)}** documentos encontrados en CxP Anterior")
                
                # ============================================================
                # 3. EXTRAER DOCUMENTOS DE RECEPCIONES
                # ============================================================
                st.markdown("##### 📦 Documentos en Recepciones")
                
                recepciones_docs = {}
                if tiene_recepciones:
                    df_rec_clean = ProcesadorArchivos._limpiar_columnas(df_recepciones)
                    
                    idx_rec = None
                    for idx, row in df_rec_clean.iterrows():
                        row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                        if 'compra' in row_str and 'proveedor' in row_str and 'recep' in row_str:
                            idx_rec = idx
                            break
                    if idx_rec is None:
                        idx_rec = ProcesadorArchivos._encontrar_fila_datos(df_rec_clean, ['compra', 'proveedor', 'recep'])
                    
                    if idx_rec is not None and idx_rec >= 0 and idx_rec < len(df_rec_clean):
                        df_datos = df_rec_clean.iloc[idx_rec:].reset_index(drop=True)
                        if len(df_datos) > 0:
                            header_row = df_datos.iloc[0]
                            new_cols = [str(col).strip() if pd.notna(col) else f'col_{i}' for i, col in enumerate(header_row)]
                            df_datos.columns = new_cols
                            df_rec_clean = df_datos.iloc[1:].reset_index(drop=True)
                    
                    # Buscar columnas
                    cols_doc_rec = []
                    for col in df_rec_clean.columns:
                        col_l = str(col).lower()
                        if 'fact' in col_l or 'compra' in col_l or 'documento' in col_l:
                            cols_doc_rec.append(col)
                    
                    col_rec_monto = None
                    for col in df_rec_clean.columns:
                        clean_col = re.sub(r'[^a-z0-9]', '', str(col).lower())
                        if 'neto' in clean_col and 'iva' in clean_col:
                            col_rec_monto = col
                            break
                    if col_rec_monto is None:
                        for col in df_rec_clean.columns:
                            clean_col = re.sub(r'[^a-z0-9]', '', str(col).lower())
                            if 'neto' in clean_col or 'total' in clean_col:
                                col_rec_monto = col
                                break
                    
                    if cols_doc_rec and col_rec_monto:
                        for idx, row in df_rec_clean.iterrows():
                            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_rec_monto])
                            if not monto:
                                continue
                            for col_doc in cols_doc_rec:
                                doc = str(row[col_doc]).strip()
                                if doc and doc != 'nan' and doc != 'None':
                                    doc_norm = re.sub(r'[^0-9]', '', doc)
                                    doc_norm = re.sub(r'^0+', '', doc_norm)
                                    if doc_norm:
                                        doc_upper = doc.upper()
                                        if 'NE' in doc_upper:
                                            tipo = 'NE'
                                        elif 'OT' in doc_upper:
                                            tipo = 'OT'
                                        elif 'FA' in doc_upper or 'FACT' in doc_upper:
                                            tipo = 'FA'
                                        else:
                                            tipo = 'DESCONOCIDO'
                                        recepciones_docs[doc_norm] = {
                                            'original': doc,
                                            'monto': float(monto),
                                            'tipo': tipo
                                        }
                
                st.info(f"📦 **{len(recepciones_docs)}** documentos encontrados en Recepciones")
                
                # ============================================================
                # 4. ANÁLISIS CRUZADO DE DOCUMENTOS
                # ============================================================
                st.markdown("---")
                st.markdown("#### 📊 Análisis Cruzado de Documentos")
                
                # 🔥 CLASIFICACIÓN CORRECTA DE CADA TIPO DE DOCUMENTO
                
                # 1. OT NUEVAS: Están en CxP Actual pero NO en CxP Anterior
                ot_nuevas = []
                for doc_norm, info in cxp_actual_docs.items():
                    if info['tipo'] == 'OT' and doc_norm not in cxp_anterior_docs:
                        ot_nuevas.append({
                            'documento': info['original'],
                            'monto': info['monto'],
                            'proveedor': info.get('proveedor', 'No identificado'),
                            'tipo': 'OT NUEVA (Carga Manual)'
                        })
                
                # 2. OT ELIMINADAS: Están en CxP Anterior pero NO en CxP Actual
                ot_eliminadas = []
                for doc_norm, info in cxp_anterior_docs.items():
                    if info['tipo'] == 'OT' and doc_norm not in cxp_actual_docs:
                        ot_eliminadas.append({
                            'documento': info['original'],
                            'monto': info['monto'],
                            'tipo': 'OT ELIMINADA'
                        })
                
                # 3. NE en Recepciones pero NO en CxP (Pago al Contado)
                ne_pago_contado = []
                for doc_norm, info in recepciones_docs.items():
                    if info['tipo'] == 'NE' and doc_norm not in cxp_actual_docs:
                        ne_pago_contado.append({
                            'documento': info['original'],
                            'monto': info['monto'],
                            'tipo': 'NE (Pago al Contado)'
                        })
                
                # 4. 🔥 FA en CxP pero NO en Recepciones (Facturas sin Recepción)
                fa_en_cxp_no_recepcion = []
                for doc_norm, info in cxp_actual_docs.items():
                    if info['tipo'] == 'FA' and doc_norm not in recepciones_docs:
                        fa_en_cxp_no_recepcion.append({
                            'documento': info['original'],
                            'monto': info['monto'],
                            'proveedor': info.get('proveedor', 'No identificado'),
                            'tipo': 'FA en CxP sin Recepción'
                        })
                
                # 5. NE en CxP pero NO en Recepciones (Notas de Entrega sin Recepción)
                ne_en_cxp_no_recepcion = []
                for doc_norm, info in cxp_actual_docs.items():
                    if info['tipo'] == 'NE' and doc_norm not in recepciones_docs:
                        ne_en_cxp_no_recepcion.append({
                            'documento': info['original'],
                            'monto': info['monto'],
                            'proveedor': info.get('proveedor', 'No identificado'),
                            'tipo': 'NE en CxP sin Recepción'
                        })
                
                # 6. FA en Recepciones pero NO en CxP (Facturas no registradas en CxP)
                fa_en_recepcion_no_cxp = []
                for doc_norm, info in recepciones_docs.items():
                    if info['tipo'] == 'FA' and doc_norm not in cxp_actual_docs:
                        fa_en_recepcion_no_cxp.append({
                            'documento': info['original'],
                            'monto': info['monto'],
                            'tipo': 'FA en Recepción sin CxP'
                        })
                
                # Calcular totales
                total_ot_nuevas = sum([x['monto'] for x in ot_nuevas])
                total_ot_eliminadas = sum([x['monto'] for x in ot_eliminadas])
                total_ne_pago_contado = sum([x['monto'] for x in ne_pago_contado])
                total_fa_en_cxp_no_recepcion = sum([x['monto'] for x in fa_en_cxp_no_recepcion])
                total_ne_en_cxp_no_recepcion = sum([x['monto'] for x in ne_en_cxp_no_recepcion])
                total_fa_en_recepcion_no_cxp = sum([x['monto'] for x in fa_en_recepcion_no_cxp])
                
                # Mostrar resultados en columnas
                st.markdown("##### 📊 Resultados del Análisis")
                
                col_a1, col_a2, col_a3 = st.columns(3)
                
                with col_a1:
                    st.metric("🆕 OT Nuevas (Carga Manual)", len(ot_nuevas), delta=f"{formato_venezolano(total_ot_nuevas)}")
                    if ot_nuevas:
                        st.warning(f"⚠️ {len(ot_nuevas)} OT nuevas detectadas")
                        for item in ot_nuevas[:3]:
                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])}")
                        if len(ot_nuevas) > 3:
                            st.write(f"... y {len(ot_nuevas) - 3} más")
                    else:
                        st.success("✅ No hay OT nuevas")
                
                with col_a2:
                    st.metric("🗑️ OT Eliminadas", len(ot_eliminadas), delta=f"{formato_venezolano(total_ot_eliminadas)}")
                    if ot_eliminadas:
                        st.info(f"ℹ️ {len(ot_eliminadas)} OT eliminadas")
                        for item in ot_eliminadas[:3]:
                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])}")
                        if len(ot_eliminadas) > 3:
                            st.write(f"... y {len(ot_eliminadas) - 3} más")
                    else:
                        st.success("✅ No hay OT eliminadas")
                
                with col_a3:
                    st.metric("⚠️ NE Pago al Contado", len(ne_pago_contado), delta=f"{formato_venezolano(total_ne_pago_contado)}")
                    if ne_pago_contado:
                        st.info(f"ℹ️ {len(ne_pago_contado)} NE pagadas al contado")
                        for item in ne_pago_contado[:3]:
                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])}")
                        if len(ne_pago_contado) > 3:
                            st.write(f"... y {len(ne_pago_contado) - 3} más")
                    else:
                        st.success("✅ No hay NE pagadas al contado")
                
                # Segunda fila de columnas
                col_b1, col_b2, col_b3 = st.columns(3)
                
                with col_b1:
                    st.metric("📄 FA en CxP sin Recepción", len(fa_en_cxp_no_recepcion), delta=f"{formato_venezolano(total_fa_en_cxp_no_recepcion)}")
                    if fa_en_cxp_no_recepcion:
                        st.error(f"❌ {len(fa_en_cxp_no_recepcion)} FA en CxP sin Recepción")
                        for item in fa_en_cxp_no_recepcion[:3]:
                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])} ({item['proveedor']})")
                        if len(fa_en_cxp_no_recepcion) > 3:
                            st.write(f"... y {len(fa_en_cxp_no_recepcion) - 3} más")
                    else:
                        st.success("✅ No hay FA sin Recepción")
                
                with col_b2:
                    st.metric("📄 NE en CxP sin Recepción", len(ne_en_cxp_no_recepcion), delta=f"{formato_venezolano(total_ne_en_cxp_no_recepcion)}")
                    if ne_en_cxp_no_recepcion:
                        st.warning(f"⚠️ {len(ne_en_cxp_no_recepcion)} NE en CxP sin Recepción")
                        for item in ne_en_cxp_no_recepcion[:3]:
                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])} ({item['proveedor']})")
                        if len(ne_en_cxp_no_recepcion) > 3:
                            st.write(f"... y {len(ne_en_cxp_no_recepcion) - 3} más")
                    else:
                        st.success("✅ No hay NE sin Recepción")
                
                with col_b3:
                    st.metric("📄 FA en Recepción sin CxP", len(fa_en_recepcion_no_cxp), delta=f"{formato_venezolano(total_fa_en_recepcion_no_cxp)}")
                    if fa_en_recepcion_no_cxp:
                        st.warning(f"⚠️ {len(fa_en_recepcion_no_cxp)} FA en Recepción sin CxP")
                        for item in fa_en_recepcion_no_cxp[:3]:
                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])}")
                        if len(fa_en_recepcion_no_cxp) > 3:
                            st.write(f"... y {len(fa_en_recepcion_no_cxp) - 3} más")
                    else:
                        st.success("✅ No hay FA sin CxP")
                
                # ============================================================
                # 5. RESULTADO DEL ANÁLISIS - DIAGNÓSTICO FINAL
                # ============================================================
                st.markdown("---")
                st.markdown("#### 🎯 Diagnóstico de la Diferencia")
                
                # Calcular diferencia explicada
                # La diferencia se explica por: OT Nuevas + NE Pago al Contado + FA en Recepción sin CxP
                diferencia_explicada = total_ot_nuevas + total_ne_pago_contado + total_fa_en_recepcion_no_cxp
                diferencia_no_explicada = abs(diff_cxp) - diferencia_explicada
                
                st.markdown(f"""
                | Concepto | Monto | Explicación |
                |----------|-------|-------------|
                | **Diferencia Total** | {formato_venezolano(abs(diff_cxp))} | Diferencia en CxP Calculado vs Reportado |
                | 🆕 **OT Nuevas (Carga Manual)** | {formato_venezolano(total_ot_nuevas)} | Documentos OT que no estaban en CxP Anterior |
                | ⚠️ **NE (Pago al Contado)** | {formato_venezolano(total_ne_pago_contado)} | NE en Recepciones pero NO en CxP |
                | 📄 **FA en Recepción sin CxP** | {formato_venezolano(total_fa_en_recepcion_no_cxp)} | Facturas en Recepción pero NO en CxP |
                | 🗑️ **OT Eliminadas** | {formato_venezolano(total_ot_eliminadas)} | Documentos que salieron del CxP |
                | 📄 **FA en CxP sin Recepción** | {formato_venezolano(total_fa_en_cxp_no_recepcion)} | Facturas en CxP pero NO en Recepciones |
                | 📄 **NE en CxP sin Recepción** | {formato_venezolano(total_ne_en_cxp_no_recepcion)} | NE en CxP pero NO en Recepciones |
                | **Diferencia Explicada** | {formato_venezolano(diferencia_explicada)} | Suma de OT Nuevas + NE Pago al Contado + FA en Recepción sin CxP |
                | **Diferencia NO Explicada** | {formato_venezolano(diferencia_no_explicada)} | ⚠️ Requiere revisión manual |
                """)
                
                if abs(diferencia_no_explicada) < 0.01:
                    st.success("✅ **¡DIFERENCIA EXPLICADA COMPLETAMENTE!** Todos los documentos coinciden con la variación en CxP.")
                    
                    # Mostrar resumen de la conciliación
                    st.markdown("#### 📋 Resumen de Conciliación")
                    
                    resumen_parts = []
                    if len(ot_nuevas) > 0:
                        resumen_parts.append(f"🆕 **{len(ot_nuevas)} OT Nuevas** (Carga Manual): {formato_venezolano(total_ot_nuevas)}")
                    if len(ne_pago_contado) > 0:
                        resumen_parts.append(f"⚠️ **{len(ne_pago_contado)} NE (Pago al Contado)**: {formato_venezolano(total_ne_pago_contado)}")
                    if len(fa_en_recepcion_no_cxp) > 0:
                        resumen_parts.append(f"📄 **{len(fa_en_recepcion_no_cxp)} FA en Recepción sin CxP**: {formato_venezolano(total_fa_en_recepcion_no_cxp)}")
                    
                    if resumen_parts:
                        st.markdown(f"""
                        **La diferencia de {formato_venezolano(abs(diff_cxp))} en CxP se explica por:**
                        
                        {chr(10).join(['- ' + p for p in resumen_parts])}
                        
                        ✅ **Todas las diferencias están justificadas.**
                        """)
                    else:
                        st.success("✅ No hay diferencias que explicar.")
                else:
                    st.error(f"❌ **DIFERENCIA NO EXPLICADA:** {formato_venezolano(diferencia_no_explicada)} Bs. no identificados.")
                    st.markdown("""
                    **Posibles causas:**
                    - Documentos con formato diferente (no reconocidos como NE/OT/FA)
                    - Errores de digitación en montos
                    - Documentos duplicados o faltantes en los archivos
                    - Recepciones sin documento asociado
                    - Ajustes manuales no registrados
                    """)
                    
                    # Mostrar documentos no clasificados
                    docs_no_clasificados = []
                    for doc_norm, info in cxp_actual_docs.items():
                        if info['tipo'] == 'DESCONOCIDO':
                            docs_no_clasificados.append({
                                'documento': info['original'],
                                'monto': info['monto'],
                                'proveedor': info.get('proveedor', 'No identificado')
                            })
                    
                    if docs_no_clasificados:
                        st.warning(f"⚠️ **{len(docs_no_clasificados)} documentos no clasificados** en CxP (no son NE, OT o FA):")
                        df_no_clas = pd.DataFrame(docs_no_clasificados)
                        st.dataframe(df_no_clas, width='stretch')
                
            except Exception as e:
                st.error(f"❌ Error en el análisis de documentos: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    st.markdown("---")
    # ============================================================
    # 🔥 TRAZABILIDAD DE TRANSFERENCIAS EN TRÁNSITO
    # ============================================================
    st.markdown("### 🔍 Trazabilidad de Transferencias en Tránsito")
    st.caption("Análisis detallado: Tránsito Anterior + Ingresos - Cobranzas = Tránsito Calculado vs Tránsito Reportado")
    
    # Mostrar el cálculo paso a paso
    st.markdown("#### 📊 Paso a paso del cálculo")
    
    col_t1, col_t2, col_t3, col_t4, col_t5 = st.columns(5)
    
    with col_t1:
        st.metric("🔄 Tránsito Anterior", formato_venezolano(transito_anterior))
    with col_t2:
        st.metric("📈 Total Ingresos", formato_venezolano(total_ingresos))
    with col_t3:
        st.metric("💰 Cobranzas Procesadas", formato_venezolano(cobranzas))
    with col_t4:
        st.metric("📊 Tránsito Calculado", formato_venezolano(transito_calculado))
    with col_t5:
        st.metric("📄 Tránsito Reportado", formato_venezolano(transito_reportado) if transito_reportado is not None else "N/A")
    
    # Verificar si hay diferencia
    diff_transito = safe_number(transito_calculado) - safe_number(transito_reportado) if transito_reportado is not None else 0
    
    if abs(diff_transito) < 0.01:
        st.success("✅ **¡CONCILIACIÓN PERFECTA!** El Tránsito Calculado coincide con el Tránsito Reportado.")
    else:
        st.error(f"⚠️ **DIFERENCIA DETECTADA:** {formato_venezolano(abs(diff_transito))} Bs. de diferencia entre Calculado y Reportado")
        
        # ============================================================
        # 🔥 ANÁLISIS PROFUNDO DE TRANSFERENCIAS EN TRÁNSITO
        # ============================================================
        st.markdown("---")
        st.markdown("#### 🔍 Análisis de Transferencias en Tránsito")
        
        # Verificar si tenemos los archivos necesarios
        tiene_cobranzas = 'df_cobranzas' in locals() and df_cobranzas is not None
        tiene_tb = 'df_tb' in locals() and df_tb is not None
        tiene_estado_cuenta = 'df_estado_cuenta' in locals() and df_estado_cuenta is not None
        
        if not tiene_cobranzas and not tiene_tb:
            st.warning("⚠️ **Faltan archivos para el análisis profundo.** Sube el archivo de Cobranzas y/o TB (Transferencias en Tránsito) para continuar.")
        else:
            try:
                import re
                
                # ============================================================
                # 1. EXTRAER TRANSFERENCIAS DEL ARCHIVO TB (TRÁNSITO REPORTADO)
                # ============================================================
                st.markdown("##### 📄 Transferencias en Tránsito Reportado (TB)")
                
                tb_docs = {}
                if tiene_tb:
                    df_tb_clean = ProcesadorArchivos._limpiar_columnas(df_tb)
                    
                    # Buscar cabecera en TB
                    idx_tb = None
                    for idx, row in df_tb_clean.iterrows():
                        row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                        if any(k in row_str for k in ['total tb', 'tb', 'transferencia']):
                            idx_tb = idx
                            break
                    if idx_tb is None:
                        idx_tb = ProcesadorArchivos._encontrar_fila_datos(df_tb_clean, ['banco', 'referencia', 'monto'])
                    
                    if idx_tb is not None and idx_tb >= 0 and idx_tb < len(df_tb_clean):
                        df_datos = df_tb_clean.iloc[idx_tb:].reset_index(drop=True)
                        if len(df_datos) > 0:
                            header_row = df_datos.iloc[0]
                            new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                            df_datos.columns = new_cols
                            df_tb_clean = df_datos.iloc[1:].reset_index(drop=True)
                    
                    # Buscar columnas
                    col_ref = ProcesadorArchivos._buscar_columna(df_tb_clean, 'referencia', 'nro', 'deposito', 'documento')
                    col_monto_tb = ProcesadorArchivos._buscar_columna(df_tb_clean, 'monto', 'total', 'importe', 'saldo')
                    col_banco = ProcesadorArchivos._buscar_columna(df_tb_clean, 'banco', 'cuenta', 'entidad')
                    col_fecha_tb = ProcesadorArchivos._buscar_columna(df_tb_clean, 'fecha', 'fec', 'f. contable')
                    
                    if col_ref and col_monto_tb:
                        for idx, row in df_tb_clean.iterrows():
                            ref = str(row[col_ref]).strip()
                            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_tb])
                            if ref and ref != 'nan' and ref != 'None' and monto:
                                ref_norm = re.sub(r'[^0-9]', '', ref)
                                if ref_norm:
                                    fecha = ''
                                    if col_fecha_tb:
                                        try:
                                            fecha_val = row[col_fecha_tb]
                                            if pd.notna(fecha_val):
                                                if isinstance(fecha_val, pd.Timestamp):
                                                    fecha = fecha_val.strftime('%d/%m/%Y')
                                                else:
                                                    fecha = str(fecha_val).strip()
                                        except:
                                            pass
                                    
                                    banco = ''
                                    if col_banco:
                                        try:
                                            banco_val = str(row[col_banco]).strip()
                                            if banco_val and banco_val != 'nan' and banco_val != 'None':
                                                banco = banco_val
                                        except:
                                            pass
                                    
                                    tb_docs[ref_norm] = {
                                        'referencia': ref,
                                        'monto': float(monto),
                                        'banco': banco,
                                        'fecha': fecha,
                                        'tipo': 'TRÁNSITO'
                                    }
                
                st.info(f"📄 **{len(tb_docs)}** transferencias encontradas en TB (Tránsito Reportado)")
                
                # ============================================================
                # 2. EXTRAER COBRANZAS DEL ARCHIVO DE COBRANZAS
                # ============================================================
                st.markdown("##### 💰 Cobranzas Procesadas")
                
                cobranzas_docs = {}
                if tiene_cobranzas:
                    df_cob_clean = ProcesadorArchivos._limpiar_columnas(df_cobranzas)
                    
                    # Buscar cabecera en Cobranzas
                    idx_cob = None
                    for idx, row in df_cob_clean.iterrows():
                        row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                        if 'banco' in row_str and 'cuenta' in row_str and 'deposito' in row_str:
                            idx_cob = idx
                            break
                    if idx_cob is None:
                        idx_cob = ProcesadorArchivos._encontrar_fila_datos(df_cob_clean, ['banco', 'deposito', 'monto'])
                    
                    if idx_cob is not None and idx_cob >= 0 and idx_cob < len(df_cob_clean):
                        df_datos = df_cob_clean.iloc[idx_cob:].reset_index(drop=True)
                        if len(df_datos) > 0:
                            header_row = df_datos.iloc[0]
                            new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                            df_datos.columns = new_cols
                            df_cob_clean = df_datos.iloc[1:].reset_index(drop=True)
                    
                    # Buscar columnas
                    col_ref_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'deposito', 'nro', 'referencia', 'documento')
                    col_monto_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'monto', 'total', 'importe')
                    col_banco_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'banco', 'cuenta', 'entidad')
                    col_fecha_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'fecha', 'fec', 'f. cobranza')
                    
                    if col_ref_cob and col_monto_cob:
                        for idx, row in df_cob_clean.iterrows():
                            ref = str(row[col_ref_cob]).strip()
                            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_cob])
                            if ref and ref != 'nan' and ref != 'None' and monto:
                                ref_norm = re.sub(r'[^0-9]', '', ref)
                                if ref_norm:
                                    fecha = ''
                                    if col_fecha_cob:
                                        try:
                                            fecha_val = row[col_fecha_cob]
                                            if pd.notna(fecha_val):
                                                if isinstance(fecha_val, pd.Timestamp):
                                                    fecha = fecha_val.strftime('%d/%m/%Y')
                                                else:
                                                    fecha = str(fecha_val).strip()
                                        except:
                                            pass
                                    
                                    banco = ''
                                    if col_banco_cob:
                                        try:
                                            banco_val = str(row[col_banco_cob]).strip()
                                            if banco_val and banco_val != 'nan' and banco_val != 'None':
                                                banco = banco_val
                                        except:
                                            pass
                                    
                                    cobranzas_docs[ref_norm] = {
                                        'referencia': ref,
                                        'monto': float(monto),
                                        'banco': banco,
                                        'fecha': fecha,
                                        'tipo': 'COBRANZA'
                                    }
                
                st.info(f"💰 **{len(cobranzas_docs)}** cobranzas encontradas")
                
                # ============================================================
                # 3. EXTRAER INGRESOS DEL ESTADO DE CUENTA
                # ============================================================
                st.markdown("##### 🏦 Ingresos del Estado de Cuenta")
                
                ingresos_docs = {}
                if tiene_estado_cuenta:
                    try:
                        df_ec_clean = ProcesadorArchivos._limpiar_columnas(df_estado_cuenta)
                        
                        # Buscar cabecera en Estado de Cuenta
                        idx_ec = None
                        for idx, row in df_ec_clean.iterrows():
                            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                            if 'fecha' in row_str and ('credito' in row_str or 'debito' in row_str):
                                idx_ec = idx
                                break
                        if idx_ec is None:
                            idx_ec = ProcesadorArchivos._encontrar_fila_datos(df_ec_clean, ['fecha', 'credito', 'debito'])
                        
                        if idx_ec is not None and idx_ec >= 0 and idx_ec < len(df_ec_clean):
                            df_datos = df_ec_clean.iloc[idx_ec:].reset_index(drop=True)
                            if len(df_datos) > 0:
                                header_row = df_datos.iloc[0]
                                new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                                df_datos.columns = new_cols
                                df_ec_clean = df_datos.iloc[1:].reset_index(drop=True)
                        
                        # Buscar columnas
                        col_ref_ec = ProcesadorArchivos._buscar_columna(df_ec_clean, 'referencia', 'nro', 'documento', 'descripción')
                        col_credito = ProcesadorArchivos._buscar_columna(df_ec_clean, 'credito', 'abono', 'ingreso')
                        col_fecha_ec = ProcesadorArchivos._buscar_columna(df_ec_clean, 'fecha', 'fec', 'f. contable')
                        
                        if col_ref_ec and col_credito:
                            for idx, row in df_ec_clean.iterrows():
                                ref = str(row[col_ref_ec]).strip()
                                credito = ProcesadorArchivos._convertir_numero_europeo(row[col_credito])
                                if ref and ref != 'nan' and ref != 'None' and credito and credito > 0:
                                    ref_norm = re.sub(r'[^0-9]', '', ref)
                                    if ref_norm:
                                        fecha = ''
                                        if col_fecha_ec:
                                            try:
                                                fecha_val = row[col_fecha_ec]
                                                if pd.notna(fecha_val):
                                                    if isinstance(fecha_val, pd.Timestamp):
                                                        fecha = fecha_val.strftime('%d/%m/%Y')
                                                    else:
                                                        fecha = str(fecha_val).strip()
                                            except:
                                                pass
                                        
                                        ingresos_docs[ref_norm] = {
                                            'referencia': ref,
                                            'monto': float(credito),
                                            'banco': 'Estado de Cuenta',
                                            'fecha': fecha,
                                            'tipo': 'INGRESO'
                                        }
                    except Exception as e:
                        st.warning(f"⚠️ Error al leer Estado de Cuenta: {str(e)}")
                
                st.info(f"🏦 **{len(ingresos_docs)}** ingresos encontrados en Estado de Cuenta")
                
                # ============================================================
                # 4. ANÁLISIS CRUZADO
                # ============================================================
                st.markdown("---")
                st.markdown("#### 📊 Análisis Cruzado de Transferencias")
                
                # IDENTIFICAR TRANSFERENCIAS EN TRÁNSITO QUE YA FUERON COBRADAS
                # Una transferencia en tránsito se "convierte" en cobranza cuando:
                # - La referencia existe en TB (Tránsito)
                # - Y la misma referencia existe en Cobranzas Procesadas
                # - O la misma referencia existe en Ingresos del Estado de Cuenta
                
                transito_ya_cobrado = []
                for ref_norm, info in tb_docs.items():
                    # Verificar si la referencia está en Cobranzas
                    if ref_norm in cobranzas_docs:
                        transito_ya_cobrado.append({
                            'referencia': info['referencia'],
                            'monto_transito': info['monto'],
                            'monto_cobranza': cobranzas_docs[ref_norm]['monto'],
                            'banco': info.get('banco', 'No identificado'),
                            'fecha': info.get('fecha', 'No disponible'),
                            'estado': '✅ YA COBRADO (Coincide con Cobranzas)'
                        })
                    # Verificar si la referencia está en Ingresos del Estado de Cuenta
                    elif ref_norm in ingresos_docs:
                        transito_ya_cobrado.append({
                            'referencia': info['referencia'],
                            'monto_transito': info['monto'],
                            'monto_ingreso': ingresos_docs[ref_norm]['monto'],
                            'banco': info.get('banco', 'No identificado'),
                            'fecha': info.get('fecha', 'No disponible'),
                            'estado': '✅ YA COBRADO (Coincide con Ingresos E/C)'
                        })
                
                # IDENTIFICAR TRANSFERENCIAS EN TRÁNSITO QUE AÚN NO HAN SIDO COBRADAS
                transito_pendiente = []
                for ref_norm, info in tb_docs.items():
                    if ref_norm not in cobranzas_docs and ref_norm not in ingresos_docs:
                        transito_pendiente.append({
                            'referencia': info['referencia'],
                            'monto': info['monto'],
                            'banco': info.get('banco', 'No identificado'),
                            'fecha': info.get('fecha', 'No disponible'),
                            'estado': '⏳ PENDIENTE DE COBRO (No está en Cobranzas ni en E/C)'
                        })
                
                # IDENTIFICAR COBRANZAS QUE NO ESTÁN EN TRÁNSITO (Ya fueron procesadas)
                cobranzas_sin_transito = []
                for ref_norm, info in cobranzas_docs.items():
                    if ref_norm not in tb_docs:
                        cobranzas_sin_transito.append({
                            'referencia': info['referencia'],
                            'monto': info['monto'],
                            'banco': info.get('banco', 'No identificado'),
                            'fecha': info.get('fecha', 'No disponible'),
                            'estado': '✅ PROCESADA (Ya no está en Tránsito)'
                        })
                
                # Calcular totales
                total_ya_cobrado = sum([x.get('monto_transito', x.get('monto', 0)) for x in transito_ya_cobrado])
                total_pendiente = sum([x['monto'] for x in transito_pendiente])
                total_cobranzas_procesadas = sum([x['monto'] for x in cobranzas_sin_transito])
                
                # Mostrar resultados
                col_r1, col_r2, col_r3 = st.columns(3)
                
                with col_r1:
                    st.metric("✅ Ya Cobradas", len(transito_ya_cobrado), delta=f"{formato_venezolano(total_ya_cobrado)}")
                    if transito_ya_cobrado:
                        st.success(f"✅ {len(transito_ya_cobrado)} transferencias ya fueron cobradas")
                        for item in transito_ya_cobrado[:3]:
                            st.write(f"- 📄 {item['referencia']}: {formato_venezolano(item['monto_transito'])}")
                        if len(transito_ya_cobrado) > 3:
                            st.write(f"... y {len(transito_ya_cobrado) - 3} más")
                    else:
                        st.info("ℹ️ No hay transferencias ya cobradas")
                
                with col_r2:
                    st.metric("⏳ Pendientes de Cobro", len(transito_pendiente), delta=f"{formato_venezolano(total_pendiente)}")
                    if transito_pendiente:
                        st.warning(f"⏳ {len(transito_pendiente)} transferencias pendientes de cobro")
                        for item in transito_pendiente[:3]:
                            st.write(f"- 📄 {item['referencia']}: {formato_venezolano(item['monto'])}")
                        if len(transito_pendiente) > 3:
                            st.write(f"... y {len(transito_pendiente) - 3} más")
                    else:
                        st.success("✅ No hay transferencias pendientes")
                
                with col_r3:
                    st.metric("✅ Cobranzas Procesadas", len(cobranzas_sin_transito), delta=f"{formato_venezolano(total_cobranzas_procesadas)}")
                    if cobranzas_sin_transito:
                        st.info(f"ℹ️ {len(cobranzas_sin_transito)} cobranzas ya procesadas (salieron de Tránsito)")
                        for item in cobranzas_sin_transito[:3]:
                            st.write(f"- 📄 {item['referencia']}: {formato_venezolano(item['monto'])}")
                        if len(cobranzas_sin_transito) > 3:
                            st.write(f"... y {len(cobranzas_sin_transito) - 3} más")
                    else:
                        st.success("✅ No hay cobranzas procesadas")
                
                # ============================================================
                # 5. DIAGNÓSTICO FINAL
                # ============================================================
                st.markdown("---")
                st.markdown("#### 🎯 Diagnóstico de la Diferencia")
                
                # La diferencia se explica por: 
                # - Transferencias pendientes (deben estar en Tránsito)
                # - Cobranzas procesadas (ya no están en Tránsito)
                diferencia_explicada_transito = total_pendiente + total_cobranzas_procesadas
                diferencia_no_explicada_transito = abs(diff_transito) - diferencia_explicada_transito
                
                st.markdown(f"""
                | Concepto | Monto | Explicación |
                |----------|-------|-------------|
                | **Diferencia Total** | {formato_venezolano(abs(diff_transito))} | Diferencia en Tránsito Calculado vs Reportado |
                | ⏳ **Transferencias Pendientes** | {formato_venezolano(total_pendiente)} | Transferencias en TB que NO están en Cobranzas |
                | ✅ **Cobranzas Procesadas** | {formato_venezolano(total_cobranzas_procesadas)} | Cobranzas que ya no están en Tránsito |
                | ✅ **Transferencias Ya Cobradas** | {formato_venezolano(total_ya_cobrado)} | Transferencias que coinciden con Cobranzas |
                | **Diferencia Explicada** | {formato_venezolano(diferencia_explicada_transito)} | Suma de Pendientes + Cobranzas Procesadas |
                | **Diferencia NO Explicada** | {formato_venezolano(diferencia_no_explicada_transito)} | ⚠️ Requiere revisión manual |
                """)
                
                if abs(diferencia_no_explicada_transito) < 0.01:
                    st.success("✅ **¡DIFERENCIA EXPLICADA COMPLETAMENTE!** Todas las transferencias coinciden con la variación en Tránsito.")
                    
                    # Mostrar resumen de la conciliación
                    st.markdown("#### 📋 Resumen de Conciliación de Tránsito")
                    
                    resumen_parts = []
                    if len(transito_pendiente) > 0:
                        resumen_parts.append(f"⏳ **{len(transito_pendiente)} Transferencias Pendientes**: {formato_venezolano(total_pendiente)}")
                    if len(cobranzas_sin_transito) > 0:
                        resumen_parts.append(f"✅ **{len(cobranzas_sin_transito)} Cobranzas Procesadas**: {formato_venezolano(total_cobranzas_procesadas)}")
                    if len(transito_ya_cobrado) > 0:
                        resumen_parts.append(f"✅ **{len(transito_ya_cobrado)} Transferencias Ya Cobradas**: {formato_venezolano(total_ya_cobrado)}")
                    
                    if resumen_parts:
                        st.markdown(f"""
                        **La diferencia de {formato_venezolano(abs(diff_transito))} en Transferencias en Tránsito se explica por:**
                        
                        {chr(10).join(['- ' + p for p in resumen_parts])}
                        
                        ✅ **Todas las diferencias están justificadas.**
                        """)
                    else:
                        st.success("✅ No hay diferencias que explicar.")
                else:
                    st.error(f"❌ **DIFERENCIA NO EXPLICADA:** {formato_venezolano(diferencia_no_explicada_transito)} Bs. no identificados.")
                    st.markdown("""
                    **Posibles causas:**
                    - Transferencias en Tránsito sin referencia clara
                    - Cobranzas que no están registradas en el archivo TB
                    - Errores de digitación en montos o referencias
                    - Transferencias de días anteriores que no fueron conciliadas
                    - Depósitos que aún no han sido procesados por el banco
                    """)
                    
                    # Mostrar referencias no coincidentes
                    referencias_tb = set(tb_docs.keys())
                    referencias_cob = set(cobranzas_docs.keys())
                    referencias_ing = set(ingresos_docs.keys())
                    
                    referencias_no_encontradas = referencias_tb - referencias_cob - referencias_ing
                    if referencias_no_encontradas:
                        st.warning(f"⚠️ **{len(referencias_no_encontradas)} referencias en TB que no coinciden con Cobranzas ni Ingresos:**")
                        for ref in list(referencias_no_encontradas)[:10]:
                            info = tb_docs.get(ref, {})
                            st.write(f"- {info.get('referencia', ref)}: {formato_venezolano(info.get('monto', 0))}")
                        if len(referencias_no_encontradas) > 10:
                            st.write(f"... y {len(referencias_no_encontradas) - 10} más")
                
                # ============================================================
                # 6. TABLA DETALLADA DE TRANSFERENCIAS
                # ============================================================
                with st.expander("📋 Ver detalle completo de transferencias", expanded=False):
                    st.markdown("##### ✅ Transferencias Ya Cobradas")
                    if transito_ya_cobrado:
                        df_ya_cobrado = pd.DataFrame(transito_ya_cobrado)
                        st.dataframe(df_ya_cobrado, width='stretch')
                    else:
                        st.info("No hay transferencias ya cobradas")
                    
                    st.markdown("##### ⏳ Transferencias Pendientes")
                    if transito_pendiente:
                        df_pendiente = pd.DataFrame(transito_pendiente)
                        st.dataframe(df_pendiente, width='stretch')
                    else:
                        st.info("No hay transferencias pendientes")
                    
                    st.markdown("##### ✅ Cobranzas Procesadas (Ya no están en Tránsito)")
                    if cobranzas_sin_transito:
                        df_procesadas = pd.DataFrame(cobranzas_sin_transito)
                        st.dataframe(df_procesadas, width='stretch')
                    else:
                        st.info("No hay cobranzas procesadas")
                
            except Exception as e:
                st.error(f"❌ Error en el análisis de transferencias: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    
    st.markdown("---")
    # ============================================================
    # 🔥 TRAZABILIDAD DE CUENTAS POR COBRAR
    # ============================================================
    st.markdown("### 🔍 Trazabilidad de Cuentas por Cobrar")
    st.caption("Análisis detallado: CxC Anterior + Facturación - Cobranzas = CxC Calculado vs CxC Reportado")
    
    # Mostrar el cálculo paso a paso
    st.markdown("#### 📊 Paso a paso del cálculo")
    
    col_c1, col_c2, col_c3, col_c4, col_c5 = st.columns(5)
    
    with col_c1:
        st.metric("💰 CxC Anterior", formato_venezolano(cx_c_anterior))
    with col_c2:
        st.metric("📊 Facturación", formato_venezolano(facturacion))
    with col_c3:
        st.metric("💰 Cobranzas Procesadas", formato_venezolano(cobranzas))
    with col_c4:
        st.metric("📊 CxC Calculado", formato_venezolano(cx_c_calculado))
    with col_c5:
        st.metric("📄 CxC Reportado", formato_venezolano(cx_c_reportado) if cx_c_reportado is not None else "N/A")
    
    # Verificar si hay diferencia
    diff_cxc = safe_number(cx_c_calculado) - safe_number(cx_c_reportado) if cx_c_reportado is not None else 0
    
    if abs(diff_cxc) < 0.01:
        st.success("✅ **¡CONCILIACIÓN PERFECTA!** El CxC Calculado coincide con el CxC Reportado.")
    else:
        st.error(f"⚠️ **DIFERENCIA DETECTADA:** {formato_venezolano(abs(diff_cxc))} Bs. de diferencia entre Calculado y Reportado")
        
        # ============================================================
        # 🔥 ANÁLISIS PROFUNDO DE CUENTAS POR COBRAR
        # ============================================================
        st.markdown("---")
        st.markdown("#### 🔍 Análisis de Cobranzas Duplicadas o Rezagadas")
        st.caption("Verificación de cobranzas que se repiten entre días o que están rezagadas")
        
        # Verificar si tenemos los archivos necesarios
        tiene_cobranzas = 'df_cobranzas' in locals() and df_cobranzas is not None
        tiene_cxc_reportado = 'df_cxc_rep' in locals() and df_cxc_rep is not None
        tiene_facturacion = 'df_facturacion' in locals() and df_facturacion is not None
        
        if not tiene_cobranzas and not tiene_cxc_reportado:
            st.warning("⚠️ **Faltan archivos para el análisis profundo.** Sube el archivo de Cobranzas y/o CxC Reportado para continuar.")
        else:
            try:
                import re
                import os
                from datetime import timedelta
                from config import RUTA_ARCHIVOS
                
                # ============================================================
                # 1. EXTRAER COBRANZAS DEL ARCHIVO DE COBRANZAS PROCESADAS (DÍA ACTUAL)
                # ============================================================
                st.markdown("##### 💰 Cobranzas Procesadas del Día Actual")
                
                cobranzas_actual_docs = {}
                if tiene_cobranzas:
                    df_cob_clean = ProcesadorArchivos._limpiar_columnas(df_cobranzas)
                    
                    # Buscar cabecera en Cobranzas
                    idx_cob = None
                    for idx, row in df_cob_clean.iterrows():
                        row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                        if 'banco' in row_str and 'cuenta' in row_str and 'deposito' in row_str:
                            idx_cob = idx
                            break
                    if idx_cob is None:
                        idx_cob = ProcesadorArchivos._encontrar_fila_datos(df_cob_clean, ['banco', 'deposito', 'monto'])
                    
                    if idx_cob is not None and idx_cob >= 0 and idx_cob < len(df_cob_clean):
                        df_datos = df_cob_clean.iloc[idx_cob:].reset_index(drop=True)
                        if len(df_datos) > 0:
                            header_row = df_datos.iloc[0]
                            new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                            df_datos.columns = new_cols
                            df_cob_clean = df_datos.iloc[1:].reset_index(drop=True)
                    
                    # Buscar columnas
                    col_ref_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'deposito', 'nro', 'referencia', 'documento')
                    col_monto_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'monto', 'total', 'importe')
                    col_banco_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'banco', 'cuenta', 'entidad')
                    col_fecha_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'fecha', 'fec', 'f. cobranza')
                    col_cliente_cob = ProcesadorArchivos._buscar_columna(df_cob_clean, 'cliente', 'nombre', 'rif', 'cedula')
                    
                    if col_ref_cob and col_monto_cob:
                        for idx, row in df_cob_clean.iterrows():
                            ref = str(row[col_ref_cob]).strip()
                            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_cob])
                            if ref and ref != 'nan' and ref != 'None' and monto:
                                ref_norm = re.sub(r'[^0-9]', '', ref)
                                if ref_norm:
                                    fecha = ''
                                    if col_fecha_cob:
                                        try:
                                            fecha_val = row[col_fecha_cob]
                                            if pd.notna(fecha_val):
                                                if isinstance(fecha_val, pd.Timestamp):
                                                    fecha = fecha_val.strftime('%d/%m/%Y')
                                                else:
                                                    fecha = str(fecha_val).strip()
                                        except:
                                            pass
                                    
                                    banco = ''
                                    if col_banco_cob:
                                        try:
                                            banco_val = str(row[col_banco_cob]).strip()
                                            if banco_val and banco_val != 'nan' and banco_val != 'None':
                                                banco = banco_val
                                        except:
                                            pass
                                    
                                    cliente = ''
                                    if col_cliente_cob:
                                        try:
                                            cliente_val = str(row[col_cliente_cob]).strip()
                                            if cliente_val and cliente_val != 'nan' and cliente_val != 'None':
                                                cliente = cliente_val
                                        except:
                                            pass
                                    
                                    cobranzas_actual_docs[ref_norm] = {
                                        'referencia': ref,
                                        'monto': float(monto),
                                        'banco': banco,
                                        'fecha': fecha,
                                        'cliente': cliente,
                                        'tipo': 'COBRANZA_ACTUAL'
                                    }
                
                st.info(f"💰 **{len(cobranzas_actual_docs)}** cobranzas encontradas en el día actual")
                
                # ============================================================
                # 2. EXTRAER COBRANZAS DEL DÍA ANTERIOR (DESDE ARCHIVO GUARDADO)
                # ============================================================
                st.markdown("##### 📂 Cobranzas del Día Anterior (para detectar duplicados)")
                
                cobranzas_anterior_docs = {}
                try:
                    from config import RUTA_ARCHIVOS
                    empresa_clean = re.sub(r'[^\w\-_]', '_', st.session_state.empresa_activa)
                    fecha_ant_str = (pd.Timestamp(fecha_procesar) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    filename_ant = f"cobranzas_{empresa_clean}_{fecha_ant_str}.xlsx"
                    filepath_ant = os.path.join(RUTA_ARCHIVOS, filename_ant)
                    
                    if os.path.exists(filepath_ant):
                        df_cob_ant = pd.read_excel(filepath_ant)
                        df_cob_ant_clean = ProcesadorArchivos._limpiar_columnas(df_cob_ant)
                        
                        # Buscar cabecera en Cobranzas Anterior
                        idx_cob_ant = None
                        for idx, row in df_cob_ant_clean.iterrows():
                            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                            if 'banco' in row_str and 'cuenta' in row_str and 'deposito' in row_str:
                                idx_cob_ant = idx
                                break
                        if idx_cob_ant is None:
                            idx_cob_ant = ProcesadorArchivos._encontrar_fila_datos(df_cob_ant_clean, ['banco', 'deposito', 'monto'])
                        
                        if idx_cob_ant is not None and idx_cob_ant >= 0 and idx_cob_ant < len(df_cob_ant_clean):
                            df_datos = df_cob_ant_clean.iloc[idx_cob_ant:].reset_index(drop=True)
                            if len(df_datos) > 0:
                                header_row = df_datos.iloc[0]
                                new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                                df_datos.columns = new_cols
                                df_cob_ant_clean = df_datos.iloc[1:].reset_index(drop=True)
                        
                        # Buscar columnas
                        col_ref_cob_ant = ProcesadorArchivos._buscar_columna(df_cob_ant_clean, 'deposito', 'nro', 'referencia', 'documento')
                        col_monto_cob_ant = ProcesadorArchivos._buscar_columna(df_cob_ant_clean, 'monto', 'total', 'importe')
                        col_banco_cob_ant = ProcesadorArchivos._buscar_columna(df_cob_ant_clean, 'banco', 'cuenta', 'entidad')
                        col_fecha_cob_ant = ProcesadorArchivos._buscar_columna(df_cob_ant_clean, 'fecha', 'fec', 'f. cobranza')
                        
                        if col_ref_cob_ant and col_monto_cob_ant:
                            for idx, row in df_cob_ant_clean.iterrows():
                                ref = str(row[col_ref_cob_ant]).strip()
                                monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_cob_ant])
                                if ref and ref != 'nan' and ref != 'None' and monto:
                                    ref_norm = re.sub(r'[^0-9]', '', ref)
                                    if ref_norm:
                                        fecha = ''
                                        if col_fecha_cob_ant:
                                            try:
                                                fecha_val = row[col_fecha_cob_ant]
                                                if pd.notna(fecha_val):
                                                    if isinstance(fecha_val, pd.Timestamp):
                                                        fecha = fecha_val.strftime('%d/%m/%Y')
                                                    else:
                                                        fecha = str(fecha_val).strip()
                                            except:
                                                pass
                                        
                                        banco = ''
                                        if col_banco_cob_ant:
                                            try:
                                                banco_val = str(row[col_banco_cob_ant]).strip()
                                                if banco_val and banco_val != 'nan' and banco_val != 'None':
                                                    banco = banco_val
                                            except:
                                                pass
                                        
                                        cobranzas_anterior_docs[ref_norm] = {
                                            'referencia': ref,
                                            'monto': float(monto),
                                            'banco': banco,
                                            'fecha': fecha,
                                            'tipo': 'COBRANZA_ANTERIOR'
                                        }
                        
                        st.info(f"📂 **{len(cobranzas_anterior_docs)}** cobranzas encontradas en el día anterior ({fecha_ant_str})")
                    else:
                        st.info(f"ℹ️ No se encontró archivo de cobranzas del día anterior ({fecha_ant_str})")
                except Exception as e:
                    st.warning(f"⚠️ Error al leer cobranzas del día anterior: {str(e)}")
                
                # ============================================================
                # 3. ANÁLISIS CRUZADO - DETECTAR COBRANZAS DUPLICADAS
                # ============================================================
                st.markdown("---")
                st.markdown("#### 📊 Análisis Cruzado de Cobranzas")
                
                # 🔥 IDENTIFICAR COBRANZAS DUPLICADAS (Están en día actual y también en día anterior)
                cobranzas_duplicadas = []
                for ref_norm, info in cobranzas_actual_docs.items():
                    if ref_norm in cobranzas_anterior_docs:
                        cobranzas_duplicadas.append({
                            'referencia': info['referencia'],
                            'monto_actual': info['monto'],
                            'monto_anterior': cobranzas_anterior_docs[ref_norm]['monto'],
                            'banco': info.get('banco', 'No identificado'),
                            'fecha_actual': info.get('fecha', 'No disponible'),
                            'fecha_anterior': cobranzas_anterior_docs[ref_norm].get('fecha', 'No disponible'),
                            'cliente': info.get('cliente', 'No identificado'),
                            'estado': '🔴 DUPLICADA (Ya estaba en día anterior)'
                        })
                
                # 🔥 IDENTIFICAR COBRANZAS REZAGADAS (Están en día anterior pero NO en día actual - ya fueron procesadas)
                cobranzas_rezagadas = []
                for ref_norm, info in cobranzas_anterior_docs.items():
                    if ref_norm not in cobranzas_actual_docs:
                        cobranzas_rezagadas.append({
                            'referencia': info['referencia'],
                            'monto': info['monto'],
                            'banco': info.get('banco', 'No identificado'),
                            'fecha': info.get('fecha', 'No disponible'),
                            'estado': '✅ YA PROCESADA (No está en el día actual)'
                        })
                
                # 🔥 IDENTIFICAR COBRANZAS NUEVAS (Están en día actual pero NO en día anterior)
                cobranzas_nuevas = []
                for ref_norm, info in cobranzas_actual_docs.items():
                    if ref_norm not in cobranzas_anterior_docs:
                        cobranzas_nuevas.append({
                            'referencia': info['referencia'],
                            'monto': info['monto'],
                            'banco': info.get('banco', 'No identificado'),
                            'fecha': info.get('fecha', 'No disponible'),
                            'cliente': info.get('cliente', 'No identificado'),
                            'estado': '🆕 NUEVA (No estaba en día anterior)'
                        })
                
                # Calcular totales
                total_duplicadas = sum([x['monto_actual'] for x in cobranzas_duplicadas])
                total_rezagadas = sum([x['monto'] for x in cobranzas_rezagadas])
                total_nuevas = sum([x['monto'] for x in cobranzas_nuevas])
                
                # Mostrar resultados
                col_dup1, col_dup2, col_dup3 = st.columns(3)
                
                with col_dup1:
                    st.metric("🔴 Cobranzas Duplicadas", len(cobranzas_duplicadas), delta=f"{formato_venezolano(total_duplicadas)}")
                    if cobranzas_duplicadas:
                        st.error(f"❌ **{len(cobranzas_duplicadas)} cobranzas DUPLICADAS** (ya estaban en el día anterior)")
                        for item in cobranzas_duplicadas[:5]:
                            st.write(f"- 🔴 {item['referencia']}: {formato_venezolano(item['monto_actual'])} ({item['cliente']})")
                            st.caption(f"  Día anterior: {formato_venezolano(item['monto_anterior'])} | Fecha: {item['fecha_actual']}")
                        if len(cobranzas_duplicadas) > 5:
                            st.write(f"... y {len(cobranzas_duplicadas) - 5} más")
                    else:
                        st.success("✅ No hay cobranzas duplicadas")
                
                with col_dup2:
                    st.metric("✅ Cobranzas Rezagadas", len(cobranzas_rezagadas), delta=f"{formato_venezolano(total_rezagadas)}")
                    if cobranzas_rezagadas:
                        st.info(f"ℹ️ {len(cobranzas_rezagadas)} cobranzas ya estaban en el día anterior (ya procesadas)")
                        for item in cobranzas_rezagadas[:5]:
                            st.write(f"- ✅ {item['referencia']}: {formato_venezolano(item['monto'])}")
                            st.caption(f"  Fecha: {item['fecha']}")
                        if len(cobranzas_rezagadas) > 5:
                            st.write(f"... y {len(cobranzas_rezagadas) - 5} más")
                    else:
                        st.success("✅ No hay cobranzas rezagadas")
                
                with col_dup3:
                    st.metric("🆕 Cobranzas Nuevas", len(cobranzas_nuevas), delta=f"{formato_venezolano(total_nuevas)}")
                    if cobranzas_nuevas:
                        st.success(f"✅ {len(cobranzas_nuevas)} cobranzas nuevas (no estaban en el día anterior)")
                        for item in cobranzas_nuevas[:5]:
                            st.write(f"- 🆕 {item['referencia']}: {formato_venezolano(item['monto'])} ({item['cliente']})")
                        if len(cobranzas_nuevas) > 5:
                            st.write(f"... y {len(cobranzas_nuevas) - 5} más")
                    else:
                        st.info("ℹ️ No hay cobranzas nuevas")
                
                # ============================================================
                # 4. ANÁLISIS DE FACTURACIÓN VS CxC REPORTADO
                # ============================================================
                st.markdown("---")
                st.markdown("#### 📊 Análisis de Facturación vs CxC Reportado")
                
                if tiene_facturacion and tiene_cxc_reportado:
                    try:
                        # Extraer facturas del archivo de facturación
                        df_fact_clean = ProcesadorArchivos._limpiar_columnas(df_facturacion)
                        
                        # Buscar cabecera en Facturación
                        idx_fact = None
                        for idx, row in df_fact_clean.iterrows():
                            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                            if 'factura' in row_str and 'total' in row_str:
                                idx_fact = idx
                                break
                        if idx_fact is None:
                            idx_fact = ProcesadorArchivos._encontrar_fila_datos(df_fact_clean, ['factura', 'total', 'cliente'])
                        
                        if idx_fact is not None and idx_fact >= 0 and idx_fact < len(df_fact_clean):
                            df_datos = df_fact_clean.iloc[idx_fact:].reset_index(drop=True)
                            if len(df_datos) > 0:
                                header_row = df_datos.iloc[0]
                                new_cols = [str(col).strip() if pd.notna(col) else f'col_{j}' for j, col in enumerate(header_row)]
                                df_datos.columns = new_cols
                                df_fact_clean = df_datos.iloc[1:].reset_index(drop=True)
                        
                        # Buscar columnas
                        col_fact_num = ProcesadorArchivos._buscar_columna(df_fact_clean, 'factura', 'nro', 'documento')
                        col_fact_monto = ProcesadorArchivos._buscar_columna(df_fact_clean, 'total', 'monto', 'importe')
                        col_fact_cliente = ProcesadorArchivos._buscar_columna(df_fact_clean, 'cliente', 'nombre', 'rif')
                        
                        if col_fact_num and col_fact_monto:
                            facturas = []
                            for idx, row in df_fact_clean.iterrows():
                                factura = str(row[col_fact_num]).strip()
                                monto = ProcesadorArchivos._convertir_numero_europeo(row[col_fact_monto])
                                if factura and factura != 'nan' and factura != 'None' and monto:
                                    cliente = ''
                                    if col_fact_cliente:
                                        try:
                                            cliente_val = str(row[col_fact_cliente]).strip()
                                            if cliente_val and cliente_val != 'nan' and cliente_val != 'None':
                                                cliente = cliente_val
                                        except:
                                            pass
                                    
                                    facturas.append({
                                        'factura': factura,
                                        'monto': float(monto),
                                        'cliente': cliente
                                    })
                            
                            if facturas:
                                st.info(f"📊 **{len(facturas)}** facturas encontradas en el archivo de facturación")
                                
                                # Mostrar resumen de facturación
                                df_facturas = pd.DataFrame(facturas)
                                st.dataframe(df_facturas, width='stretch')
                            else:
                                st.info("ℹ️ No se encontraron facturas para analizar")
                    except Exception as e:
                        st.warning(f"⚠️ Error al analizar facturación: {str(e)}")
                
                # ============================================================
                # 5. DIAGNÓSTICO FINAL
                # ============================================================
                st.markdown("---")
                st.markdown("#### 🎯 Diagnóstico de la Diferencia")
                
                # La diferencia se explica por: Cobranzas Duplicadas + Cobranzas Rezagadas
                diferencia_explicada_cxc = total_duplicadas + total_rezagadas
                diferencia_no_explicada_cxc = abs(diff_cxc) - diferencia_explicada_cxc
                
                st.markdown(f"""
                | Concepto | Monto | Explicación |
                |----------|-------|-------------|
                | **Diferencia Total** | {formato_venezolano(abs(diff_cxc))} | Diferencia en CxC Calculado vs Reportado |
                | 🔴 **Cobranzas Duplicadas** | {formato_venezolano(total_duplicadas)} | Cobranzas que ya estaban en el día anterior |
                | ✅ **Cobranzas Rezagadas** | {formato_venezolano(total_rezagadas)} | Cobranzas que ya no están en el día actual |
                | 🆕 **Cobranzas Nuevas** | {formato_venezolano(total_nuevas)} | Cobranzas que no estaban en el día anterior |
                | **Diferencia Explicada** | {formato_venezolano(diferencia_explicada_cxc)} | Suma de Duplicadas + Rezagadas |
                | **Diferencia NO Explicada** | {formato_venezolano(diferencia_no_explicada_cxc)} | ⚠️ Requiere revisión manual |
                """)
                
                if abs(diferencia_no_explicada_cxc) < 0.01:
                    st.success("✅ **¡DIFERENCIA EXPLICADA COMPLETAMENTE!** Todas las cobranzas coinciden con la variación en CxC.")
                    
                    st.markdown("#### 📋 Resumen de Conciliación de CxC")
                    
                    resumen_parts = []
                    if len(cobranzas_duplicadas) > 0:
                        resumen_parts.append(f"🔴 **{len(cobranzas_duplicadas)} Cobranzas Duplicadas**: {formato_venezolano(total_duplicadas)}")
                    if len(cobranzas_rezagadas) > 0:
                        resumen_parts.append(f"✅ **{len(cobranzas_rezagadas)} Cobranzas Rezagadas**: {formato_venezolano(total_rezagadas)}")
                    if len(cobranzas_nuevas) > 0:
                        resumen_parts.append(f"🆕 **{len(cobranzas_nuevas)} Cobranzas Nuevas**: {formato_venezolano(total_nuevas)}")
                    
                    if resumen_parts:
                        st.markdown(f"""
                        **La diferencia de {formato_venezolano(abs(diff_cxc))} en Cuentas por Cobrar se explica por:**
                        
                        {chr(10).join(['- ' + p for p in resumen_parts])}
                        
                        ✅ **Todas las diferencias están justificadas.**
                        """)
                    else:
                        st.success("✅ No hay diferencias que explicar.")
                else:
                    st.error(f"❌ **DIFERENCIA NO EXPLICADA:** {formato_venezolano(diferencia_no_explicada_cxc)} Bs. no identificados.")
                    st.markdown("""
                    **Posibles causas:**
                    - Cobranzas que no tienen referencia clara
                    - Facturas que no están registradas en el sistema
                    - Errores de digitación en montos o referencias
                    - Notas de crédito que afectan CxC
                    - Ajustes manuales no registrados
                    """)
                    
                    # Mostrar referencias no coincidentes
                    if cobranzas_actual_docs and cobranzas_anterior_docs:
                        referencias_actual = set(cobranzas_actual_docs.keys())
                        referencias_anterior = set(cobranzas_anterior_docs.keys())
                        
                        referencias_no_coincidentes = referencias_actual - referencias_anterior
                        if referencias_no_coincidentes:
                            st.warning(f"⚠️ **{len(referencias_no_coincidentes)} referencias en cobranzas actuales que no coinciden con el día anterior:**")
                            for ref in list(referencias_no_coincidentes)[:10]:
                                info = cobranzas_actual_docs.get(ref, {})
                                st.write(f"- {info.get('referencia', ref)}: {formato_venezolano(info.get('monto', 0))} ({info.get('cliente', 'N/A')})")
                            if len(referencias_no_coincidentes) > 10:
                                st.write(f"... y {len(referencias_no_coincidentes) - 10} más")
                
                # ============================================================
                # 6. TABLA DETALLADA DE COBRANZAS
                # ============================================================
                with st.expander("📋 Ver detalle completo de cobranzas", expanded=False):
                    st.markdown("##### 🔴 Cobranzas Duplicadas")
                    if cobranzas_duplicadas:
                        df_duplicadas = pd.DataFrame(cobranzas_duplicadas)
                        st.dataframe(df_duplicadas, width='stretch')
                    else:
                        st.success("✅ No hay cobranzas duplicadas")
                    
                    st.markdown("##### ✅ Cobranzas Rezagadas (Ya procesadas en día anterior)")
                    if cobranzas_rezagadas:
                        df_rezagadas = pd.DataFrame(cobranzas_rezagadas)
                        st.dataframe(df_rezagadas, width='stretch')
                    else:
                        st.success("✅ No hay cobranzas rezagadas")
                    
                    st.markdown("##### 🆕 Cobranzas Nuevas")
                    if cobranzas_nuevas:
                        df_nuevas = pd.DataFrame(cobranzas_nuevas)
                        st.dataframe(df_nuevas, width='stretch')
                    else:
                        st.info("ℹ️ No hay cobranzas nuevas")
                
            except Exception as e:
                st.error(f"❌ Error en el análisis de cobranzas: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    
    st.markdown("---")
    # ============================================================
    # BOTONES PARA VER ARCHIVOS ORIGINALES
    # ============================================================
    st.markdown("---")
    st.markdown("#### 📂 Ver archivos originales")
    st.caption("💡 Haz clic en los botones para ver el contenido completo de cada archivo")

    archivos_verificacion = [
        ("CxC", archivo_cxc_reportado, "Cuentas por cobrar"),
        ("Inventario", archivo_inventario_reportado, "Inventario"),
        ("CxP", archivo_cxp_reportado, "Cuentas por pagar"),
        ("Tránsito", archivo_tb, "Transferencias en tránsito")
    ]

    cols = st.columns(4)
    for col, (nombre, archivo, titulo) in zip(cols, archivos_verificacion):
        with col:
            if archivo and archivos_cargados.get(titulo) is not None:
                if st.button(f"📄 Ver {nombre}", key=f"btn_{nombre}", width='stretch'):
                    mostrar_archivo_con_formato(
                        archivos_cargados[titulo], 
                        archivo.name, 
                        f"Archivo {titulo}"
                    )
            else:
                st.button(f"❌ {nombre} no cargado", disabled=True, width='stretch')

    # ============================================================
    # FORMULARIO DE AJUSTES
    # ============================================================
    st.markdown("#### ✏️ Registrar Ajustes de Diferencias")

    col_ajuste1, col_ajuste2, col_ajuste3, col_ajuste4 = st.columns(4)

    with col_ajuste1:
        ajuste_inv = st.number_input(
            "Ajuste Inventario",
            value=float(st.session_state.ajustes['inventario']['monto']),
            step=1.0,
            format="%.2f",
            key="ajuste_inv"
        )
        just_inv = st.text_input(
            "Justificación",
            value=st.session_state.ajustes['inventario']['justificacion'],
            placeholder="Ej: Ajuste por merma",
            key="just_inv"
        )

    with col_ajuste2:
        ajuste_cxc = st.number_input(
            "Ajuste CxC",
            value=float(st.session_state.ajustes['cx_c']['monto']),
            step=1.0,
            format="%.2f",
            key="ajuste_cxc"
        )
        just_cxc = st.text_input(
            "Justificación",
            value=st.session_state.ajustes['cx_c']['justificacion'],
            placeholder="Ej: Ajuste por cobranza no registrada",
            key="just_cxc"
        )

    with col_ajuste3:
        ajuste_cxp = st.number_input(
            "Ajuste CxP",
            value=float(st.session_state.ajustes['cx_p']['monto']),
            step=1.0,
            format="%.2f",
            key="ajuste_cxp"
        )
        just_cxp = st.text_input(
            "Justificación",
            value=st.session_state.ajustes['cx_p']['justificacion'],
            placeholder="Ej: Ajuste por factura no registrada",
            key="just_cxp"
        )

    with col_ajuste4:
        ajuste_transito = st.number_input(
            "Ajuste Tránsito",
            value=float(st.session_state.ajustes['transito']['monto']),
            step=1.0,
            format="%.2f",
            key="ajuste_transito"
        )
        just_transito = st.text_input(
            "Justificación",
            value=st.session_state.ajustes['transito']['justificacion'],
            placeholder="Ej: Ajuste por transferencia pendiente",
            key="just_transito"
        )

    col_btn_ajuste1, col_btn_ajuste2 = st.columns(2)
    with col_btn_ajuste1:
        if st.button("💾 Guardar Ajustes", width='stretch'):
            st.session_state.ajustes['inventario'] = {'monto': ajuste_inv, 'justificacion': just_inv}
            st.session_state.ajustes['cx_c'] = {'monto': ajuste_cxc, 'justificacion': just_cxc}
            st.session_state.ajustes['cx_p'] = {'monto': ajuste_cxp, 'justificacion': just_cxp}
            st.session_state.ajustes['transito'] = {'monto': ajuste_transito, 'justificacion': just_transito}
            
            db.guardar_ajustes(
                fecha_procesar.strftime('%Y-%m-%d'),
                st.session_state.ajustes,
                empresa=st.session_state.empresa_activa
            )
            
            st.success("✅ Ajustes guardados correctamente")
            st.rerun()
    
    with col_btn_ajuste2:
        if st.button("🔄 Resetear Ajustes", width='stretch'):
            st.session_state.ajustes = {
                'inventario': {'monto': 0.0, 'justificacion': ''},
                'cx_c': {'monto': 0.0, 'justificacion': ''},
                'cx_p': {'monto': 0.0, 'justificacion': ''},
                'transito': {'monto': 0.0, 'justificacion': ''}
            }
            st.success("✅ Ajustes reseteados a 0")
            st.rerun()

    st.markdown("---")
    
    # ============================================================
    # CIERRE DIARIO
    # ============================================================
    st.markdown("#### 📊 CIERRE DIARIO - Capital de Trabajo Neto")

    archivos_faltantes = []
    origen_archivos = {}

    if not archivo_cxc_reportado:
        archivos_faltantes.append("📄 Cuentas por cobrar (CxC)")
        origen_archivos['CxC'] = "❌ NO DISPONIBLE"
    else:
        origen_archivos['CxC'] = "📄 " + archivo_cxc_reportado.name

    if not archivo_cxp_reportado:
        archivos_faltantes.append("📄 Cuentas por pagar (CxP)")
        origen_archivos['CxP'] = "❌ NO DISPONIBLE"
    else:
        origen_archivos['CxP'] = "📄 " + archivo_cxp_reportado.name

    if not archivo_inventario_reportado:
        archivos_faltantes.append("📄 Inventario")
        origen_archivos['Inventario'] = "❌ NO DISPONIBLE"
    else:
        origen_archivos['Inventario'] = "📄 " + archivo_inventario_reportado.name

    if not archivo_tb:
        archivos_faltantes.append("📄 Transferencias en tránsito (TB)")
        origen_archivos['Tránsito'] = "❌ NO DISPONIBLE"
    else:
        origen_archivos['Tránsito'] = "📄 " + archivo_tb.name

    origen_archivos['Bancos'] = "📄 " + archivo_estado_cuenta.name if archivo_estado_cuenta else "📄 Estado de cuenta"

    if archivos_faltantes:
        st.warning(f"""
        ⚠️ **Faltan archivos de verificación para el Cierre Diario:**
        
        {', '.join(archivos_faltantes)}
        
        **El Cierre Diario SOLO usa valores de los archivos de verificación.**
        Carga los archivos faltantes para obtener el Capital de Trabajo Neto correcto.
        """)

    if archivo_cxc_reportado:
        cx_c_cierre = saldos_reportados.get('Cuentas por cobrar')
        if cx_c_cierre is None or cx_c_cierre == 0:
            st.error("❌ **Error:** No se pudo extraer el valor de Cuentas por cobrar del archivo.")
            cx_c_cierre = 0
        else:
            st.success(f"💰 CxC: **DESDE ARCHIVO** → {formato_venezolano(cx_c_cierre)}")
    else:
        cx_c_cierre = 0
        st.warning(f"💰 CxC: **NO DISPONIBLE** (falta archivo) → 0,00")

    if archivo_inventario_reportado:
        inventario_cierre = saldos_reportados.get('Inventario')
        if inventario_cierre is None or inventario_cierre == 0:
            st.error("❌ **Error:** No se pudo extraer el valor de Inventario del archivo.")
            inventario_cierre = 0
        else:
            st.success(f"📦 Inventario: **DESDE ARCHIVO** → {formato_venezolano(inventario_cierre)}")
    else:
        inventario_cierre = 0
        st.warning(f"📦 Inventario: **NO DISPONIBLE** (falta archivo) → 0,00")

    if archivo_cxp_reportado:
        cx_p_cierre = saldos_reportados.get('Cuentas por pagar')
        if cx_p_cierre is None or cx_p_cierre == 0:
            st.error("❌ **Error:** No se pudo extraer el valor de Cuentas por pagar del archivo.")
            cx_p_cierre = 0
        else:
            st.success(f"📋 CxP: **DESDE ARCHIVO** → {formato_venezolano(cx_p_cierre)}")
    else:
        cx_p_cierre = 0
        st.warning(f"📋 CxP: **NO DISPONIBLE** (falta archivo) → 0,00")

    if archivo_tb:
        transito_cierre = saldos_reportados.get('Transferencias en tránsito')
        if transito_cierre is None or transito_cierre == 0:
            st.error("❌ **Error:** No se pudo extraer el valor de Transferencias en tránsito del archivo.")
            transito_cierre = 0
        else:
            st.success(f"🔄 Tránsito: **DESDE ARCHIVO** → {formato_venezolano(transito_cierre)}")
    else:
        transito_cierre = 0
        st.warning(f"🔄 Tránsito: **NO DISPONIBLE** (falta archivo) → 0,00")

    bancos_cierre = saldo_final
    st.success(f"🏦 Bancos: **DESDE ESTADO DE CUENTA** → {formato_venezolano(bancos_cierre)}")

    cx_c_cierre = safe_number(cx_c_cierre)
    inventario_cierre = safe_number(inventario_cierre)
    bancos_cierre = safe_number(bancos_cierre)
    cx_p_cierre = safe_number(cx_p_cierre)
    transito_cierre = safe_number(transito_cierre)

    activos_operativos = cx_c_cierre + inventario_cierre + bancos_cierre
    pasivos_operativos = cx_p_cierre + transito_cierre
    capital_neto = activos_operativos - pasivos_operativos

    st.markdown("#### 📋 Detalle del Cierre Diario")

    cierre_detalle = [
        {"Concepto": "📦 Inventario", "Archivo Origen": origen_archivos.get('Inventario', 'NO DISPONIBLE'), "Tipo": "ACTIVO", "Monto": formato_venezolano(inventario_cierre)},
        {"Concepto": "💰 Cuentas por cobrar", "Archivo Origen": origen_archivos.get('CxC', 'NO DISPONIBLE'), "Tipo": "ACTIVO", "Monto": formato_venezolano(cx_c_cierre)},
        {"Concepto": "🏦 Bancos", "Archivo Origen": origen_archivos.get('Bancos', 'NO DISPONIBLE'), "Tipo": "ACTIVO", "Monto": formato_venezolano(bancos_cierre)},
        {"Concepto": "📌 TOTAL ACTIVOS OPERATIVOS", "Archivo Origen": "Suma de activos", "Tipo": "ACTIVO_TOTAL", "Monto": formato_venezolano(activos_operativos)},
        {"Concepto": "📋 Cuentas por pagar", "Archivo Origen": origen_archivos.get('CxP', 'NO DISPONIBLE'), "Tipo": "PASIVO", "Monto": formato_venezolano(cx_p_cierre)},
        {"Concepto": "🔄 Transferencias en tránsito", "Archivo Origen": origen_archivos.get('Tránsito', 'NO DISPONIBLE'), "Tipo": "PASIVO", "Monto": formato_venezolano(transito_cierre)},
        {"Concepto": "📌 TOTAL PASIVOS OPERATIVOS", "Archivo Origen": "Suma de pasivos", "Tipo": "PASIVO_TOTAL", "Monto": formato_venezolano(pasivos_operativos)},
        {"Concepto": "🏁 CAPITAL DE TRABAJO NETO", "Archivo Origen": "Activos - Pasivos", "Tipo": "CAPITAL", "Monto": formato_venezolano(capital_neto)}
    ]

    df_cierre = pd.DataFrame(cierre_detalle)

    def color_cierre_rows(row):
        if row['Tipo'] == 'ACTIVO_TOTAL':
            return ['background-color: #e8f5e9; font-weight: bold;'] * len(row)
        elif row['Tipo'] == 'PASIVO_TOTAL':
            return ['background-color: #fff3e0; font-weight: bold;'] * len(row)
        elif row['Tipo'] == 'CAPITAL':
            if capital_neto >= 0:
                return ['background-color: #0f3d2e; color: white; font-weight: bold; font-size: 1.1rem;'] * len(row)
            else:
                return ['background-color: #3d1a1a; color: white; font-weight: bold; font-size: 1.1rem;'] * len(row)
        elif row['Tipo'] == 'ACTIVO':
            return ['background-color: #f1f8f4;'] * len(row)
        elif row['Tipo'] == 'PASIVO':
            return ['background-color: #fff8f0;'] * len(row)
        return [''] * len(row)

    styled_df = df_cierre.style.apply(color_cierre_rows, axis=1).hide(axis='index')
    st.dataframe(styled_df, width='stretch')

    with st.expander("📂 Ver origen detallado de cada archivo", expanded=False):
        st.markdown("""
        ### 📂 Origen de los archivos utilizados en el Cierre Diario
        
        | Concepto | Archivo | Estado |
        |----------|---------|--------|
        """)
        
        if archivo_cxc_reportado:
            st.markdown(f"| 💰 Cuentas por cobrar | `{archivo_cxc_reportado.name}` | ✅ Cargado |")
        else:
            st.markdown("| 💰 Cuentas por cobrar | **NO CARGADO** | ❌ No disponible |")
        
        if archivo_inventario_reportado:
            st.markdown(f"| 📦 Inventario | `{archivo_inventario_reportado.name}` | ✅ Cargado |")
        else:
            st.markdown("| 📦 Inventario | **NO CARGADO** | ❌ No disponible |")
        
        if archivo_cxp_reportado:
            st.markdown(f"| 📋 Cuentas por pagar | `{archivo_cxp_reportado.name}` | ✅ Cargado |")
        else:
            st.markdown("| 📋 Cuentas por pagar | **NO CARGADO** | ❌ No disponible |")
        
        if archivo_tb:
            st.markdown(f"| 🔄 Transferencias en tránsito | `{archivo_tb.name}` | ✅ Cargado |")
        else:
            st.markdown("| 🔄 Transferencias en tránsito | **NO CARGADO** | ❌ No disponible |")
        
        if archivo_estado_cuenta:
            st.markdown(f"| 🏦 Bancos | `{archivo_estado_cuenta.name}` | ✅ Cargado |")
        else:
            st.markdown("| 🏦 Bancos | **NO CARGADO** | ❌ No disponible |")
        
        st.markdown("""
        
        ### 📌 Valores extraídos:
        """)
        
        st.markdown(f"""
        | Concepto | Valor | Origen |
        |----------|-------|--------|
        | Cuentas por cobrar | {formato_venezolano(cx_c_cierre)} | {origen_archivos.get('CxC', 'NO DISPONIBLE')} |
        | Inventario | {formato_venezolano(inventario_cierre)} | {origen_archivos.get('Inventario', 'NO DISPONIBLE')} |
        | Bancos | {formato_venezolano(bancos_cierre)} | {origen_archivos.get('Bancos', 'NO DISPONIBLE')} |
        | Cuentas por pagar | {formato_venezolano(cx_p_cierre)} | {origen_archivos.get('CxP', 'NO DISPONIBLE')} |
        | Transferencias en tránsito | {formato_venezolano(transito_cierre)} | {origen_archivos.get('Tránsito', 'NO DISPONIBLE')} |
        """)

    # ============================================================
    # RESUMEN DEL CIERRE DIARIO - KPIS CORPORATIVOS
    # ============================================================
    st.markdown("---")
    st.markdown("#### 📊 Resumen del Cierre Diario")
    st.caption("💡 Haz clic en cada KPI para ver su composición detallada")

    col_c1, col_c2, col_c3 = st.columns(3)

    with col_c1:
        popover_activos = f"""
        ##### 📈 Composición de Activos Operativos
        
        | Concepto | Monto | Archivo Origen |
        |----------|-------|----------------|
        | **Cuentas por cobrar** | {formato_venezolano(cx_c_cierre)} | {'✅ Cargado' if archivo_cxc_reportado else '❌ No disponible'} |
        | **Inventario** | {formato_venezolano(inventario_cierre)} | {'✅ Cargado' if archivo_inventario_reportado else '❌ No disponible'} |
        | **Bancos** | {formato_venezolano(bancos_cierre)} | ✅ Estado de cuenta |
        | **TOTAL ACTIVOS** | **{formato_venezolano(activos_operativos)}** |  |
        
        ✅ Valores tomados de los archivos de verificación.
        """
        
        with st.popover("", width='stretch'):
            st.markdown(popover_activos)
            if cx_c_cierre > 0 or inventario_cierre > 0 or bancos_cierre > 0:
                fig, ax = plt.subplots(figsize=(6, 3))
                componentes = ['CxC', 'Inventario', 'Bancos']
                valores = [cx_c_cierre, inventario_cierre, bancos_cierre]
                colores = ['#3498db', '#2ecc71', '#f39c12']
                ax.bar(componentes, valores, color=colores)
                ax.set_title('Composición de Activos', fontsize=10, color='#0a1628')
                ax.set_ylabel('Monto (Bs.)', color='#6a8aac')
                ax.set_facecolor('#f8fafc')
                plt.tight_layout()
                st.pyplot(fig)
        
        st.markdown(f"""
        <div class="kpi-card kpi-activos">
            <div class="icon-bg">📈</div>
            <div class="label">📈 ACTIVOS OPERATIVOS</div>
            <div class="value">{formato_venezolano(activos_operativos)}</div>
            <div class="sub-label">💡 Haz clic para ver detalle</div>
        </div>
        """, unsafe_allow_html=True)

    with col_c2:
        popover_pasivos = f"""
        ##### 📉 Composición de Pasivos Operativos
        
        | Concepto | Monto | Archivo Origen |
        |----------|-------|----------------|
        | **Cuentas por pagar** | {formato_venezolano(cx_p_cierre)} | {'✅ Cargado' if archivo_cxp_reportado else '❌ No disponible'} |
        | **Transferencias en tránsito** | {formato_venezolano(transito_cierre)} | {'✅ Cargado' if archivo_tb else '❌ No disponible'} |
        | **TOTAL PASIVOS** | **{formato_venezolano(pasivos_operativos)}** |  |
        
        ✅ Valores tomados de los archivos de verificación.
        """
        
        with st.popover("", width='stretch'):
            st.markdown(popover_pasivos)
        
        st.markdown(f"""
        <div class="kpi-card kpi-pasivos">
            <div class="icon-bg">📉</div>
            <div class="label">📉 PASIVOS OPERATIVOS</div>
            <div class="value">{formato_venezolano(pasivos_operativos)}</div>
            <div class="sub-label">💡 Haz clic para ver detalle</div>
        </div>
        """, unsafe_allow_html=True)

    with col_c3:
        if capital_neto >= 0:
            clase = "kpi-capital-positivo"
            emoji = "✅"
        else:
            clase = "kpi-capital-negativo"
            emoji = "❌"
        
        popover_capital = f"""
        ##### 🏁 Cálculo del Capital de Trabajo Neto
        
        | Concepto | Fórmula | Monto |
        |----------|---------|-------|
        | **Activos Operativos** | CxC + Inv. + Bancos | {formato_venezolano(activos_operativos)} |
        | **Pasivos Operativos** | CxP + Tránsito | {formato_venezolano(pasivos_operativos)} |
        | **CAPITAL DE TRABAJO NETO** | Activos - Pasivos | **{formato_venezolano(capital_neto)}** |
        
        **Ratio Activos/Pasivos:** {f"{activos_operativos / pasivos_operativos:.2f}x" if pasivos_operativos > 0 else "N/A"}
        
        {f"✅ Capital de Trabajo Neto POSITIVO: {formato_venezolano(capital_neto)}" if capital_neto >= 0 else f"❌ Capital de Trabajo Neto NEGATIVO: {formato_venezolano(capital_neto)}"}
        """
        
        with st.popover("", width='stretch'):
            st.markdown(popover_capital)
        
        st.markdown(f"""
        <div class="kpi-card {clase}">
            <div class="icon-bg">🏁</div>
            <div class="label">{emoji} CAPITAL DE TRABAJO NETO</div>
            <div class="value">{formato_venezolano(capital_neto)}</div>
            <div class="sub-label">💡 Haz clic para ver detalle</div>
        </div>
        """, unsafe_allow_html=True)

    with st.expander("📌 Detalle del Cierre Diario", expanded=False):
        st.markdown(f"""
        ### 📊 Cierre Diario - {fecha_procesar.strftime('%Y-%m-%d')}
        
        | Concepto | Origen | Valor |
        |----------|--------|-------|
        | **ACTIVOS OPERATIVOS** | | |
        | Cuentas por cobrar | {'Archivo CxC' if archivo_cxc_reportado else '❌ NO DISPONIBLE'} | {formato_venezolano(cx_c_cierre)} |
        | Inventario | {'Archivo Inventario' if archivo_inventario_reportado else '❌ NO DISPONIBLE'} | {formato_venezolano(inventario_cierre)} |
        | Bancos | Estado de cuenta | {formato_venezolano(bancos_cierre)} |
        | | **Total Activos** | **{formato_venezolano(activos_operativos)}** |
        | | | |
        | **PASIVOS OPERATIVOS** | | |
        | Cuentas por pagar | {'Archivo CxP' if archivo_cxp_reportado else '❌ NO DISPONIBLE'} | {formato_venezolano(cx_p_cierre)} |
        | Transferencias en tránsito | {'Archivo TB' if archivo_tb else '❌ NO DISPONIBLE'} | {formato_venezolano(transito_cierre)} |
        | | **Total Pasivos** | **{formato_venezolano(pasivos_operativos)}** |
        | | | |
        | **🏁 CAPITAL DE TRABAJO NETO** | Activos - Pasivos | **{formato_venezolano(capital_neto)}** |
        """)

        if capital_neto >= 0:
            st.success(f"✅ Capital de Trabajo Neto POSITIVO: {formato_venezolano(capital_neto)}")
        else:
            st.error(f"❌ Capital de Trabajo Neto NEGATIVO: {formato_venezolano(capital_neto)}")

        st.markdown("""
        ### ⚠️ Importante
        **El Cierre Diario utiliza EXCLUSIVAMENTE los valores de los archivos de verificación:**
        - Cuentas por cobrar → Archivo CxC
        - Inventario → Archivo Inventario
        - Cuentas por pagar → Archivo CxP
        - Transferencias en tránsito → Archivo TB
        
        **NO utiliza valores calculados** de facturación, cobranzas o egresos.
        """)
    
    st.markdown("---")
    
    # ============================================================
    # VALIDACIONES CRUZADAS
    # ============================================================
    st.markdown("#### ✅ Validaciones Cruzadas")
    
    diff_bancos = safe_number(bancos_calculado) - safe_number(saldo_final)
    if abs(diff_bancos) > 0.01:
        st.error(f"❌ **Bancos**: Diferencia de {formato_venezolano(abs(diff_bancos))} Bs. con el saldo final del estado de cuenta")
    else:
        st.success(f"✅ **Bancos**: Coincide con el saldo final del estado de cuenta")
    
    if cobranzas > safe_number(st.session_state.saldos['cx_c']) + facturacion:
        st.warning(f"⚠️ **CxC**: Cobranzas ({formato_venezolano(cobranzas)}) superan saldo disponible")
    
    if pagos_proveedores > safe_number(st.session_state.saldos['cx_p']) + recepcion_total:
        st.warning(f"⚠️ **CxP**: Pagos a proveedores ({formato_venezolano(pagos_proveedores)}) superan saldo disponible")
    
    if transito_calculado >= 0:
        st.success(f"✅ **Transferencias**: Saldo positivo ({formato_venezolano(transito_calculado)})")
    else:
        st.error(f"❌ **Transferencias**: Saldo negativo ({formato_venezolano(transito_calculado)})")
    
    st.info(f"ℹ️ **Saldo Final Bancario Reportado**: {formato_venezolano(saldo_final)} Bs.")
    
    st.markdown("---")
    
    # ============================================================
    # KPI - RESUMEN DEL DÍA
    # ============================================================
    st.markdown("#### 📊 Resumen del Día")
    
    capital_anterior = safe_number(st.session_state.saldos.get('capital_anterior', capital_calculado))
    var_capital = capital_calculado - capital_anterior
    
    col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
    
    with col_kpi1:
        st.markdown(f"""
        <div class="kpi-card kpi-capital">
            <div class="icon-bg">🏁</div>
            <div class="label">🏁 CAPITAL DE TRABAJO NETO</div>
            <div class="value">{formato_venezolano(capital_calculado)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_kpi2:
        arrow = "📉" if var_capital < 0 else "📈"
        if var_capital >= 0:
            color_class = "kpi-capital-positivo"
        else:
            color_class = "kpi-capital-negativo"
        st.markdown(f"""
        <div class="kpi-card {color_class}">
            <div class="icon-bg">{arrow}</div>
            <div class="label">{arrow} VARIACIÓN DEL CAPITAL</div>
            <div class="value">{formato_venezolano(var_capital)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_kpi3:
        st.markdown(f"""
        <div class="kpi-card kpi-capital">
            <div class="icon-bg">🔄</div>
            <div class="label">🔄 TRANSFERENCIAS EN TRÁNSITO</div>
            <div class="value">{formato_venezolano(transito_calculado)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ============================================================
    # BOTONES DE ACCIÓN
    # ============================================================
    
    inventario_final = saldos_reportados.get('Inventario', inventario_calculado)
    cx_c_final = saldos_reportados.get('Cuentas por cobrar', cx_c_calculado)
    cx_p_final = saldos_reportados.get('Cuentas por pagar', cx_p_calculado)
    transito_final = saldos_reportados.get('Transferencias en tránsito', transito_calculado)
    bancos_final = bancos_calculado
    
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("💾 Guardar saldos calculados", width='stretch'):
            saldos_guardar = {
                'inventario': inventario_final,
                'cx_c': cx_c_final,
                'bancos': bancos_final,
                'cx_p': cx_p_final,
                'transito': transito_final,
                'capital': capital_calculado
            }
            
            # 1. Guardar saldos diarios
            db.guardar_saldos(
                fecha_procesar.strftime('%Y-%m-%d'),
                saldos_guardar,
                empresa=st.session_state.empresa_activa
            )
            
            # 2. Guardar inconsistencias detectadas históricamente
            fecha_str = fecha_procesar.strftime('%Y-%m-%d')
            empresa_activa = st.session_state.empresa_activa
            
            try:
                conn = sqlite3.connect(db.db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM inconsistencias WHERE fecha = ? AND empresa = ?", (fecha_str, empresa_activa))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error al borrar inconsistencias previas: {e}")

            if abs(diff_inv) > 0.01:
                db.guardar_inconsistencia(
                    fecha_str, "Inventario", inventario_calculado, 
                    inventario_reportado if inventario_reportado is not None else 0.0, 
                    diff_inv, f"Diferencia de inventario en el cierre: {diff_inv:.2f}",
                    empresa=empresa_activa
                )
            if abs(diff_cxc) > 0.01:
                db.guardar_inconsistencia(
                    fecha_str, "Cuentas por cobrar", cx_c_calculado, 
                    cx_c_reportado if cx_c_reportado is not None else 0.0, 
                    diff_cxc, f"Diferencia de CxC en el cierre: {diff_cxc:.2f}",
                    empresa=empresa_activa
                )
            if abs(diff_cxp) > 0.01:
                db.guardar_inconsistencia(
                    fecha_str, "Cuentas por pagar", cx_p_calculado, 
                    cx_p_reportado if cx_p_reportado is not None else 0.0, 
                    diff_cxp, f"Diferencia de CxP en el cierre: {diff_cxp:.2f}",
                    empresa=empresa_activa
                )
            if abs(diff_transito) > 0.01:
                db.guardar_inconsistencia(
                    fecha_str, "Transferencias en tránsito", transito_calculado, 
                    transito_reportado if transito_reportado is not None else 0.0, 
                    diff_transito, f"Diferencia de Tránsito en el cierre: {diff_transito:.2f}",
                    empresa=empresa_activa
                )
            if abs(diferencia_bancos) > 0.01:
                db.guardar_inconsistencia(
                    fecha_str, "Bancos", bancos_calculado, saldo_final, 
                    diferencia_bancos, f"Diferencia de Bancos en el cierre vs Estado de Cuenta: {diferencia_bancos:.2f}",
                    empresa=empresa_activa
                )

            # 3. Guardar resultado de auditoría en auditoria_memoria.db
            from motor_auditoria import guardar_resultado_cierre, calcular_kpis
            fallas = st.session_state.get('fallas_detectadas')
            df_c = st.session_state.get('df_consolidado')
            hay_err = st.session_state.get('hay_errores')
            
            if fallas is None or df_c is None:
                from motor_auditoria import ejecutar_auditoria_inteligente
                hay_err, fallas, df_c = ejecutar_auditoria_inteligente(
                    archivo_facturacion, archivo_cobranzas, archivo_egresos, archivo_estado_cuenta
                )
            
            kpis = calcular_kpis(df_c)
            guardar_resultado_cierre(
                hay_err, fallas, df_c, kpis, 
                fecha=fecha_str, 
                empresa=empresa_activa
            )
            
            st.session_state.saldos['inventario'] = inventario_final
            st.session_state.saldos['cx_c'] = cx_c_final
            st.session_state.saldos['bancos'] = bancos_final
            st.session_state.saldos['cx_p'] = cx_p_final
            st.session_state.saldos['transito'] = transito_final
            st.session_state.saldos['capital_anterior'] = capital_calculado
            
            st.success("✅ Saldos, inconsistencias y reporte de auditoría guardados correctamente")
            st.rerun()
    
    with col_btn2:
        if st.button("📊 Ver gráfico evolución", width='stretch'):
            historial = db.obtener_historial_saldos_completo(30, empresa=st.session_state.empresa_activa)
            if not historial.empty and len(historial) > 1:
                try:
                    historial_ordenado = historial.sort_values('fecha')
                    
                    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
                    
                    axes[0].plot(historial_ordenado['fecha'], historial_ordenado['capital'], 
                                marker='o', linewidth=2, color='#c9a84c')
                    axes[0].set_title('Evolución del Capital de Trabajo Neto', fontsize=14, fontweight='bold', color='#0a1628')
                    axes[0].set_xlabel('Fecha', color='#6a8aac')
                    axes[0].set_ylabel('Capital (Bs.)', color='#6a8aac')
                    axes[0].grid(True, alpha=0.3)
                    axes[0].set_facecolor('#f8fafc')
                    axes[0].tick_params(axis='x', rotation=45, colors='#6a8aac')
                    
                    axes[1].plot(historial_ordenado['fecha'], historial_ordenado['inventario'], 
                                marker='s', linewidth=2, label='Inventario', color='#2ecc71')
                    axes[1].plot(historial_ordenado['fecha'], historial_ordenado['cx_c'], 
                                marker='^', linewidth=2, label='CxC', color='#3498db')
                    axes[1].plot(historial_ordenado['fecha'], historial_ordenado['bancos'], 
                                marker='d', linewidth=2, label='Bancos', color='#f39c12')
                    axes[1].set_title('Evolución de Componentes del Capital', fontsize=14, fontweight='bold', color='#0a1628')
                    axes[1].set_xlabel('Fecha', color='#6a8aac')
                    axes[1].set_ylabel('Monto (Bs.)', color='#6a8aac')
                    axes[1].legend(loc='upper left')
                    axes[1].grid(True, alpha=0.3)
                    axes[1].set_facecolor('#f8fafc')
                    axes[1].tick_params(axis='x', rotation=45, colors='#6a8aac')
                    
                    plt.tight_layout()
                    st.pyplot(fig)
                except Exception as e:
                    st.warning(f"No se pudo generar el gráfico: {str(e)}")
            else:
                st.info("No hay suficientes datos históricos para generar gráficos (mínimo 2 días)")
    
    # ============================================================
    # REGLAS DE NEGOCIO
    # ============================================================
    with st.expander("📌 Reglas de negocio aplicadas"):
        st.markdown("""
        | Movimiento | Efecto |
        |------------|--------|
        | Recepción de mercancía | Aumenta inventario |
        | Costo de facturación | Disminuye inventario |
        | Cobranzas | Disminuye CxC / Aumenta bancos |
        | Notas de crédito (clientes) | Disminuye CxC |
        | Notas de crédito (proveedores) | Disminuye CxP |
        | Egresos iPago | Disminuye bancos |
        | Estado de Cuenta Bancario | Determina saldo final bancario |
        | Transferencias en tránsito | Se toma desde TB |
        
        **Fórmulas clave:**  
        🔄 Transferencias en tránsito = Tránsito inicial + Ingresos del día - Cobranzas  
        📋 Cuentas por pagar = CxP inicial + Recepciones - Pagos proveedores  
        🏦 Bancos = Saldo Inicial (estado de cuenta) + Ingresos - Egresos
        
        **Cierre Diario:**  
        🏁 Capital de Trabajo Neto = (CxC + Inventario + Bancos) - (CxP + Transferencias en tránsito)
        
        **Los valores del Cierre Diario se toman EXCLUSIVAMENTE de los archivos de verificación:**
        - CxC → Archivo "CUENTAS POR COBRAR"
        - Inventario → Archivo "INVENTARIO"
        - CxP → Archivo "CUENTAS POR PAGAR"
        - Tránsito → Archivo "TB.xlsx"
        - Bancos → Estado de cuenta bancario
        
        **NO se utilizan valores calculados** para el Cierre Diario.
        """)

else:
    # --- MÓDULO VISUAL PASIVO DE AUDITORÍA (ÚLTIMO CIERRE DEL BOT) ---
    existe_c, fecha_c, hay_err_c, fallas_c, df_c_c, kpis_c = cargar_ultimo_cierre()
    if existe_c:
        st.markdown("---")
        st.markdown("#### 🤖 Cierre Diario Automático (Procesado por el Bot)")
        renderizar_modulo_auditoria(
            fallas_c,
            df_c_c,
            hay_err_c,
            f"Bot Nocturno - {fecha_c}",
            usuario_info.get('nombre', 'Analista')
        )
        st.markdown("---")
        
    st.info("👈 Carga los archivos obligatorios del día en la barra lateral para comenzar la validación")
    st.info("📌 **Archivos obligatorios:** Facturación, Cobranzas, Egresos iPago y Estado de Cuenta")
    st.info("ℹ️ **Archivos opcionales:** Recepción de mercancía, Notas de crédito, Costo de facturación")
    
    with st.expander("📋 Formatos esperados de los archivos"):
        st.markdown("""
        ### Facturación diaria (Ranking de Ventas)
        | Vendedor | Facturas | Div. Neto | Total |
        |----------|----------|-----------|-------|
        | JHORDAN PALOMO | 4 | 1220.79 | ... |
        | Totales: | 26 | 15288.18 | ... |
        
        ### Cobranzas procesadas
        | Banco | Cuenta | Fecha Cobranza | # Deposito | Monto Cobranza |
        |-------|--------|----------------|------------|----------------|
        | MCESIA | 02 - BANCO DE VENEZUELA | 2026-06-15 | 0591367815942 | 263.75 |
        
        ### Recepciones del día (OPCIONAL)
        | Compra | Proveedor | F. Recepción | $ Neto + IVA |
        |--------|-----------|--------------|--------------|
        | 0000000587 | MOLINOS NACIONALES | 15/06/2026 | 21612.5 |
        | Total General: | | | 21612.5 |
        
        ### Egresos iPago
        | Fecha Pago | Empresa | Proveedor | Tipo de Pago | Tipo de Egreso | Cuenta | Monto | Monto USD |
        |------------|---------|-----------|--------------|----------------|--------|-------|-----------|
        | 2026-06-17 | CORPORACION GUAYANA | MOLINOS NACIONALES | PROVEEDORES DE MERCANCIA | Proveedor | BODEGUITA GUAYANA | 5967800 | 10000.00 |
        
        ### Estado de cuenta bancario
        | Fecha | Referencia | Descripción | Crédito | Débito |
        |-------|------------|-------------|---------|--------|
        | 15/06/2026 | 0591367815942 | TRANSF RECIBIDA | 154.930,00 | 0,00 |
        
        ### TB.xlsx (Transferencias en tránsito)
        | Cuenta | Referencia | Fecha | Descripción | Monto |
        |--------|------------|-------|-------------|-------|
        | BANCO DE VENEZUELA | 059137177692 | 2026-05-30 | TRANSF RECIBIDA | 5152834 |
        
        ### Costo de Facturación (Reporte de Utilidad)
        | Producto | Cantidad | Precio | Total | **Costo** | ... |
        |----------|----------|--------|-------|-----------|-----|
        | ... | ... | ... | ... | ... | ... |
        | **Total General:** | | | | **1.417,00** | |
        """)

# ============================================================
# 🤖 ASISTENTE IA - DEEPSEEK (SIEMPRE VISIBLE)
# ============================================================
st.markdown("---")
st.header("🤖 Asistente IA - DeepSeek")

with st.expander("💬 Haz una consulta al asistente", expanded=True):
    pregunta_usuario = st.text_area(
        "Escribe tu pregunta sobre el sistema:", 
        "¿Cómo puedo optimizar el proceso de conciliación de saldos?",
        height=100
    )
    
    if st.button("Consultar a DeepSeek", width='stretch'):
        if pregunta_usuario:
            with st.spinner("Consultando a DeepSeek... ⏳"):
                try:
                    contexto = f"Sistema de validación de trazabilidad financiera diaria para el Grupo Bodeguita Oriente. Empresa: {st.session_state.empresa_activa}. Fecha: {fecha_procesar.strftime('%Y-%m-%d')}"
                    respuesta = consultar_deepseek(pregunta_usuario, contexto)
                    st.success("✅ Respuesta del asistente:")
                    st.markdown(f"💬 {respuesta}")
                except Exception as e:
                    st.error(f"❌ Error al consultar DeepSeek: {str(e)}")
        else:
            st.warning("⚠️ Por favor escribe una pregunta antes de consultar.")
    
    st.caption("💡 Puedes preguntar sobre: cálculos, errores, optimización, reglas de negocio, etc.")

# ============================================================
# PIE DE PÁGINA
# ============================================================
st.markdown("---")
st.caption("✨ Validador de Trazabilidad Diaria - Capital de Trabajo Neto Operativo | Grupo Bodeguita Oriente")
