# app.py - Con campos para saldos iniciales manuales - VERSIÓN COMPLETA CON CIERRE DIARIO Y VISUALIZACIÓN DE ARCHIVOS

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

def formato_venezolano_desde_str(valor_str):
    """
    Convierte un string con formato venezolano a número para cálculos
    """
    if valor_str is None or valor_str == "-" or valor_str == "":
        return 0
    try:
        if isinstance(valor_str, str):
            # Remover puntos de miles y reemplazar coma decimal
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
    
    with st.expander(f"📄 {titulo} - {nombre_archivo}", expanded=False):
        # Mostrar estadísticas básicas
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📊 Filas", len(df))
        with col2:
            st.metric("📋 Columnas", len(df.columns))
        with col3:
            # Intentar mostrar el total si hay una columna de montos
            columnas_numericas = df.select_dtypes(include=['number']).columns
            if len(columnas_numericas) > 0:
                total = df[columnas_numericas[0]].sum()
                st.metric("💰 Total", formato_venezolano(total))
        
        # Mostrar el DataFrame completo con estilo
        st.dataframe(
            df.style.background_gradient(subset=columnas_numericas, cmap='Blues', low=0.1, high=0.9),
            use_container_width=True,
            height=400
        )
        
        # Mostrar nombres de columnas
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
        cursor: pointer;
        transition: transform 0.2s;
    }
    
    .kpi-card:hover {
        transform: translateY(-3px);
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
    
    .popover-hint {
        color: #667eea;
        font-size: 0.8rem;
        text-align: center;
        margin-top: -5px;
        margin-bottom: 10px;
        opacity: 0.7;
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
    # SALDOS INICIALES MANUALES
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
    
    # ============================================================
    # FILTRO POR RANGO DE FECHAS
    # ============================================================
    st.markdown("#### 📅 Filtro por Rango de Fechas")
    
    col_fecha1, col_fecha2 = st.columns(2)
    with col_fecha1:
        fecha_desde = st.date_input(
            "📅 Desde", 
            st.session_state.fecha_desde,
            key="filtro_desde"
        )
    with col_fecha2:
        fecha_hasta = st.date_input(
            "📅 Hasta", 
            st.session_state.fecha_hasta,
            key="filtro_hasta"
        )
    
    col_btn_f1, col_btn_f2 = st.columns(2)
    with col_btn_f1:
        if st.button("🔍 Aplicar Filtro", use_container_width=True):
            st.session_state.fecha_desde = fecha_desde
            st.session_state.fecha_hasta = fecha_hasta
            st.session_state.mostrar_historial = True
            st.rerun()
    
    with col_btn_f2:
        if st.button("🔄 Resetear", use_container_width=True):
            st.session_state.fecha_desde = datetime.now() - pd.Timedelta(days=7)
            st.session_state.fecha_hasta = datetime.now()
            st.session_state.mostrar_historial = False
            st.session_state.historial_data = None
            st.rerun()
    
    # Mostrar historial automáticamente después de aplicar filtro
    if st.session_state.get('mostrar_historial', False):
        desde = st.session_state.fecha_desde
        hasta = st.session_state.fecha_hasta
        
        historial = db.obtener_historial_por_fechas(
            desde.strftime('%Y-%m-%d'), 
            hasta.strftime('%Y-%m-%d')
        )
        
        if not historial.empty:
            # Guardar en session_state para usarlo en el área principal
            st.session_state.historial_data = historial.copy()
            
            # Formatear columnas numéricas para mostrar
            df_mostrar = historial.copy()
            columnas_numericas = ['inventario', 'cx_c', 'bancos', 'cx_p', 'transito', 'capital']
            for col in columnas_numericas:
                if col in df_mostrar.columns:
                    df_mostrar[col] = df_mostrar[col].apply(formato_venezolano)
            
            st.dataframe(df_mostrar, use_container_width=True)
            st.caption(f"📊 Mostrando registros desde {desde.strftime('%d/%m/%Y')} hasta {hasta.strftime('%d/%m/%Y')}")
            
            # Resumen del período
            col_res1, col_res2, col_res3 = st.columns(3)
            with col_res1:
                st.metric("📊 Total de días", len(historial))
            with col_res2:
                if 'capital' in historial.columns and len(historial) > 0:
                    capital_inicial_val = safe_number(historial.iloc[0]['capital'])
                    capital_final_val = safe_number(historial.iloc[-1]['capital'])
                    st.metric("📈 Variación capital", formato_venezolano(capital_final_val - capital_inicial_val))
            with col_res3:
                if 'capital' in historial.columns and len(historial) > 0:
                    st.metric("🏁 Capital final", formato_venezolano(safe_number(historial.iloc[-1]['capital'])))
        else:
            st.info("No hay registros en el rango de fechas seleccionado")
            st.session_state.historial_data = None
    
    st.markdown("---")
    
    st.markdown("#### 📂 Archivos del día")
    
    archivo_facturacion = st.file_uploader("Facturación diaria", type=["xlsx", "xls"], key="fact")
    archivo_cobranzas = st.file_uploader("Cobranzas procesadas", type=["xlsx", "xls"], key="cob")
    archivo_recepciones = st.file_uploader("Recepciones del día (OPCIONAL)", type=["xlsx", "xls"], key="rec")
    archivo_egresos = st.file_uploader("Egresos iPago", type=["xlsx", "xls"], key="egr")
    archivo_estado_cuenta = st.file_uploader("Estado de cuenta bancario", type=["xlsx", "xls"], key="estado")
    archivo_notas_credito_cliente = st.file_uploader("Notas de crédito (clientes)", type=["xlsx", "xls"], key="notas_cliente")
    archivo_notas_credito_proveedor = st.file_uploader("Notas de crédito (proveedores)", type=["xlsx", "xls"], key="notas_proveedor")
    
    # ============================================================
    # ARCHIVO DE COSTO DE FACTURACIÓN
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
# MOSTRAR HISTORIAL FILTRADO EN EL ÁREA PRINCIPAL
# ============================================================
if st.session_state.get('mostrar_historial', False) and st.session_state.get('historial_data') is not None:
    with st.expander("📊 Historial Filtrado", expanded=True):
        historial = st.session_state.historial_data
        df_mostrar = historial.copy()
        columnas_numericas = ['inventario', 'cx_c', 'bancos', 'cx_p', 'transito', 'capital']
        for col in columnas_numericas:
            if col in df_mostrar.columns:
                df_mostrar[col] = df_mostrar[col].apply(formato_venezolano)
        
        st.dataframe(df_mostrar, use_container_width=True)
        
        # Gráfico de evolución del capital
        if 'capital' in historial.columns and len(historial) > 1:
            try:
                fig, ax = plt.subplots(figsize=(10, 4))
                historial_ordenado = historial.sort_values('fecha')
                ax.plot(historial_ordenado['fecha'], historial_ordenado['capital'], marker='o', linewidth=2, color='#667eea')
                ax.set_title('Evolución del Capital de Trabajo Neto', fontsize=14, fontweight='bold')
                ax.set_xlabel('Fecha')
                ax.set_ylabel('Capital (Bs.)')
                ax.grid(True, alpha=0.3)
                plt.xticks(rotation=45)
                plt.tight_layout()
                st.pyplot(fig)
            except:
                pass

# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================
# Recepción ahora es OPCIONAL
# Solo Facturación, Cobranzas, Egresos y Estado de Cuenta son obligatorios
if archivo_facturacion and archivo_cobranzas and archivo_egresos and archivo_estado_cuenta:
    
    st.markdown(f"### 📈 Resultados de la Validación")
    st.markdown(f"**📅 Fecha procesada:** {fecha_procesar.strftime('%Y-%m-%d')}")
    
    # ============================================================
    # 🔥 SALDOS INICIALES - DESPLEGABLE CON ORIGEN
    # ============================================================
    with st.expander("📌 Saldos Iniciales - Ver detalle de origen", expanded=False):
        
        # Origen de los saldos iniciales
        origen_saldos = {}
        
        # Verificar si los saldos vienen del día anterior o son manuales
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
        
        # Mostrar los saldos con su origen
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
        
        # Mostrar el capital anterior si existe
        if st.session_state.saldos.get('capital_anterior', 0) > 0:
            st.markdown(f"""
            | 🏁 Capital anterior | {formato_venezolano(st.session_state.saldos['capital_anterior'])} | 📂 Calculado del día anterior |
            """)
    
    # Saldos iniciales resumidos
    st.markdown("#### 📌 Saldos Iniciales (Resumen)")
    
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
    
    # ============================================================
    # LECTURA DE ARCHIVOS DE MOVIMIENTOS CON VISUALIZACIÓN
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
    
    # Leer archivo de Recepción (OPCIONAL)
    recepcion_total = 0.0
    df_recepciones = None
    compras_credito = 0.0
    
    if archivo_recepciones:
        try:
            df_recepciones = pd.read_excel(archivo_recepciones)
            mostrar_archivo_con_formato(df_recepciones, archivo_recepciones.name, "Recepción de Mercancía")
            recepcion_total, compras_credito, _, _ = ProcesadorArchivos.procesar_recepciones(df_recepciones)
            st.info(f"✅ Recepción de mercancía procesada: {formato_venezolano(recepcion_total)}")
        except Exception as e:
            st.warning(f"⚠️ Error procesando Recepción: {str(e)}")
            recepcion_total = 0.0
            compras_credito = 0.0
    else:
        st.info("ℹ️ No se cargó archivo de Recepción. Se usará valor 0,00 para inventario.")
    
    # Leer archivo de costo de facturación
    costo_facturacion = 0.0
    if archivo_costo_facturacion:
        try:
            df_costo = pd.read_excel(archivo_costo_facturacion)
            mostrar_archivo_con_formato(df_costo, archivo_costo_facturacion.name, "Costo de Facturación")
            costo_facturacion = ProcesadorArchivos.procesar_costo_facturacion(df_costo)
            st.success(f"✅ Costo de facturación cargado: {formato_venezolano(costo_facturacion)}")
        except Exception as e:
            st.warning(f"⚠️ Error al leer costo de facturación: {str(e)}")
    else:
        st.info("ℹ️ No se cargó archivo de costo de facturación. El costo se mantendrá en 0.")
    
    # ============================================================
    # ARCHIVOS DE VERIFICACIÓN - CON VISUALIZACIÓN
    # ============================================================
    saldos_reportados = {}
    archivos_cargados = {}
    
    # --- CUENTAS POR COBRAR ---
    if archivo_cxc_reportado:
        try:
            df_cxc_rep = pd.read_excel(archivo_cxc_reportado)
            saldos_reportados['Cuentas por cobrar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxc_rep, 'cxc')
            archivos_cargados['CxC'] = df_cxc_rep
            mostrar_archivo_con_formato(df_cxc_rep, archivo_cxc_reportado.name, "Cuentas por Cobrar")
        except Exception as e:
            st.warning(f"⚠️ Error al leer CxC reportado: {str(e)}")
    
    # --- CUENTAS POR PAGAR ---
    if archivo_cxp_reportado:
        try:
            df_cxp_rep = pd.read_excel(archivo_cxp_reportado)
            saldos_reportados['Cuentas por pagar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxp_rep, 'cxp')
            archivos_cargados['CxP'] = df_cxp_rep
            mostrar_archivo_con_formato(df_cxp_rep, archivo_cxp_reportado.name, "Cuentas por Pagar")
        except Exception as e:
            st.warning(f"⚠️ Error al leer CxP reportado: {str(e)}")
    
    # --- INVENTARIO ---
    if archivo_inventario_reportado:
        try:
            df_inv_rep = pd.read_excel(archivo_inventario_reportado)
            saldos_reportados['Inventario'] = ProcesadorArchivos.extraer_saldo_reportado(df_inv_rep, 'inventario')
            archivos_cargados['Inventario'] = df_inv_rep
            mostrar_archivo_con_formato(df_inv_rep, archivo_inventario_reportado.name, "Inventario")
        except Exception as e:
            st.warning(f"⚠️ Error al leer Inventario reportado: {str(e)}")
    
    # --- TRANSFERENCIAS EN TRÁNSITO (TB) ---
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
    
    # Notas de crédito
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
    
    # PROCESAMIENTO DE MOVIMIENTOS
    try:
        facturacion, _, _, _ = ProcesadorArchivos.procesar_facturacion(df_facturacion)
        cobranzas, _, _ = ProcesadorArchivos.procesar_cobranzas(df_cobranzas)
        pagos_proveedores, pagos_gastos, _, _ = ProcesadorArchivos.procesar_egresos(df_egresos)
        
        saldo_inicial_bancos, ingresos_id, ingresos_no_id, egresos_bancarios, saldo_final, total_ingresos, total_egresos = ProcesadorArchivos.procesar_estado_cuenta(
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
    notas_credito_proveedor = safe_number(notas_credito_proveedor)
    ingresos_id = safe_number(ingresos_id)
    ingresos_no_id = safe_number(ingresos_no_id)
    saldo_final = safe_number(saldo_final)
    saldo_inicial_bancos = safe_number(saldo_inicial_bancos)
    
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
            "Egresos iPago",
            "Estado de Cuenta Bancario",
            "Transferencias en Tránsito"
        ],
        "Monto": [
            formato_venezolano(facturacion),
            formato_venezolano(costo_facturacion),
            formato_venezolano(cobranzas),
            formato_venezolano(recepcion_total),
            formato_venezolano(pagos_proveedores + pagos_gastos),
            formato_venezolano(saldo_final),
            formato_venezolano(saldos_reportados.get('Transferencias en tránsito', 0))
        ]
    }
    st.dataframe(pd.DataFrame(mov_data), use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # ============================================================
    # CÁLCULOS Y VALIDACIONES
    # ============================================================
    
    inventario_calculado = safe_number(st.session_state.saldos['inventario']) + recepcion_total - costo_facturacion
    cx_c_calculado = safe_number(st.session_state.saldos['cx_c']) + facturacion - cobranzas - notas_credito_cliente    
    bancos_calculado = safe_number(saldo_final)
    cx_p_calculado = safe_number(st.session_state.saldos['cx_p']) + recepcion_total - pagos_proveedores
    transito_calculado = safe_number(st.session_state.saldos['transito']) + ingresos_totales - cobranzas
    capital_calculado = (inventario_calculado + cx_c_calculado + bancos_calculado) - (cx_p_calculado + transito_calculado)
    
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
    # FUNCIÓN PARA EXPLICAR DIFERENCIAS
    # ============================================================
    def explicar_diferencia(cuenta, calculado, reportado):
        diferencia = calculado - reportado
        
        if abs(diferencia) < 0.01:
            return "✅ Sin diferencia"

        if cuenta == "Inventario":
            return f"Salida de inventario no explicada por {formato_venezolano(abs(diferencia))}"
        elif cuenta == "Cuentas por cobrar":
            return f"CxC adicional pendiente por {formato_venezolano(abs(diferencia))}"
        elif cuenta == "Cuentas por pagar":
            return f"Ajuste / NC proveedor pendiente por {formato_venezolano(abs(diferencia))}"
        elif cuenta == "Transferencias en tránsito":
            return f"Transferencias pendientes por {formato_venezolano(abs(diferencia))}"

        return ""
    
    # ============================================================
    # 🔥 COMPARACIÓN VS VALORES REPORTADOS - CON AJUSTE
    # ============================================================
    st.markdown("#### 📋 Comparación vs Valores Reportados")

    # Obtener valores reportados
    inventario_reportado = saldos_reportados.get('Inventario')
    cx_c_reportado = saldos_reportados.get('Cuentas por cobrar')
    cx_p_reportado = saldos_reportados.get('Cuentas por pagar')
    transito_reportado = saldos_reportados.get('Transferencias en tránsito')

    # Obtener valores del día anterior
    inventario_anterior = safe_number(st.session_state.saldos.get('inventario', 0))
    cx_c_anterior = safe_number(st.session_state.saldos.get('cx_c', 0))
    bancos_anterior = safe_number(st.session_state.saldos.get('bancos', 0))
    cx_p_anterior = safe_number(st.session_state.saldos.get('cx_p', 0))
    transito_anterior = safe_number(st.session_state.saldos.get('transito', 0))

    # Inicializar ajustes en session_state si no existen
    if 'ajustes' not in st.session_state:
        st.session_state.ajustes = {
            'inventario': {'monto': 0.0, 'justificacion': ''},
            'cx_c': {'monto': 0.0, 'justificacion': ''},
            'cx_p': {'monto': 0.0, 'justificacion': ''},
            'transito': {'monto': 0.0, 'justificacion': ''}
        }

    resultados_data = []

    # Función para crear cada fila de la tabla
    def crear_fila_comparacion(cuenta, formula, valor_anterior, valor_calculado, valor_reportado, key_ajuste):
        diferencia = safe_number(valor_calculado) - safe_number(valor_reportado) if valor_reportado is not None else 0
        
        # Obtener ajuste actual
        ajuste_actual = st.session_state.ajustes.get(key_ajuste, {'monto': 0.0, 'justificacion': ''})
        monto_ajuste = ajuste_actual.get('monto', 0.0)
        justificacion = ajuste_actual.get('justificacion', '')
        
        # Calcular diferencia ajustada
        diferencia_ajustada = diferencia - monto_ajuste
        estado_ajuste = "✅ 0,00" if abs(diferencia_ajustada) < 0.01 else formatear_diferencia(diferencia_ajustada, 0)
        
        return {
            "Cuenta": cuenta,
            "Fórmula": formula,
            "Información día anterior": formato_venezolano(valor_anterior),
            "Calculado": formato_venezolano(valor_calculado),
            "Reportado": formato_venezolano(valor_reportado) if valor_reportado is not None else "-",
            "Diferencia": formatear_diferencia(valor_calculado, valor_reportado),
            "Ajuste": monto_ajuste,
            "Diferencia Ajustada": estado_ajuste,
            "Justificación": justificacion if justificacion else "-",
            "Origen": explicar_diferencia(cuenta, valor_calculado, valor_reportado if valor_reportado is not None else 0)
        }

    # Inventario
    resultados_data.append(crear_fila_comparacion(
        "Inventario",
        "Inv. inicial + Recepción - Costo facturación",
        inventario_anterior,
        inventario_calculado,
        inventario_reportado,
        'inventario'
    ))

    # Cuentas por cobrar
    resultados_data.append(crear_fila_comparacion(
        "Cuentas por cobrar",
        "CxC inicial + Facturación - Cobranzas - Notas crédito clientes",
        cx_c_anterior,
        cx_c_calculado,
        cx_c_reportado,
        'cx_c'
    ))

    # Bancos
    resultados_data.append({
        "Cuenta": "Bancos",
        "Fórmula": "Bancos inicial + Ingresos - (Pagos proveedores + Gastos)",
        "Información día anterior": formato_venezolano(bancos_anterior),
        "Calculado": formato_venezolano(bancos_calculado),
        "Reportado": "-",
        "Diferencia": "-",
        "Ajuste": 0,
        "Diferencia Ajustada": "-",
        "Justificación": "-",
        "Origen": "Tomado del estado de cuenta"
    })

    # Cuentas por pagar
    resultados_data.append(crear_fila_comparacion(
        "Cuentas por pagar",
        "CxP inicial + Recepciones - Pagos proveedores",
        cx_p_anterior,
        cx_p_calculado,
        cx_p_reportado,
        'cx_p'
    ))

    # Transferencias en tránsito
    resultados_data.append(crear_fila_comparacion(
        "Transferencias en tránsito",
        "Tránsito inicial + Ingresos del día - Cobranzas",
        transito_anterior,
        transito_calculado,
        transito_reportado,
        'transito'
    ))

    # Capital de Trabajo Neto
    resultados_data.append({
        "Cuenta": "Capital de Trabajo Neto",
        "Fórmula": "(Inv + CxC + Bancos) - (CxP + Tránsito)",
        "Información día anterior": "-",
        "Calculado": formato_venezolano(capital_calculado),
        "Reportado": "-",
        "Diferencia": "-",
        "Ajuste": 0,
        "Diferencia Ajustada": "-",
        "Justificación": "-",
        "Origen": "Calculado automáticamente"
    })

    # Mostrar tabla de comparación
    df_comparacion = pd.DataFrame(resultados_data)
    st.dataframe(df_comparacion, use_container_width=True, hide_index=True)

    # ============================================================
    # 🔥 BOTONES PARA VER ARCHIVOS ORIGINALES
    # ============================================================
    st.markdown("---")
    st.markdown("#### 📂 Ver archivos originales")
    st.caption("💡 Haz clic en los botones para ver el contenido completo de cada archivo")

    # Crear una fila de botones para ver cada archivo
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
                if st.button(f"📄 Ver {nombre}", key=f"btn_{nombre}", use_container_width=True):
                    # Mostrar el DataFrame en un expander
                    mostrar_archivo_con_formato(
                        archivos_cargados[titulo], 
                        archivo.name, 
                        f"Archivo {titulo}"
                    )
            else:
                st.button(f"❌ {nombre} no cargado", disabled=True, use_container_width=True)

    # ============================================================
    # 🔥 FORMULARIO DE AJUSTES
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

    # Botón para guardar ajustes
    col_btn_ajuste1, col_btn_ajuste2 = st.columns(2)
    with col_btn_ajuste1:
        if st.button("💾 Guardar Ajustes", use_container_width=True):
            st.session_state.ajustes['inventario'] = {'monto': ajuste_inv, 'justificacion': just_inv}
            st.session_state.ajustes['cx_c'] = {'monto': ajuste_cxc, 'justificacion': just_cxc}
            st.session_state.ajustes['cx_p'] = {'monto': ajuste_cxp, 'justificacion': just_cxp}
            st.session_state.ajustes['transito'] = {'monto': ajuste_transito, 'justificacion': just_transito}
            
            # Guardar en base de datos
            db.guardar_ajustes(
                fecha_procesar.strftime('%Y-%m-%d'),
                st.session_state.ajustes
            )
            
            st.success("✅ Ajustes guardados correctamente")
            st.rerun()
    
    with col_btn_ajuste2:
        if st.button("🔄 Resetear Ajustes", use_container_width=True):
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
    # 🔥 CIERRE DIARIO - CON ORIGEN DE ARCHIVOS
    # ============================================================
    st.markdown("#### 📊 CIERRE DIARIO - Capital de Trabajo Neto")

    # ============================================================
    # 1. VALIDAR QUE LOS ARCHIVOS DE VERIFICACIÓN ESTÉN CARGADOS
    # ============================================================

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

    # ============================================================
    # 2. OBTENER VALORES DE ARCHIVOS DE VERIFICACIÓN (SOLO)
    # ============================================================

    # 🔥 CxC: SOLO del archivo de verificación
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

    # 🔥 Inventario: SOLO del archivo de verificación
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

    # 🔥 CxP: SOLO del archivo de verificación
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

    # 🔥 Tránsito: SOLO del archivo TB
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

    # 🔥 Bancos: SIEMPRE del estado de cuenta (archivo obligatorio)
    bancos_cierre = saldo_final
    st.success(f"🏦 Bancos: **DESDE ESTADO DE CUENTA** → {formato_venezolano(bancos_cierre)}")

    # ============================================================
    # 3. ASEGURAR VALORES NUMÉRICOS
    # ============================================================
    cx_c_cierre = safe_number(cx_c_cierre)
    inventario_cierre = safe_number(inventario_cierre)
    bancos_cierre = safe_number(bancos_cierre)
    cx_p_cierre = safe_number(cx_p_cierre)
    transito_cierre = safe_number(transito_cierre)

    # ============================================================
    # 4. CALCULAR ACTIVOS Y PASIVOS OPERATIVOS
    # ============================================================

    activos_operativos = cx_c_cierre + inventario_cierre + bancos_cierre
    pasivos_operativos = cx_p_cierre + transito_cierre
    capital_neto = activos_operativos - pasivos_operativos

    # ============================================================
    # 5. MOSTRAR TABLA DEL CIERRE DIARIO CON ORIGEN DE ARCHIVOS
    # ============================================================

    st.markdown("#### 📋 Detalle del Cierre Diario")

    # Crear DataFrame para mostrar con origen de archivo
    cierre_detalle = [
        {
            "Concepto": "📦 Inventario",
            "Archivo Origen": origen_archivos.get('Inventario', 'NO DISPONIBLE'),
            "Tipo": "ACTIVO",
            "Monto": formato_venezolano(inventario_cierre)
        },
        {
            "Concepto": "💰 Cuentas por cobrar",
            "Archivo Origen": origen_archivos.get('CxC', 'NO DISPONIBLE'),
            "Tipo": "ACTIVO",
            "Monto": formato_venezolano(cx_c_cierre)
        },
        {
            "Concepto": "🏦 Bancos",
            "Archivo Origen": origen_archivos.get('Bancos', 'NO DISPONIBLE'),
            "Tipo": "ACTIVO",
            "Monto": formato_venezolano(bancos_cierre)
        },
        {
            "Concepto": "📌 TOTAL ACTIVOS OPERATIVOS",
            "Archivo Origen": "Suma de activos",
            "Tipo": "ACTIVO_TOTAL",
            "Monto": formato_venezolano(activos_operativos)
        },
        {
            "Concepto": "📋 Cuentas por pagar",
            "Archivo Origen": origen_archivos.get('CxP', 'NO DISPONIBLE'),
            "Tipo": "PASIVO",
            "Monto": formato_venezolano(cx_p_cierre)
        },
        {
            "Concepto": "🔄 Transferencias en tránsito",
            "Archivo Origen": origen_archivos.get('Tránsito', 'NO DISPONIBLE'),
            "Tipo": "PASIVO",
            "Monto": formato_venezolano(transito_cierre)
        },
        {
            "Concepto": "📌 TOTAL PASIVOS OPERATIVOS",
            "Archivo Origen": "Suma de pasivos",
            "Tipo": "PASIVO_TOTAL",
            "Monto": formato_venezolano(pasivos_operativos)
        },
        {
            "Concepto": "🏁 CAPITAL DE TRABAJO NETO",
            "Archivo Origen": "Activos - Pasivos",
            "Tipo": "CAPITAL",
            "Monto": formato_venezolano(capital_neto)
        }
    ]

    df_cierre = pd.DataFrame(cierre_detalle)

    # Función para colorear las filas
    def color_cierre_rows(row):
        if row['Tipo'] == 'ACTIVO_TOTAL':
            return ['background-color: #e8f5e9; font-weight: bold;'] * len(row)
        elif row['Tipo'] == 'PASIVO_TOTAL':
            return ['background-color: #fff3e0; font-weight: bold;'] * len(row)
        elif row['Tipo'] == 'CAPITAL':
            if capital_neto >= 0:
                return ['background-color: #667eea; color: white; font-weight: bold; font-size: 1.1rem;'] * len(row)
            else:
                return ['background-color: #dc3545; color: white; font-weight: bold; font-size: 1.1rem;'] * len(row)
        elif row['Tipo'] == 'ACTIVO':
            return ['background-color: #f1f8f4;'] * len(row)
        elif row['Tipo'] == 'PASIVO':
            return ['background-color: #fff8f0;'] * len(row)
        return [''] * len(row)

    styled_df = df_cierre.style.apply(color_cierre_rows, axis=1).hide(axis='index')
    st.dataframe(styled_df, use_container_width=True)

    # ============================================================
    # 6. DETALLE CON ORIGEN DE ARCHIVOS (DESPLEGABLE)
    # ============================================================
    with st.expander("📂 Ver origen detallado de cada archivo", expanded=False):
        st.markdown("""
        ### 📂 Origen de los archivos utilizados en el Cierre Diario
        
        | Concepto | Archivo | Estado |
        |----------|---------|--------|
        """)
        
        # Cuentas por cobrar
        if archivo_cxc_reportado:
            st.markdown(f"| 💰 Cuentas por cobrar | `{archivo_cxc_reportado.name}` | ✅ Cargado |")
        else:
            st.markdown("| 💰 Cuentas por cobrar | **NO CARGADO** | ❌ No disponible |")
        
        # Inventario
        if archivo_inventario_reportado:
            st.markdown(f"| 📦 Inventario | `{archivo_inventario_reportado.name}` | ✅ Cargado |")
        else:
            st.markdown("| 📦 Inventario | **NO CARGADO** | ❌ No disponible |")
        
        # Cuentas por pagar
        if archivo_cxp_reportado:
            st.markdown(f"| 📋 Cuentas por pagar | `{archivo_cxp_reportado.name}` | ✅ Cargado |")
        else:
            st.markdown("| 📋 Cuentas por pagar | **NO CARGADO** | ❌ No disponible |")
        
        # Transferencias en tránsito
        if archivo_tb:
            st.markdown(f"| 🔄 Transferencias en tránsito | `{archivo_tb.name}` | ✅ Cargado |")
        else:
            st.markdown("| 🔄 Transferencias en tránsito | **NO CARGADO** | ❌ No disponible |")
        
        # Bancos
        if archivo_estado_cuenta:
            st.markdown(f"| 🏦 Bancos | `{archivo_estado_cuenta.name}` | ✅ Cargado |")
        else:
            st.markdown("| 🏦 Bancos | **NO CARGADO** | ❌ No disponible |")
        
        st.markdown("""
        
        ### 📌 Valores extraídos:
        """)
        
        # Mostrar los valores extraídos con su origen
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
    # 7. RESUMEN DEL CIERRE DIARIO - CON KPIS CLICABLES
    # ============================================================
    st.markdown("---")
    st.markdown("#### 📊 Resumen del Cierre Diario")
    st.caption("💡 Haz clic en cada KPI para ver su composición detallada")

    col_c1, col_c2, col_c3 = st.columns(3)

    with col_c1:
        # KPI de Activos con popover
        with st.popover("📈 Ver detalle de Activos", use_container_width=True):
            st.markdown("##### Composición de Activos Operativos")
            st.markdown(f"""
            | Concepto | Monto | Archivo Origen |
            |----------|-------|----------------|
            | **Cuentas por cobrar** | {formato_venezolano(cx_c_cierre)} | {'✅ Cargado' if archivo_cxc_reportado else '❌ No disponible'} |
            | **Inventario** | {formato_venezolano(inventario_cierre)} | {'✅ Cargado' if archivo_inventario_reportado else '❌ No disponible'} |
            | **Bancos** | {formato_venezolano(bancos_cierre)} | ✅ Estado de cuenta |
            | **TOTAL ACTIVOS** | **{formato_venezolano(activos_operativos)}** |  |
            """)
            st.caption("✅ Valores tomados de los archivos de verificación.")
            
            # Mostrar gráfico de barras si hay datos
            if cx_c_cierre > 0 or inventario_cierre > 0 or bancos_cierre > 0:
                fig, ax = plt.subplots(figsize=(6, 3))
                componentes = ['CxC', 'Inventario', 'Bancos']
                valores = [cx_c_cierre, inventario_cierre, bancos_cierre]
                colores = ['#17a2b8', '#28a745', '#ffc107']
                ax.bar(componentes, valores, color=colores)
                ax.set_title('Composición de Activos', fontsize=10)
                ax.set_ylabel('Monto (Bs.)')
                plt.tight_layout()
                st.pyplot(fig)
        
        st.metric("📈 Activos Operativos", formato_venezolano(activos_operativos))

    with col_c2:
        # KPI de Pasivos con popover
        with st.popover("📉 Ver detalle de Pasivos", use_container_width=True):
            st.markdown("##### Composición de Pasivos Operativos")
            st.markdown(f"""
            | Concepto | Monto | Archivo Origen |
            |----------|-------|----------------|
            | **Cuentas por pagar** | {formato_venezolano(cx_p_cierre)} | {'✅ Cargado' if archivo_cxp_reportado else '❌ No disponible'} |
            | **Transferencias en tránsito** | {formato_venezolano(transito_cierre)} | {'✅ Cargado' if archivo_tb else '❌ No disponible'} |
            | **TOTAL PASIVOS** | **{formato_venezolano(pasivos_operativos)}** |  |
            """)
            st.caption("✅ Valores tomados de los archivos de verificación.")
        
        st.metric("📉 Pasivos Operativos", formato_venezolano(pasivos_operativos))

    with col_c3:
        signo = "✅" if capital_neto >= 0 else "❌"
        # KPI de Capital con popover
        with st.popover("🏁 Ver detalle del Capital", use_container_width=True):
            st.markdown("##### Cálculo del Capital de Trabajo Neto")
            st.markdown(f"""
            | Concepto | Fórmula | Monto |
            |----------|---------|-------|
            | **Activos Operativos** | CxC + Inv. + Bancos | {formato_venezolano(activos_operativos)} |
            | **Pasivos Operativos** | CxP + Tránsito | {formato_venezolano(pasivos_operativos)} |
            | **CAPITAL DE TRABAJO NETO** | Activos - Pasivos | **{formato_venezolano(capital_neto)}** |
            """)
            
            # Mostrar relación Activos vs Pasivos
            if pasivos_operativos > 0:
                ratio = activos_operativos / pasivos_operativos
                st.metric("📊 Ratio Activos/Pasivos", f"{ratio:.2f}x")
            
            if capital_neto >= 0:
                st.success(f"✅ Capital de Trabajo Neto POSITIVO: {formato_venezolano(capital_neto)}")
            else:
                st.error(f"❌ Capital de Trabajo Neto NEGATIVO: {formato_venezolano(capital_neto)}")
        
        st.metric(f"{signo} Capital de Trabajo Neto", formato_venezolano(capital_neto))

    # ============================================================
    # 8. DETALLE DE LA VALIDACIÓN (DESPLEGABLE)
    # ============================================================
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
        st.error(f"❌ **Bancos**: Diferencia de {formato_venezolano(abs(diff_bancos))} Bs.")
    else:
        st.success(f"✅ **Bancos**: Coincide")
    
    if cobranzas > safe_number(st.session_state.saldos['cx_c']) + facturacion:
        st.warning(f"⚠️ **CxC**: Cobranzas ({formato_venezolano(cobranzas)}) superan saldo disponible")
    
    if pagos_proveedores > safe_number(st.session_state.saldos['cx_p']) + recepcion_total:
        st.warning(f"⚠️ **CxP**: Pagos ({formato_venezolano(pagos_proveedores)}) superan saldo disponible")
    
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
    
    inventario_final = saldos_reportados.get('Inventario', inventario_calculado)
    cx_c_final = saldos_reportados.get('Cuentas por cobrar', cx_c_calculado)
    cx_p_final = saldos_reportados.get('Cuentas por pagar', cx_p_calculado)
    transito_final = saldos_reportados.get('Transferencias en tránsito', transito_calculado)
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
        if st.button("📊 Ver gráfico evolución", use_container_width=True):
            historial = db.obtener_historial_saldos_completo(30)
            if not historial.empty and len(historial) > 1:
                try:
                    historial_ordenado = historial.sort_values('fecha')
                    
                    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
                    
                    # Gráfico 1: Evolución del Capital
                    axes[0].plot(historial_ordenado['fecha'], historial_ordenado['capital'], 
                                marker='o', linewidth=2, color='#667eea')
                    axes[0].set_title('Evolución del Capital de Trabajo Neto', fontsize=14, fontweight='bold')
                    axes[0].set_xlabel('Fecha')
                    axes[0].set_ylabel('Capital (Bs.)')
                    axes[0].grid(True, alpha=0.3)
                    axes[0].tick_params(axis='x', rotation=45)
                    
                    # Gráfico 2: Componentes del Capital
                    axes[1].plot(historial_ordenado['fecha'], historial_ordenado['inventario'], 
                                marker='s', linewidth=2, label='Inventario', color='#28a745')
                    axes[1].plot(historial_ordenado['fecha'], historial_ordenado['cx_c'], 
                                marker='^', linewidth=2, label='CxC', color='#17a2b8')
                    axes[1].plot(historial_ordenado['fecha'], historial_ordenado['bancos'], 
                                marker='d', linewidth=2, label='Bancos', color='#ffc107')
                    axes[1].set_title('Evolución de Componentes del Capital', fontsize=14, fontweight='bold')
                    axes[1].set_xlabel('Fecha')
                    axes[1].set_ylabel('Monto (Bs.)')
                    axes[1].legend()
                    axes[1].grid(True, alpha=0.3)
                    axes[1].tick_params(axis='x', rotation=45)
                    
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
