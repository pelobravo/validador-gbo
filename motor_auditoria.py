import re
import os
import sqlite3
import pandas as pd
import numpy as np
import streamlit as st

# Ruta de la base de datos local en la raíz del proyecto
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auditoria_memoria.db")

def inicializar_bd():
    """
    Inicializa la base de datos SQLite3 y crea la tabla de excepciones históricas si no existe.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS excepciones_conciliacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia TEXT NOT NULL,
            monto REAL NOT NULL,
            banco TEXT NOT NULL,
            tipo_excepcion TEXT NOT NULL,
            usuario_analista TEXT NOT NULL,
            fecha_aprobacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(referencia, monto, banco)
        )
    """)
    conn.commit()
    conn.close()

def registrar_excepcion(referencia, monto, banco, tipo_excepcion, usuario_analista):
    """
    Registra una excepción validada por el analista en la base de datos local.
    Limpia la referencia antes de insertarla para garantizar coherencia en búsquedas futuras.
    Invalida el caché de Streamlit para obligar una recarga en la siguiente ejecución.
    """
    inicializar_bd()
    
    # Normalizar referencia de la misma forma que en Pandas
    ref_limpia = str(referencia).strip()
    ref_limpia = re.sub(r'\s+', '', ref_limpia)
    ref_limpia = re.sub(r'^0+', '', ref_limpia)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    success = False
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO excepciones_conciliacion 
            (referencia, monto, banco, tipo_excepcion, usuario_analista)
            VALUES (?, ?, ?, ?, ?)
        """, (ref_limpia, float(monto), str(banco), str(tipo_excepcion), str(usuario_analista)))
        conn.commit()
        success = True
        
        # Limpiar el caché de la función de Streamlit
        st.cache_data.clear()
    except Exception as e:
        print(f"Error al registrar excepción en la BD: {e}")
    finally:
        conn.close()
    return success

def buscar_excepcion(referencia, monto, banco_nombre):
    """
    Busca si existe una excepción histórica registrada en la BD para la transacción dada.
    Retorna el nombre del analista que la aprobó si existe, o None si no existe.
    """
    inicializar_bd()
    
    # Normalizar referencia
    ref_limpia = str(referencia).strip()
    ref_limpia = re.sub(r'\s+', '', ref_limpia)
    ref_limpia = re.sub(r'^0+', '', ref_limpia)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    analista = None
    try:
        # Se busca con tolerancia por redondeo de flotantes en monto
        cursor.execute("""
            SELECT usuario_analista FROM excepciones_conciliacion 
            WHERE referencia = ? AND ABS(monto - ?) < 0.01 AND (banco = ? OR ? LIKE '%' || banco || '%')
        """, (ref_limpia, float(monto), str(banco_nombre), str(banco_nombre)))
        row = cursor.fetchone()
        if row:
            analista = row[0]
    except Exception as e:
        print(f"Error al buscar excepción en la BD: {e}")
    finally:
        conn.close()
    return analista

def normalize_cols(df, label):
    """
    Normaliza y limpia un DataFrame detectando columnas de Referencia, Fecha y Monto.
    Limpia referencias removiendo espacios y ceros a la izquierda mediante expresiones regulares.
    """
    if df is None or df.empty:
        return None
    
    df = df.copy()
    
    # Limpieza básica de nombres de columnas
    orig_cols = list(df.columns)
    clean_cols = [str(c).strip().lower() for c in orig_cols]
    df.columns = clean_cols
    
    # 1. Identificación de columna de Referencia
    ref_col = None
    ref_candidates = ['referencia', 'ref', 'nro_referencia', 'nro. referencia', 'numero de referencia', 
                      'numero_referencia', 'soporte', 'transaccion', 'documento', 'nro. ref', 'nro ref']
    for name in ref_candidates:
        if name in clean_cols:
            ref_col = name
            break
    if not ref_col:
        for c in clean_cols:
            if 'referencia' in c or 'ref' in c or 'trans' in c or 'doc' in c:
                ref_col = c
                break
    if not ref_col:
        ref_col = clean_cols[0]  # Fallback a la primera columna
        
    # 2. Identificación de columna de Fecha
    date_col = None
    date_candidates = ['fecha', 'fec', 'fecha_valor', 'fecha valor', 'date', 'f. valor', 'f_valor', 'fecha_registro']
    for name in date_candidates:
        if name in clean_cols:
            date_col = name
            break
    if not date_col:
        for c in clean_cols:
            if 'fecha' in c or 'fec' in c or 'date' in c:
                date_col = c
                break
    if not date_col:
        date_col = clean_cols[1] if len(clean_cols) > 1 else clean_cols[0]
        
    # 3. Identificación de columna de Monto
    amount_col = None
    amount_candidates = ['monto', 'importe', 'amount', 'monto_bs', 'monto_usd', 'total', 'mto', 'debe', 'haber', 
                         'monto neto', 'neto']
    for name in amount_candidates:
        if name in clean_cols:
            amount_col = name
            break
    if not amount_col:
        for c in clean_cols:
            if 'monto' in c or 'imp' in c or 'total' in c or 'amount' in c:
                amount_col = c
                break
    if not amount_col:
        amount_col = clean_cols[2] if len(clean_cols) > 2 else clean_cols[0]
        
    # Mapeo a nombres estándar
    df = df.rename(columns={ref_col: 'referencia', date_col: 'fecha', amount_col: 'monto'})
    
    # --- Limpieza de Referencia ---
    df['referencia'] = df['referencia'].astype(str).str.strip()
    df['referencia'] = df['referencia'].str.replace(r'\s+', '', regex=True)
    df['referencia'] = df['referencia'].str.replace(r'^0+', '', regex=True)
    
    # --- Parseo de Fecha ---
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
    
    # --- Parseo de Monto ---
    if df['monto'].dtype == object:
        df['monto'] = df['monto'].astype(str).str.replace(r'[^\d\.\-]', '', regex=True)
    df['monto'] = pd.to_numeric(df['monto'], errors='coerce').fillna(0.0)
    
    # Eliminar registros con fechas inválidas o referencias vacías
    df = df.dropna(subset=['referencia', 'fecha'])
    df = df[df['referencia'] != '']
    
    df['_origen'] = label
    
    return df[['referencia', 'fecha', 'monto', '_origen']]

def load_excel_safe(file_obj):
    """
    Carga de forma segura un archivo Excel desde un objeto Streamlit UploadedFile o DataFrame.
    """
    if file_obj is None:
        return None
    if isinstance(file_obj, pd.DataFrame):
        return file_obj.copy()
    
    try:
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        return pd.read_excel(file_obj)
    except Exception as e:
        st.error(f"Error al procesar el archivo Excel: {e}")
        return None

@st.cache_data(show_spinner="🔍 Cruzando información y conciliando en memoria...")
def ejecutar_auditoria_inteligente(file_facturacion, file_cobranzas, file_ipago, file_banco):
    """
    Motor centralizado de cruce perimetral indexado en memoria con aprendizaje SQLite3.
    Retorna:
        - hay_errores: bool (indica si hay errores ACTIVOS no auto-corregidos)
        - fallas_detectadas: lista de diccionarios (incluye fallas activas y auto-correcciones verdes)
        - df_consolidado: DataFrame con el reporte de discrepancias y conciliación
    """
    # Inicializar la base de datos por seguridad
    inicializar_bd()
    
    # 1. Carga segura de archivos
    df_fact = load_excel_safe(file_facturacion)
    df_cobr = load_excel_safe(file_cobranzas)
    df_ipag = load_excel_safe(file_ipago)
    df_bnco = load_excel_safe(file_banco)
    
    # 2. Normalización de columnas y referencias
    df_fact_n = normalize_cols(df_fact, 'Facturacion')
    df_cobr_n = normalize_cols(df_cobr, 'Cobranzas')
    df_ipag_n = normalize_cols(df_ipag, 'iPago')
    df_bnco_n = normalize_cols(df_bnco, 'Banco')
    
    # 3. Consolidar el lado del sistema (iPago y Cobranzas)
    system_dfs = []
    if df_ipag_n is not None and not df_ipag_n.empty:
        system_dfs.append(df_ipag_n)
    if df_cobr_n is not None and not df_cobr_n.empty:
        system_dfs.append(df_cobr_n)
        
    if system_dfs:
        df_sistema = pd.concat(system_dfs, ignore_index=True)
    else:
        df_sistema = pd.DataFrame(columns=['referencia', 'fecha', 'monto', '_origen'])
        
    if df_bnco_n is None or df_bnco_n.empty:
        df_bnco_n = pd.DataFrame(columns=['referencia', 'fecha', 'monto', '_origen'])
        
    # Estructuras para almacenar hallazgos
    fallas_detectadas = []
    consolidated_records = []
    
    # 4. Obtener todas las referencias únicas encontradas
    todas_las_referencias = set(df_bnco_n['referencia']).union(set(df_sistema['referencia']))
    
    for ref in todas_las_referencias:
        b_rows = df_bnco_n[df_bnco_n['referencia'] == ref].copy()
        s_rows = df_sistema[df_sistema['referencia'] == ref].copy()
        
        b_rows['_matched'] = False
        s_rows['_matched'] = False
        
        # FASE A: Buscar coincidencias perfectas en Monto y Fecha (tolerancia <= 24h)
        for b_idx, b_row in b_rows.iterrows():
            best_s_idx = None
            min_time_diff = pd.Timedelta(days=999)
            
            for s_idx, s_row in s_rows.iterrows():
                if s_row['_matched']:
                    continue
                if abs(b_row['monto'] - s_row['monto']) < 0.01:
                    time_diff = abs(b_row['fecha'] - s_row['fecha'])
                    if time_diff <= pd.Timedelta(hours=24) and time_diff < min_time_diff:
                        min_time_diff = time_diff
                        best_s_idx = s_idx
            
            if best_s_idx is not None:
                b_rows.loc[b_idx, '_matched'] = True
                s_rows.loc[best_s_idx, '_matched'] = True
                
                consolidated_records.append({
                    'referencia': ref,
                    'fecha_banco': b_row['fecha'],
                    'monto_banco': b_row['monto'],
                    'fecha_sistema': s_rows.loc[best_s_idx, 'fecha'],
                    'monto_sistema': s_rows.loc[best_s_idx, 'monto'],
                    'origen_sistema': s_rows.loc[best_s_idx, '_origen'],
                    'estatus': 'CONCILIADO',
                    'alerta': 'VERDE',
                    'diferencia': 0.0
                })
                
        # FASE B: Buscar diferencias de monto (Misma referencia, Fecha <= 24h, pero Monto no cuadra)
        for b_idx, b_row in b_rows.iterrows():
            if b_rows.loc[b_idx, '_matched']:
                continue
                
            best_s_idx = None
            min_time_diff = pd.Timedelta(days=999)
            
            for s_idx, s_row in s_rows.iterrows():
                if s_row['_matched']:
                    continue
                time_diff = abs(b_row['fecha'] - s_row['fecha'])
                if time_diff <= pd.Timedelta(hours=24) and time_diff < min_time_diff:
                    min_time_diff = time_diff
                    best_s_idx = s_idx
            
            if best_s_idx is not None:
                b_rows.loc[b_idx, '_matched'] = True
                s_rows.loc[best_s_idx, '_matched'] = True
                s_row = s_rows.loc[best_s_idx]
                
                diff_exacta = abs(b_row['monto'] - s_row['monto'])
                
                # --- AUTO-CORRECCIÓN EVOLUTIVA (Consulta a Base de Datos) ---
                # Validamos si existe excepción para monto de banco o de sistema en sus respectivos módulos
                analista_nombre = buscar_excepcion(ref, b_row['monto'], 'Banco') or buscar_excepcion(ref, s_row['monto'], s_row['_origen'])
                
                if analista_nombre is not None:
                    # Registramos la auto-corrección verde
                    falla = {
                        'tipo': 'VERDE_CORREGIDO',
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(b_row['fecha']) else 'N/A',
                        'monto_banco': float(b_row['monto']),
                        'fecha_sistema': s_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(s_row['fecha']) else 'N/A',
                        'monto_sistema': float(s_row['monto']),
                        'origen': s_row['_origen'],
                        'destino': 'Banco',
                        'diferencia': float(diff_exacta),
                        'causa': f"🟢 Movimiento AUTO-CORREGIDO por el motor. Causa: Excepción histórica aprobada previamente por el analista {analista_nombre}.",
                        'accion': "No requiere acción. Validada previamente."
                    }
                    fallas_detectadas.append(falla)
                    
                    consolidated_records.append({
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'],
                        'monto_banco': b_row['monto'],
                        'fecha_sistema': s_row['fecha'],
                        'monto_sistema': s_row['monto'],
                        'origen_sistema': s_row['_origen'],
                        'estatus': 'AUTO-CORREGIDO',
                        'alerta': 'VERDE_CORREGIDO',
                        'diferencia': diff_exacta
                    })
                else:
                    # Es una Alerta Naranja Activa
                    falla = {
                        'tipo': 'NARANJA',
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(b_row['fecha']) else 'N/A',
                        'monto_banco': float(b_row['monto']),
                        'fecha_sistema': s_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(s_row['fecha']) else 'N/A',
                        'monto_sistema': float(s_row['monto']),
                        'origen': s_row['_origen'],
                        'destino': 'Banco',
                        'diferencia': float(diff_exacta),
                        'causa': f"Diferencia de monto para la referencia {ref}. Banco registra {b_row['monto']:.2f} Bs/USD mientras que Sistema ({s_row['_origen']}) registra {s_row['monto']:.2f} Bs/USD.",
                        'accion': "Validar los soportes de pago y estados de cuenta. Ajustar el registro en el sistema administrativo."
                    }
                    fallas_detectadas.append(falla)
                    
                    consolidated_records.append({
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'],
                        'monto_banco': b_row['monto'],
                        'fecha_sistema': s_row['fecha'],
                        'monto_sistema': s_row['monto'],
                        'origen_sistema': s_row['_origen'],
                        'estatus': 'DIFERENCIA MONTO',
                        'alerta': 'NARANJA',
                        'diferencia': diff_exacta
                    })
                
        # FASE C: Registrar movimientos de Banco no encontrados en el Sistema
        for b_idx, b_row in b_rows.iterrows():
            if not b_rows.loc[b_idx, '_matched']:
                # --- AUTO-CORRECCIÓN EVOLUTIVA (Consulta a Base de Datos) ---
                analista_nombre = buscar_excepcion(ref, b_row['monto'], 'Banco')
                
                if analista_nombre is not None:
                    falla = {
                        'tipo': 'VERDE_CORREGIDO',
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(b_row['fecha']) else 'N/A',
                        'monto_banco': float(b_row['monto']),
                        'fecha_sistema': 'N/A',
                        'monto_sistema': 0.0,
                        'origen': 'Banco',
                        'destino': 'iPago / Cobranzas',
                        'diferencia': float(b_row['monto']),
                        'causa': f"🟢 Movimiento AUTO-CORREGIDO por el motor. Causa: Excepción histórica aprobada previamente por el analista {analista_nombre}.",
                        'accion': "No requiere acción. Validada previamente."
                    }
                    fallas_detectadas.append(falla)
                    
                    consolidated_records.append({
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'],
                        'monto_banco': b_row['monto'],
                        'fecha_sistema': None,
                        'monto_sistema': 0.0,
                        'origen_sistema': 'Ninguno',
                        'estatus': 'AUTO-CORREGIDO',
                        'alerta': 'VERDE_CORREGIDO',
                        'diferencia': b_row['monto']
                    })
                else:
                    # Es una Alerta Roja Activa (Falta en Sistema)
                    falla = {
                        'tipo': 'ROJA',
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(b_row['fecha']) else 'N/A',
                        'monto_banco': float(b_row['monto']),
                        'fecha_sistema': 'N/A',
                        'monto_sistema': 0.0,
                        'origen': 'Banco',
                        'destino': 'iPago / Cobranzas',
                        'diferencia': float(b_row['monto']),
                        'causa': f"El movimiento con referencia {ref} fue liquidado en el Banco pero no se encuentra registrado en los módulos de Cobranzas o Egresos iPago.",
                        'accion': "Generar el registro correspondiente en el sistema administrativo (Factura cobrada o Egreso registrado en iPago) para conciliar el saldo bancario."
                    }
                    fallas_detectadas.append(falla)
                    
                    consolidated_records.append({
                        'referencia': ref,
                        'fecha_banco': b_row['fecha'],
                        'monto_banco': b_row['monto'],
                        'fecha_sistema': None,
                        'monto_sistema': 0.0,
                        'origen_sistema': 'Ninguno',
                        'estatus': 'FALTA EN SISTEMA',
                        'alerta': 'ROJA',
                        'diferencia': b_row['monto']
                    })
                
        # FASE D: Registrar movimientos de iPago no encontrados en el Banco
        for s_idx, s_row in s_rows.iterrows():
            if not s_rows.loc[s_idx, '_matched']:
                is_ipago = s_row['_origen'] == 'iPago'
                
                if is_ipago:
                    # --- AUTO-CORRECCIÓN EVOLUTIVA (Consulta a Base de Datos) ---
                    analista_nombre = buscar_excepcion(ref, s_row['monto'], 'iPago')
                    
                    if analista_nombre is not None:
                        falla = {
                            'tipo': 'VERDE_CORREGIDO',
                            'referencia': ref,
                            'fecha_banco': 'N/A',
                            'monto_banco': 0.0,
                            'fecha_sistema': s_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(s_row['fecha']) else 'N/A',
                            'monto_sistema': float(s_row['monto']),
                            'origen': 'iPago',
                            'destino': 'Banco',
                            'diferencia': float(s_row['monto']),
                            'causa': f"🟢 Movimiento AUTO-CORREGIDO por el motor. Causa: Excepción histórica aprobada previamente por el analista {analista_nombre}.",
                            'accion': "No requiere acción. Validada previamente en tránsito."
                        }
                        fallas_detectadas.append(falla)
                        
                        consolidated_records.append({
                            'referencia': ref,
                            'fecha_banco': None,
                            'monto_banco': 0.0,
                            'fecha_sistema': s_row['fecha'],
                            'monto_sistema': s_row['monto'],
                            'origen_sistema': s_row['_origen'],
                            'estatus': 'AUTO-CORREGIDO',
                            'alerta': 'VERDE_CORREGIDO',
                            'diferencia': s_row['monto']
                        })
                    else:
                        # Es una Alerta Amarilla Activa (Transacción en Tránsito)
                        falla = {
                            'tipo': 'AMARILLA',
                            'referencia': ref,
                            'fecha_banco': 'N/A',
                            'monto_banco': 0.0,
                            'fecha_sistema': s_row['fecha'].strftime('%Y-%m-%d %H:%M') if pd.notnull(s_row['fecha']) else 'N/A',
                            'monto_sistema': float(s_row['monto']),
                            'origen': 'iPago',
                            'destino': 'Banco',
                            'diferencia': float(s_row['monto']),
                            'causa': f"El egreso con referencia {ref} está en el sistema iPago pero no se visualiza en ningún estado de cuenta bancario cargado.",
                            'accion': "Monitorear el estado de cuenta en los próximos cierres bancarios. Confirmar si quedó diferida."
                        }
                        fallas_detectadas.append(falla)
                        
                        consolidated_records.append({
                            'referencia': ref,
                            'fecha_banco': None,
                            'monto_banco': 0.0,
                            'fecha_sistema': s_row['fecha'],
                            'monto_sistema': s_row['monto'],
                            'origen_sistema': s_row['_origen'],
                            'estatus': 'TRANSACCION EN TRANSITO',
                            'alerta': 'AMARILLA',
                            'diferencia': s_row['monto']
                        })
                else:
                    # Cobranzas no conciliadas (no genera alerta según especificación, pero va en reporte)
                    consolidated_records.append({
                        'referencia': ref,
                        'fecha_banco': None,
                        'monto_banco': 0.0,
                        'fecha_sistema': s_row['fecha'],
                        'monto_sistema': s_row['monto'],
                        'origen_sistema': s_row['_origen'],
                        'estatus': 'NO CONCILIADO (COBRANZAS)',
                        'alerta': 'GRIS',
                        'diferencia': s_row['monto']
                    })

    # Generar el DataFrame consolidado final
    df_consolidado = pd.DataFrame(consolidated_records)
    if df_consolidado.empty:
        df_consolidado = pd.DataFrame(columns=[
            'referencia', 'fecha_banco', 'monto_banco', 'fecha_sistema', 'monto_sistema', 
            'origen_sistema', 'estatus', 'alerta', 'diferencia'
        ])
    else:
        # Ordenar cronológicamente priorizando la fecha de banco
        df_consolidado = df_consolidado.sort_values(by=['fecha_banco', 'fecha_sistema'], na_position='last')
        
    # Verificar si hay errores activos (rojo, amarillo, naranja) excluyendo las auto-correcciones verdes
    hay_errores = any(f['tipo'] in ['ROJA', 'AMARILLA', 'NARANJA'] for f in fallas_detectadas)
    
    return hay_errores, fallas_detectadas, df_consolidado
