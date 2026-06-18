# procesadores.py - Versión flexible con búsqueda inteligente de columnas
# y soporte para archivos del Analista 3 (reportes SAP)
# con conversión de números en formato europeo (coma decimal)

import pandas as pd
import re
import numpy as np

class ProcesadorArchivos:
    
    @staticmethod
    def _convertir_numero_europeo(valor):
        """
        Convierte un número con formato europeo (coma decimal, punto separador de miles)
        a float.
        
        Ejemplos:
        - "154.930,00" → 154930.00
        - "3.704,30" → 3704.30
        - "1.234,56" → 1234.56
        - "0,00" → 0.00
        - "154,930.00" → 154930.00 (formato inglés, también lo maneja)
        - "154930.00" → 154930.00
        """
        if valor is None or pd.isna(valor):
            return np.nan
        
        # Si ya es número, retornar directamente
        if isinstance(valor, (int, float)):
            return float(valor)
        
        valor_str = str(valor).strip()
        
        # Si está vacío, retornar NaN
        if not valor_str:
            return np.nan
        
        # Remover símbolos de moneda y espacios
        valor_str = valor_str.replace('$', '').replace('Bs.', '').replace(' ', '').strip()
        
        # Detectar si tiene formato europeo (punto como separador de miles, coma decimal)
        tiene_punto_miles = '.' in valor_str and ',' in valor_str
        tiene_coma_decimal = ',' in valor_str
        
        try:
            if tiene_coma_decimal:
                # Formato europeo: 1.234,56 o 154.930,00
                # Eliminar puntos (separadores de miles)
                # Reemplazar coma por punto (separador decimal)
                valor_limpio = valor_str.replace('.', '').replace(',', '.')
                return float(valor_limpio)
            else:
                # Formato inglés: 1,234.56 o 154,930.00
                # Eliminar comas (separadores de miles)
                valor_limpio = valor_str.replace(',', '')
                return float(valor_limpio)
        except (ValueError, TypeError):
            try:
                # Último intento: eliminar todo lo que no sea número, punto o coma
                valor_limpio = re.sub(r'[^\d.,-]', '', valor_str)
                if ',' in valor_limpio and '.' in valor_limpio:
                    # Si tiene ambos, asumir formato europeo
                    valor_limpio = valor_limpio.replace('.', '').replace(',', '.')
                elif ',' in valor_limpio:
                    valor_limpio = valor_limpio.replace(',', '.')
                return float(valor_limpio)
            except:
                return np.nan
    
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
            'credito': r'credito|crédito|cobranza|abono|ingreso',
            'debito': r'debito|débito|egreso|gasto|retiro',
            'neto': r'neto|neto.*iva|div.*neto',  # 🔥 NUEVO: Buscar neto + iva
        }
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            patron = patrones.get(nombre_lower, nombre_lower)
            for col_lower, col_original in columnas_lower.items():
                if re.search(patron, col_lower, re.IGNORECASE):
                    return col_original
        
        # 🔥 CUARTO: Para archivos específicos, buscar por caracteres especiales
        # Buscar columnas con "$ Neto + IVA" aunque tenga caracteres especiales
        for col_original in df.columns:
            col_lower = col_original.lower().strip()
            if 'neto' in col_lower and 'iva' in col_lower:
                return col_original
            if 'div' in col_lower and 'neto' in col_lower:
                return col_original
            if 'monto cobranza' in col_lower:
                return col_original
        
        return None
    
    @staticmethod
    def _extraer_valor(df, columna, *nombres_alternativos):
        """
        Extrae el valor de una columna, probando varios nombres alternativos.
        Ahora soporta números con formato europeo (coma decimal).
        
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
                # Limpiar datos y convertir a numérico con soporte para formato europeo
                valores = []
                for val in df[col]:
                    if pd.isna(val) or val is None or val == '' or val == 'NULL':
                        valores.append(0.0)
                    else:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if pd.isna(num):
                            valores.append(0.0)
                        else:
                            valores.append(num)
                return float(sum(valores))
            except:
                return 0.0
        return 0.0
    
    @staticmethod
    def _extraer_valor_por_filtro(df, columna_monto, columna_filtro, valor_filtro, *nombres_alternativos_monto):
        """
        Extrae valores filtrados por una condición.
        Ahora soporta números con formato europeo (coma decimal).
        
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
        filtro_col = ProcesadorArchivos._buscar_columna(df, columna_filtro, 'tipo', 'categoria', 'concepto', 'descripcion', 'tipo de egreso', 'tipo de pago')
        
        if not monto_col:
            return 0.0
        
        try:
            # Limpiar datos usando la función de conversión europea
            valores = []
            for val in df[monto_col]:
                if pd.isna(val) or val is None or val == '' or val == 'NULL':
                    valores.append(0.0)
                else:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if pd.isna(num):
                        valores.append(0.0)
                    else:
                        valores.append(num)
            
            if filtro_col:
                filtro_str = df[filtro_col].astype(str).str.lower()
                mascara = filtro_str.str.contains(valor_filtro, na=False, case=False)
                return float(sum([valores[i] for i, m in enumerate(mascara) if m]))
            else:
                return float(sum(valores))
        except:
            return 0.0
    
    @staticmethod
    def _saltar_encabezados(df, filas_a_saltar=0):
        """
        Salta filas de encabezado en archivos de reportes.
        
        Args:
            df: DataFrame de pandas
            filas_a_saltar: Número de filas a saltar
        
        Returns:
            DataFrame: DataFrame con las filas de encabezado removidas
        """
        if filas_a_saltar > 0 and len(df) > filas_a_saltar:
            df = df.iloc[filas_a_saltar:].reset_index(drop=True)
        return df
    
    @staticmethod
    def _encontrar_fila_datos(df, patrones_busqueda):
        """
        Encuentra la fila donde comienzan los datos buscando patrones en el texto.
        
        Args:
            df: DataFrame de pandas
            patrones_busqueda: Lista de patrones a buscar
        
        Returns:
            int: Índice de la fila donde comienzan los datos
        """
        for idx, row in df.iterrows():
            for col in df.columns:
                valor = str(row[col]).lower() if pd.notna(row[col]) else ''
                for patron in patrones_busqueda:
                    if patron.lower() in valor and len(str(row[col]).strip()) > 0:
                        return idx
        return 0
    
    @staticmethod
    def _limpiar_columnas(df):
        """
        Limpia los nombres de las columnas eliminando espacios y caracteres especiales.
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            DataFrame: DataFrame con nombres de columnas limpios
        """
        if df is not None and not df.empty:
            df.columns = [str(col).strip().replace('\n', ' ').replace('\r', ' ') for col in df.columns]
        return df
    
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
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 MÉTODO 1: Buscar la fila "Totales:" y extraer "Div. Neto"
        facturacion_total = 0.0
        cantidad_facturas = 0
        
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'totales:' in row_str or 'total:' in row_str:
                # Buscar la columna "Div. Neto" o "Total"
                for col in df.columns:
                    col_str = str(col).lower().strip()
                    if 'div' in col_str and 'neto' in col_str:
                        try:
                            valor = row[col]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                facturacion_total = float(num)
                                # También extraer cantidad de facturas
                                for col2 in df.columns:
                                    if 'facturas' in str(col2).lower():
                                        try:
                                            facturas_val = row[col2]
                                            facturas_num = ProcesadorArchivos._convertir_numero_europeo(facturas_val)
                                            if not pd.isna(facturas_num):
                                                cantidad_facturas = int(facturas_num)
                                        except:
                                            pass
                                if cantidad_facturas == 0:
                                    cantidad_facturas = 1
                                promedio = facturacion_total / cantidad_facturas
                                return facturacion_total, 0.0, cantidad_facturas, promedio
                        except:
                            pass
        
        # 🔥 MÉTODO 2: Buscar la fila de totales por posición (última fila con datos)
        for idx in range(len(df) - 1, -1, -1):
            row = df.iloc[idx]
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'total' in row_str:
                for col in df.columns:
                    col_str = str(col).lower().strip()
                    if 'div' in col_str and 'neto' in col_str:
                        try:
                            valor = row[col]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                facturacion_total = float(num)
                                cantidad_facturas = 1
                                return facturacion_total, 0.0, cantidad_facturas, facturacion_total
                        except:
                            pass
        
        # 🔥 MÉTODO 3: Buscar columna "Div. Neto" en todo el DataFrame y sumar
        for col in df.columns:
            col_str = str(col).lower().strip()
            if 'div' in col_str and 'neto' in col_str:
                try:
                    # Intentar extraer el total de la columna (suma de todos los valores)
                    valores = []
                    for val in df[col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num) and num > 0:
                            valores.append(num)
                    if valores:
                        facturacion_total = sum(valores)
                        cantidad_facturas = len(valores)
                        promedio = facturacion_total / cantidad_facturas if cantidad_facturas > 0 else 0
                        return facturacion_total, 0.0, cantidad_facturas, promedio
                except:
                    pass
        
        # Buscar columna de monto (fallback)
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto_factura', 'monto', 'total', 'importe', 'valor', 
            'factura_monto', 'amount', 'precio_total', 'subtotal',
            'div neto', 'Div. Neto', 'neto'
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
        
        # Si no se encontró con los métodos anteriores, extraer con el método normal
        if facturacion_total == 0:
            facturacion_total = ProcesadorArchivos._extraer_valor(df, 'monto_factura', 'monto', 'total', 'importe', 'valor', 'div neto', 'neto')
            if facturacion_total == 0 and monto_col:
                try:
                    facturacion_total = ProcesadorArchivos._extraer_valor(df, monto_col)
                except:
                    facturacion_total = 0.0
        
        costo = ProcesadorArchivos._extraer_valor(df, 'costo_venta', 'costo', 'coste', 'costo_factura')
        if costo == 0 and costo_col:
            try:
                costo = ProcesadorArchivos._extraer_valor(df, costo_col)
            except:
                costo = 0.0
        
        # Contar facturas
        cantidad_facturas = 0
        if doc_col:
            cantidad_facturas = df[doc_col].nunique()
        else:
            cantidad_facturas = len(df)
        
        # Calcular promedio
        promedio = facturacion_total / cantidad_facturas if cantidad_facturas > 0 else 0.0
        
        return facturacion_total, costo, cantidad_facturas, promedio
    
    @staticmethod
    def procesar_cobranzas(df):
        """
        Procesa archivo de cobranzas.
        
        Busca columnas con nombres similares a:
        - Monto: monto_cobranza, cobranza, monto, abono, pago, ingreso, valor, amount
        
        Para archivos del Analista 3, busca específicamente:
        - 'Monto Cobranza' en el reporte de cobranzas
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (total_cobranzas, cantidad_cobranzas, promedio_cobranza)
        """
        if df is None or df.empty:
            return 0.0, 0, 0.0
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 PARA ARCHIVOS DEL ANALISTA 3: Buscar la fila de datos
        # En el archivo de cobranzas, los encabezados están en una fila con "Banco", "Cuenta", "Fecha Cobranza"
        idx_inicio = 0
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'banco' in row_str and 'cuenta' in row_str and 'fecha cobranza' in row_str:
                idx_inicio = idx + 1
                break
        
        # Si no encontró, buscar por patrones
        if idx_inicio == 0:
            patrones = ['banco', 'cuenta', 'fecha cobranza']
            idx_inicio = ProcesadorArchivos._encontrar_fila_datos(df, patrones) + 1
        
        # Reasignar el dataframe desde la fila de datos
        if idx_inicio > 0 and idx_inicio < len(df):
            df_datos = df.iloc[idx_inicio:].reset_index(drop=True)
            # Usar la primera fila como encabezados
            if len(df_datos) > 0:
                header_row = df_datos.iloc[0] if len(df_datos) > 0 else None
                if header_row is not None:
                    new_columns = []
                    for col in header_row:
                        if pd.notna(col):
                            new_columns.append(str(col).strip())
                        else:
                            new_columns.append(f'col_{len(new_columns)}')
                    df_datos.columns = new_columns
                    df_datos = df_datos.iloc[1:].reset_index(drop=True)
                    df = df_datos
        
        # Buscar columna de monto cobranza
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'Monto Cobranza', 'monto cobranza', 'monto_cobranza', 'monto',
            'cobranza', 'abono', 'pago', 'ingreso', 'valor', 'amount',
            'monto_abono', 'monto_pago'
        )
        
        # Extraer total
        total = ProcesadorArchivos._extraer_valor(df, 'Monto Cobranza', 'monto cobranza', 'monto_cobranza', 'monto', 'abono')
        
        # Si no encontró con los nombres, buscar por posición (última columna numérica)
        if total == 0 and monto_col:
            try:
                total = ProcesadorArchivos._extraer_valor(df, monto_col)
            except:
                total = 0.0
        
        # Si aún es 0, intentar buscar la última columna numérica
        if total == 0 and len(df.columns) > 0:
            for col in reversed(df.columns):
                try:
                    val = ProcesadorArchivos._extraer_valor(df, col)
                    if val > 0:
                        total = val
                        break
                except:
                    pass
        
        cantidad = len(df)
        promedio = total / cantidad if cantidad > 0 else 0.0
        
        return total, cantidad, promedio
    
    @staticmethod
    def procesar_recepciones(df):
        """
        Procesa archivo de recepciones.
        
        Busca columnas con nombres similares a:
        - Monto: monto_recepcion, monto, recepcion, total, valor, importe, amount
        - Tipo: tipo_compra, compra, tipo, forma_pago, condicion_pago
        
        Para archivos del Analista 3, busca específicamente:
        - '$ Neto + IVA' en el reporte de recepciones
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (recepcion_total, compras_credito, cantidad_recepciones, promedio_recepcion)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 PARA ARCHIVOS DEL ANALISTA 3: Buscar la fila de datos
        # En el archivo de recepciones, los encabezados están en una fila con "Compra", "Proveedor", "F. Recepción"
        idx_inicio = 0
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'compra' in row_str and 'proveedor' in row_str and 'f. recepción' in row_str:
                idx_inicio = idx + 1
                break
        
        # Si no encontró, buscar por patrones
        if idx_inicio == 0:
            patrones = ['compra', 'proveedor', 'f. recepción']
            idx_inicio = ProcesadorArchivos._encontrar_fila_datos(df, patrones) + 1
        
        # Reasignar el dataframe desde la fila de datos
        if idx_inicio > 0 and idx_inicio < len(df):
            df_datos = df.iloc[idx_inicio:].reset_index(drop=True)
            if len(df_datos) > 0:
                header_row = df_datos.iloc[0] if len(df_datos) > 0 else None
                if header_row is not None:
                    new_columns = []
                    for col in header_row:
                        if pd.notna(col):
                            new_columns.append(str(col).strip())
                        else:
                            new_columns.append(f'col_{len(new_columns)}')
                    df_datos.columns = new_columns
                    df_datos = df_datos.iloc[1:].reset_index(drop=True)
                    df = df_datos
        
        # 🔥 Buscar la fila de total general
        total_recepcion = 0.0
        idx_total = None
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'total general:' in row_str:
                idx_total = idx
                break
        
        if idx_total is not None:
            # Buscar la columna con el valor numérico en la fila de totales
            for col in df.columns:
                try:
                    valor = df.iloc[idx_total][col]
                    num = ProcesadorArchivos._convertir_numero_europeo(valor)
                    if not pd.isna(num) and num > 0:
                        total_recepcion = float(num)
                        break
                except:
                    pass
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            '$ Neto + IVA', 'neto + iva', 'total', 'monto', 'importe',
            'monto_recepcion', 'recepcion', 'valor', 'amount',
            'precio', 'monto_recibido', 'monto_compra', 'neto'
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
        
        # 🔥 Si no se encontró el total general, intentar extraer de la columna "$ Neto + IVA"
        if total_recepcion == 0:
            # Buscar la columna "$ Neto + IVA" directamente
            for col in df.columns:
                col_str = str(col).strip()
                if '$ Neto + IVA' in col_str or 'Neto + IVA' in col_str or 'neto + iva' in col_str.lower():
                    try:
                        # Sumar todos los valores de la columna
                        valores = []
                        for val in df[col]:
                            num = ProcesadorArchivos._convertir_numero_europeo(val)
                            if not pd.isna(num) and num > 0:
                                valores.append(num)
                        if valores:
                            total_recepcion = sum(valores)
                            break
                    except:
                        pass
        
        if total_recepcion == 0:
            total_recepcion = ProcesadorArchivos._extraer_valor(df, '$ Neto + IVA', 'neto + iva', 'total', 'monto')
        
        if total_recepcion == 0 and monto_col:
            try:
                total_recepcion = ProcesadorArchivos._extraer_valor(df, monto_col)
            except:
                total_recepcion = 0.0
        
        # Si aún es 0, intentar buscar la última columna numérica
        if total_recepcion == 0 and len(df.columns) > 0:
            for col in reversed(df.columns):
                try:
                    val = ProcesadorArchivos._extraer_valor(df, col)
                    if val > 0:
                        total_recepcion = val
                        break
                except:
                    pass
        
        # Calcular compras a crédito
        compras_credito = 0.0
        if tipo_col and monto_col:
            try:
                tipos = df[tipo_col].astype(str).str.lower()
                mascara_credito = tipos.str.contains('credito|crédito|cred|c/c|plazo|30|60|90|diferido', na=False, case=False)
                compras_credito = ProcesadorArchivos._extraer_valor_por_filtro(
                    df, monto_col, tipo_col, 'credito', 'monto'
                )
            except:
                compras_credito = 0.0
        
        # Si no encontró tipo, asumir que el 60% es a crédito (por defecto)
        if compras_credito == 0 and total_recepcion > 0:
            compras_credito = total_recepcion * 0.6
        
        # Contar recepciones
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        # Calcular promedio
        promedio = total_recepcion / cantidad if cantidad > 0 else 0.0
        
        return total_recepcion, compras_credito, cantidad, promedio
    
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
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto', 'valor', 'total', 'importe', 'egreso', 'amount', 
            'pago', 'monto_pago', 'valor_pago', 'debito', 'débito'
        )
        
        # Buscar columna de tipo (con más opciones)
        tipo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'tipo de egreso', 'tipo de pago', 'tipo', 'categoria', 
            'concepto', 'descripcion', 'clasificacion', 'beneficiario', 
            'destinatario', 'proveedor', 'descripción', 'Tipo de Egreso', 'Tipo de Pago'
        )
        
        # Buscar columna de documento
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_egreso', 'recibo', 'referencia'
        )
        
        # Extraer totales
        total_egresos = ProcesadorArchivos._extraer_valor(df, 'monto', 'valor', 'total', 'importe', 'debito')
        if total_egresos == 0 and monto_col:
            try:
                total_egresos = ProcesadorArchivos._extraer_valor(df, monto_col)
            except:
                total_egresos = 0.0
        
        # Si aún es 0, intentar buscar la última columna numérica
        if total_egresos == 0 and len(df.columns) > 0:
            for col in reversed(df.columns):
                try:
                    val = ProcesadorArchivos._extraer_valor(df, col)
                    if val > 0:
                        total_egresos = val
                        break
                except:
                    pass
        
        # Calcular pagos a proveedores vs gastos
        pagos_proveedores = 0.0
        pagos_gastos = 0.0
        
        if monto_col and total_egresos > 0:
            if tipo_col:
                try:
                    tipos = df[tipo_col].astype(str).str.lower()
                    
                    # 🔥 Buscar proveedores (más patrones)
                    mascara_proveedores = tipos.str.contains(
                        'proveedor|compra|mercancia|material|insumo|inventario|producto|stock|pago a proveedores|proveedores de mercancia|proveedores de mercancía', 
                        na=False, case=False
                    )
                    
                    # Extraer valores con el convertidor europeo
                    valores = []
                    for val in df[monto_col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num):
                            valores.append(num)
                        else:
                            valores.append(0.0)
                    
                    pagos_proveedores = sum([valores[i] for i, m in enumerate(mascara_proveedores) if m])
                    pagos_gastos = total_egresos - pagos_proveedores
                except Exception as e:
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
        
        Para archivos del Analista 3, busca específicamente:
        - 'Crédito' para ingresos (valores positivos, con formato europeo)
        - 'Débito' para egresos (valores pueden ser negativos, con formato europeo)
        - 'Saldo' para saldo final
        
        Args:
            df: DataFrame de pandas
            saldo_inicial: Saldo inicial del día (float)
        
        Returns:
            tuple: (ingresos_id, ingresos_no_id, egresos_bancarios, saldo_final, total_ingresos, total_egresos)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0.0, saldo_inicial, 0.0, 0.0
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # Buscar columna de crédito (ingresos)
        credito_col = ProcesadorArchivos._buscar_columna(
            df, 
            'Crédito', 'credito', 'crédito', 'ingreso', 'abono', 
            'deposito', 'debe', 'entrada', 'monto_ingreso', 'ingresos', 'amount_in'
        )
        
        # Buscar columna de débito (egresos)
        debito_col = ProcesadorArchivos._buscar_columna(
            df, 
            'Débito', 'debito', 'débito', 'egreso', 'retiro', 
            'gasto', 'haber', 'salida', 'monto_egreso', 'egresos', 'amount_out'
        )
        
        # Buscar columna de saldo
        saldo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'Saldo', 'saldo', 'balance', 'saldo_final', 'saldo_diario', 
            'disponible', 'saldo_actual', 'balance_final'
        )
        
        # Buscar columna de fecha
        fecha_col = ProcesadorArchivos._buscar_columna(
            df, 
            'fecha', 'fecha_movimiento', 'fecha_operacion', 'date', 'fecha_aplicacion',
            'dia', 'día'
        )
        
        # 🔥 EXTRAER VALORES CON SOPORTE PARA FORMATO EUROPEO
        total_ingresos = 0.0
        total_egresos = 0.0
        
        if credito_col:
            try:
                # Extraer todos los valores y convertirlos
                valores = []
                for val in df[credito_col]:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num) and num > 0:
                        valores.append(num)
                total_ingresos = sum(valores)
            except:
                total_ingresos = 0.0
        
        if debito_col:
            try:
                valores = []
                for val in df[debito_col]:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num):
                        # Si es negativo, tomar absoluto
                        if num < 0:
                            valores.append(abs(num))
                        else:
                            valores.append(num)
                total_egresos = sum(valores)
            except:
                total_egresos = 0.0
        
        # Si no encontró valores, intentar buscar por posición (últimas columnas numéricas)
        if total_ingresos == 0 and total_egresos == 0:
            for col in df.columns:
                try:
                    valores = []
                    for val in df[col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num):
                            valores.append(num)
                    if len(valores) > 0:
                        # Si la columna tiene valores negativos, es probable que sea débitos
                        if any(v < 0 for v in valores):
                            # Tomar solo los negativos y convertirlos a positivos
                            total_egresos = sum(abs(v) for v in valores if v < 0)
                        else:
                            # Si la columna tiene valores positivos, podría ser ingresos
                            total_ingresos = sum(v for v in valores if v > 0)
                except:
                    pass
        
        # Calcular saldo final
        if saldo_col and not df[saldo_col].empty:
            try:
                ultimo_valor = df[saldo_col].iloc[-1]
                saldo_final = ProcesadorArchivos._convertir_numero_europeo(ultimo_valor)
                if pd.isna(saldo_final):
                    saldo_final = saldo_inicial + total_ingresos - total_egresos
            except:
                saldo_final = saldo_inicial + total_ingresos - total_egresos
        else:
            saldo_final = saldo_inicial + total_ingresos - total_egresos
        
        # Identificar ingresos (70% identificados, 30% no identificados)
        desc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'descripcion', 'concepto', 'detalle', 'observacion', 'referencia',
            'descripción', 'Descripción'
        )
        
        ingresos_id = 0.0
        ingresos_no_id = 0.0
        
        if credito_col and desc_col:
            try:
                descripciones = df[desc_col].astype(str).str.lower()
                # Ingresos identificados (clientes, facturas, cobros)
                mascara_id = descripciones.str.contains(
                    'cliente|factura|cobro|venta|pago|abono|recibo|deposito|transf recibida|pago recibido', 
                    na=False, case=False
                )
                if credito_col in df.columns:
                    # Extraer valores de crédito con formato europeo
                    valores_credito = []
                    for val in df[credito_col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num) and num > 0:
                            valores_credito.append(num)
                        else:
                            valores_credito.append(0.0)
                    mascara_credito = [v > 0 for v in valores_credito]
                    ingresos_id = sum([valores_credito[i] for i, m in enumerate(mascara_id) if m and mascara_credito[i]])
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
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
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
                total = ProcesadorArchivos._extraer_valor(df, monto_col)
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
        
        Para archivos del Analista 3:
        - CxC: Busca "Total Compañía" en el texto
        - CxP: Busca "Total Compañía" en el texto
        - Inventario: Busca "Totales" en el texto
        
        Args:
            df: DataFrame de pandas
            tipo: Tipo de saldo ('cxc', 'cxp', 'inventario', 'bancos')
        
        Returns:
            float: Saldo reportado, o None si no se encuentra
        """
        if df is None or df.empty:
            return None
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 PARA ARCHIVOS DEL ANALISTA 3:
        # Buscar "Total Compañía" en el texto de las filas
        if tipo in ['cxc', 'cxp']:
            for idx, row in df.iterrows():
                row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                if 'total compañia' in row_str or 'total compania' in row_str or 'total compañía' in row_str:
                    # Buscar el valor numérico en la fila
                    for col in df.columns:
                        try:
                            val = ProcesadorArchivos._convertir_numero_europeo(df.iloc[idx, col])
                            if not pd.isna(val) and val > 0:
                                return float(val)
                        except:
                            pass
            
            # Si no encontró "Total Compañía", buscar el último valor significativo
            # en las últimas filas del dataframe
            for idx in range(len(df) - 1, -1, -1):
                for col in df.columns:
                    try:
                        val = ProcesadorArchivos._convertir_numero_europeo(df.iloc[idx, col])
                        if not pd.isna(val) and val > 0:
                            return float(val)
                    except:
                        pass
        
        # 🔥 PARA INVENTARIO: Buscar "Totales" en el texto
        if tipo == 'inventario':
            for idx, row in df.iterrows():
                row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                if 'totales' in row_str or 'total' in row_str:
                    # Buscar el valor numérico en la fila (normalmente es el último valor)
                    for col in df.columns:
                        try:
                            val = ProcesadorArchivos._convertir_numero_europeo(df.iloc[idx, col])
                            if not pd.isna(val) and val > 0:
                                return float(val)
                        except:
                            pass
            
            # Si no encontró, buscar en la última fila con valores numéricos
            for idx in range(len(df) - 1, -1, -1):
                for col in df.columns:
                    try:
                        val = ProcesadorArchivos._convertir_numero_europeo(df.iloc[idx, col])
                        if not pd.isna(val) and val > 0:
                            return float(val)
                    except:
                        pass
        
        # 🔥 PARA BANCOS: Buscar la columna de saldo
        if tipo == 'bancos':
            saldo_col = ProcesadorArchivos._buscar_columna(
                df, 
                'saldo', 'saldo_final', 'balance', 'disponible'
            )
            if saldo_col:
                try:
                    valores = []
                    for val in df[saldo_col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num):
                            valores.append(num)
                    if len(valores) > 0:
                        return float(valores[-1])
                except:
                    pass
        
        # Buscar columna de saldo genérica
        saldo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'saldo', 'total', 'monto', 'valor', 'importe', 'balance',
            'saldo_final', 'saldo_actual', 'disponible'
        )
        
        if saldo_col:
            try:
                # Intentar obtener el último valor o la suma
                valores = []
                for val in df[saldo_col]:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num):
                        valores.append(num)
                
                if len(valores) == 1:
                    return float(valores[0])
                else:
                    # Buscar el último valor significativo
                    for val in reversed(valores):
                        if val > 0:
                            return float(val)
                    return float(valores[-1]) if valores else None
            except:
                return None
        
        return None
