# app.py - Con campos para saldos iniciales manuales - VERSIÓN COMPLETA CON CIERRE DIARIO Y VISUALIZACIÓN DE ARCHIVOS
# 🔥 MODIFICADO: Identificación y visualización de OT Nuevas en Cuentas por Pagar
# 🤖 INTEGRACIÓN CON DEEPSEEK API
# 🎨 MEJORADO: Uploaders en parte superior, KPIs con tarjetas, botón Limpiar al pie
# 📋 REORGANIZADO: Estructura con pestañas (Resumen, Conciliación, Archivos)
# 🎯 REFACTORIZADO: KPIs con función mostrar_kpi_paso_paso para mejor legibilidad
# 📊 MEJORADO: Resúmenes con tarjetas ejecutivas en dos columnas
# 🔄 NUEVO: Uploader Recepción Trazabilidad para trazabilidad de inventarios
# 📦 CORREGIDO: Función mostrar_kpi_cantidades para KPIs de unidades sin formato Bs.
# 🔥 REFACTORIZADO: Detección de duplicados internos en Cobranzas (2026-07-09)
# 🆕 AGREGADO: Uploaders para Cobranzas Anterior y Tránsito Anterior (Trazabilidad histórica)
# 🔥 AGREGADO: Cruce avanzado de cobranzas interdiarias y conciliación de tránsito
# 🎯 AGREGADO: Motor automático de detección de errores interdiarios (Cobranzas)

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
archivo_recepciones_trazabilidad = None  # <--- NUEVO
archivo_notas_credito_cliente = None
archivo_notas_credito_proveedor = None
archivo_costo_facturacion = None
archivo_cxc_reportado = None
archivo_cxp_reportado = None
archivo_cxp_anterior = None
archivo_inventario_reportado = None
archivo_inventario_anterior = None
archivo_tb = None
# 🆕 NUEVAS VARIABLES PARA TRAZABILIDAD CONTRA EL DÍA ANTERIOR
archivo_cobranzas_anterior = None
archivo_transito_anterior = None
fecha_procesar = datetime.now()

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
# FUNCIÓN PARA MOSTRAR KPI PASO A PASO (NUEVA)
# ============================================================
def mostrar_kpi_paso_paso(col, titulo, valor, icono, variante="blue"):
    """
    Genera tarjetas KPI corporativas consistentes y visibles para el panel principal.
    Variantes disponibles: blue, green, red, orange, purple
    """
    mapa_colores = {
        "blue": {"bg": "#f0f7ff", "border": "#0056b3", "text": "#0056b3"},
        "green": {"bg": "#f0fff4", "border": "#1e7e34", "text": "#1e7e34"},
        "red": {"bg": "#fff5f5", "border": "#c82333", "text": "#c82333"},
        "orange": {"bg": "#fff9db", "border": "#d97706", "text": "#d97706"},
        "purple": {"bg": "#fcf0ff", "border": "#85144b", "text": "#85144b"}
    }
    
    cfg = mapa_colores.get(variante, mapa_colores["blue"])
    valor_formateado = formato_venezolano(valor)
    
    html = f"""
    <div style="
        background-color: {cfg['bg']};
        border-left: 5px solid {cfg['border']};
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        margin-bottom: 15px;
    ">
        <div style="font-size: 0.75rem; font-weight: 700; color: #4a5568; text-transform: uppercase; letter-spacing: 0.5px;">
            {icono} {titulo}
        </div>
        <div style="font-size: 1.5rem; font-weight: 800; color: {cfg['text']}; margin-top: 5px; font-family: 'Inter', sans-serif;">
            {valor_formateado} <span style="font-size: 0.8rem; font-weight: 500; color: #718096;">Bs.</span>
        </div>
    </div>
    """
    with col:
        st.markdown(html, unsafe_allow_html=True)

# ============================================================
# FUNCIÓN PARA MOSTRAR KPI DE CANTIDADES (UNIDADES) - CORREGIDO
# ============================================================
def mostrar_kpi_cantidades(col, titulo, valor, icono, variante="blue"):
    """
    Genera tarjetas KPI exclusivas para cantidades físicas (unidades),
    eliminando el formato monetario de Bolívares (Bs.).
    """
    mapa_colores = {
        "blue": {"bg": "#f0f7ff", "border": "#0056b3", "text": "#0056b3"},
        "green": {"bg": "#f0fff4", "border": "#1e7e34", "text": "#1e7e34"},
        "red": {"bg": "#fff5f5", "border": "#c82333", "text": "#c82333"},
        "orange": {"bg": "#fff9db", "border": "#d97706", "text": "#d97706"},
        "purple": {"bg": "#fcf0ff", "border": "#85144b", "text": "#85144b"}
    }
    
    cfg = mapa_colores.get(variante, mapa_colores["blue"])
    # Formatear con separador de miles tradicional, sin decimales flotantes erróneos si son enteros
    valor_formateado = f"{float(valor):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    if valor_formateado.endswith(",00"):
        valor_formateado = valor_formateado[:-3]  # Mostrar número entero limpio si no tiene decimales reales
        
    html = f"""
    <div style="
        background-color: {cfg['bg']};
        border-left: 5px solid {cfg['border']};
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        margin-bottom: 15px;
    ">
        <div style="font-size: 0.75rem; font-weight: 700; color: #4a5568; text-transform: uppercase; letter-spacing: 0.5px;">
            {icono} {titulo}
        </div>
        <div style="font-size: 1.5rem; font-weight: 800; color: {cfg['text']}; margin-top: 5px; font-family: 'Inter', sans-serif;">
            {valor_formateado} <span style="font-size: 0.8rem; font-weight: 500; color: #718096;">Und.</span>
        </div>
    </div>
    """
    with col:
        st.markdown(html, unsafe_allow_html=True)

# ============================================================
# FUNCIÓN PARA MOSTRAR ARCHIVO CON FORMATO (MODIFICADA - SIN AUTO-RENDERIZADO)
# ============================================================
def mostrar_archivo_con_formato(df, nombre_archivo, titulo):
    """
    Muestra un DataFrame con formato mejorado y estadísticas básicas
    - Ahora no se renderiza automáticamente, solo retorna el DataFrame y metadatos
    """
    if df is None or df.empty:
        return None, "⚠️ Archivo vacío", None
    
    # 🔥 CONVERTIR TODAS LAS FECHAS A STRING PARA EVITAR ERRORES DE PYARROW
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        elif df[col].dtype == 'object':
            try:
                df[col] = df[col].apply(lambda x: str(x) if not pd.isna(x) else x)
            except:
                pass
    
    # Estadísticas básicas
    stats = {
        'filas': len(df),
        'columnas': len(df.columns),
        'total': None
    }
    columnas_numericas = df.select_dtypes(include=['number']).columns
    if len(columnas_numericas) > 0:
        stats['total'] = df[columnas_numericas[0]].sum()
    
    return df, stats, columnas_numericas

# ============================================================
# FUNCIÓN PARA RENDERIZAR ARCHIVO EN PESTAÑA
# ============================================================
def renderizar_archivo_en_tab(df, nombre_archivo, titulo, stats, columnas_numericas):
    """Renderiza un archivo en la pestaña de archivos"""
    if df is None or df.empty:
        st.warning(f"⚠️ El archivo {nombre_archivo} está vacío")
        return
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📊 Filas", stats['filas'])
    with col2:
        st.metric("📋 Columnas", stats['columnas'])
    with col3:
        if stats['total'] is not None:
            st.metric("💰 Total", formato_venezolano(stats['total']))
    
    st.dataframe(
        df.style.background_gradient(subset=columnas_numericas, cmap='Blues', low=0.1, high=0.9),
        use_container_width=True,
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
       MEJORA DE VISIBILIDAD DE UPLOADERS EN ÁREA PRINCIPAL
       ============================================================ */
    .main .stFileUploader > label {
        color: #1a3a5c !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        opacity: 1 !important;
    }

    .main .stFileUploader > label .stMarkdown {
        color: #1a3a5c !important;
    }

    .main .stFileUploader > label span {
        color: #1a3a5c !important;
    }

    .main .stFileUploader .stMarkdown p {
        color: #4a6a8c !important;
    }
    
    /* ============================================================
       CORRECCIÓN DE CONTRASTE EN SIDEBAR (CHAT INPUT Y EXPANDERS)
       ============================================================ */
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] select,
    [data-testid="stSidebar"] [data-testid="stChatInput"] textarea,
    [data-testid="stSidebar"] [data-testid="stChatInput"] p {
        color: #0f172a !important;
        background-color: #ffffff !important;
        -webkit-text-fill-color: #0f172a !important;
    }
    
    [data-testid="stSidebar"] textarea::placeholder,
    [data-testid="stSidebar"] input::placeholder {
        color: #64748b !important;
        opacity: 0.8 !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: transparent !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 10px !important;
    }
    
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        background-color: #0a1628 !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
        justify-content: center !important;
        display: flex !important;
        padding: 10px !important;
    }
    
    [data-testid="stSidebar"] [data-testid="stExpander"] summary * {
        color: #e8c86a !important;
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
# INICIALIZACIÓN DE SESSION STATE - BANDERAS DE CONTROL
# ============================================================
if 'empresa_activa' not in st.session_state:
    st.session_state.empresa_activa = "Bodeguita Guayana"

# Banderas para control de visualización de tablas dinámicas
if 'mostrar_todos_productos' not in st.session_state:
    st.session_state.mostrar_todos_productos = False
if 'mostrar_solo_diff' not in st.session_state:
    st.session_state.mostrar_solo_diff = False
if 'mostrar_cambio_precio' not in st.session_state:
    st.session_state.mostrar_cambio_precio = False
if 'mostrar_cxp_actual' not in st.session_state:
    st.session_state.mostrar_cxp_actual = False
if 'mostrar_cxp_recepciones' not in st.session_state:
    st.session_state.mostrar_cxp_recepciones = False
if 'mostrar_cxp_cruzado' not in st.session_state:
    st.session_state.mostrar_cxp_cruzado = False
if 'mostrar_cxc_duplicadas' not in st.session_state:
    st.session_state.mostrar_cxc_duplicadas = False
if 'mostrar_cxc_nc' not in st.session_state:
    st.session_state.mostrar_cxc_nc = False
if 'mostrar_cxc_completo' not in st.session_state:
    st.session_state.mostrar_cxc_completo = False
if 'mostrar_transito_analisis' not in st.session_state:
    st.session_state.mostrar_transito_analisis = False
if 'mostrar_transito_tb' not in st.session_state:
    st.session_state.mostrar_transito_tb = False

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
                fecha_ant_encontrada = "Archivo Subido"
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
            st.dataframe(df_ot_nuevas_display[columnas_mostrar], use_container_width=True)
            
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
                st.dataframe(df_ot_elim[['documento', 'Monto', 'estado']], use_container_width=True)
                st.metric("💰 Total OT Eliminadas", formato_venezolano(total_ot_eliminadas))
            else:
                st.info("No hay OT que hayan sido eliminadas del CxP entre el día anterior y hoy.")

        # Tabla de NE Conciliados
        with st.expander("✅ NE Conciliados (Están en Recepciones y en CxP)", expanded=False):
            if ne_en_cxp:
                df_ne_conc = pd.DataFrame(ne_en_cxp)
                st.dataframe(df_ne_conc, use_container_width=True)
            else:
                st.info("No hay NE conciliados en este período.")

        # Tabla de NE Faltantes (Pago al Contado)
        with st.expander("⚠️ NE en Recepciones pero NO en CxP (Posible Pago al Contado)", expanded=False):
            if ne_faltantes:
                st.warning(f"🔍 Se encontraron {len(ne_faltantes)} NE que están en Recepciones pero NO en Cuentas por Pagar.")
                st.info("💡 Esto indica que la recepción fue pagada al contado y no generó deuda en CxP.")
                df_ne_falt = pd.DataFrame(ne_faltantes)
                st.dataframe(df_ne_falt, use_container_width=True)
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
                st.dataframe(df_ot[['documento', 'Monto', 'estado']], use_container_width=True)
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
            st.dataframe(df_docs, use_container_width=True)
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
        
    st.dataframe(df_formatted, use_container_width=True, hide_index=True)
    
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
        
    # 🔥 KPIS CON DISEÑO DE TARJETAS CORPORATIVAS
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
        <div class="dashboard-kpi-card {color_kpi}" style="border-radius: 16px; padding: 20px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.08);">
            <div class="dashboard-kpi-title" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.7;">🏁 Capital de Trabajo</div>
            <div class="dashboard-kpi-value" style="font-size: 1.8rem; font-weight: 800; margin-top: 4px;">{formato_venezolano(capital_trabajo)} Bs.</div>
            <div class="dashboard-kpi-desc" style="font-size: 0.7rem; opacity: 0.6; margin-top: 4px;">Cierre al {ultimo['fecha']}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_e2:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-blue" style="border-radius: 16px; padding: 20px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.08);">
            <div class="dashboard-kpi-title" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.7;">🏦 Saldo Bancos</div>
            <div class="dashboard-kpi-value" style="font-size: 1.8rem; font-weight: 800; margin-top: 4px;">{formato_venezolano(bancos)} Bs.</div>
            <div class="dashboard-kpi-desc" style="font-size: 0.7rem; opacity: 0.6; margin-top: 4px;">Cierre al {ultimo['fecha']}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_e3:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-purple" style="border-radius: 16px; padding: 20px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.08);">
            <div class="dashboard-kpi-title" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.7;">📦 Activos Operativos</div>
            <div class="dashboard-kpi-value" style="font-size: 1.8rem; font-weight: 800; margin-top: 4px;">{formato_venezolano(activos)} Bs.</div>
            <div class="dashboard-kpi-desc" style="font-size: 0.7rem; opacity: 0.6; margin-top: 4px;">Inventario + CxC</div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_e4:
        st.markdown(f"""
        <div class="dashboard-kpi-card kpi-variant-orange" style="border-radius: 16px; padding: 20px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.08);">
            <div class="dashboard-kpi-title" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.7;">📋 Pasivos Operativos</div>
            <div class="dashboard-kpi-value" style="font-size: 1.8rem; font-weight: 800; margin-top: 4px;">{formato_venezolano(pasivos)} Bs.</div>
            <div class="dashboard-kpi-desc" style="font-size: 0.7rem; opacity: 0.6; margin-top: 4px;">CxP + En Tránsito</div>
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
        st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
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
        st.dataframe(df_incons, use_container_width=True, hide_index=True)
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
if (st.session_state.get("fact_top") is not None and 
    st.session_state.get("cob_top") is not None and 
    st.session_state.get("egr_top") is not None and 
    st.session_state.get("estado_top") is not None):
    st.session_state.modo_vista = "🔍 Ficha de Validación"

# ============================================================
# 🔥 UPLOADERS EN LA PARTE SUPERIOR (NUEVA UBICACIÓN)
# ============================================================
with st.container():
    st.markdown("### 📂 Carga de Archivos del Día")
    st.caption("Sube los archivos obligatorios para comenzar la validación")
    
    # Crear 4 columnas para los archivos obligatorios
    col_u1, col_u2, col_u3, col_u4 = st.columns(4)
    
    with col_u1:
        archivo_facturacion = st.file_uploader("📊 Facturación", type=["xlsx", "xls"], key="fact_top")
    with col_u2:
        archivo_cobranzas = st.file_uploader("💰 Cobranzas", type=["xlsx", "xls"], key="cob_top")
    with col_u3:
        archivo_egresos = st.file_uploader("💳 Egresos iPago", type=["xlsx", "xls"], key="egr_top")
    with col_u4:
        archivo_estado_cuenta = st.file_uploader("🏦 Estado de Cuenta", type=["xlsx", "xls"], key="estado_top")
    
    # Segunda fila - Archivos opcionales
    st.markdown("#### 📎 Archivos Opcionales")
    col_u5, col_u6, col_u7, col_u8 = st.columns(4)
    
    with col_u5:
        archivo_recepciones = st.file_uploader("📦 Recepciones", type=["xlsx", "xls"], key="rec_top")
    with col_u6:
        archivo_recepciones_trazabilidad = st.file_uploader("📊 Recepción Trazabilidad", type=["xlsx", "xls"], key="rec_traz_top")  # <--- NUEVO
    with col_u7:
        archivo_notas_credito_cliente = st.file_uploader("📝 NC Clientes", type=["xlsx", "xls"], key="notas_cliente_top")
    with col_u8:
        archivo_notas_credito_proveedor = st.file_uploader("📝 NC Proveedores", type=["xlsx", "xls"], key="notas_proveedor_top")
    
    # Tercera fila - Archivos de verificación
    st.markdown("#### 🔍 Archivos de Verificación")
    col_u9, col_u10, col_u11, col_u12 = st.columns(4)
    
    with col_u9:
        archivo_cxc_reportado = st.file_uploader("📄 CxC Reportado", type=["xlsx", "xls"], key="cxc_rep_top")
    with col_u10:
        archivo_cxp_reportado = st.file_uploader("📄 CxP Reportado", type=["xlsx", "xls"], key="cxp_rep_top")
    with col_u11:
        archivo_inventario_reportado = st.file_uploader("📄 Inventario Reportado", type=["xlsx", "xls"], key="inv_rep_top")
    with col_u12:
        archivo_tb = st.file_uploader("🔄 TB.xlsx", type=["xlsx", "xls"], key="tb_top")
    
    # Cuarta fila - Archivos adicionales
    st.markdown("#### 📎 Archivos Adicionales")
    col_u13, col_u14, col_u15, col_u16 = st.columns(4)
    
    with col_u13:
        archivo_costo_facturacion = st.file_uploader("📈 Costo Facturación", type=["xlsx", "xls"], key="costo_fact_top")
    with col_u14:
        archivo_inventario_anterior = st.file_uploader("📦 Inventario Anterior", type=["xlsx", "xls"], key="inv_ant_top")
    with col_u15:
        archivo_cxp_anterior = st.file_uploader("📄 CxP Día Anterior", type=["xlsx", "xls"], key="cxp_ant_top")
    with col_u16:
        # 🆕 AGREGADOS: Nuevos Uploaders de trazabilidad histórica
        archivo_cobranzas_anterior = st.file_uploader("💰 Cobranzas Día Anterior", type=["xlsx", "xls"], key="cob_ant_top")

    # Añadimos una quinta fila o expandimos abajo para el de tránsito histórico
    st.markdown("#### 🔄 Trazabilidad de Saldos Históricos")
    col_u17, col_u18, col_u19, col_u20 = st.columns(4)
    with col_u17:
        archivo_transito_anterior = st.file_uploader("🔄 Tránsito Día Anterior", type=["xlsx", "xls"], key="transito_ant_top")
    
    st.markdown("---")
# ============================================================
# SIDEBAR CORPORATIVA (SEGÚN ROL) - SIN UPLOADERS
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
            
            fecha_procesar = st.date_input("📅 Fecha a procesar", datetime.now(), key="gerente_fecha_proc")
            fecha_str = fecha_procesar.strftime("%Y-%m-%d")
            tasa_guardada = db.obtener_tasa_bcv(fecha_str)
            tasa_bcv = st.number_input("💵 Tasa BCV", value=float(tasa_guardada or 1), step=0.0001, format="%.4f", key="gerente_tasa_bcv")
            db.guardar_tasa_bcv(fecha_str, tasa_bcv)
            
    # LÓGICA DE BARRA LATERAL PARA EL ANALISTA
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
                st.dataframe(df_mostrar, use_container_width=True)
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
archivo_recepciones_trazabilidad = obtener_archivo_historico_o_subido(archivo_recepciones_trazabilidad, "recepcion_trazabilidad")
archivo_notas_credito_cliente = obtener_archivo_historico_o_subido(archivo_notas_credito_cliente, "notas_cliente")
archivo_notas_credito_proveedor = obtener_archivo_historico_o_subido(archivo_notas_credito_proveedor, "notas_proveedor")
archivo_costo_facturacion = obtener_archivo_historico_o_subido(archivo_costo_facturacion, "costo_facturacion")
archivo_cxc_reportado = obtener_archivo_historico_o_subido(archivo_cxc_reportado, "cxc_reportado")
archivo_cxp_reportado = obtener_archivo_historico_o_subido(archivo_cxp_reportado, "cxp_reportado")
archivo_cxp_anterior = obtener_archivo_historico_o_subido(archivo_cxp_anterior, "cxp_anterior")
archivo_inventario_reportado = obtener_archivo_historico_o_subido(archivo_inventario_reportado, "inventario_reportado")
archivo_inventario_anterior = obtener_archivo_historico_o_subido(archivo_inventario_anterior, "inventario_anterior")
archivo_tb = obtener_archivo_historico_o_subido(archivo_tb, "tb")

# 🆕 RESOLUCIÓN DE LOS NUEVOS UPLOADERS HISTÓRICOS
archivo_cobranzas_anterior = obtener_archivo_historico_o_subido(archivo_cobranzas_anterior, "cobranzas_anterior")
archivo_transito_anterior = obtener_archivo_historico_o_subido(archivo_transito_anterior, "transito_anterior")

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
        
        st.dataframe(df_mostrar, use_container_width=True)
        
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
# PROCESAMIENTO PRINCIPAL (SI HAY ARCHIVOS OBLIGATORIOS)
# ============================================================
if archivo_facturacion and archivo_cobranzas and archivo_egresos and archivo_estado_cuenta:
    
    st.markdown(f"### 📈 Resultados de la Validación")
    st.markdown(f"**📅 Fecha procesada:** {fecha_procesar.strftime('%Y-%m-%d')}")
    cargas_status_alerts = []
    
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
    # LECTURA DE ARCHIVOS (SILENCIOSA - SIN RENDERIZADO AUTOMÁTICO)
    # ============================================================
    archivos_data = {}
    try:
        df_facturacion = pd.read_excel(archivo_facturacion)
        archivos_data['Facturación'] = {'df': df_facturacion, 'nombre': archivo_facturacion.name}
        
        df_cobranzas = pd.read_excel(archivo_cobranzas)
        archivos_data['Cobranzas'] = {'df': df_cobranzas, 'nombre': archivo_cobranzas.name}
        
        df_egresos = pd.read_excel(archivo_egresos)
        archivos_data['Egresos'] = {'df': df_egresos, 'nombre': archivo_egresos.name}
        
        df_estado_cuenta = pd.read_excel(archivo_estado_cuenta)
        archivos_data['Estado Cuenta'] = {'df': df_estado_cuenta, 'nombre': archivo_estado_cuenta.name}
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
            archivos_data['Recepciones'] = {'df': df_recepciones, 'nombre': archivo_recepciones.name}
            recepcion_total, compras_credito, _, _ = ProcesadorArchivos.procesar_recepciones(df_recepciones)
            cargas_status_alerts.append(('info', f'✅ Recepción de mercancía procesada: {formato_venezolano(recepcion_total)}'))
            
            # Análisis de recepciones rezagadas de días anteriores
            mostrar_recepciones_rezagadas(df_recepciones, fecha_procesar, st.session_state.empresa_activa)
        except Exception as e:
            st.warning(f"⚠️ Error procesando Recepción: {str(e)}")
            recepcion_total = 0.0
            compras_credito = 0.0
    else:
        cargas_status_alerts.append(('info', 'ℹ️ No se cargó archivo de Recepción. Se usará valor 0,00 para inventario.'))
    
    # ============================================================
    # RECEPCIÓN TRAZABILIDAD (NUEVO - Para trazabilidad de inventarios)
    # ============================================================
    df_recepciones_traz = None
    recepcion_traz_data = {}

    if archivo_recepciones_trazabilidad:
        try:
            df_recepciones_traz = pd.read_excel(archivo_recepciones_trazabilidad)
            archivos_data['Recepción Trazabilidad'] = {'df': df_recepciones_traz, 'nombre': archivo_recepciones_trazabilidad.name}
            
            # 🔥 MOSTRAR VISTA PREVIA DEL ARCHIVO
            # Vista previa deferred
            pass
            
            # Procesar el archivo de Recepción Trazabilidad para extraer productos y cantidades
            recepcion_traz_data = ProcesadorArchivos.procesar_recepcion_trazabilidad(df_recepciones_traz)
            
            # 🔥 MOSTRAR LO QUE SE EXTRAJO
            if recepcion_traz_data:
                cargas_status_alerts.append(('success', f'✅ Recepción Trazabilidad procesada: {len(recepcion_traz_data)} productos registrados'))
                pass
                # Mostrar los primeros 5 productos
                items = list(recepcion_traz_data.items())[:5]
                for codigo, info in items:
                    pass
            else:
                cargas_status_alerts.append(('warning', '⚠️ No se pudieron extraer datos del archivo de Recepción Trazabilidad'))
                cargas_status_alerts.append(('info', '💡 Verifica que el archivo tenga columnas: Código/Producto/Cantidad'))
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error procesando Recepción Trazabilidad: {str(e)}'))
            import traceback
            pass
            df_recepciones_traz = None
            recepcion_traz_data = {}
    else:
        cargas_status_alerts.append(('info', 'ℹ️ No se cargó archivo de Recepción Trazabilidad. La trazabilidad de inventarios por producto usará solo ventas.'))
        
    # ============================================================
    # COSTO DE FACTURACIÓN - DEBE EXTRAER DE COLUMNA E
    # ============================================================
    costo_facturacion = 0.0
    if archivo_costo_facturacion:
        try:
            df_costo = pd.read_excel(archivo_costo_facturacion)
            archivos_data['Costo Facturación'] = {'df': df_costo, 'nombre': archivo_costo_facturacion.name}
            costo_facturacion = ProcesadorArchivos.procesar_costo_facturacion(df_costo)
            cargas_status_alerts.append(('success', f'✅ Costo de facturación cargado: {formato_venezolano(costo_facturacion)}'))
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al leer costo de facturación: {str(e)}'))
    else:
        cargas_status_alerts.append(('info', 'ℹ️ No se cargó archivo de costo de facturación. El costo se mantendrá en 0.'))
    
    # ============================================================
    # ARCHIVOS DE VERIFICACIÓN
    # ============================================================
    saldos_reportados = {}
    archivos_cargados = {}
    
    if archivo_cxc_reportado:
        try:
            df_cxc_rep = pd.read_excel(archivo_cxc_reportado)
            archivos_data['CxC Reportado'] = {'df': df_cxc_rep, 'nombre': archivo_cxc_reportado.name}
            saldos_reportados['Cuentas por cobrar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxc_rep, 'cxc')
            archivos_cargados['CxC'] = df_cxc_rep
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al leer CxC reportado: {str(e)}'))
    
    if archivo_cxp_reportado:
        try:
            df_cxp_rep = pd.read_excel(archivo_cxp_reportado)
            archivos_data['CxP Reportado'] = {'df': df_cxp_rep, 'nombre': archivo_cxp_reportado.name}
            saldos_reportados['Cuentas por pagar'] = ProcesadorArchivos.extraer_saldo_reportado(df_cxp_rep, 'cxp')
            archivos_cargados['CxP'] = df_cxp_rep
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al leer CxP reportado: {str(e)}'))
    
    df_inv_ant = None
    if archivo_inventario_reportado:
        try:
            df_inv_rep = pd.read_excel(archivo_inventario_reportado)
            archivos_data['Inventario Reportado'] = {'df': df_inv_rep, 'nombre': archivo_inventario_reportado.name}
            saldos_reportados['Inventario'] = ProcesadorArchivos.extraer_saldo_reportado(df_inv_rep, 'inventario')
            archivos_cargados['Inventario'] = df_inv_rep
            
            # Guardar el archivo en RUTA_ARCHIVOS para histórico
            try:
                from config import RUTA_ARCHIVOS
                os.makedirs(RUTA_ARCHIVOS, exist_ok=True)
                file_dest = os.path.join(RUTA_ARCHIVOS, f"inventario_{st.session_state.empresa_activa}_{fecha_procesar.strftime('%Y-%m-%d')}.xlsx")
                df_inv_rep.to_excel(file_dest, index=False)
            except Exception as save_err:
                print(f"Error al guardar inventario en histórico: {save_err}")
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al leer Inventario reportado: {str(e)}'))
            
    # Intentar cargar inventario anterior (1. desde upload, 2. desde histórico)
    if 'archivo_inventario_anterior' in locals() and archivo_inventario_anterior:
        try:
            df_inv_ant = pd.read_excel(archivo_inventario_anterior)
            archivos_data['Inventario Anterior'] = {'df': df_inv_ant, 'nombre': archivo_inventario_anterior.name}
            cargas_status_alerts.append(('info', '📄 Carga exitosa del Inventario del Día Anterior (desde archivo subido).'))
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al leer Inventario del Día Anterior subido: {str(e)}'))
    else:
        # Intentar cargar desde el histórico guardado
        try:
            from config import RUTA_ARCHIVOS
            fecha_ant_str = (pd.Timestamp(fecha_procesar) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            file_ant_path = os.path.join(RUTA_ARCHIVOS, f"inventario_{st.session_state.empresa_activa}_{fecha_ant_str}.xlsx")
            if os.path.exists(file_ant_path):
                df_inv_ant = pd.read_excel(file_ant_path)
                archivos_data['Inventario Anterior'] = {'df': df_inv_ant, 'nombre': f"inventario_{fecha_ant_str}.xlsx"}
                cargas_status_alerts.append(('info', f'📄 Se cargó automáticamente el Inventario del Día Anterior ({fecha_ant_str}) desde el histórico.'))
        except Exception as cache_err:
            print(f"Error al buscar inventario anterior en histórico: {cache_err}")
    
    if archivo_tb:
        try:
            df_tb = pd.read_excel(archivo_tb)
            archivos_data['TB'] = {'df': df_tb, 'nombre': archivo_tb.name}
            transito_reportado = extraer_transito_reportado(df_tb, st.session_state.saldos['transito'])
            if transito_reportado is not None:
                saldos_reportados['Transferencias en tránsito'] = transito_reportado
                archivos_cargados['Tránsito'] = df_tb
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al leer TB.xlsx: {str(e)}'))
    
    # ============================================================
    # NOTAS DE CRÉDITO
    # ============================================================
    notas_credito_cliente = 0
    if archivo_notas_credito_cliente:
        try:
            df_notas_cliente = pd.read_excel(archivo_notas_credito_cliente)
            archivos_data['Notas Crédito Clientes'] = {'df': df_notas_cliente, 'nombre': archivo_notas_credito_cliente.name}
            notas_credito_cliente, _, _ = ProcesadorArchivos.procesar_notas_credito(df_notas_cliente)
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al procesar notas de crédito clientes: {str(e)}'))
    
    notas_credito_proveedor = 0
    if archivo_notas_credito_proveedor:
        try:
            df_notas_proveedor = pd.read_excel(archivo_notas_credito_proveedor)
            archivos_data['Notas Crédito Proveedores'] = {'df': df_notas_proveedor, 'nombre': archivo_notas_credito_proveedor.name}
            notas_credito_proveedor, _, _ = ProcesadorArchivos.procesar_notas_credito(df_notas_proveedor)
        except Exception as e:
            cargas_status_alerts.append(('warning', f'⚠️ Error al procesar notas de crédito proveedores: {str(e)}'))
    
    # ============================================================
    # PROCESAMIENTO DE MOVIMIENTOS
    # ============================================================
    try:
        facturacion, _, _, _ = ProcesadorArchivos.procesar_facturacion(df_facturacion)
        cobranzas, _, _ = ProcesadorArchivos.procesar_cobranzas(df_cobranzas)
        
        pagos_proveedores, pagos_gastos, total_egresos, df_proveedores = ProcesadorArchivos.procesar_egresos(df_egresos)
        
        df_proveedores_existe = not df_proveedores.empty
        
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
    # 🔥 CALCULAR DIFERENCIAS
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
    # ESTRUCTURA PRINCIPAL CON PESTAÑAS
    # ============================================================
    tab_resumen, tab_conciliacion, tab_auditoria_archivos = st.tabs([
        "📈 Resumen Ejecutivo", 
        "🔍 Conciliación y Auditoría Profunda", 
        "📄 Archivos Fuente y Auditoría del Bot"
    ])
    
    # ============================================================
    # PESTAÑA 1: RESUMEN EJECUTIVO
    # ============================================================
    with tab_resumen:
    
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
        with st.expander("📋 Movimientos del día procesados", expanded=False):
            st.dataframe(pd.DataFrame(mov_data), use_container_width=True, hide_index=True)
    
        # ============================================================
        # 📊 RESUMEN DE EGRESOS Y ESTADO DE CUENTA - TARJETAS EJECUTIVAS
        # ============================================================
        st.markdown("<br>", unsafe_allow_html=True)

        # Crear dos grandes columnas para separar los dos resúmenes del día
        col_res_izq, col_res_der = st.columns(2)

        with col_res_izq:
            st.markdown(f"""
            <div style="
                background: linear-gradient(180deg, #ffffff 0%, #f4f7fa 100%);
                border: 1px solid #e2e8f0;
                border-top: 4px solid #0056b3;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.03);
                height: 100%;
            ">
                <h5 style="color: #0a1628; margin-top: 0; font-weight: 700; font-size: 0.95rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                    📊 Resumen de Egresos iPago
                </h5>
                <div style="display: flex; justify-content: space-between; margin-top: 12px; font-size: 0.85rem;">
                    <span style="color: #4a5568;">🏪 Proveedores de Mercancía:</span>
                    <span style="font-weight: 700; color: #1a202c;">{formato_venezolano(pagos_proveedores)} Bs.</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 0.85rem;">
                    <span style="color: #4a5568;">📦 Otros Gastos:</span>
                    <span style="font-weight: 700; color: #1a202c;">{formato_venezolano(pagos_gastos)} Bs.</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 12px; padding-top: 8px; border-top: 1px dashed #cbd5e1; font-size: 0.9rem; font-weight: 700;">
                    <span style="color: #0056b3;">📌 Total Egresos iPago:</span>
                    <span style="color: #0056b3;">{formato_venezolano(total_egresos)} Bs.</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col_res_der:
            st.markdown(f"""
            <div style="
                background: linear-gradient(180deg, #ffffff 0%, #f4f7fa 100%);
                border: 1px solid #e2e8f0;
                border-top: 4px solid #1e7e34;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.03);
                height: 100%;
            ">
                <h5 style="color: #0a1628; margin-top: 0; font-weight: 700; font-size: 0.95rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
                    🏦 Resumen del Estado de Cuenta
                </h5>
                <div style="display: flex; justify-content: space-between; margin-top: 12px; font-size: 0.85rem;">
                    <span style="color: #4a5568;">💰 Saldo Inicial:</span>
                    <span style="font-weight: 700; color: {'#c82333' if saldo_inicial_bancos < 0 else '#1e7e34'};">
                        {formato_venezolano(saldo_inicial_bancos)} Bs.
                    </span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 0.85rem;">
                    <span style="color: #4a5568;">📈 Ingresos (Créditos):</span>
                    <span style="font-weight: 700; color: #1e7e34;">+{formato_venezolano(total_ingresos)} Bs.</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 0.85rem;">
                    <span style="color: #4a5568;">📉 Egresos (Débitos):</span>
                    <span style="font-weight: 700; color: #c82333;">-{formato_venezolano(total_egresos_banco)} Bs.</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-top: 12px; padding-top: 8px; border-top: 1px dashed #cbd5e1; font-size: 0.9rem; font-weight: 700;">
                    <span style="color: #1e7e34;">🏁 Saldo Final de Banco:</span>
                    <span style="color: #1e7e34;">{formato_venezolano(saldo_final)} Bs.</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
    
        st.markdown("---")
    
        # ============================================================
        # 🔥 SALDO DEL ESTADO DE CUENTA - MODIFICADO CON mostrar_kpi_paso_paso
        # ============================================================
        st.markdown("#### 📊 Saldo del Estado de Cuenta")
        st.caption("💡 Este es el saldo que viene del archivo de estado de cuenta")

        col_ec1, col_ec2, col_ec3, col_ec4 = st.columns(4)

        mostrar_kpi_paso_paso(col_ec1, "Saldo Inicial", saldo_inicial_bancos, "🏦", "blue")
        mostrar_kpi_paso_paso(col_ec2, "Ingresos", total_ingresos, "📈", "green")
        mostrar_kpi_paso_paso(col_ec3, "Egresos", total_egresos_banco, "📉", "red")
        mostrar_kpi_paso_paso(col_ec4, "Saldo Final", saldo_final, "🏁", "orange")

        st.markdown("---")
        # Mostrar información detallada del cálculo de Bancos
        st.markdown("#### 📊 Detalle del cálculo de Bancos")
        
        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
        
        mostrar_kpi_paso_paso(col_b1, "Saldo Inicial (E/C)", saldo_inicial_bancos, "🏦", "blue")
        mostrar_kpi_paso_paso(col_b2, "Ingresos (E/C)", total_ingresos, "📈", "green")
        mostrar_kpi_paso_paso(col_b3, "Egresos (E/C)", total_egresos_banco, "📉", "red")
        mostrar_kpi_paso_paso(col_b4, "Bancos Calculado", bancos_calculado, "🏁", "orange")
        
        # ============================================================
        # ✅ VERIFICACIÓN CON ESTADO DE CUENTA - MODIFICADO CON mostrar_kpi_paso_paso
        # ============================================================
        st.markdown("#### ✅ Verificación con Estado de Cuenta")

        col_v1, col_v2, col_v3 = st.columns(3)

        mostrar_kpi_paso_paso(col_v1, "Saldo Final (Estado de Cuenta)", saldo_final, "📋", "blue")
        mostrar_kpi_paso_paso(col_v2, "Bancos Calculado", bancos_calculado, "📊", "orange")

        # Alerta de color dinámica para la tarjeta de diferencia
        diferencia_bancos = bancos_calculado - saldo_final
        variante_diff = "green" if abs(diferencia_bancos) < 0.01 else "red"
        icono_diff = "✅" if abs(diferencia_bancos) < 0.01 else "⚠️"
        titulo_diff = "Diferencia (Coincide)" if abs(diferencia_bancos) < 0.01 else "Diferencia (Descuadrado)"

        mostrar_kpi_paso_paso(col_v3, titulo_diff, diferencia_bancos, icono_diff, variante_diff)
        
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
        
        # 💡 CORRECCIÓN: Calcular el capital anterior directo de los saldos base existentes
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
        
        st.dataframe(
            df_comparacion[columnas_mostrar].style.apply(colorear_filas, axis=1).hide(axis='index'),
            use_container_width=True
        )
        
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
        # AJUSTES MANUALES - ENVOLVER EN EXPANDER
        # ============================================================
        with st.expander("✏️ Configurar Ajustes Técnicos de Diferencias", expanded=False):
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

        # ============================================================
        # CIERRE DIARIO - RESUMEN
        # ============================================================
        st.markdown("---")
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
        st.dataframe(styled_df, use_container_width=True)

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
    # PESTAÑA 2: CONCILIACIÓN Y AUDITORÍA PROFUNDA
    # ============================================================
    with tab_conciliacion:
        st.markdown("### 🔍 Conciliación y Auditoría Profunda")
        
        # ============================================================
        # 🔍 ANÁLISIS DE OTRAS CUENTAS (CxC, CxP, TRANSITO)
        # ============================================================
        st.markdown("### 🔍 Análisis de Diferencias en Otras Cuentas")
        
        # --- CUENTAS POR COBRAR ---
        if abs(diff_cxc) > 0.01:
            with st.expander(f"👤 Cuentas por Cobrar (Diferencia: {formatear_diferencia(cx_c_calculado, cx_c_reportado)})", expanded=False):
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
            with st.expander(f"🤝 Cuentas por Pagar (Diferencia: {formatear_diferencia(cx_p_calculado, cx_p_reportado)})", expanded=False):
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
            with st.expander(f"✈️ Transferencias en Tránsito (Diferencia: {formatear_diferencia(transito_calculado, transito_reportado)})", expanded=False):
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
            with st.expander(f"🏦 Bancos (Diferencia: {formatear_diferencia(bancos_calculado, saldo_final)})", expanded=False):
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
        # 🔥 TRAZABILIDAD DE CUENTAS POR PAGAR (MEJORADO)
        # ============================================================
        st.markdown("### 🔍 Trazabilidad de Cuentas por Pagar")
        st.caption("Análisis detallado: CxP Anterior + Recepciones - Pagos Proveedores = CxP Calculado vs CxP Reportado")
        
        # Mostrar el cálculo paso a paso
        st.markdown("#### 📊 Paso a paso del cálculo")
        
        col_p1, col_p2, col_p3, col_p4, col_p5 = st.columns(5)
        
        mostrar_kpi_paso_paso(col_p1, "CxP Anterior", cx_p_anterior, "📋", "blue")
        mostrar_kpi_paso_paso(col_p2, "Recepciones", recepcion_total, "📦", "purple")
        mostrar_kpi_paso_paso(col_p3, "Pagos Proveedores", pagos_proveedores, "💰", "orange")
        mostrar_kpi_paso_paso(col_p4, "CxP Calculado", cx_p_calculado, "📊", "green")
        mostrar_kpi_paso_paso(col_p5, "CxP Reportado", cx_p_reportado if cx_p_reportado is not None else 0, "📄", "blue")
        
        # Verificar si hay diferencia
        diff_cxp_calc = safe_number(cx_p_calculado) - safe_number(cx_p_reportado) if cx_p_reportado is not None else 0
        
        if abs(diff_cxp_calc) < 0.01:
            st.success("✅ **¡CONCILIACIÓN PERFECTA!** El CxP Calculado coincide con el CxP Reportado.")
        else:
            st.error(f"⚠️ **DIFERENCIA DETECTADA:** {formato_venezolano(abs(diff_cxp_calc))} Bs. de diferencia entre Calculado y Reportado")
            
            # ============================================================
            # ANÁLISIS PROFUNDO DE DOCUMENTOS (NE / OT / FA) CON BOTONES
            # ============================================================
            st.markdown("---")
            st.markdown("#### 🔍 Análisis de Documentos (NE / OT / FA)")
            
            # Verificar si tenemos los archivos necesarios
            tiene_recepciones = 'df_recepciones' in locals() and df_recepciones is not None
            tiene_cxp_rep = 'df_cxp_rep' in locals() and df_cxp_rep is not None
            
            if not tiene_recepciones and not tiene_cxp_rep:
                st.warning("⚠️ **Faltan archivos para el análisis profundo.** Sube el archivo de Recepciones y/o CxP Reportado para continuar.")
            else:
                # Botones para controlar la visualización
                with st.expander("🔍 Análisis Detallado de Documentos (NE / OT / FA)", expanded=False):
                    if 'df_recepciones' in locals() and df_recepciones is not None:
                        mostrar_recepciones_rezagadas(df_recepciones, fecha_procesar, st.session_state.empresa_activa)
                    if 'df_proveedores_existe' in locals() and df_proveedores_existe:
                        with st.expander("📋 Detalle de PROVEEDORES DE MERCANCIA (filtrados)", expanded=False):
                            st.success(f"✅ Se encontraron {len(df_proveedores)} registros de PROVEEDORES DE MERCANCIA")
                            st.dataframe(df_proveedores, use_container_width=True)
                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("💰 Pagos a Proveedores de Mercancía", formato_venezolano(pagos_proveedores))
                            with col2:
                                st.metric("📦 Otros Gastos", formato_venezolano(pagos_gastos))
                    elif 'df_proveedores' in locals() and not df_proveedores.empty:
                        pass
                    else:
                        with st.expander("📋 Detalle de PROVEEDORES DE MERCANCIA (filtrados)", expanded=False):
                            st.warning("⚠️ No se encontraron registros de PROVEEDORES DE MERCANCIA en el archivo de egresos")
                            st.info("ℹ️ Asegúrate de que la columna 'Tipo de Pago' tenga 'PROVEEDORES DE MERCANCIA'")
                            if 'df_egresos' in locals() and len(df_egresos.columns) >= 4:
                                col_tipo_pago = df_egresos.columns[3]
                                tipos_unicos = df_egresos[col_tipo_pago].unique()
                                st.write("📌 Tipos de Pago encontrados en el archivo:")
                                st.write(tipos_unicos)
                    st.markdown("--- ")
                    st.markdown("#### 🔍 Análisis de Documentos (NE / OT / FA)")
                    col_btn_cxp1, col_btn_cxp2, col_btn_cxp3 = st.columns(3)
                    
                    with col_btn_cxp1:
                        if st.button("📋 Ver Documentos CxP Actual", width='stretch', key="btn_cxp_actual_tab2"):
                            st.session_state['mostrar_cxp_actual'] = not st.session_state.get('mostrar_cxp_actual', False)
                    
                    with col_btn_cxp2:
                        if st.button("📋 Ver Documentos Recepciones", width='stretch', key="btn_cxp_recepciones_tab2"):
                            st.session_state['mostrar_cxp_recepciones'] = not st.session_state.get('mostrar_cxp_recepciones', False)
                    
                    with col_btn_cxp3:
                        if st.button("📊 Ver Análisis Cruzado", width='stretch', key="btn_cxp_cruzado_tab2"):
                            st.session_state['mostrar_cxp_cruzado'] = not st.session_state.get('mostrar_cxp_cruzado', False)
                    
                    try:
                        import re
                        
                        # ============================================================
                        # 1. EXTRAER DOCUMENTOS DEL CxP ACTUAL
                        # ============================================================
                        cxp_actual_docs = {}
                        if tiene_cxp_rep:
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
                            
                            col_doc = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'documento', 'doc', 'factura', 'nro_doc', 'referencia')
                            col_monto = None
                            if len(df_cxp_clean.columns) > 2:
                                col_monto = df_cxp_clean.columns[2]
                            else:
                                col_monto = ProcesadorArchivos._buscar_columna(df_cxp_clean, 'saldo', 'saldo pendt', 'pendiente', 'monto')
                            
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
                                            if 'NE' in doc_upper:
                                                tipo = 'NE'
                                            elif 'OT' in doc_upper:
                                                tipo = 'OT'
                                            elif 'FA' in doc_upper or 'FACT' in doc_upper:
                                                tipo = 'FA'
                                            else:
                                                tipo = 'DESCONOCIDO'
                                            
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
                        
                        # ============================================================
                        # 2. EXTRAER DOCUMENTOS DE RECEPCIONES
                        # ============================================================
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
                        
                        # ============================================================
                        # MOSTRAR DOCUMENTOS SEGÚN BOTONES
                        # ============================================================
                        if st.session_state.get('mostrar_cxp_actual', False):
                            with st.expander("📋 Documentos en CxP Reportado (Día Actual)", expanded=True):
                                if cxp_actual_docs:
                                    df_cxp_docs = pd.DataFrame(list(cxp_actual_docs.values()))
                                    tipos_actual = {}
                                    for doc in cxp_actual_docs.values():
                                        tipos_actual[doc['tipo']] = tipos_actual.get(doc['tipo'], 0) + 1
                                    st.write("**Clasificación:** " + ", ".join([f"{k}: {v}" for k, v in tipos_actual.items()]))
                                    st.dataframe(df_cxp_docs, use_container_width=True)
                                    st.metric("📄 Total Documentos", len(cxp_actual_docs))
                                else:
                                    st.info("No hay documentos en CxP Reportado")
                        
                        if st.session_state.get('mostrar_cxp_recepciones', False):
                            with st.expander("📦 Documentos en Recepciones", expanded=True):
                                if recepciones_docs:
                                    df_rec_docs = pd.DataFrame(list(recepciones_docs.values()))
                                    tipos_rec = {}
                                    for doc in recepciones_docs.values():
                                        tipos_rec[doc['tipo']] = tipos_rec.get(doc['tipo'], 0) + 1
                                    st.write("**Clasificación:** " + ", ".join([f"{k}: {v}" for k, v in tipos_rec.items()]))
                                    st.dataframe(df_rec_docs, use_container_width=True)
                                    st.metric("📦 Total Recepciones", len(recepciones_docs))
                                else:
                                    st.info("No hay documentos en Recepciones")
                        
                        # ============================================================
                        # ANÁLISIS CRUZADO DE DOCUMENTOS
                        # ============================================================
                        if st.session_state.get('mostrar_cxp_cruzado', False):
                            with st.expander("📊 Análisis Cruzado de Documentos", expanded=True):
                                # Clasificar documentos
                                ot_nuevas = []
                                for doc_norm, info in cxp_actual_docs.items():
                                    if info['tipo'] == 'OT':
                                        ot_nuevas.append({
                                            'documento': info['original'],
                                            'monto': info['monto'],
                                            'proveedor': info.get('proveedor', 'No identificado'),
                                            'tipo': 'OT NUEVA (Carga Manual)'
                                        })
                                
                                ne_pago_contado = []
                                for doc_norm, info in recepciones_docs.items():
                                    if info['tipo'] == 'NE' and doc_norm not in cxp_actual_docs:
                                        ne_pago_contado.append({
                                            'documento': info['original'],
                                            'monto': info['monto'],
                                            'tipo': 'NE (Pago al Contado)'
                                        })
                                
                                fa_en_cxp_no_recepcion = []
                                for doc_norm, info in cxp_actual_docs.items():
                                    if info['tipo'] == 'FA' and doc_norm not in recepciones_docs:
                                        fa_en_cxp_no_recepcion.append({
                                            'documento': info['original'],
                                            'monto': info['monto'],
                                            'proveedor': info.get('proveedor', 'No identificado'),
                                            'tipo': 'FA en CxP sin Recepción'
                                        })
                                
                                fa_en_recepcion_no_cxp = []
                                for doc_norm, info in recepciones_docs.items():
                                    if info['tipo'] == 'FA' and doc_norm not in cxp_actual_docs:
                                        fa_en_recepcion_no_cxp.append({
                                            'documento': info['original'],
                                            'monto': info['monto'],
                                            'tipo': 'FA en Recepción sin CxP'
                                        })
                                
                                total_ot_nuevas = sum([x['monto'] for x in ot_nuevas])
                                total_ne_pago_contado = sum([x['monto'] for x in ne_pago_contado])
                                total_fa_en_cxp_no_recepcion = sum([x['monto'] for x in fa_en_cxp_no_recepcion])
                                total_fa_en_recepcion_no_cxp = sum([x['monto'] for x in fa_en_recepcion_no_cxp])
                                
                                # Mostrar resultados
                                col_a1, col_a2 = st.columns(2)
                                
                                with col_a1:
                                    st.metric("🆕 OT Nuevas", len(ot_nuevas), delta=f"{formato_venezolano(total_ot_nuevas)}")
                                    if ot_nuevas:
                                        st.warning(f"⚠️ {len(ot_nuevas)} OT nuevas detectadas")
                                        for item in ot_nuevas[:5]:
                                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])}")
                                        if len(ot_nuevas) > 5:
                                            st.write(f"... y {len(ot_nuevas) - 5} más")
                                    else:
                                        st.success("✅ No hay OT nuevas")
                                    
                                    st.metric("📄 FA en CxP sin Recepción", len(fa_en_cxp_no_recepcion), delta=f"{formato_venezolano(total_fa_en_cxp_no_recepcion)}")
                                    if fa_en_cxp_no_recepcion:
                                        st.error(f"❌ {len(fa_en_cxp_no_recepcion)} FA en CxP sin Recepción")
                                        for item in fa_en_cxp_no_recepcion[:5]:
                                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])} ({item['proveedor']})")
                                        if len(fa_en_cxp_no_recepcion) > 5:
                                            st.write(f"... y {len(fa_en_cxp_no_recepcion) - 5} más")
                                    else:
                                        st.success("✅ No hay FA sin Recepción")
                                
                                with col_a2:
                                    st.metric("⚠️ NE Pago al Contado", len(ne_pago_contado), delta=f"{formato_venezolano(total_ne_pago_contado)}")
                                    if ne_pago_contado:
                                        st.info(f"ℹ️ {len(ne_pago_contado)} NE pagadas al contado")
                                        for item in ne_pago_contado[:5]:
                                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])}")
                                        if len(ne_pago_contado) > 5:
                                            st.write(f"... y {len(ne_pago_contado) - 5} más")
                                    else:
                                        st.success("✅ No hay NE pagadas al contado")
                                    
                                    st.metric("📄 FA en Recepción sin CxP", len(fa_en_recepcion_no_cxp), delta=f"{formato_venezolano(total_fa_en_recepcion_no_cxp)}")
                                    if fa_en_recepcion_no_cxp:
                                        st.warning(f"⚠️ {len(fa_en_recepcion_no_cxp)} FA en Recepción sin CxP")
                                        for item in fa_en_recepcion_no_cxp[:5]:
                                            st.write(f"- 📄 {item['documento']}: {formato_venezolano(item['monto'])}")
                                        if len(fa_en_recepcion_no_cxp) > 5:
                                            st.write(f"... y {len(fa_en_recepcion_no_cxp) - 5} más")
                                    else:
                                        st.success("✅ No hay FA sin CxP")
                                
                                # Diagnóstico
                                st.markdown("---")
                                st.markdown("#### 🎯 Diagnóstico de la Diferencia")
                                
                                diferencia_explicada = total_ot_nuevas + total_ne_pago_contado + total_fa_en_recepcion_no_cxp
                                diferencia_no_explicada = abs(diff_cxp_calc) - diferencia_explicada
                                
                                st.markdown(f"""
                                | Concepto | Monto | Explicación |
                                |----------|-------|-------------|
                                | **Diferencia Total** | {formato_venezolano(abs(diff_cxp_calc))} | Diferencia en CxP Calculado vs Reportado |
                                | 🆕 **OT Nuevas** | {formato_venezolano(total_ot_nuevas)} | Cargas manuales nuevas |
                                | ⚠️ **NE Pago al Contado** | {formato_venezolano(total_ne_pago_contado)} | NE en Recepciones pero NO en CxP |
                                | 📄 **FA en Recepción sin CxP** | {formato_venezolano(total_fa_en_recepcion_no_cxp)} | Facturas en Recepción pero NO en CxP |
                                | **Diferencia Explicada** | {formato_venezolano(diferencia_explicada)} | Suma de diferencias identificadas |
                                | **Diferencia NO Explicada** | {formato_venezolano(diferencia_no_explicada)} | ⚠️ Requiere revisión manual |
                                """)
                                
                                if abs(diferencia_no_explicada) < 0.01:
                                    st.success("✅ **¡DIFERENCIA EXPLICADA COMPLETAMENTE!**")
                                else:
                                    st.error(f"❌ **DIFERENCIA NO EXPLICADA:** {formato_venezolano(diferencia_no_explicada)} Bs.")
                        
                        # Botón para cerrar todas las vistas de CxP
                        col_btn_close1, col_btn_close2, col_btn_close3 = st.columns(3)
                        with col_btn_close2:
                            if st.button("🔒 Cerrar todas las vistas de CxP", width='stretch'):
                                st.session_state['mostrar_cxp_actual'] = False
                                st.session_state['mostrar_cxp_recepciones'] = False
                                st.session_state['mostrar_cxp_cruzado'] = False
                                st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error en el análisis de documentos: {str(e)}")
                        import traceback
                        st.code(traceback.format_exc())
        
        st.markdown("---")
        
        # ============================================================
        # 🔥 TRAZABILIDAD DE TRANSFERENCIAS EN TRÁNSITO (MEJORADO CON AUDITORÍA DE DESADUANAJE)
        # ============================================================
        st.markdown("### 🔍 Trazabilidad de Transferencias en Tránsito")
        st.caption("Análisis detallado: Tránsito Anterior + Ingresos - Cobranzas = Tránsito Calculado vs Tránsito Reportado")
        
        # Mostrar el cálculo paso a paso
        st.markdown("#### 📊 Paso a paso del cálculo")
        
        col_t1, col_t2, col_t3, col_t4, col_t5 = st.columns(5)
        
        mostrar_kpi_paso_paso(col_t1, "Tránsito Anterior", transito_anterior, "🔄", "blue")
        mostrar_kpi_paso_paso(col_t2, "Total Ingresos", total_ingresos, "📈", "green")
        mostrar_kpi_paso_paso(col_t3, "Cobranzas", cobranzas, "💰", "orange")
        mostrar_kpi_paso_paso(col_t4, "Tránsito Calculado", transito_calculado, "📊", "purple")
        mostrar_kpi_paso_paso(col_t5, "Tránsito Reportado", transito_reportado if transito_reportado is not None else 0, "📄", "blue")
        
        # Verificar si hay diferencia
        diff_transito_calc = safe_number(transito_calculado) - safe_number(transito_reportado) if transito_reportado is not None else 0
        
        if abs(diff_transito_calc) < 0.01:
            st.success("✅ **¡CONCILIACIÓN PERFECTA!** El Tránsito Calculado coincide con el Tránsito Reportado.")
        else:
            st.error(f"⚠️ **DIFERENCIA DETECTADA:** {formato_venezolano(abs(diff_transito_calc))} Bs. de diferencia")
            
            # Botones para análisis
            st.markdown("---")
            with st.expander("🔍 Auditoría de Desaduanaje de Tránsito Histórico", expanded=False):
                st.markdown("--- ")
                col_btn_t1, col_btn_t2 = st.columns(2)
                
                with col_btn_t1:
                    if st.button("📊 Ver Análisis de Transferencias", width='stretch', key="btn_transito_analisis_tab2"):
                        st.session_state['mostrar_transito_analisis'] = not st.session_state.get('mostrar_transito_analisis', False)
                
                with col_btn_t2:
                    if st.button("📋 Ver Detalle de TB", width='stretch', key="btn_transito_tb_tab2"):
                        st.session_state['mostrar_transito_tb'] = not st.session_state.get('mostrar_transito_tb', False)
                
                if st.session_state.get('mostrar_transito_analisis', False) or st.session_state.get('mostrar_transito_tb', False):
                    try:
                        import re
                        
                        tiene_tb = 'df_tb' in locals() and df_tb is not None
                        tiene_cobranzas = 'df_cobranzas' in locals() and df_cobranzas is not None
                        
                        # 🔥 EXTRAER TRÁNSITO DEL DÍA ANTERIOR DESDE ARCHIVO SUBIDO
                        transito_anterior_docs = {}
                        if archivo_transito_anterior is not None:
                            try:
                                df_tran_ant = pd.read_excel(archivo_transito_anterior)
                                df_tran_ant_clean = ProcesadorArchivos._limpiar_columnas(df_tran_ant)
                                idx_tran_ant = ProcesadorArchivos._encontrar_fila_datos(df_tran_ant_clean, ['cuenta', 'referencia', 'monto'])
                                if idx_tran_ant >= 0:
                                    df_datos_tran = df_tran_ant_clean.iloc[idx_tran_ant:].reset_index(drop=True)
                                    df_datos_tran.columns = [str(c).strip() for c in df_datos_tran.iloc[0]]
                                    df_tran_ant_clean = df_datos_tran.iloc[1:].reset_index(drop=True)
                                    
                                    col_ref_t = ProcesadorArchivos._buscar_columna(df_tran_ant_clean, 'referencia', 'nro', 'documento')
                                    col_monto_t = ProcesadorArchivos._buscar_columna(df_tran_ant_clean, 'monto', 'total')
                                    
                                    if col_ref_t and col_monto_t:
                                        for idx, row in df_tran_ant_clean.iterrows():
                                            ref = str(row[col_ref_t]).strip()
                                            monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_t])
                                            if ref and monto:
                                                ref_norm = re.sub(r'[^0-9]', '', ref)
                                                transito_anterior_docs[ref_norm] = float(monto)
                            except Exception as e:
                                st.error(f"⚠️ Error al procesar Tránsito del Día Anterior: {e}")
                        
                        # 🔥 EXTRAER INGRESOS DEL ESTADO DE CUENTA DE HOY (REFERENCIAS)
                        ingresos_actual_docs = {}
                        if 'df_estado_cuenta' in locals() and df_estado_cuenta is not None:
                            try:
                                df_ec_clean = ProcesadorArchivos._limpiar_columnas(df_estado_cuenta)
                                idx_ec = ProcesadorArchivos._encontrar_fila_datos(df_ec_clean, ['fecha', 'referencia', 'descripción', 'crédito', 'débito'])
                                if idx_ec >= 0:
                                    df_datos_ec = df_ec_clean.iloc[idx_ec:].reset_index(drop=True)
                                    df_datos_ec.columns = [str(c).strip() for c in df_datos_ec.iloc[0]]
                                    df_ec_clean = df_datos_ec.iloc[1:].reset_index(drop=True)
                                    
                                    col_ref_ec = ProcesadorArchivos._buscar_columna(df_ec_clean, 'referencia', 'nro', 'documento')
                                    col_credito = ProcesadorArchivos._buscar_columna(df_ec_clean, 'crédito', 'credito', 'ingreso')
                                    
                                    if col_ref_ec and col_credito:
                                        for idx, row in df_ec_clean.iterrows():
                                            ref = str(row[col_ref_ec]).strip()
                                            credito = ProcesadorArchivos._convertir_numero_europeo(row[col_credito])
                                            if ref and credito and credito > 0:
                                                ref_norm = re.sub(r'[^0-9]', '', ref)
                                                ingresos_actual_docs[ref_norm] = float(credito)
                            except Exception as e:
                                pass
                        
                        # 🔥 CRUZAR TRÁNSITO ANTERIOR CONTRA INGRESOS DEL BANCO DE HOY
                        transit_efectivo = []
                        transit_pendiente = []
                        
                        for ref_norm, monto_t in transito_anterior_docs.items():
                            if ref_norm in ingresos_actual_docs:
                                transit_efectivo.append({
                                    'Referencia': ref_norm, 
                                    'Monto Tránsito Ayer': monto_t, 
                                    'Monto Ingreso Hoy': ingresos_actual_docs[ref_norm],
                                    'Estatus': '✅ Efectiva en Banco Hoy'
                                })
                            else:
                                transit_pendiente.append({
                                    'Referencia': ref_norm, 
                                    'Monto': monto_t, 
                                    'Estatus': '⏳ Sigue en Tránsito (No ingresó hoy)'
                                })
                        
                        # Mostrar resultados del desaduanaje
                        if transit_efectivo:
                            st.success(f"📈 {len(transit_efectivo)} Transferencias en tránsito de ayer se hicieron efectivas hoy en el banco:")
                            df_efectivo = pd.DataFrame(transit_efectivo)
                            st.dataframe(df_efectivo, use_container_width=True)
                        
                        if transit_pendiente:
                            st.warning(f"⏳ {len(transit_pendiente)} Transferencias siguen flotando en tránsito:")
                            df_pendiente = pd.DataFrame(transit_pendiente)
                            st.dataframe(df_pendiente, use_container_width=True)
                        
                        if not transito_anterior_docs:
                            st.info("ℹ️ No hay registros de Tránsito del día anterior para evaluar desaduanaje.")
                        
                        # 🔥 EXTRAER TB ACTUAL (ya existente)
                        tb_docs = {}
                        if tiene_tb and st.session_state.get('mostrar_transito_tb', False):
                            df_tb_clean = ProcesadorArchivos._limpiar_columnas(df_tb)
                            
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
                            
                            col_ref = ProcesadorArchivos._buscar_columna(df_tb_clean, 'referencia', 'nro', 'deposito', 'documento')
                            col_monto_tb = ProcesadorArchivos._buscar_columna(df_tb_clean, 'monto', 'total', 'importe', 'saldo')
                            
                            if col_ref and col_monto_tb:
                                for idx, row in df_tb_clean.iterrows():
                                    ref = str(row[col_ref]).strip()
                                    monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_tb])
                                    if ref and ref != 'nan' and ref != 'None' and monto:
                                        ref_norm = re.sub(r'[^0-9]', '', ref)
                                        if ref_norm:
                                            tb_docs[ref_norm] = {
                                                'referencia': ref,
                                                'monto': float(monto)
                                            }
                            
                            with st.expander("📄 Transferencias en Tránsito (TB Actual)", expanded=True):
                                if tb_docs:
                                    df_tb_docs = pd.DataFrame(list(tb_docs.values()))
                                    st.dataframe(df_tb_docs, use_container_width=True)
                                    st.metric("📄 Total TB Actual", len(tb_docs))
                                else:
                                    st.info("No hay transferencias en TB Actual")
                        
                        # Botón para cerrar vistas de Tránsito
                        if st.button("🔒 Cerrar todas las vistas de Tránsito", width='stretch'):
                            st.session_state['mostrar_transito_analisis'] = False
                            st.session_state['mostrar_transito_tb'] = False
                            st.rerun()
                            
                    except Exception as e:
                        st.error(f"❌ Error en el análisis de transferencias: {str(e)}")
                        import traceback
                        st.code(traceback.format_exc())
        
        st.markdown("---")
        
        # ============================================================
        # 🔥 TRAZABILIDAD DE CUENTAS POR COBRAR (CON KPIs + MOTOR DE AUDITORÍA)
        # ============================================================
        st.markdown("### 🔍 Trazabilidad de Cuentas por Cobrar")
        st.caption("Análisis detallado: CxC Anterior + Facturación - Cobranzas - NC Clientes = CxC Calculado vs CxC Reportado")

        # Mostrar el cálculo paso a paso
        st.markdown("#### 📊 Paso a paso del cálculo")
        
        col_c1, col_c2, col_c3, col_c4, col_c5, col_c6 = st.columns(6)
        
        mostrar_kpi_paso_paso(col_c1, "CxC Anterior", cx_c_anterior, "💰", "blue")
        mostrar_kpi_paso_paso(col_c2, "Facturación", facturacion, "📊", "green")
        mostrar_kpi_paso_paso(col_c3, "Cobranzas", cobranzas, "💰", "orange")
        mostrar_kpi_paso_paso(col_c4, "NC Clientes", notas_credito_cliente, "📝", "red")
        mostrar_kpi_paso_paso(col_c5, "CxC Calculado", cx_c_calculado, "📊", "purple")
        mostrar_kpi_paso_paso(col_c6, "CxC Reportado", cx_c_reportado if cx_c_reportado is not None else 0, "📄", "blue")
        
        # Verificar si hay diferencia
        diff_cxc_calc = safe_number(cx_c_calculado) - safe_number(cx_c_reportado) if cx_c_reportado is not None else 0
        
        if abs(diff_cxc_calc) < 0.01:
            st.success("✅ **¡CONCILIACIÓN PERFECTA!** El CxC Calculado coincide con el CxC Reportado.")
        else:
            st.error(f"⚠️ **DIFERENCIA DETECTADA:** {formato_venezolano(abs(diff_cxc_calc))} Bs. de diferencia")

        # ============================================================
        # 🎯 MOTOR AUTOMÁTICO DE DETECCIÓN DE ERRORES INTERDIARIOS (COBRANZAS)
        # ============================================================
        with st.expander("🚨 Auditoría Avanzada de Cobranzas (Duplicados y Errores Interdiarios)", expanded=True):
            tiene_cob_actual = 'df_cobranzas' in locals() and df_cobranzas is not None
            tiene_cob_anterior = archivo_cobranzas_anterior is not None

            if tiene_cob_actual:
                # 1. Extracción exhaustiva del archivo de HOY
                df_hoy_clean = ProcesadorArchivos._limpiar_columnas(df_cobranzas)
                idx_hoy = ProcesadorArchivos._encontrar_fila_datos(df_hoy_clean, ['banco', 'deposito', 'monto'])
                if idx_hoy >= 0:
                    df_hoy_clean = df_hoy_clean.iloc[idx_hoy:].reset_index(drop=True)
                    df_hoy_clean.columns = [str(c).strip().lower() for c in df_hoy_clean.iloc[0]]
                    df_hoy_clean = df_hoy_clean.iloc[1:].reset_index(drop=True)
                
                col_ref_hoy = ProcesadorArchivos._buscar_columna(df_hoy_clean, 'deposito', 'nro', 'referencia')
                col_monto_hoy = ProcesadorArchivos._buscar_columna(df_hoy_clean, 'monto', 'total', 'monto cobranza')
                col_cliente_hoy = ProcesadorArchivos._buscar_columna(df_hoy_clean, 'cliente', 'nombre')

                # Diccionario detallado de HOY para cruzamiento rápido
                cobranzas_hoy_map = []
                for idx, row in df_hoy_clean.iterrows():
                    try:
                        ref = str(row[col_ref_hoy]).strip() if col_ref_hoy in df_hoy_clean.columns else ""
                        monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_hoy]) if col_monto_hoy in df_hoy_clean.columns else 0.0
                        cliente = str(row[col_cliente_hoy]).strip() if col_cliente_hoy in df_hoy_clean.columns else "No identificado"
                        
                        if monto and monto > 0:
                            ref_norm = re.sub(r'[^0-9]', '', ref) if ref else f"sin_ref_{idx}"
                            cobranzas_hoy_map.append({
                                'ref_norm': ref_norm,
                                'referencia_orig': ref,
                                'monto': float(monto),
                                'cliente': cliente,
                                'fila': idx + 1
                            })
                    except:
                        pass

                # 2. Extracción exhaustiva del archivo de AYER
                cobranzas_ayer_map = []
                if tiene_cob_anterior:
                    try:
                        df_ayer_raw = pd.read_excel(archivo_cobranzas_anterior)
                        df_ayer_clean = ProcesadorArchivos._limpiar_columnas(df_ayer_raw)
                        idx_ayer = ProcesadorArchivos._encontrar_fila_datos(df_ayer_clean, ['banco', 'deposito', 'monto'])
                        if idx_ayer >= 0:
                            df_ayer_clean = df_ayer_clean.iloc[idx_ayer:].reset_index(drop=True)
                            df_ayer_clean.columns = [str(c).strip().lower() for c in df_ayer_clean.iloc[0]]
                            df_ayer_clean = df_ayer_clean.iloc[1:].reset_index(drop=True)
                        
                        col_ref_ayer = ProcesadorArchivos._buscar_columna(df_ayer_clean, 'deposito', 'nro', 'referencia')
                        col_monto_ayer = ProcesadorArchivos._buscar_columna(df_ayer_clean, 'monto', 'total', 'monto cobranza')
                        col_cliente_ayer = ProcesadorArchivos._buscar_columna(df_ayer_clean, 'cliente', 'nombre')

                        for idx, row in df_ayer_clean.iterrows():
                            try:
                                ref = str(row[col_ref_ayer]).strip() if col_ref_ayer in df_ayer_clean.columns else ""
                                monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_ayer]) if col_monto_ayer in df_ayer_clean.columns else 0.0
                                cliente = str(row[col_cliente_ayer]).strip() if col_cliente_ayer in df_ayer_clean.columns else "No identificado"
                                
                                if monto and monto > 0:
                                    ref_norm = re.sub(r'[^0-9]', '', ref) if ref else f"sin_ref_ant_{idx}"
                                    cobranzas_ayer_map.append({
                                        'ref_norm': ref_norm,
                                        'referencia_orig': ref,
                                        'monto': float(monto),
                                        'cliente': cliente,
                                        'fila': idx + 1
                                    })
                            except:
                                pass
                    except Exception as e:
                        st.error(f"⚠️ Error procesando el archivo histórico de cobranzas: {e}")

                # ============================================================
                # 🔥 EJECUCIÓN DE AUDITORÍA CIEGA (HALLAR ALERTA DE 3040 Y OTROS)
                # ============================================================
                alertas_halladas = []
                
                # Algoritmo de cruce ciego
                for item_hoy in cobranzas_hoy_map:
                    monto_h = item_hoy['monto']
                    ref_h = item_hoy['ref_norm']
                    
                    # A. Buscar duplicados de referencias contra AYER
                    for item_ayer in cobranzas_ayer_map:
                        if ref_h and ref_h == item_ayer['ref_norm'] and not ref_h.startswith("sin_ref"):
                            alertas_halladas.append({
                                'Tipo Falla': '🔴 DUPLICADO INTERDIARIO (Misma Ref.)',
                                'Monto': monto_h,
                                'Detalle': f"Ref {item_hoy['referencia_orig']} procesada ayer (Fila {item_ayer['fila']}) y hoy (Fila {item_hoy['fila']})",
                                'Cliente': item_hoy['cliente']
                            })
                    
                    # B. Buscar patrones sospechosos por MONTO EXACTO (Como los 3040 Bs.)
                    for item_ayer in cobranzas_ayer_map:
                        if abs(monto_h - item_ayer['monto']) < 0.01 and ref_h != item_ayer['ref_norm']:
                            alertas_halladas.append({
                                'Tipo Falla': '💥 COINCIDENCIA CRÍTICA DE MONTO (Posible Doble Registro)',
                                'Monto': monto_h,
                                'Detalle': f"Monto idéntico hallado ayer (Ref: {item_ayer['referencia_orig']}) y hoy (Ref: {item_hoy['referencia_orig']})",
                                'Cliente': item_hoy['cliente']
                            })

                # Renderizado de resultados de Auditoría Ciega
                if alertas_halladas:
                    df_alertas = pd.DataFrame(alertas_halladas).drop_duplicates(subset=['Detalle'])
                    st.error(f"🚨 El motor de auditoría automatizada detectó {len(df_alertas)} irregularidades críticas sin asistencia:")
                    
                    df_display_alertas = df_alertas.copy()
                    df_display_alertas['Monto (Bs.)'] = df_display_alertas['Monto'].apply(formato_venezolano)
                    
                    st.dataframe(
                        df_display_alertas[['Tipo Falla', 'Monto (Bs.)', 'Detalle', 'Cliente']],
                        use_container_width=True
                    )
                    
                    # Foco específico en el descuadre de 3040
                    target_alert = df_alertas[df_alertas['Monto'] == 3040.0]
                    if not target_alert.empty:
                        st.toast("🎯 ¡Monto de 3040 localizado con éxito por trazabilidad!")
                        st.warning(f"🏁 **Hallazgo crítico:** El sistema interceptó la transacción de **3.040,00 Bs.** Detalles del cruce: {target_alert.iloc[0]['Detalle']}.")
                else:
                    st.success("✅ Auditoría ciega completada: Los montos y referencias mapeados entre ambos días lucen consistentes.")
            else:
                st.info("ℹ️ Sube los archivos de cobranza de ambos días para ejecutar el análisis inteligente en background.")

        st.markdown("---")
        
        # ============================================================
        # 📦 TRAZABILIDAD DE INVENTARIO - PRODUCTO POR PRODUCTO
        # ============================================================
        st.markdown("### 📦 Trazabilidad de Inventario - Producto por Producto")
        st.caption("Análisis detallado: Inventario Anterior - Ventas + Recepción = Inventario Esperado vs Inventario Reportado")

        # Verificar si tenemos los archivos necesarios
        tiene_inv_ant = 'df_inv_ant' in locals() and df_inv_ant is not None
        tiene_inv_rep = 'df_inv_rep' in locals() and df_inv_rep is not None
        tiene_costo = 'df_costo' in locals() and df_costo is not None
        tiene_rec_traz = 'df_recepciones_traz' in locals() and df_recepciones_traz is not None and recepcion_traz_data

        if tiene_inv_ant and tiene_inv_rep:
            try:
                # ============================================================
                # 1. CARGAR DATOS DE INVENTARIO ANTERIOR Y ACTUAL
                # ============================================================
                inv_prev = ProcesadorArchivos.cargar_detalle_inventario(df_inv_ant)
                inv_curr = ProcesadorArchivos.cargar_detalle_inventario(df_inv_rep)
                
                if inv_prev is not None and inv_curr is not None:
                    # ============================================================
                    # 2. CARGAR COSTO DE FACTURACIÓN (VENTAS)
                    # ============================================================
                    util_df = None
                    if tiene_costo:
                        util_df = ProcesadorArchivos.cargar_detalle_utilidad(df_costo)
                    
                    # ============================================================
                    # 3. CARGAR RECEPCIÓN TRAZABILIDAD (COMPRAS DEL DÍA) - CORREGIDO
                    # ============================================================
                    recepciones_traz = {}
                    total_recepcion_cantidad = 0.0
                    
                    if tiene_rec_traz:
                        # Usar los datos ya procesados de recepcion_traz_data
                        recepciones_traz = recepcion_traz_data
                        # Calcular el total de unidades recibidas
                        for codigo, info in recepciones_traz.items():
                            total_recepcion_cantidad += info.get('cantidad', 0)
                        st.success(f"✅ Recepción Trazabilidad cargada: {len(recepciones_traz)} productos, {total_recepcion_cantidad:.2f} unidades totales")
                        st.info(f"📦 Productos recibidos: {', '.join([info.get('producto', codigo) for codigo, info in list(recepciones_traz.items())[:5]])}")
                    else:
                        st.info("ℹ️ No se cargó archivo de Recepción Trazabilidad. Solo se usarán ventas para el cálculo.")
                    
                    # ============================================================
                    # 4. DICCIONARIOS PARA BÚSQUEDA RÁPIDA
                    # ============================================================
                    inv_prev_dict = inv_prev.set_index('Producto').to_dict('index')
                    inv_curr_dict = inv_curr.set_index('Producto').to_dict('index')
                    util_dict = util_df.set_index('Cod_Producto').to_dict('index') if util_df is not None else {}
                    
                    # ============================================================
                    # 5. OBTENER TODOS LOS PRODUCTOS
                    # ============================================================
                    all_prods = set(inv_prev_dict.keys()).union(set(inv_curr_dict.keys()))
                    
                    # ============================================================
                    # 6. VARIABLES PARA ACUMULAR TOTALES
                    # ============================================================
                    diferencias = []
                    total_inicial_valor = 0.0
                    total_ventas_valor = 0.0
                    total_recepcion_valor = 0.0
                    total_esperado_valor = 0.0
                    total_reportado_valor = 0.0
                    
                    total_inicial_cant = 0.0
                    total_ventas_cant = 0.0
                    total_recepcion_cant = 0.0
                    total_esperado_cant = 0.0
                    total_reportado_cant = 0.0
                    
                    # ============================================================
                    # 7. PROCESAR PRODUCTO POR PRODUCTO
                    # ============================================================
                    for p in all_prods:
                        # Obtener datos de inventario anterior
                        p_prev = inv_prev_dict.get(p, {'Cantidad': 0.0, 'Precio/Unidad': 0.0, 'Total(*)': 0.0, 'Descrip_Clean': 'N/A'})
                        
                        # Obtener datos de inventario actual (reportado)
                        p_curr = inv_curr_dict.get(p, {'Cantidad': 0.0, 'Precio/Unidad': 0.0, 'Total(*)': 0.0, 'Descrip_Clean': 'N/A'})
                        
                        # Obtener datos de ventas (costo de facturación)
                        u_row = util_dict.get(p, {'Cantidad': 0.0, 'Costo_Total': 0.0, 'Producto_Original': 'N/A'})
                        
                        # 🔥 CORREGIDO: Obtener datos de recepción trazabilidad
                        qty_recepcion_traz = 0.0
                        if p in recepciones_traz:
                            qty_recepcion_traz = recepciones_traz[p].get('cantidad', 0)
                        
                        # --- VALORES ---
                        qty_prev = p_prev['Cantidad']
                        price_prev = p_prev['Precio/Unidad']
                        val_prev = p_prev['Total(*)']
                        
                        qty_curr = p_curr['Cantidad']
                        price_curr = p_curr['Precio/Unidad']
                        val_curr = p_curr['Total(*)']
                        
                        qty_sold = u_row['Cantidad']
                        cost_sold = u_row['Costo_Total']
                        
                        desc = p_curr['Descrip_Clean'] if p_curr['Descrip_Clean'] != 'N/A' else (p_prev['Descrip_Clean'] if p_prev['Descrip_Clean'] != 'N/A' else u_row['Producto_Original'])
                        
                        # --- CÁLCULOS POR VALOR (Financiero) ---
                        expected_val = val_prev - cost_sold + (qty_recepcion_traz * price_prev)
                        val_diff = val_curr - expected_val
                        
                        # --- CÁLCULOS POR CANTIDAD (Trazabilidad) ---
                        expected_qty = qty_prev - qty_sold + qty_recepcion_traz
                        qty_diff = qty_curr - expected_qty
                        
                        # --- ACUMULAR TOTALES ---
                        total_inicial_valor += val_prev
                        total_ventas_valor += cost_sold
                        total_recepcion_valor += qty_recepcion_traz * price_prev
                        total_esperado_valor += expected_val
                        total_reportado_valor += val_curr
                        
                        total_inicial_cant += qty_prev
                        total_ventas_cant += qty_sold
                        total_recepcion_cant += qty_recepcion_traz
                        total_esperado_cant += expected_qty
                        total_reportado_cant += qty_curr
                        
                        # --- DETERMINAR ESTADO DEL PRODUCTO ---
                        estado = "✅ OK"
                        if abs(qty_diff) > 0.01 and abs(val_diff) > 0.01:
                            estado = "🔴 FALTANTE" if qty_diff < 0 else "🟢 SOBRANTE"
                        elif abs(qty_diff) > 0.01:
                            estado = "🟡 DIF. CANTIDAD"
                        elif abs(val_diff) > 0.01:
                            estado = "🟠 DIF. PRECIO"
                        
                        # --- GUARDAR SOLO PRODUCTOS CON MOVIMIENTO O DIFERENCIA ---
                        if abs(qty_sold) > 0.01 or abs(qty_diff) > 0.01 or abs(val_diff) > 0.01 or abs(price_curr - price_prev) > 0.01:
                            efecto_precio = (price_curr - price_prev) * qty_curr if qty_curr > 0 else 0
                            
                            diferencias.append({
                                'Código': p,
                                'Descripción': desc[:40],
                                'Estado': estado,
                                'Q. Anterior': qty_prev,
                                'Vendido': qty_sold,
                                'Recepción': qty_recepcion_traz,
                                'Q. Esperada': expected_qty,
                                'Q. Reportada': qty_curr,
                                'Dif. Cantidad': qty_diff,
                                'Precio Ant.': price_prev,
                                'Precio Nuevo': price_curr,
                                'Efecto Precio': efecto_precio,
                                'Dif. Valor': val_diff
                            })
                    
                    # ============================================================
                    # 8. SECCIÓN 1: KPIS PASO A PASO - POR VALOR (FINANCIERO)
                    # ============================================================
                    st.markdown("#### 📊 Paso a paso del cálculo de Inventario (VALORES)")
                    
                    col_inv1, col_inv2, col_inv3, col_inv4, col_inv5 = st.columns(5)
                    
                    mostrar_kpi_paso_paso(col_inv1, "Inv. Anterior (valor)", total_inicial_valor, "📦", "blue")
                    mostrar_kpi_paso_paso(col_inv2, "Costo de Ventas", total_ventas_valor, "📊", "red")
                    mostrar_kpi_paso_paso(col_inv3, "Recepción (valor)", total_recepcion_valor, "📥", "purple")
                    mostrar_kpi_paso_paso(col_inv4, "Inv. Esperado", total_esperado_valor, "📋", "orange")
                    mostrar_kpi_paso_paso(col_inv5, "Inv. Reportado", total_reportado_valor, "📄", "green")
                    
                    # ============================================================
                    # 9. VERIFICACIÓN DE INVENTARIO POR VALOR
                    # ============================================================
                    st.markdown("#### ✅ Verificación de Inventario (VALORES)")
                    
                    col_v_inv1, col_v_inv2, col_v_inv3 = st.columns(3)
                    
                    mostrar_kpi_paso_paso(col_v_inv1, "Inventario Esperado", total_esperado_valor, "📋", "orange")
                    mostrar_kpi_paso_paso(col_v_inv2, "Inventario Reportado", total_reportado_valor, "📄", "green")
                    
                    diff_total_valor = total_reportado_valor - total_esperado_valor
                    variante_diff_valor = "green" if abs(diff_total_valor) < 0.01 else ("red" if diff_total_valor < 0 else "orange")
                    icono_diff_valor = "✅" if abs(diff_total_valor) < 0.01 else ("⚠️" if diff_total_valor > 0 else "❌")
                    titulo_diff_valor = "Diferencia (Coincide)" if abs(diff_total_valor) < 0.01 else ("Sobrante" if diff_total_valor > 0 else "Faltante")
                    
                    mostrar_kpi_paso_paso(col_v_inv3, titulo_diff_valor, diff_total_valor, icono_diff_valor, variante_diff_valor)
                    
                    # ============================================================
                    # 10. KPIS PASO A PASO - POR CANTIDAD (TRAZABILIDAD) - CORREGIDO
                    # ============================================================
                    st.markdown("---")
                    st.markdown("#### 📊 Paso a paso del cálculo de Inventario (CANTIDADES - Trazabilidad)")
                    
                    col_inv_c1, col_inv_c2, col_inv_c3, col_inv_c4, col_inv_c5 = st.columns(5)
                    
                    mostrar_kpi_cantidades(col_inv_c1, "Inv. Anterior (und)", total_inicial_cant, "📦", "blue")
                    mostrar_kpi_cantidades(col_inv_c2, "Ventas (und)", total_ventas_cant, "📊", "red")
                    mostrar_kpi_cantidades(col_inv_c3, "Recepción (und)", total_recepcion_cant, "📥", "purple")
                    mostrar_kpi_cantidades(col_inv_c4, "Inv. Esperado (und)", total_esperado_cant, "📋", "orange")
                    mostrar_kpi_cantidades(col_inv_c5, "Inv. Reportado (und)", total_reportado_cant, "📄", "green")
                    
                    # ============================================================
                    # 11. VERIFICACIÓN DE INVENTARIO POR CANTIDAD - CORREGIDO
                    # ============================================================
                    st.markdown("#### ✅ Verificación de Inventario (CANTIDADES)")
                    
                    col_v_inv_c1, col_v_inv_c2, col_v_inv_c3 = st.columns(3)
                    
                    mostrar_kpi_cantidades(col_v_inv_c1, "Esperado (und)", total_esperado_cant, "📋", "orange")
                    mostrar_kpi_cantidades(col_v_inv_c2, "Reportado (und)", total_reportado_cant, "📄", "green")
                    
                    diff_total_cant = total_reportado_cant - total_esperado_cant
                    variante_diff_cant = "green" if abs(diff_total_cant) < 0.01 else ("red" if diff_total_cant < 0 else "orange")
                    icono_diff_cant = "✅" if abs(diff_total_cant) < 0.01 else ("⚠️" if diff_total_cant > 0 else "❌")
                    titulo_diff_cant = "Diferencia (Coincide)" if abs(diff_total_cant) < 0.01 else ("Sobrante" if diff_total_cant > 0 else "Faltante")
                    
                    mostrar_kpi_cantidades(col_v_inv_c3, titulo_diff_cant, diff_total_cant, icono_diff_cant, variante_diff_cant)
                    
                    # ============================================================
                    # 12. ESTADÍSTICAS DE PRODUCTOS
                    # ============================================================
                    st.markdown("---")
                    st.markdown("#### 📈 Estadísticas de Productos")
                    
                    col_est1, col_est2, col_est3, col_est4 = st.columns(4)
                    
                    with col_est1:
                        st.metric("📦 Total Productos", len(diferencias))
                    with col_est2:
                        ok_count = len([d for d in diferencias if d['Estado'] == '✅ OK'])
                        st.metric("✅ Productos OK", ok_count, delta=f"{ok_count}/{len(diferencias)}")
                    with col_est3:
                        warning_count = len([d for d in diferencias if d['Estado'] != '✅ OK'])
                        st.metric("⚠️ Con Diferencias", warning_count, delta=f"{warning_count}/{len(diferencias)}")
                    with col_est4:
                        total_unidades = sum([d['Vendido'] for d in diferencias])
                        st.metric("📊 Total Ventas (Und.)", f"{total_unidades:,.0f}")
                    
                    # ============================================================
                    # 13. BOTONES PARA EXPLORAR DETALLES
                    # ============================================================
                    st.markdown("---")
                    st.markdown("#### 🔍 Explorar Detalles de Inventario")
                    
                    with st.expander("🔍 Explorar Detalles y Tabla de Productos", expanded=False):
                        col_btn1, col_btn2, col_btn3 = st.columns(3)
                        
                        with col_btn1:
                            if st.button("📋 Ver Todos los Productos", width='stretch', key="btn_todos_productos_tab2"):
                                st.session_state['mostrar_todos_productos'] = not st.session_state.get('mostrar_todos_productos', False)
                        
                        with col_btn2:
                            if st.button("⚠️ Solo Productos con Diferencias", width='stretch', key="btn_productos_diff_tab2"):
                                st.session_state['mostrar_solo_diff'] = not st.session_state.get('mostrar_solo_diff', False)
                        
                        with col_btn3:
                            if st.button("💰 Productos con Cambio de Precio", width='stretch', key="btn_cambio_precio_tab2"):
                                st.session_state['mostrar_cambio_precio'] = not st.session_state.get('mostrar_cambio_precio', False)
                        
                        # ============================================================
                        # 14. TABLA DE PRODUCTOS
                        # ============================================================
                        st.markdown("---")
                        
                        mostrar_todos = st.session_state.get('mostrar_todos_productos', False)
                        mostrar_solo_diff = st.session_state.get('mostrar_solo_diff', False)
                        mostrar_cambio_precio = st.session_state.get('mostrar_cambio_precio', False)
                        
                        if mostrar_todos or mostrar_solo_diff or mostrar_cambio_precio:
                            df_display = pd.DataFrame(diferencias)
                            
                            if mostrar_solo_diff:
                                df_display = df_display[df_display['Estado'] != '✅ OK']
                                titulo_tabla = f"⚠️ Productos con Diferencias ({len(df_display)})"
                            elif mostrar_cambio_precio:
                                cambios_precio = [d for d in diferencias if abs(d['Efecto Precio']) > 0.01]
                                df_display = pd.DataFrame(cambios_precio)
                                titulo_tabla = f"💰 Productos con Cambio de Precio ({len(df_display)})"
                            else:
                                titulo_tabla = f"📋 Todos los Productos ({len(df_display)})"
                            
                            if not df_display.empty:
                                with st.expander(f"📊 {titulo_tabla}", expanded=True):
                                    df_formatted = df_display.copy()
                                    for col in ['Precio Ant.', 'Precio Nuevo', 'Efecto Precio', 'Dif. Valor']:
                                        if col in df_formatted.columns:
                                            df_formatted[col] = df_formatted[col].apply(formato_venezolano)
                                    
                                    df_formatted['Dif. Cantidad'] = df_formatted['Dif. Cantidad'].apply(lambda x: f"{x:.2f}")
                                    df_formatted['Q. Anterior'] = df_formatted['Q. Anterior'].apply(lambda x: f"{x:.2f}")
                                    df_formatted['Vendido'] = df_formatted['Vendido'].apply(lambda x: f"{x:.2f}")
                                    df_formatted['Recepción'] = df_formatted['Recepción'].apply(lambda x: f"{x:.2f}")
                                    df_formatted['Q. Esperada'] = df_formatted['Q. Esperada'].apply(lambda x: f"{x:.2f}")
                                    df_formatted['Q. Reportada'] = df_formatted['Q. Reportada'].apply(lambda x: f"{x:.2f}")
                                    
                                    columnas_mostrar = ['Código', 'Descripción', 'Estado', 'Q. Anterior', 'Vendido', 'Recepción', 'Q. Esperada', 'Q. Reportada', 'Dif. Cantidad', 'Precio Ant.', 'Precio Nuevo', 'Efecto Precio', 'Dif. Valor']
                                    columnas_existentes = [c for c in columnas_mostrar if c in df_formatted.columns]
                                    
                                    def colorear_estado(row):
                                        estado = row['Estado']
                                        if estado == '🔴 FALTANTE':
                                            return ['background-color: #ffcccc;'] * len(row)
                                        elif estado == '🟢 SOBRANTE':
                                            return ['background-color: #ccffcc;'] * len(row)
                                        elif estado == '🟠 DIF. PRECIO':
                                            return ['background-color: #fff3cd;'] * len(row)
                                        elif estado == '🟡 DIF. CANTIDAD':
                                            return ['background-color: #fff3cd;'] * len(row)
                                        return [''] * len(row)
                                    
                                    st.dataframe(
                                        df_formatted[columnas_existentes].style.apply(colorear_estado, axis=1).hide(axis='index'),
                                        use_container_width=True,
                                        height=400
                                    )
                                    
                                    if mostrar_solo_diff or mostrar_todos:
                                        col_res1, col_res2, col_res3 = st.columns(3)
                                        with col_res1:
                                            faltantes = len(df_display[df_display['Estado'] == '🔴 FALTANTE'])
                                            st.metric("🔴 Faltantes", faltantes)
                                        with col_res2:
                                            sobrantes = len(df_display[df_display['Estado'] == '🟢 SOBRANTE'])
                                            st.metric("🟢 Sobrantes", sobrantes)
                                        with col_res3:
                                            otras = len(df_display[~df_display['Estado'].isin(['🔴 FALTANTE', '🟢 SOBRANTE', '✅ OK'])])
                                            st.metric("🟡 Otras Diferencias", otras)
                            else:
                                st.info("ℹ️ No hay productos que coincidan con el filtro seleccionado.")
                            
                            if st.button("🔒 Cerrar todas las vistas", width='stretch'):
                                st.session_state['mostrar_todos_productos'] = False
                                st.session_state['mostrar_solo_diff'] = False
                                st.session_state['mostrar_cambio_precio'] = False
                                st.rerun()
                        else:
                            st.info("👆 **Haz clic en uno de los botones arriba** para explorar el detalle de productos.")
                    
                    # ============================================================
                    # 15. RESUMEN DE DIFERENCIAS
                    # ============================================================
                    if diferencias:
                        st.markdown("---")
                        st.markdown("#### 📊 Resumen de Diferencias de Inventario")
                        
                        total_faltante = sum([d['Dif. Cantidad'] for d in diferencias if d['Estado'] == '🔴 FALTANTE'])
                        total_sobrante = sum([d['Dif. Cantidad'] for d in diferencias if d['Estado'] == '🟢 SOBRANTE'])
                        total_efecto_precio = sum([d['Efecto Precio'] for d in diferencias if abs(d['Efecto Precio']) > 0.01])
                        
                        col_res1, col_res2, col_res3 = st.columns(3)
                        
                        with col_res1:
                            if total_faltante < 0:
                                st.error(f"🔴 **Faltante:** {abs(total_faltante):.2f} unidades")
                            else:
                                st.success(f"✅ **Faltante:** 0 unidades")
                        
                        with col_res2:
                            if total_sobrante > 0:
                                st.success(f"🟢 **Sobrante:** {total_sobrante:.2f} unidades")
                            else:
                                st.info("ℹ️ **Sobrante:** 0 unidades")
                        
                        with col_res3:
                            if abs(total_efecto_precio) > 0.01:
                                if total_efecto_precio > 0:
                                    st.warning(f"📈 **Efecto Precio:** +{formato_venezolano(total_efecto_precio)} Bs.")
                                else:
                                    st.warning(f"📉 **Efecto Precio:** {formato_venezolano(total_efecto_precio)} Bs.")
                            else:
                                st.success("✅ **Efecto Precio:** 0 Bs.")
                else:
                    st.warning("⚠️ No se pudieron cargar los detalles de inventario. Verifica el formato de los archivos.")
            except Exception as e:
                st.error(f"❌ Error en el análisis de trazabilidad de inventario: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
        else:
            st.info("📄 **Carga los siguientes archivos para ver el análisis detallado de inventario:**")
            st.info("- 📦 **Inventario Anterior** (día anterior)")
            st.info("- 📄 **Inventario Reportado** (día actual)")
            st.info("- 📈 **Costo de Facturación** (opcional, para ventas)")
            st.info("- 📥 **Recepción Trazabilidad** (opcional, para compras)")

        st.markdown("---")

# ============================================================
# PESTAÑA 3: ARCHIVOS FUENTE DEL DÍA
# ============================================================
with tab_auditoria_archivos:
    st.markdown("### 📄 Archivos Fuente y Auditoría del Bot")
    st.caption("Visualización de los archivos Excel cargados y conciliación histórica del bot.")

    # 1. Alertas de procesamiento diferidas
    if 'cargas_status_alerts' in locals() and cargas_status_alerts:
        with st.expander("📝 Registro de Carga de Archivos y Alertas de Procesamiento", expanded=False):
            for tipo, msg in cargas_status_alerts:
                if tipo == "info": st.info(msg)
                elif tipo == "success": st.success(msg)
                elif tipo == "warning": st.warning(msg)
                elif tipo == "error": st.error(msg)

    # 2. Motor de Auditoría y Trazabilidad de Errores (Manual)
    st.markdown("#### 🔍 Motor de Auditoría y Trazabilidad de Errores (Manual)")
    if st.button("🔍 Ejecutar Auditoría de Trazabilidad Manual", width='stretch', key="btn_auditoria_manual_tab3_new"):
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

    # 3. Módulo Pasivo del Bot Nocturno
    st.markdown("---")
    st.markdown("#### 🤖 Módulo Pasivo del Bot Nocturno")
    existe_bot, fecha_bot, hay_err_bot, fallas_bot, df_c_bot, kpis_bot = cargar_ultimo_cierre(
        fecha=fecha_procesar.strftime('%Y-%m-%d'),
        empresa=st.session_state.empresa_activa
    )
    if existe_bot:
        st.success(f"📅 **Último cierre automático registrado:** {fecha_bot}")
        col_bot1, col_bot2, col_bot3 = st.columns(3)
        col_bot1.metric("💵 Tasa BCV (Bot)", f"{kpis_bot.get('tasa_bcv', 0.0):.2f} Bs/$")
        col_bot2.metric("📊 Total Balance (VES)", f"{kpis_bot.get('total_ves', 0.0):,.2f} VES")
        col_bot3.metric("📈 Consolidado (USD)", f"${kpis_bot.get('total_usd', 0.0):,.2f}")

        with st.expander("🔍 Ver detalle de Auditoría del Bot Nocturno", expanded=False):
            renderizar_modulo_auditoria(
                fallas_bot, df_c_bot, hay_err_bot, fecha_bot,
                analista_default="Bot Nocturno"
            )
    else:
        st.info("ℹ️ No se encontró un cierre automático del bot nocturno registrado para esta fecha.")

    st.markdown("---")
    # VISUALIZACIÓN DE ARCHIVOS
    # ============================================================
    st.markdown("#### 📋 Archivos Cargados")
    
    # Crear tabs para cada archivo
    archivos_tabs = list(archivos_data.keys())
    if archivos_tabs:
        tabs = st.tabs(archivos_tabs)
        for tab, nombre in zip(tabs, archivos_tabs):
            with tab:
                info = archivos_data[nombre]
                df = info['df']
                nombre_archivo = info['nombre']
                
                # Procesar el archivo para mostrar
                df_proc, stats, col_numericas = mostrar_archivo_con_formato(df, nombre_archivo, nombre)
                if df_proc is not None and stats is not None:
                    renderizar_archivo_en_tab(df_proc, nombre_archivo, nombre, stats, col_numericas)
                else:
                    st.warning(f"⚠️ No se pudo procesar el archivo {nombre}")
    else:
        st.info("ℹ️ No hay archivos cargados para visualizar.")
    
    # ============================================================
    # BOTONES DE VERIFICACIÓN DE ARCHIVOS
    # ============================================================
    st.markdown("---")
    st.markdown("#### 📂 Ver archivos de verificación")

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
                if st.button(f"📄 Ver {nombre}", key=f"btn_{nombre}_tab3", width='stretch'):
                    df_verif, stats_verif, col_num_verif = mostrar_archivo_con_formato(
                        archivos_cargados[titulo], 
                        archivo.name, 
                        f"Archivo {titulo}"
                    )
                    if df_verif is not None and stats_verif is not None:
                        renderizar_archivo_en_tab(df_verif, archivo.name, f"Archivo {titulo}", stats_verif, col_num_verif)
                    else:
                        st.warning("⚠️ No se pudo procesar el archivo")
            else:
                st.button(f"❌ {nombre} no cargado", disabled=True, width='stretch')
    # ============================================================
    # REGLAS DE NEGOCIO (FUERA DE LAS PESTAÑAS)
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
# 🗑️ LIMPIAR SALDOS (AL PIE DE PÁGINA)
# ============================================================
st.markdown("---")
col_clean1, col_clean2, col_clean3 = st.columns([1, 2, 1])
with col_clean2:
    if st.button("🗑️ LIMPIAR SALDOS", use_container_width=True):
        db.limpiar_saldos()
        st.success("✅ Tabla saldos_diarios limpiada correctamente")
        st.rerun()

# ============================================================
# PIE DE PÁGINA
# ============================================================
st.markdown("---")
st.caption("✨ Validador de Trazabilidad Diaria - Capital de Trabajo Neto Operativo | Grupo Bodeguita Oriente")
