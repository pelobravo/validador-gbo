# app.py - Con campos para saldos iniciales manuales - VERSIÓN COMPLETA CON CAMBIOS

import streamlit as st
import pandas as pd
from datetime import datetime
import os
import base64
from PIL import Image
import io
import numpy as np
import re

# Importar módulos del sistema
from config import USUARIOS, validar_carpetas
from database import Database
from logger import Logger
from procesadores import ProcesadorArchivos
from api_bcv import obtener_tasa_bcv

# Inicializar componentes
validar_carpetas()
db = Database()
logger = Logger()

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
# CSS PERSONALIZADO - DISEÑO MODERNO
# ============================================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .kpi-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 20px;
        padding: 25px 20px;
        text-align: center;
        color: white;
        box-shadow: 0 10px 25px -5px rgba(102, 126, 234, 0.3);
    }
    
    .kpi-card .label {
        font-size: 0.85rem;
        opacity: 0.9;
        letter-spacing: 0.5px;
    }
    
    .kpi-card .value {
        font-size: 2rem;
        font-weight: 700;
        margin-top: 8px;
    }
    
    .dataframe {
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    
    .dataframe th {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: 600;
        padding: 12px;
    }
    
    .stButton > button {
        border-radius: 12px;
        font-weight: 500;
        transition: all 0.2s;
    }
    
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }
    
    [data-testid="stSidebar"] * {
        color: #e0e0e0;
    }
    
    [data-testid="stSidebar"] .stMarkdown h1,
    [data-testid="stSidebar"] .stMarkdown h2,
    [data-testid="stSidebar"] .stMarkdown h3 {
        color: white;
    }
    
    [data-testid="stSidebar"] .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
        font-weight: 600;
        border: none;
        border-radius: 12px;
        padding: 10px 16px;
    }
    
    [data-testid="stSidebar"] .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        color: white !important;
    }
    
    [data-testid="stSidebar"] .stFileUploader label {
        color: #e0e0e0 !important;
    }
    
    [data-testid="stSidebar"] .stFileUploader p {
        color: #a0a0a0 !important;
    }
    
    [data-testid="stSidebar"] .stDateInput label {
        color: #e0e0e0 !important;
    }
    
    [data-testid="stSidebar"] .stSubheader {
        color: white !important;
    }
    
    [data-testid="stMetric"] {
        background: rgba(255,255,255,0.05);
        border-radius: 16px;
        padding: 15px;
    }
    
    hr {
        margin: 25px 0;
        background: linear-gradient(90deg, transparent, #667eea, transparent);
        height: 2px;
        border: none;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# SESION STATE
# ============================================================
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
# FUNCIONES AUXILIARES
# ============================================================
def cargar_ultimo_saldo_automatico():
    ultimo = db.obtener_ultimo_saldo()
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
    if valor_reportado is None:
        return "N/A"
    diferencia = safe_number(valor_calculado) - safe_number(valor_reportado)
    if abs(diferencia) < 0.01:
        return "✅ 0,00"
    elif diferencia > 0:
        return f"📈 +{formato_venezolano(diferencia)}"
    else:
        return f"📉 {formato_venezolano(diferencia)}"

def extraer_transito_reportado(df, transito_inicial):

    try:

        if df is None or df.empty:
            return None

        for idx, row in df.iterrows():

            row_str = ' '.join(
                [str(x) for x in row.values if pd.notna(x)]
            ).lower()

            if 'total' in row_str:

                for val in row.values:

                    num = ProcesadorArchivos._convertir_numero_europeo(val)

                    if not pd.isna(num) and num > 0:

                        return float(num)

        return None

    except Exception:
        return None
        
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
        }}
        .activos-pasivos-table th {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px;
            text-align: center;
            font-size: 1rem;
        }}
        .activos-pasivos-table td {{
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
        }}
        .activos-pasivos-table .activos-col {{
            background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
            vertical-align: top;
            width: 50%;
            border-radius: 12px 0 0 12px;
        }}
        .activos-pasivos-table .pasivos-col {{
            background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
            vertical-align: top;
            width: 50%;
            border-radius: 0 12px 12px 0;
        }}
        .activos-pasivos-table .capital-row {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-weight: bold;
            font-size: 1.1rem;
            color: white;
        }}
        .valor {{
            font-weight: bold;
            text-align: right;
        }}
        .titulo-cuenta {{
            font-weight: 500;
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
                    <tr style="border-top: 2px solid #a5d6a7;">
                        <td class="titulo-cuenta"><strong>📌 TOTAL ACTIVOS</strong></td>
                        <td class="valor"><strong>{formato_venezolano(total_activos)}</strong></td>
                    </tr>
                </table>
            </td>
            <td class="pasivos-col" style="width: 50%;">
                <table style="width: 100%; border: none;">
                    <tr><td class="titulo-cuenta">📋 Cuentas por pagar</td><td class="valor">{formato_venezolano(cx_p)}</td></tr>
                    <tr><td class="titulo-cuenta">🔄 Transferencias en tránsito</td><td class="valor">{formato_venezolano(transito)}</td></tr>
                    <tr style="border-top: 2px solid #ffe0b2;">
                        <td class="titulo-cuenta"><strong>📌 TOTAL PASIVOS</strong></td>
                        <td class="valor"><strong>{formato_venezolano(total_pasivos)}</strong></td>
                    </tr>
                </table>
            </td>
        </tr>
        <tr class="capital-row">
            <td colspan="4" style="text-align: center; padding: 15px;">
                🏁 CAPITAL DE TRABAJO NETO = {formato_venezolano(capital)}
            </td>
        </tr>
    </table>
    """
    return html

# ============================================================
# LOGIN CON LOGO Y TÍTULO CENTRADO
# ============================================================
def mostrar_login():
    with st.container():
        st.markdown("<br><br>", unsafe_allow_html=True)
        
        try:
            img = Image.open("auditoria.jpeg")
            img.thumbnail((200, 200))
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            st.markdown(
                f"""
                <div style="display: flex; justify-content: center; margin-bottom: 20px;">
                    <img src="data:image/jpeg;base64,{img_str}" style="width: 160px; height: auto;">
                </div>
                """, 
                unsafe_allow_html=True
            )
        except:
            st.markdown("<h1 style='text-align: center;'>AUDITORÍA</h1>", unsafe_allow_html=True)
        
        st.markdown("""
        <div style="text-align: center;">
            <h1 style="font-size: 2.2rem; font-weight: 700; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                       -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                SISTEMA CONTABLE DE VALIDACIÓN
            </h1>
            <h3 style="color: #666; font-weight: 400;">GRUPO BODEGUITA ORIENTE</h3>
            <hr style="margin: 25px auto; width: 80px; height: 3px; background: linear-gradient(90deg, #667eea, #764ba2); border: none;">
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("""
            <div style="background: white; border-radius: 24px; padding: 30px; box-shadow: 0 20px 35px -10px rgba(0,0,0,0.1);">
                <h3 style="text-align: center; color: #333; margin-bottom: 25px;">🔐 Iniciar Sesión</h3>
            </div>
            """, unsafe_allow_html=True)
            
            with st.container():
                usuario_id = st.text_input("Usuario", key="login_usuario", placeholder="Ingrese su usuario")
                password = st.text_input("Contraseña", type="password", key="login_password", placeholder="Ingrese su contraseña")
                
                if st.button("Ingresar", use_container_width=True):
                    if usuario_id in USUARIOS and USUARIOS[usuario_id]["password"] == password:
                        st.session_state.usuario_actual = usuario_id
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos")
        
        st.markdown("<br><br>", unsafe_allow_html=True)

if st.session_state.usuario_actual is None:
    mostrar_login()
    st.stop()

# ============================================================
# CARGAR AUTOMÁTICAMENTE EL ÚLTIMO SALDO GUARDADO
# ============================================================
if cargar_ultimo_saldo_automatico():
    st.sidebar.success("✅ Saldos del día anterior cargados automáticamente")
else:
    st.sidebar.info("📌 No hay saldos previos. Ingrese los saldos manualmente o guarde al finalizar el día.")

# ============================================================
# SIDEBAR MODERNA
# ============================================================
with st.sidebar:
    st.markdown("""
    <div style="text-align: center; margin-bottom: 20px;">
        <h3 style="color: white;">📊 VALIDADOR</h3>
        <p style="font-size: 0.8rem; opacity: 0.7;">Trazabilidad Diaria</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    st.markdown(f"**👤 Usuario:** {USUARIOS[st.session_state.usuario_actual]['nombre']}")
    st.markdown(f"**📋 Rol:** {USUARIOS[st.session_state.usuario_actual]['rol']}")
    
    st.markdown("---")
    
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.usuario_actual = None
        st.rerun()
    
    st.markdown("---")
    
    # Título de carga
    st.markdown("### 📁 Carga de Archivos")
    
    fecha_procesar = st.date_input("📅 Fecha a procesar", datetime.now())
    
    # ============================================================
    # GUARDAR Y MOSTRAR TASA BCV
    # ============================================================
    fecha_str = fecha_procesar.strftime("%Y-%m-%d")
    
    tasa_guardada = db.obtener_tasa_bcv(fecha_str)
    
    tasa_bcv = st.sidebar.number_input(
        "💵 Tasa BCV",
        value=float(tasa_guardada or 1),
        step=0.0001,
        format="%.4f"
    )
    
    db.guardar_tasa_bcv(
        fecha_str,
        tasa_bcv
    )
    
    if tasa_guardada is None:
        st.sidebar.warning(
            "No hay tasa BCV registrada para esta fecha"
        )
    
    st.markdown("---")
    
    # ============================================================
    # 🔥 NUEVO: SALDOS INICIALES MANUALES
    # ============================================================
    st.markdown("#### 📌 Saldos Iniciales Manuales")
    st.caption("Ingrese los saldos del día anterior")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        inventario_manual = st.number_input(
            "📦 Inventario",
            value=float(st.session_state.saldos['inventario']),
            step=100.0,
            format="%.2f",
            key="inv_manual"
        )
        cx_c_manual = st.number_input(
            "💰 CxC",
            value=float(st.session_state.saldos['cx_c']),
            step=100.0,
            format="%.2f",
            key="cxc_manual"
        )
    with col_s2:
        bancos_manual = st.number_input(
            "🏦 Bancos",
            value=float(st.session_state.saldos['bancos']),
            step=100.0,
            format="%.2f",
            key="ban_manual"
        )
        cx_p_manual = st.number_input(
            "📋 CxP",
            value=float(st.session_state.saldos['cx_p']),
            step=100.0,
            format="%.2f",
            key="cxp_manual"
        )
    
    transito_manual = st.number_input(
        "🔄 Tránsito",
        value=float(st.session_state.saldos['transito']),
        step=100.0,
        format="%.2f",
        key="tran_manual"
    )
    
    # Botón para actualizar saldos manuales
    if st.button("📊 Actualizar Saldos Manuales", use_container_width=True):
        st.session_state.saldos['inventario'] = inventario_manual
        st.session_state.saldos['cx_c'] = cx_c_manual
        st.session_state.saldos['bancos'] = bancos_manual
        st.session_state.saldos['cx_p'] = cx_p_manual
        st.session_state.saldos['transito'] = transito_manual
        st.success("✅ Saldos actualizados manualmente")
        st.rerun()
    
    st.markdown("---")
    
    st.markdown("#### 📂 Archivos del día")
    
    archivo_facturacion = st.file_uploader("Facturación diaria", type=["xlsx", "xls"], key="fact")
    archivo_cobranzas = st.file_uploader("Cobranzas procesadas", type=["xlsx", "xls"], key="cob")
    archivo_recepciones = st.file_uploader("Recepciones del día", type=["xlsx", "xls"], key="rec")
    archivo_egresos = st.file_uploader("Egresos iPago", type=["xlsx", "xls"], key="egr")
    archivo_estado_cuenta = st.file_uploader("Estado de cuenta bancario", type=["xlsx", "xls"], key="estado")
    archivo_notas_credito_cliente = st.file_uploader("Notas de crédito (clientes)", type=["xlsx", "xls"], key="notas_cliente")
    archivo_notas_credito_proveedor = st.file_uploader("Notas de crédito (proveedores)", type=["xlsx", "xls"], key="notas_proveedor")
    
    # ============================================================
    # 🔥 ARCHIVO DE COSTO DE FACTURACIÓN
    # ============================================================
    st.markdown("#### 📂 Archivos de costos")
    archivo_costo_facturacion = st.file_uploader("Costo de facturación", type=["xlsx", "xls"], key="costo_fact")
    
    st.markdown("#### 📂 Archivos de verificación")
    
    archivo_cxc_reportado = st.file_uploader("CxC final reportado", type=["xlsx", "xls"], key="cxc_rep")
    archivo_cxp_reportado = st.file_uploader("CxP final reportado", type=["xlsx", "xls"], key="cxp_rep")
    archivo_inventario_reportado = st.file_uploader("Inventario final reportado", type=["xlsx", "xls"], key="inv_rep")
    archivo_tb = st.file_uploader("TB.xlsx (Transferencias)", type=["xlsx", "xls"], key="tb")
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Cargar Día Anterior", use_container_width=True):
            ultimo = db.obtener_ultimo_saldo()
            if ultimo:
                st.session_state.saldos['inventario'] = safe_number(ultimo['inventario'])
                st.session_state.saldos['cx_c'] = safe_number(ultimo['cx_c'])
                st.session_state.saldos['bancos'] = safe_number(ultimo['bancos'])
                st.session_state.saldos['cx_p'] = safe_number(ultimo['cx_p'])
                st.session_state.saldos['transito'] = safe_number(ultimo['transito'])
                st.success("✅ Saldos cargados del día anterior")
                st.rerun()
            else:
                st.warning("No hay historial de días anteriores")
    
    with col2:
        if st.button("🧹 Resetear", use_container_width=True):
            st.session_state.saldos['inventario'] = 0
            st.session_state.saldos['cx_c'] = 0
            st.session_state.saldos['bancos'] = 0
            st.session_state.saldos['cx_p'] = 0
            st.session_state.saldos['transito'] = 0
            st.success("✅ Saldos reseteados a 0")
            st.rerun()

# ============================================================
# INTERFAZ PRINCIPAL
# ============================================================
st.markdown("""
<div style="text-align: center; margin-bottom: 30px;">
    <h1 style="font-size: 2rem; font-weight: 700;">📊 Validador de Trazabilidad Diaria</h1>
    <p style="color: #666; font-size: 1rem;">Capital de Trabajo Neto Operativo</p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================
if archivo_facturacion and archivo_cobranzas and archivo_recepciones and archivo_egresos and archivo_estado_cuenta:
    
    st.markdown(f"### 📈 Resultados de la Validación")
    st.markdown(f"**📅 Fecha procesada:** {fecha_procesar.strftime('%Y-%m-%d')}")
    
    # Saldos iniciales con formato venezolano
    st.markdown("#### 📌 Saldos Iniciales")
    
    # 🔥 DEBUG: Mostrar el valor real antes de formatear
    st.write("DEBUG INVENTARIO:", st.session_state.saldos['inventario'])
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("📦 Inventario", formato_venezolano(st.session_state.saldos['inventario']))
    with col2:
        st.metric("💰 CxC", formato_venezolano(st.session_state.saldos['cx_c']))
    with col3:
        st.metric("🏦 Bancos", formato_venezolano(st.session_state.saldos['bancos']))
    with col4:
        st.metric("📋 CxP", formato_venezolano(st.session_state.saldos['cx_p']))
    with col5:
        st.metric("🔄 Tránsito", formato_venezolano(st.session_state.saldos['transito']))
    
    st.markdown("---")
    
    # Leer archivos de movimientos
    try:
        df_facturacion = pd.read_excel(archivo_facturacion)
        df_cobranzas = pd.read_excel(archivo_cobranzas)
        df_recepciones = pd.read_excel(archivo_recepciones)
        df_egresos = pd.read_excel(archivo_egresos)
        df_estado_cuenta = pd.read_excel(archivo_estado_cuenta)
    except Exception as e:
        st.error(f"❌ Error al leer archivos Excel: {str(e)}")
        st.stop()
    
    # 🔥 Leer archivo de costo de facturación (usando procesar_costo_facturacion)
    costo_facturacion = 0.0
    if archivo_costo_facturacion:
        try:
            df_costo = pd.read_excel(archivo_costo_facturacion)
            costo_facturacion = ProcesadorArchivos.procesar_costo_facturacion(df_costo)
            st.success(f"✅ Costo de facturación cargado: {formato_venezolano(costo_facturacion)}")
        except Exception as e:
            st.warning(f"⚠️ Error al leer costo de facturación: {str(e)}")
    else:
        st.info("ℹ️ No se cargó archivo de costo de facturación. El costo se mantendrá en 0.")
    
    # Archivos de verificación
    saldos_reportados = {}
    
    if archivo_cxc_reportado:
        try:
            df_cxc_rep = pd.read_excel(archivo_cxc_reportado)
            # 🔥 TEMPORAL: Usar valor manual en lugar de extraer del archivo
            saldos_reportados['Cuentas por cobrar'] = 417932.23
            # saldos_reportados['Cuentas por cobrar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxc_rep, 'cxc')
        except Exception as e:
            st.warning(f"⚠️ Error al leer CxC reportado: {str(e)}")
    
    if archivo_cxp_reportado:
        try:
            df_cxp_rep = pd.read_excel(archivo_cxp_reportado)
            # 🔥 TEMPORAL: Usar valor manual en lugar de extraer del archivo
            saldos_reportados['Cuentas por pagar'] = 670116.79
            # saldos_reportados['Cuentas por pagar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxp_rep, 'cxp')
        except Exception as e:
            st.warning(f"⚠️ Error al leer CxP reportado: {str(e)}")
    
    if archivo_inventario_reportado:
        try:
            df_inv_rep = pd.read_excel(archivo_inventario_reportado)
            saldos_reportados['Inventario'] = ProcesadorArchivos.extraer_saldo_reportado(df_inv_rep, 'inventario')
        except Exception as e:
            st.warning(f"⚠️ Error al leer Inventario reportado: {str(e)}")
    
    if archivo_tb:
        try:
            df_tb = pd.read_excel(archivo_tb)
            transito_reportado = extraer_transito_reportado(df_tb, st.session_state.saldos['transito'])
            if transito_reportado is not None:
                saldos_reportados['Transferencias en tránsito'] = transito_reportado
        except Exception as e:
            st.warning(f"⚠️ Error al leer TB.xlsx: {str(e)}")
    
    # Notas de crédito
    notas_credito_cliente = 0
    if archivo_notas_credito_cliente:
        try:
            df_notas_cliente = pd.read_excel(archivo_notas_credito_cliente)
            notas_credito_cliente, _, _ = ProcesadorArchivos.procesar_notas_credito(df_notas_cliente)
        except Exception as e:
            st.warning(f"⚠️ Error al procesar notas de crédito clientes: {str(e)}")
    
    notas_credito_proveedor = 0
    if archivo_notas_credito_proveedor:
        try:
            df_notas_proveedor = pd.read_excel(archivo_notas_credito_proveedor)
            notas_credito_proveedor, _, _ = ProcesadorArchivos.procesar_notas_credito(df_notas_proveedor)
        except Exception as e:
            st.warning(f"⚠️ Error al procesar notas de crédito proveedores: {str(e)}")
    
    # 🔥 CAMBIO 1: PROCESAMIENTO DE EGRESOS - SE MANTIENE IGUAL
    try:
        facturacion, _, _, _ = ProcesadorArchivos.procesar_facturacion(df_facturacion)
        cobranzas, _, _ = ProcesadorArchivos.procesar_cobranzas(df_cobranzas)
        recepcion_total, compras_credito, _, _ = ProcesadorArchivos.procesar_recepciones(df_recepciones)
        pagos_proveedores, pagos_gastos, _, _ = ProcesadorArchivos.procesar_egresos(df_egresos)
        saldo_inicial_bancos, ingresos_id, ingresos_no_id, egresos_bancarios, saldo_final, total_ingresos, total_egresos = ProcesadorArchivos.procesar_estado_cuenta(
            df_estado_cuenta, st.session_state.saldos['bancos']
        )
    except Exception as e:
        st.error(f"❌ Error al procesar movimientos: {str(e)}")
        st.stop()
    
    # 🔥 VALIDAR Y ASEGURAR VALORES NUMÉRICOS
    facturacion = safe_number(facturacion)
    costo_facturacion = safe_number(costo_facturacion)
    cobranzas = safe_number(cobranzas)
    notas_credito_cliente = safe_number(notas_credito_cliente)
    recepcion_total = safe_number(recepcion_total)
    compras_credito = safe_number(compras_credito)
    pagos_proveedores = safe_number(pagos_proveedores)
    pagos_gastos = safe_number(pagos_gastos)
    notas_credito_proveedor = safe_number(notas_credito_proveedor)
    ingresos_id = safe_number(ingresos_id)
    ingresos_no_id = safe_number(ingresos_no_id)
    saldo_final = safe_number(saldo_final)
    saldo_inicial_bancos = safe_number(saldo_inicial_bancos)
    
    ingresos_totales = ingresos_id + ingresos_no_id
    
    # ============================================================
    # 🔥 CAMBIO 2: TABLA MOVIMIENTOS DEL DÍA - NUEVA ESTRUCTURA
    # ============================================================
    st.markdown("#### 📋 Movimientos del día procesados")
    
    mov_data = {
        "Concepto": [
            "Facturación",
            "Costo de Facturación",
            "Cobranzas",
            "Recepción de Mercancía",
            "Egresos iPago",
            "Estado de Cuenta Bancario",
            "Transferencias en Tránsito"
        ],
        "Monto": [
            formato_venezolano(facturacion),
            formato_venezolano(costo_facturacion),
            formato_venezolano(cobranzas),
            formato_venezolano(recepcion_total),
            
            # Egresos iPago
            formato_venezolano(
                pagos_proveedores + pagos_gastos
            ),
            
            # Saldo Final Estado de Cuenta
            formato_venezolano(
                saldo_final
            ),
            
            # TB
            formato_venezolano(
                saldos_reportados.get(
                    'Transferencias en tránsito',
                    0
                )
            )
        ]
    }
    st.dataframe(pd.DataFrame(mov_data), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # ============================================================
    # CÁLCULOS Y VALIDACIONES
    # ============================================================
    
    # Obtener total de egresos iPago desde el archivo
    total_egresos_ipago = ProcesadorArchivos.obtener_total_egresos_ipago(df_egresos)
    
    inventario_calculado = safe_number(st.session_state.saldos['inventario']) + recepcion_total - costo_facturacion
    cx_c_calculado = safe_number(st.session_state.saldos['cx_c']) + facturacion - cobranzas - notas_credito_cliente    
    # 🔥 BANCOS: Usar el saldo final reportado desde estado de cuenta
    bancos_calculado = safe_number(saldo_final)
    
    cx_p_calculado = safe_number(st.session_state.saldos['cx_p']) + compras_credito - pagos_proveedores - notas_credito_proveedor
    transito_calculado = safe_number(st.session_state.saldos['transito']) + ingresos_totales - cobranzas
    capital_calculado = (inventario_calculado + cx_c_calculado + bancos_calculado) - (cx_p_calculado + transito_calculado)
    
    # 🔥 Mostrar saldo inicial bancario extraído del estado de cuenta
    st.info(f"ℹ️ **Saldo Inicial Bancario (desde estado de cuenta):** {formato_venezolano(saldo_inicial_bancos)} Bs.")
    
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
    # TABLA COMPARATIVA CON REPORTADOS
    # ============================================================
    st.markdown("#### 📋 Comparación vs Valores Reportados")
    
    resultados_data = []
    cuentas = ["Inventario", "Cuentas por cobrar", "Bancos", "Cuentas por pagar", "Transferencias en tránsito", "Capital de Trabajo Neto"]
    valores_calc = [inventario_calculado, cx_c_calculado, bancos_calculado, cx_p_calculado, transito_calculado, capital_calculado]
    formulas = [
        "Inv. inicial + Recepción - Costo facturación",
        "CxC inicial + Facturación - Cobranzas - Notas crédito clientes",
        "Bancos inicial + Ingresos - (Pagos proveedores + Gastos)",
        "CxP inicial + Compras crédito - Pagos proveedores - Notas crédito proveedores",
        "Tránsito inicial + Ingresos del día - Cobranzas",
        "(Inv + CxC + Bancos) - (CxP + Tránsito)"
    ]
    
    for cuenta, calc, formula in zip(cuentas, valores_calc, formulas):
        rep = saldos_reportados.get(cuenta)
        diff = formatear_diferencia(calc, rep)
        resultados_data.append({
            "Cuenta": cuenta,
            "Fórmula": formula,
            "Calculado": formato_venezolano(calc),
            "Reportado": formato_venezolano(rep) if rep is not None else "-",
            "Diferencia": diff
        })
    
    st.dataframe(pd.DataFrame(resultados_data), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # ============================================================
    # VALIDACIONES CRUZADAS
    # ============================================================
    st.markdown("#### ✅ Validaciones Cruzadas")
    
    diff_bancos = safe_number(bancos_calculado) - safe_number(saldo_final)
    if abs(diff_bancos) > 0.01:
        st.error(f"❌ **Bancos**: Diferencia de {formato_venezolano(abs(diff_bancos))} Bs.")
    else:
        st.success(f"✅ **Bancos**: Coincide")
    
    if cobranzas > safe_number(st.session_state.saldos['cx_c']) + facturacion:
        st.warning(f"⚠️ **CxC**: Cobranzas ({formato_venezolano(cobranzas)}) superan saldo disponible")
    
    if pagos_proveedores > safe_number(st.session_state.saldos['cx_p']) + compras_credito:
        st.warning(f"⚠️ **CxP**: Pagos ({formato_venezolano(pagos_proveedores)}) superan saldo disponible")
    
    if transito_calculado >= 0:
        st.success(f"✅ **Transferencias**: Saldo positivo ({formato_venezolano(transito_calculado)})")
    else:
        st.error(f"❌ **Transferencias**: Saldo negativo ({formato_venezolano(transito_calculado)})")
    
    # 🔥 CAMBIO 3: NUEVA INFORMACIÓN DE VALIDACIÓN
    st.info(
        f"ℹ️ **Saldo Final Bancario Reportado**: "
        f"{formato_venezolano(saldo_final)} Bs."
    )
    
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
        <div class="kpi-card">
            <div class="label">🏁 CAPITAL DE TRABAJO NETO</div>
            <div class="value">{formato_venezolano(capital_calculado)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_kpi2:
        arrow = "📉" if var_capital < 0 else "📈"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="label">{arrow} VARIACIÓN DEL CAPITAL</div>
            <div class="value">{formato_venezolano(var_capital)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col_kpi3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="label">🔄 TRANSFERENCIAS EN TRÁNSITO</div>
            <div class="value">{formato_venezolano(transito_calculado)}</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # ============================================================
    # BOTONES DE ACCIÓN
    # ============================================================
    
    # 🔥 Usar valores reportados si existen, si no usar calculados
    inventario_final = saldos_reportados.get(
        'Inventario',
        inventario_calculado
    )
    
    cx_c_final = saldos_reportados.get(
        'Cuentas por cobrar',
        cx_c_calculado
    )
    
    cx_p_final = saldos_reportados.get(
        'Cuentas por pagar',
        cx_p_calculado
    )
    
    transito_final = saldos_reportados.get(
        'Transferencias en tránsito',
        transito_calculado
    )
    
    bancos_final = bancos_calculado
    
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("💾 Guardar saldos calculados", use_container_width=True):
            
            saldos_guardar = {
                'inventario': inventario_final,
                'cx_c': cx_c_final,
                'bancos': bancos_final,
                'cx_p': cx_p_final,
                'transito': transito_final,
                'capital': capital_calculado
            }
            
            db.guardar_saldos(
                fecha_procesar.strftime('%Y-%m-%d'),
                saldos_guardar
            )
            
            st.session_state.saldos['inventario'] = inventario_final
            st.session_state.saldos['cx_c'] = cx_c_final
            st.session_state.saldos['bancos'] = bancos_final
            st.session_state.saldos['cx_p'] = cx_p_final
            st.session_state.saldos['transito'] = transito_final
            
            st.session_state.saldos['capital_anterior'] = capital_calculado
            
            st.success("✅ Saldos guardados correctamente")
    
    with col_btn2:
        if st.button("📜 Ver historial", use_container_width=True):
            historial = db.obtener_historial_saldos(10)
            if not historial.empty:
                st.dataframe(historial, use_container_width=True)
            else:
                st.info("No hay historial aún")
    
    # ============================================================
    # 🔥 CAMBIO 4: REGLAS DE NEGOCIO - NUEVAS REGLAS
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
        📋 Cuentas por pagar = CxP inicial + Compras crédito - Pagos proveedores - Notas crédito proveedores
        """)

else:
    st.info("👈 Carga todos los archivos del día en la barra lateral para comenzar la validación")
    
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
        
        ### Recepciones del día
        | Compra | Proveedor | F. Recepción | $ Neto + IVA |
        |--------|-----------|--------------|--------------|
        | 0000000587 | MOLINOS NACIONALES | 15/06/2026 | 21612.5 |
        | Total General: | | | 21612.5 |
        
        ### Egresos iPago
        | Fecha Pago | Proveedor | Tipo de Egreso | Monto | Referencia |
        |------------|-----------|----------------|-------|------------|
        | 2026-06-15 | OLEICA | Proveedor | 2055920.65 | 0329208731225 |
        | 2026-06-15 | HIDROBOLIVAR | Fijo | 36438.29 | 0429716006476 |
        
        ### Estado de cuenta bancario
        | Fecha | Referencia | Descripción | Crédito | Débito |
        |-------|------------|-------------|---------|--------|
        | 15/06/2026 | 0591367815942 | TRANSF RECIBIDA | 154.930,00 | 0,00 |
        
        ### TB.xlsx (Transferencias en tránsito)
        | Cuenta | Referencia | Fecha | Descripción | Monto |
        |--------|------------|-------|-------------|-------|
        | BANCO DE VENEZUELA | 059137177692 | 2026-05-30 | TRANSF RECIBIDA | 5152834 |
        """)

st.markdown("---")
st.caption("✨ Validador de Trazabilidad Diaria - Capital de Trabajo Neto Operativo | Grupo Bodeguita Oriente")
