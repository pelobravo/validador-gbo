import re
import pandas as pd
import numpy as np
import streamlit as st

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
    # Convertir a string, remover espacios en blanco y eliminar ceros a la izquierda mediante Regex
    df['referencia'] = df['referencia'].astype(str).str.strip()
    df['referencia'] = df['referencia'].str.replace(r'\s+', '', regex=True)
    df['referencia'] = df['referencia'].str.replace(r'^0+', '', regex=True)
    
    # --- Parseo de Fecha ---
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
    
    # --- Parseo de Monto ---
    if df['monto'].dtype == object:
        # Remover símbolos de moneda y comas/puntos extraños
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
        # Resetear el puntero para el lector de archivos si aplica (evita problemas de doble lectura)
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        return pd.read_excel(file_obj)
    except Exception as e:
        st.error(f"Error al procesar el archivo Excel: {e}")
        return None

@st.cache_data(show_spinner="🔍 Cruzando información y conciliando en memoria...")
def ejecutar_auditoria_inteligente(file_facturacion, file_cobranzas, file_ipago, file_banco):
    """
    Motor centralizado de cruce perimetral indexado en memoria.
    Retorna:
        - hay_errores: bool
        - fallas_detectadas: lista de diccionarios
        - df_consolidado: DataFrame con el reporte de discrepancias y conciliación
    """
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
        # Filtrar registros correspondientes a la referencia
        b_rows = df_bnco_n[df_bnco_n['referencia'] == ref].copy()
        s_rows = df_sistema[df_sistema['referencia'] == ref].copy()
        
        # Marcar banderas de coincidencia
        b_rows['_matched'] = False
        s_rows['_matched'] = False
        
        # FASE A: Buscar coincidencias perfectas en Monto y Fecha (tolerancia <= 24h)
        for b_idx, b_row in b_rows.iterrows():
            best_s_idx = None
            min_time_diff = pd.Timedelta(days=999)
            
            for s_idx, s_row in s_rows.iterrows():
                if s_row['_matched']:
                    continue
                # Si el monto es igual (tolerancia de 0.01 centavos)
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
                    'accion': "Validar los soportes de pago y estados de cuenta. Ajustar el registro en el sistema administrativo para reflejar el monto exacto debitado/acreditado en el banco."
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
                
        # FASE C: Registrar movimientos de Banco no encontrados en el Sistema -> ALERTA ROJA
        for b_idx, b_row in b_rows.iterrows():
            if not b_rows.loc[b_idx, '_matched']:
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
                
        # FASE D: Registrar movimientos de iPago no encontrados en el Banco -> ALERTA AMARILLA
        for s_idx, s_row in s_rows.iterrows():
            if not s_rows.loc[s_idx, '_matched']:
                is_ipago = s_row['_origen'] == 'iPago'
                
                # Agregamos todas al consolidado, pero solo generamos alerta formal para iPago como fue solicitado
                if is_ipago:
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
                        'accion': "Monitorear el estado de cuenta en los próximos cierres bancarios. Confirmar si la transferencia quedó retenida, diferida por horario nocturno, o fue rechazada."
                    }
                    fallas_detectadas.append(falla)
                
                consolidated_records.append({
                    'referencia': ref,
                    'fecha_banco': None,
                    'monto_banco': 0.0,
                    'fecha_sistema': s_row['fecha'],
                    'monto_sistema': s_row['monto'],
                    'origen_sistema': s_row['_origen'],
                    'estatus': 'TRANSACCION EN TRANSITO' if is_ipago else 'NO CONCILIADO (COBRANZAS)',
                    'alerta': 'AMARILLA' if is_ipago else 'GRIS',
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
        
    hay_errores = len(fallas_detectadas) > 0
    
    return hay_errores, fallas_detectadas, df_consolidado
