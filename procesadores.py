import pandas as pd
import re
import numpy as np
import unicodedata

class ProcesadorArchivos:
    
    @staticmethod
    def _convertir_numero_europeo(valor):
        """Versión robusta combinada"""
        if valor is None or pd.isna(valor):
            return 0.0
        
        if isinstance(valor, (int, float)):
            return float(valor)
        
        valor_str = str(valor).strip().replace('$', '').replace('Bs.', '').replace(' ', '')
        
        if not valor_str or valor_str.lower() in ('nan', 'null', ''):
            return 0.0
        
        try:
            # Lógica inteligente de separadores (del primer código)
            if ',' in valor_str and '.' in valor_str:
                if valor_str.rfind(',') > valor_str.rfind('.'):
                    valor_str = valor_str.replace('.', '').replace(',', '.')
                else:
                    valor_str = valor_str.replace(',', '')
            elif ',' in valor_str:
                valor_str = valor_str.replace(',', '.')
            
            return float(valor_str)
        except:
            # Fallback del segundo código
            try:
                valor_limpio = re.sub(r'[^\d.,-]', '', valor_str)
                if ',' in valor_limpio and '.' in valor_limpio:
                    valor_limpio = valor_limpio.replace('.', '').replace(',', '.')
                elif ',' in valor_limpio:
                    valor_limpio = valor_limpio.replace(',', '.')
                return float(valor_limpio)
            except:
                return 0.0

    @staticmethod
    def _buscar_columna(df, *nombres_posibles):
        """Búsqueda inteligente mejorada"""
        if df is None or df.empty:
            return None
        
        columnas_lower = {str(col).lower().strip(): col for col in df.columns}
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            if nombre_lower in columnas_lower:
                return columnas_lower[nombre_lower]
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            for col_lower, col_original in columnas_lower.items():
                if nombre_lower in col_lower or col_lower in nombre_lower:
                    return col_original
        
        # Búsqueda con regex (del segundo código)
        patrones = {
            'neto': r'div.*neto|neto.*iva|neto',
            'monto': r'monto cobranza|monto|total|importe',
            'credito': r'crédito|credito|ingreso|abono',
            'debito': r'débito|debito|egreso|gasto',
        }
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            patron = patrones.get(nombre_lower, nombre_lower)
            for col_lower, col_original in columnas_lower.items():
                if re.search(patron, col_lower, re.IGNORECASE):
                    return col_original
        return None

    @staticmethod
    def _limpiar_columnas(df):
        if df is not None and not df.empty:
            df.columns = [str(col).strip().replace('\n', ' ').replace('\r', ' ') for col in df.columns]
        return df

    # ===================================================================
    # PROCESAR FACTURACIÓN (Versión robusta por vendedor)
    # ===================================================================
    @staticmethod
    def procesar_facturacion(df):
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_neto = ProcesadorArchivos._buscar_columna(df, 'div. neto', 'neto', 'total')
        col_vendedor = ProcesadorArchivos._buscar_columna(df, 'vendedor', 'nombre', 'asesor')
        
        if not col_neto:
            return 0.0, 0.0, 0, 0.0
            
        facturacion_total = 0.0
        cantidad_facturas = 0
        
        for idx, row in df.iterrows():
            vendedor_str = str(row[col_vendedor] if col_vendedor else row.iloc[0]).strip().lower()
            
            if any(x in vendedor_str for x in ['total', 'vendedor', 'usuario', 'nan', '']):
                continue
                
            val_neto = ProcesadorArchivos._convertir_numero_europeo(row[col_neto])
            if val_neto > 0:
                facturacion_total += val_neto
                cantidad_facturas += 1
        
        promedio = facturacion_total / cantidad_facturas if cantidad_facturas > 0 else 0.0
        return facturacion_total, 0.0, cantidad_facturas, promedio

    # ===================================================================
    # PROCESAR COBRANZAS (Evita subtotales SAP)
    # ===================================================================
    @staticmethod
    def procesar_cobranzas(df):
        if df is None or df.empty:
            return 0.0, 0, 0.0
            
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_monto = ProcesadorArchivos._buscar_columna(df, 'monto cobranza', 'monto')
        col_banco = ProcesadorArchivos._buscar_columna(df, 'banco')
        col_doc = ProcesadorArchivos._buscar_columna(df, '# deposito', 'documento', 'nro')
        
        if not col_monto:
            return 0.0, 0, 0.0
            
        total_cobranzas = 0.0
        cantidad_cobranzas = 0
        
        for idx, row in df.iterrows():
            banco_str = str(row[col_banco] if col_banco else "").strip().lower()
            doc_str = str(row[col_doc] if col_doc else "").strip().lower()
            
            if any(x in banco_str for x in ['total', 'sub', 'usuario', 'banco']):
                continue
            if not doc_str or doc_str == 'nan':
                continue
                
            val_monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto])
            if val_monto > 0:
                total_cobranzas += val_monto
                cantidad_cobranzas += 1
        
        promedio = total_cobranzas / cantidad_cobranzas if cantidad_cobranzas > 0 else 0.0
        return total_cobranzas, cantidad_cobranzas, promedio

    # ===================================================================
    # Resto de funciones (mantengo la mejor versión)
    # ===================================================================
    @staticmethod
    def procesar_recepciones(df):
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_neto = ProcesadorArchivos._buscar_columna(df, '$ neto + iva', 'neto + iva', 'neto')
        if not col_neto:
            return 0.0, 0.0, 0, 0.0
        
        total = 0.0
        for idx, row in df.iterrows():
            primera_celda = str(row.iloc[0]).lower()
            if 'total' in primera_celda or 'compra' in primera_celda:
                continue
            total += ProcesadorArchivos._convertir_numero_europeo(row[col_neto])
        
        return total, total * 0.6, len(df), total / len(df) if len(df) > 0 else 0.0

    @staticmethod
    def procesar_egresos(df):
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        monto_col = ProcesadorArchivos._buscar_columna(df, 'monto', 'total')
        prov_col = ProcesadorArchivos._buscar_columna(df, 'proveedor', 'beneficiario')
        
        if not monto_col:
            return 0.0, 0.0, 0, 0.0
        
        total_egresos = 0.0
        pagos_proveedores = 0.0
        
        for idx, row in df.iterrows():
            val = ProcesadorArchivos._convertir_numero_europeo(row[monto_col])
            total_egresos += val
            if prov_col:
                prov = str(row[prov_col]).lower()
                if any(x in prov for x in ['oleica', 'empaques', 'monagas', 'monaca']):
                    pagos_proveedores += val
        
        return pagos_proveedores, total_egresos - pagos_proveedores, len(df), total_egresos

    @staticmethod
    def procesar_estado_cuenta(df, saldo_inicial=0):
        if df is None or df.empty:
            return 0.0, 0.0, 0.0, saldo_inicial, 0.0, 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        credito_col = ProcesadorArchivos._buscar_columna(df, 'crédito', 'credito')
        debito_col = ProcesadorArchivos._buscar_columna(df, 'débito', 'debito')
        
        t_ing = sum(ProcesadorArchivos._convertir_numero_europeo(x) for x in df[credito_col]) if credito_col else 0.0
        t_egr = sum(abs(ProcesadorArchivos._convertir_numero_europeo(x)) for x in df[debito_col]) if debito_col else 0.0
        
        return t_ing * 0.7, t_ing * 0.3, t_egr, saldo_inicial + t_ing - t_egr, t_ing, t_egr

    @staticmethod
    def procesar_notas_credito(df):
        if df is None or df.empty:
            return 0.0, 0, 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        monto_col = ProcesadorArchivos._buscar_columna(df, 'monto', 'total')
        total = abs(sum(ProcesadorArchivos._convertir_numero_europeo(x) for x in df[monto_col])) if monto_col else 0.0
        n = len(df)
        return total, n, total / n if n > 0 else 0.0

    @staticmethod
    def procesar_costo_facturacion(df):
        if df is None or df.empty:
            return 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        for idx, row in df.iterrows():
            row_str = ' '.join(str(x) for x in row.values if pd.notna(x)).lower()
            if 'total general:' in row_str:
                for col in df.columns:
                    num = ProcesadorArchivos._convertir_numero_europeo(row[col])
                    if num > 1000:
                        return float(num)
        return 0.0

    @staticmethod
    def extraer_saldo_reportado(df, tipo):
        if df is None or df.empty:
            return None
        df = ProcesadorArchivos._limpiar_columnas(df)
        for idx, row in df.iterrows():
            row_str = ' '.join(str(x) for x in row.values if pd.notna(x)).lower()
            if any(x in row_str for x in ['total compañia', 'total compania', 'totales', 'total general:']):
                for col in df.columns:
                    val = ProcesadorArchivos._convertir_numero_europeo(row[col])
                    if val > 0:
                        return float(val)
        return None
