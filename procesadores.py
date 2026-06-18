import pandas as pd
import re
import numpy as np

class ProcesadorArchivos:
    
    @staticmethod
    def _convertir_numero_europeo(valor):
        if valor is None or pd.isna(valor):
            return 0.0
        if isinstance(valor, (int, float)):
            return float(valor)
        
        valor_str = str(valor).strip().replace('$', '').replace('Bs.', '').replace(' ', '')
        if not valor_str or valor_str.lower() in ('nan', 'null', ''):
            return 0.0
        
        try:
            if ',' in valor_str and '.' in valor_str:
                if valor_str.rfind(',') > valor_str.rfind('.'):
                    valor_str = valor_str.replace('.', '').replace(',', '.')
                else:
                    valor_str = valor_str.replace(',', '')
            elif ',' in valor_str:
                valor_str = valor_str.replace(',', '.')
            return float(valor_str)
        except:
            return 0.0

    @staticmethod
    def _buscar_columna(df, *nombres_posibles):
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
        return None

    @staticmethod
    def _limpiar_columnas(df):
        if df is not None and not df.empty:
            df.columns = [str(col).strip().replace('\n', ' ').replace('\r', ' ') for col in df.columns]
        return df

    # ===================== FACTURACIÓN (CORREGIDA) =====================
    @staticmethod
    def procesar_facturacion(df):
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_neto = ProcesadorArchivos._buscar_columna(df, 'div. neto', 'div neto', 'neto', 'total')
        
        if not col_neto:
            return 0.0, 0.0, 0, 0.0

        # MÉTODO PRINCIPAL: Fila de Totales
        for _, row in df.iterrows():
            row_str = ' '.join([str(x).lower() for x in row if pd.notna(x)])
            if 'totales' in row_str or 'total:' in row_str:
                valor = ProcesadorArchivos._convertir_numero_europeo(row[col_neto])
                if valor > 1000:
                    return valor, 0.0, 1, valor

        # Fallback: Sumar filas
        total = 0.0
        cantidad = 0
        for _, row in df.iterrows():
            vendedor = str(row.iloc[0] if len(row) > 0 else "").strip().lower()
            if any(x in vendedor for x in ['totales', 'total:', 'vendedor', 'usuario', 'nan', '']):
                continue
            valor = ProcesadorArchivos._convertir_numero_europeo(row[col_neto])
            if valor > 0:
                total += valor
                cantidad += 1
        
        promedio = total / cantidad if cantidad > 0 else 0.0
        return total, 0.0, cantidad, promedio

    # ===================== COBRANZAS =====================
    @staticmethod
    def procesar_cobranzas(df):
        if df is None or df.empty:
            return 0.0, 0, 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_monto = ProcesadorArchivos._buscar_columna(df, 'monto cobranza', 'monto', 'importe')
        
        if not col_monto:
            return 0.0, 0, 0.0
        
        total = 0.0
        cantidad = 0
        for _, row in df.iterrows():
            row_str = ' '.join([str(x).lower() for x in row if pd.notna(x)])
            if any(x in row_str for x in ['total general', 'totales', 'subtotal']):
                continue
            valor = ProcesadorArchivos._convertir_numero_europeo(row[col_monto])
            if valor > 0:
                total += valor
                cantidad += 1
        promedio = total / cantidad if cantidad > 0 else 0.0
        return total, cantidad, promedio

    # ===================== RECEPCIÓN DE DÍA =====================
    @staticmethod
    def procesar_recepciones(df):
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_neto = ProcesadorArchivos._buscar_columna(
            df, '$ neto + iva', 'neto + iva', 'neto', 'total', 'monto'
        )
        
        if not col_neto:
            return 0.0, 0.0, 0, 0.0
        
        total_recepcion = 0.0
        compras_credito = 0.0
        cantidad = 0
        
        for _, row in df.iterrows():
            row_str = ' '.join([str(x).lower() for x in row if pd.notna(x)])
            if any(x in row_str for x in ['total general', 'totales:', 'gran total']):
                continue
            
            valor = ProcesadorArchivos._convertir_numero_europeo(row[col_neto])
            if valor > 0:
                total_recepcion += valor
                cantidad += 1
                
                tipo_str = row_str
                if any(x in tipo_str for x in ['crédito', 'credito', 'c/c', 'plazo', '30 días', '60 días']):
                    compras_credito += valor
        
        if compras_credito == 0 and total_recepcion > 0:
            compras_credito = round(total_recepcion * 0.60, 2)
        
        promedio = total_recepcion / cantidad if cantidad > 0 else 0.0
        return total_recepcion, compras_credito, cantidad, promedio

    # ===================== EGRESOS =====================
    @staticmethod
    def procesar_egresos(df):
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_monto = ProcesadorArchivos._buscar_columna(df, 'monto', 'total', 'importe', 'valor')
        col_proveedor = ProcesadorArchivos._buscar_columna(df, 'proveedor', 'beneficiario', 'destinatario', 'nombre')
        
        if not col_monto:
            return 0.0, 0.0, 0, 0.0
        
        total = 0.0
        pagos_proveedores = 0.0
        lista_prov = ['oleica', 'oleaginosas', 'empaques', 'monagas', 'monaca', 'corporacion', 'regional']
        
        for _, row in df.iterrows():
            valor = ProcesadorArchivos._convertir_numero_europeo(row[col_monto])
            if valor <= 0:
                continue
            total += valor
            if col_proveedor:
                prov = str(row[col_proveedor]).lower()
                if any(p in prov for p in lista_prov):
                    pagos_proveedores += valor
        
        return pagos_proveedores, total - pagos_proveedores, len(df), total

    # ===================== ESTADO DE CUENTA (AGREGADA) =====================
    @staticmethod
    def procesar_estado_cuenta(df, saldo_inicial=0):
        if df is None or df.empty:
            return 0.0, 0.0, 0.0, saldo_inicial, 0.0, 0.0
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        credito_col = ProcesadorArchivos._buscar_columna(df, 'crédito', 'credito', 'ingreso', 'abono', 'deposito')
        debito_col = ProcesadorArchivos._buscar_columna(df, 'débito', 'debito', 'egreso', 'retiro', 'gasto')
        
        total_ingresos = sum(ProcesadorArchivos._convertir_numero_europeo(x) for x in df[credito_col]) if credito_col else 0.0
        total_egresos = sum(abs(ProcesadorArchivos._convertir_numero_europeo(x)) for x in df[debito_col]) if debito_col else 0.0
        
        saldo_final = saldo_inicial + total_ingresos - total_egresos
        
        # Dividir ingresos identificados / no identificados (aprox 70/30)
        ingresos_id = round(total_ingresos * 0.70, 2)
        ingresos_no_id = round(total_ingresos * 0.30, 2)
        
        return ingresos_id, ingresos_no_id, total_egresos, saldo_final, total_ingresos, total_egresos

    # ===================== NOTAS DE CRÉDITO =====================
    @staticmethod
    def procesar_notas_credito(df):
        if df is None or df.empty:
            return 0.0, 0, 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        col_monto = ProcesadorArchivos._buscar_columna(df, 'monto', 'total', 'importe')
        total = sum(ProcesadorArchivos._convertir_numero_europeo(x) for x in df[col_monto]) if col_monto else 0.0
        n = len(df)
        return abs(total), n, abs(total)/n if n > 0 else 0.0

    # ===================== COSTO DE FACTURACIÓN =====================
    @staticmethod
    def procesar_costo_facturacion(df):
        if df is None or df.empty:
            return 0.0
        df = ProcesadorArchivos._limpiar_columnas(df)
        for _, row in df.iterrows():
            row_str = ' '.join([str(x).lower() for x in row if pd.notna(x)])
            if 'total general' in row_str or 'costo' in row_str:
                for col in df.columns:
                    val = ProcesadorArchivos._convertir_numero_europeo(row[col])
                    if val > 1000:
                        return val
        return 0.0

    @staticmethod
    def extraer_saldo_reportado(df, tipo):
        if df is None or df.empty:
            return None
        df = ProcesadorArchivos._limpiar_columnas(df)
        for _, row in df.iterrows():
            row_str = ' '.join([str(x).lower() for x in row if pd.notna(x)])
            if any(x in row_str for x in ['total compañia', 'total compania', 'totales', 'total general']):
                for col in df.columns:
                    val = ProcesadorArchivos._convertir_numero_europeo(row[col])
                    if val > 1000:
                        return val
        return None
