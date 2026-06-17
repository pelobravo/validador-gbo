# procesadores.py - Versión flexible con búsqueda inteligente de columnas

import pandas as pd
import re
import numpy as np  # 🔥 IMPORTANTE: Agregar esta línea

class ProcesadorArchivos:
    
    @staticmethod
    def _buscar_columna(df, *nombres_posibles):
        """
        Busca una columna por varios nombres posibles (sin importar mayúsculas).
        Retorna el nombre exacto de la columna si la encuentra, o None.
        
        Args:
            df: DataFrame de pandas
            *nombres_posibles: Lista de nombres posibles para buscar
        
        Returns:
            str: Nombre exacto de la columna encontrada, o None
        """
        if df is None or df.empty:
            return None
        
        # Obtener nombres de columnas en minúsculas para comparación
        columnas_lower = {col.lower().strip(): col for col in df.columns}
        
        # Primero buscar coincidencia exacta (ignorando mayúsculas)
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            if nombre_lower in columnas_lower:
                return columnas_lower[nombre_lower]
        
        # Segundo: buscar coincidencia parcial (contiene la palabra)
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            for col_lower, col_original in columnas_lower.items():
                if nombre_lower in col_lower or col_lower in nombre_lower:
                    return col_original
        
        # Tercero: buscar con expresiones regulares (palabras similares)
        patrones = {
            'monto': r'monto|total|importe|valor|amount|factura.*monto',
            'costo': r'costo|coste|costo_venta|coste_venta|costo_merca',
            'saldo': r'saldo|balance|final|saldo_final|saldo_actual',
            'ingreso': r'ingreso|abono|deposito|credito|debe|entrada',
            'egreso': r'egreso|retiro|debito|gasto|haber|salida',
            'tipo': r'tipo|categoria|concepto|descripcion|forma_pago|clasificacion',
            'cliente': r'cliente|client|nombre_cliente|razon_social',
            'proveedor': r'proveedor|prove|nombre_proveedor|beneficiario',
        }
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            patron = patrones.get(nombre_lower, nombre_lower)
            for col_lower, col_original in columnas_lower.items():
                if re.search(patron, col_lower, re.IGNORECASE):
                    return col_original
        
        return None
    
    @staticmethod
    def _extraer_valor(df, columna, *nombres_alternativos):
        """
        Extrae el valor de una columna, probando varios nombres alternativos.
        
        Args:
            df: DataFrame de pandas
            columna: Nombre principal de la columna
            *nombres_alternativos: Nombres alternativos para buscar
        
        Returns:
            float: Suma de los valores en la columna encontrada
        """
        col = ProcesadorArchivos._buscar_columna(df, columna, *nombres_alternativos)
        if col and not df[col].empty:
            try:
                # Limpiar datos y convertir a numérico
                valores = df[col].replace([None, 'None', '', 'NULL'], np.nan)
                valores = pd.to_numeric(valores, errors='coerce').fillna(0)
                return float(valores.sum())
            except:
                return 0.0
        return 0.0
    
    @staticmethod
    def _extraer_valor_por_filtro(df, columna_monto, columna_filtro, valor_filtro, *nombres_alternativos_monto):
        """
        Extrae valores filtrados por una condición.
        
        Args:
            df: DataFrame de pandas
            columna_monto: Nombre de la columna de montos
            columna_filtro: Nombre de la columna para filtrar
            valor_filtro: Valor a buscar en la columna de filtro
            *nombres_alternativos_monto: Nombres alternativos para la columna de montos
        
        Returns:
            float: Suma de los valores filtrados
        """
        monto_col = ProcesadorArchivos._buscar_columna(df, columna_monto, *nombres_alternativos_monto)
        filtro_col = ProcesadorArchivos._buscar_columna(df, columna_filtro, 'tipo', 'categoria', 'concepto', 'descripcion')
        
        if not monto_col:
            return 0.0
        
        try:
            # Limpiar datos
            valores = df[monto_col].replace([None, 'None', '', 'NULL'], np.nan)
            valores = pd.to_numeric(valores, errors='coerce').fillna(0)
            
            if filtro_col:
                # Convertir filtro a string para comparación
                filtro_str = df[filtro_col].astype(str).str.lower()
                mascara = filtro_str.str.contains(valor_filtro, na=False, case=False)
                return float(valores[mascara].sum())
            else:
                return float(valores.sum())
        except:
            return 0.0
    
    @staticmethod
    def procesar_facturacion(df):
        """
        Procesa archivo de facturación.
        
        Busca columnas con nombres similares a:
        - Monto: monto_factura, monto, total, importe, valor, factura_monto, amount
        - Costo: costo_venta, costo, coste, costo_factura, costo_mercancia, cost
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (facturacion_total, costo_total, cantidad_facturas, promedio_factura)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto_factura', 'monto', 'total', 'importe', 'valor', 
            'factura_monto', 'amount', 'precio_total', 'subtotal'
        )
        
        # Buscar columna de costo
        costo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'costo_venta', 'costo', 'coste', 'costo_factura', 
            'costo_mercancia', 'cost', 'costo_unitario', 'costo_total'
        )
        
        # Buscar columna de documento/factura
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'factura', 'doc', 'numero_factura', 'id', 'nro_factura', 'comprobante'
        )
        
        # Extraer valores
        facturacion = ProcesadorArchivos._extraer_valor(df, 'monto_factura', 'monto', 'total', 'importe', 'valor')
        if facturacion == 0 and monto_col:
            try:
                facturacion = float(df[monto_col].replace([None, 'None', ''], 0).sum())
            except:
                facturacion = 0.0
        
        costo = ProcesadorArchivos._extraer_valor(df, 'costo_venta', 'costo', 'coste', 'costo_factura')
        if costo == 0 and costo_col:
            try:
                costo = float(df[costo_col].replace([None, 'None', ''], 0).sum())
            except:
                costo = 0.0
        
        # Contar facturas
        cantidad_facturas = 0
        if doc_col:
            cantidad_facturas = df[doc_col].nunique()
        else:
            cantidad_facturas = len(df)
        
        # Calcular promedio
        promedio = facturacion / cantidad_facturas if cantidad_facturas > 0 else 0.0
        
        return facturacion, costo, cantidad_facturas, promedio
    
    @staticmethod
    def procesar_cobranzas(df):
        """
        Procesa archivo de cobranzas.
        
        Busca columnas con nombres similares a:
        - Monto: monto_cobranza, cobranza, monto, abono, pago, ingreso, valor, amount
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (total_cobranzas, cantidad_cobranzas, promedio_cobranza)
        """
        if df is None or df.empty:
            return 0.0, 0, 0.0
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto_cobranza', 'cobranza', 'monto', 'abono', 'pago', 
            'ingreso', 'valor', 'amount', 'monto_abono', 'monto_pago'
        )
        
        # Buscar columna de documento
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_comprobante', 'codigo'
        )
        
        # Extraer total
        total = ProcesadorArchivos._extraer_valor(df, 'monto_cobranza', 'cobranza', 'monto', 'abono', 'pago')
        if total == 0 and monto_col:
            try:
                total = float(df[monto_col].replace([None, 'None', ''], 0).sum())
            except:
                total = 0.0
        
        # Contar cobranzas
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        # Calcular promedio
        promedio = total / cantidad if cantidad > 0 else 0.0
        
        return total, cantidad, promedio
    
    @staticmethod
    def procesar_recepciones(df):
        """
        Procesa archivo de recepciones.
        
        Busca columnas con nombres similares a:
        - Monto: monto_recepcion, monto, recepcion, total, valor, importe, amount
        - Tipo: tipo_compra, compra, tipo, forma_pago, condicion_pago
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (recepcion_total, compras_credito, cantidad_recepciones, promedio_recepcion)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto_recepcion', 'monto', 'recepcion', 'total', 'valor', 
            'importe', 'amount', 'precio', 'monto_recibido', 'monto_compra'
        )
        
        # Buscar columna de tipo
        tipo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'tipo_compra', 'compra', 'tipo', 'forma_pago', 'condicion_pago',
            'pago', 'modalidad', 'metodo_pago'
        )
        
        # Buscar columna de documento
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_recibo', 'recibo', 'factura'
        )
        
        # Extraer total
        recepcion_total = ProcesadorArchivos._extraer_valor(df, 'monto_recepcion', 'monto', 'recepcion', 'total')
        if recepcion_total == 0 and monto_col:
            try:
                recepcion_total = float(df[monto_col].replace([None, 'None', ''], 0).sum())
            except:
                recepcion_total = 0.0
        
        # Calcular compras a crédito
        compras_credito = 0.0
        if tipo_col and monto_col:
            try:
                tipos = df[tipo_col].astype(str).str.lower()
                mascara_credito = tipos.str.contains('credito|crédito|cred|c/c|plazo|30|60|90|diferido', na=False, case=False)
                compras_credito = float(df.loc[mascara_credito, monto_col].replace([None, 'None', ''], 0).sum())
            except:
                compras_credito = 0.0
        
        # Si no encontró tipo, asumir que el 60% es a crédito (por defecto)
        if compras_credito == 0 and recepcion_total > 0:
            compras_credito = recepcion_total * 0.6
        
        # Contar recepciones
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        # Calcular promedio
        promedio = recepcion_total / cantidad if cantidad > 0 else 0.0
        
        return recepcion_total, compras_credito, cantidad, promedio
    
    @staticmethod
    def procesar_egresos(df):
        """
        Procesa archivo de egresos.
        
        Busca columnas con nombres similares a:
        - Monto: monto, valor, total, importe, egreso, amount
        - Tipo: tipo, categoria, concepto, descripcion, clasificacion
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (pagos_proveedores, pagos_gastos, cantidad_egresos, total_egresos)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto', 'valor', 'total', 'importe', 'egreso', 'amount', 
            'pago', 'monto_pago', 'valor_pago'
        )
        
        # Buscar columna de tipo
        tipo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'tipo', 'categoria', 'concepto', 'descripcion', 'clasificacion',
            'beneficiario', 'destinatario', 'proveedor'
        )
        
        # Buscar columna de documento
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_egreso', 'recibo'
        )
        
        # Extraer totales
        total_egresos = ProcesadorArchivos._extraer_valor(df, 'monto', 'valor', 'total', 'importe')
        if total_egresos == 0 and monto_col:
            try:
                total_egresos = float(df[monto_col].replace([None, 'None', ''], 0).sum())
            except:
                total_egresos = 0.0
        
        # Calcular pagos a proveedores vs gastos
        pagos_proveedores = 0.0
        pagos_gastos = 0.0
        
        if monto_col:
            if tipo_col:
                try:
                    tipos = df[tipo_col].astype(str).str.lower()
                    # Buscar proveedores (compra de mercancía)
                    mascara_proveedores = tipos.str.contains(
                        'proveedor|compra|mercancia|material|insumo|inventario|producto|stock', 
                        na=False, case=False
                    )
                    pagos_proveedores = float(df.loc[mascara_proveedores, monto_col].replace([None, 'None', ''], 0).sum())
                    
                    # Buscar gastos (lo que no es proveedor)
                    mascara_gastos = ~mascara_proveedores & (tipos.str.len() > 0)
                    pagos_gastos = float(df.loc[mascara_gastos, monto_col].replace([None, 'None', ''], 0).sum())
                except:
                    pagos_proveedores = 0.0
                    pagos_gastos = total_egresos
            else:
                # Si no hay columna de tipo, asumir que el 40% es proveedores y 60% gastos
                pagos_proveedores = total_egresos * 0.4
                pagos_gastos = total_egresos * 0.6
        
        # Contar egresos
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        return pagos_proveedores, pagos_gastos, cantidad, total_egresos
    
    @staticmethod
    def procesar_estado_cuenta(df, saldo_inicial=0):
        """
        Procesa estado de cuenta bancario.
        
        Busca columnas con nombres similares a:
        - Ingreso: ingreso, abono, deposito, credito, debe, entrada, monto_ingreso
        - Egreso: egreso, retiro, debito, gasto, haber, salida, monto_egreso
        - Saldo: saldo_final, saldo, balance, saldo_diario, disponible
        
        Args:
            df: DataFrame de pandas
            saldo_inicial: Saldo inicial del día (float)
        
        Returns:
            tuple: (ingresos_id, ingresos_no_id, egresos_bancarios, saldo_final, total_ingresos, total_egresos)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0.0, saldo_inicial, 0.0, 0.0
        
        # Buscar columna de ingresos
        ingreso_col = ProcesadorArchivos._buscar_columna(
            df, 
            'ingreso', 'abono', 'deposito', 'credito', 'debe', 'entrada',
            'monto_ingreso', 'ingresos', 'amount_in', 'recibo', 'cobro'
        )
        
        # Buscar columna de egresos
        egreso_col = ProcesadorArchivos._buscar_columna(
            df, 
            'egreso', 'retiro', 'debito', 'gasto', 'haber', 'salida',
            'monto_egreso', 'egresos', 'amount_out', 'pago', 'cheque'
        )
        
        # Buscar columna de saldo
        saldo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'saldo_final', 'saldo', 'balance', 'saldo_diario', 'disponible',
            'saldo_actual', 'balance_final'
        )
        
        # Buscar columna de fecha
        fecha_col = ProcesadorArchivos._buscar_columna(
            df, 
            'fecha', 'fecha_movimiento', 'fecha_operacion', 'date', 'fecha_aplicacion'
        )
        
        # Extraer valores
        total_ingresos = ProcesadorArchivos._extraer_valor(df, 'ingreso', 'abono', 'deposito', 'credito')
        if total_ingresos == 0 and ingreso_col:
            try:
                total_ingresos = float(df[ingreso_col].replace([None, 'None', ''], 0).sum())
            except:
                total_ingresos = 0.0
        
        total_egresos = ProcesadorArchivos._extraer_valor(df, 'egreso', 'retiro', 'debito', 'gasto')
        if total_egresos == 0 and egreso_col:
            try:
                total_egresos = float(df[egreso_col].replace([None, 'None', ''], 0).sum())
            except:
                total_egresos = 0.0
        
        # Calcular saldo final
        if saldo_col and not df[saldo_col].empty:
            try:
                saldo_final = float(df[saldo_col].replace([None, 'None', ''], np.nan).iloc[-1])
            except:
                saldo_final = saldo_inicial + total_ingresos - total_egresos
        else:
            saldo_final = saldo_inicial + total_ingresos - total_egresos
        
        # Identificar ingresos (simulación - en realidad se necesita conciliación)
        # Si hay columna de descripción, intentar identificar ingresos por concepto
        desc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'descripcion', 'concepto', 'detalle', 'observacion', 'referencia'
        )
        
        ingresos_id = 0.0
        ingresos_no_id = 0.0
        
        if ingreso_col and desc_col:
            try:
                descripciones = df[desc_col].astype(str).str.lower()
                # Ingresos identificados (clientes, facturas, cobros)
                mascara_id = descripciones.str.contains(
                    'cliente|factura|cobro|venta|pago|abono|recibo|deposito', 
                    na=False, case=False
                )
                ingresos_id = float(df.loc[mascara_id & (df[ingreso_col] > 0), ingreso_col].sum())
                ingresos_no_id = total_ingresos - ingresos_id
            except:
                ingresos_id = total_ingresos * 0.7
                ingresos_no_id = total_ingresos * 0.3
        else:
            # Si no hay descripción, asumir 70% identificados, 30% no identificados
            ingresos_id = total_ingresos * 0.7
            ingresos_no_id = total_ingresos * 0.3
        
        return ingresos_id, ingresos_no_id, total_egresos, saldo_final, total_ingresos, total_egresos
    
    @staticmethod
    def procesar_notas_credito(df):
        """
        Procesa notas de crédito.
        
        Busca columnas con nombres similares a:
        - Monto: monto, valor, total, credito, importe, amount, nota_credito
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (total_notas, cantidad_notas, promedio_nota)
        """
        if df is None or df.empty:
            return 0.0, 0, 0.0
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto', 'valor', 'total', 'credito', 'importe', 'amount',
            'nota_credito', 'monto_nota', 'abono'
        )
        
        # Buscar columna de documento
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_nota', 'nota'
        )
        
        # Extraer total
        total = ProcesadorArchivos._extraer_valor(df, 'monto', 'valor', 'total', 'credito')
        if total == 0 and monto_col:
            try:
                total = float(df[monto_col].replace([None, 'None', ''], 0).sum())
            except:
                total = 0.0
        
        # Contar notas
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        # Calcular promedio
        promedio = total / cantidad if cantidad > 0 else 0.0
        
        return total, cantidad, promedio
    
    @staticmethod
    def extraer_saldo_reportado(df, tipo):
        """
        Extrae saldo reportado de archivos de verificación.
        
        Busca columnas con nombres similares a:
        - Saldo: saldo, total, monto, valor, importe, balance
        
        Args:
            df: DataFrame de pandas
            tipo: Tipo de saldo ('cxc', 'cxp', 'inventario', 'bancos')
        
        Returns:
            float: Saldo reportado, o None si no se encuentra
        """
        if df is None or df.empty:
            return None
        
        # Buscar columna de saldo
        saldo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'saldo', 'total', 'monto', 'valor', 'importe', 'balance',
            'saldo_final', 'saldo_actual', 'disponible'
        )
        
        if saldo_col:
            try:
                # Intentar obtener el último valor o la suma
                valores = df[saldo_col].replace([None, 'None', ''], np.nan)
                valores = pd.to_numeric(valores, errors='coerce').fillna(0)
                
                if len(valores) == 1:
                    return float(valores.iloc[0])
                else:
                    # Si hay múltiples filas, buscar la última fila con datos
                    ultimo_valor = valores[valores > 0].iloc[-1] if any(valores > 0) else None
                    if ultimo_valor is not None:
                        return float(ultimo_valor)
                    return float(valores.sum())
            except:
                return None
        
        return None
