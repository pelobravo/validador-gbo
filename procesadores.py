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
            'neto': r'neto|neto.*iva|div.*neto',
        }
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            patron = patrones.get(nombre_lower, nombre_lower)
            for col_lower, col_original in columnas_lower.items():
                if re.search(patron, col_lower, re.IGNORECASE):
                    return col_original
        
        # 🔥 CUARTO: Para archivos específicos, buscar por caracteres especiales
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
    def _filtrar_por_fecha(df, fecha_col, dia=15, mes=6, año=2026):
        """
        Filtra un DataFrame por fecha específica.
        
        Args:
            df: DataFrame de pandas
            fecha_col: Nombre de la columna de fecha
            dia: Día a filtrar (default 15)
            mes: Mes a filtrar (default 6)
            año: Año a filtrar (default 2026)
        
        Returns:
            DataFrame: DataFrame filtrado
        """
        if fecha_col is None or fecha_col not in df.columns:
            return df
        
        try:
            fechas = []
            for val in df[fecha_col]:
                try:
                    if isinstance(val, pd.Timestamp):
                        fechas.append(val)
                    elif isinstance(val, str):
                        # Intentar varios formatos
                        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%y', '%d-%m-%y']:
                            try:
                                fechas.append(pd.to_datetime(val, format=fmt))
                                break
                            except:
                                continue
                        else:
                            fechas.append(pd.NaT)
                    else:
                        fechas.append(pd.NaT)
                except:
                    fechas.append(pd.NaT)
            
            # Crear máscara para la fecha específica
            mascara = []
            for f in fechas:
                if pd.notna(f) and f.day == dia and f.month == mes and f.year == año:
                    mascara.append(True)
                else:
                    mascara.append(False)
            
            return df[mascara].copy()
        except Exception as e:
            return df
    
    # ===================== FUNCIONES MODIFICADAS (SOLO ESTAS 4) =====================
    
    @staticmethod
    def procesar_facturacion(df):
        """
        Procesa archivo de facturación (ranking de ventas).
        Busca la fila "Totales:" y extrae el valor de "Div. Neto"
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (facturacion_total, costo_total, cantidad_facturas, promedio_factura)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        facturacion_total = 0.0
        cantidad_facturas = 0
        
        # 🔥 MÉTODO 1: Buscar la fila "Totales:" y extraer "Div. Neto"
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'totales:' in row_str or 'total:' in row_str:
                # Buscar SOLO la columna "Div. Neto" (NO "Facturas")
                for col in df.columns:
                    col_str = str(col).lower().strip()
                    if 'div' in col_str and 'neto' in col_str:
                        try:
                            valor = row[col]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 100:
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
        
        # 🔥 MÉTODO 2: Buscar cualquier columna con valor grande (> 1000) en la fila de totales
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'totales:' in row_str or 'total:' in row_str:
                for col in df.columns:
                    try:
                        valor = row[col]
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num) and num > 1000:
                            facturacion_total = float(num)
                            cantidad_facturas = 1
                            return facturacion_total, 0.0, cantidad_facturas, facturacion_total
                    except:
                        pass
        
        return 0.0, 0.0, 0, 0.0
    
    @staticmethod
    def procesar_cobranzas(df):
        """
        Procesa archivo de cobranzas.
        Busca la columna "Monto Cobranza" y extrae el total
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (total_cobranzas, cantidad_cobranzas, promedio_cobranza)
        """
        if df is None or df.empty:
            return 0.0, 0, 0.0
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 BUSCAR LA FILA DE DATOS
        idx_inicio = 0
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'banco' in row_str and 'cuenta' in row_str and 'fecha cobranza' in row_str:
                idx_inicio = idx + 1
                break
        
        if idx_inicio == 0:
            patrones = ['banco', 'cuenta', 'fecha cobranza']
            idx_inicio = ProcesadorArchivos._encontrar_fila_datos(df, patrones) + 1
        
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
        
        # 🔥 MÉTODO 1: Buscar la fila "Total General:" y la columna "Monto Cobranza"
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'total general:' in row_str:
                for col in df.columns:
                    col_str = str(col).lower().strip()
                    if 'monto cobranza' in col_str:
                        try:
                            valor = row[col]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 100:
                                return float(num), 1, float(num)
                        except:
                            pass
        
        # 🔥 MÉTODO 2: Buscar la columna "Monto Cobranza" y sumar todos los valores
        monto_col = None
        for col in df.columns:
            col_str = str(col).lower().strip()
            if 'monto cobranza' in col_str:
                monto_col = col
                break
        
        if monto_col:
            valores = []
            for val in df[monto_col]:
                num = ProcesadorArchivos._convertir_numero_europeo(val)
                if not pd.isna(num) and num > 0:
                    valores.append(num)
            if valores:
                total = sum(valores)
                if total > 100:
                    return float(total), len(valores), float(total / len(valores))
        
        # 🔥 MÉTODO 3: Buscar cualquier columna numérica con valores grandes (fallback)
        for col in reversed(df.columns):
            try:
                valores = []
                for val in df[col]:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num) and num > 0:
                        valores.append(num)
                if valores and len(valores) > 1:
                    total = sum(valores)
                    if total > 100:
                        return float(total), len(valores), float(total / len(valores))
            except:
                pass
        
        return 0.0, 0, 0.0
    
    @staticmethod
    def procesar_egresos(df):
        """
        Procesa archivo de egresos.
        Separa pagos a proveedores vs gastos.
        FILTRA POR FECHA (solo el día 15).
        TODO lo que NO es proveedor es gasto.
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (pagos_proveedores, pagos_gastos, cantidad_egresos, total_egresos)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 BUSCAR COLUMNA DE FECHA
        fecha_col = None
        for col in df.columns:
            col_str = str(col).lower().strip()
            if 'fecha' in col_str:
                fecha_col = col
                break
        
        # 🔥 FILTRAR POR FECHA (solo día 15 de junio 2026)
        if fecha_col:
            df = ProcesadorArchivos._filtrar_por_fecha(df, fecha_col, dia=15, mes=6, año=2026)
            if df.empty:
                return 0.0, 0.0, 0, 0.0
        
        # Buscar columna de monto
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto', 'valor', 'total', 'importe', 'egreso', 'amount', 
            'pago', 'monto_pago', 'valor_pago', 'debito', 'débito'
        )
        
        # Buscar columna de proveedor/beneficiario
        proveedor_col = ProcesadorArchivos._buscar_columna(
            df, 
            'proveedor', 'beneficiario', 'destinatario', 'descripción', 'concepto'
        )
        
        # Buscar columna de documento/referencia
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_egreso', 'recibo', 'referencia'
        )
        
        # Extraer totales
        total_egresos = 0.0
        pagos_proveedores = 0.0
        pagos_gastos = 0.0
        
        if monto_col and proveedor_col:
            # Extraer valores con el convertidor europeo
            valores = []
            for val in df[monto_col]:
                num = ProcesadorArchivos._convertir_numero_europeo(val)
                if not pd.isna(num) and num > 0:
                    valores.append(num)
                else:
                    valores.append(0.0)
            total_egresos = sum(valores)
            
            # 🔥 Identificar proveedores por nombre
            proveedores = df[proveedor_col].astype(str).str.lower()
            
            # Lista de proveedores conocidos (todos los que deben ir a proveedores)
            lista_proveedores = [
                'oleica', 'oleaginosas industriales',
                'regional de empaques', 'regional empaques',
                'corporacion 2707', 'corporacion monagas', 'corp monagas',
                'molinos nacionales', 'monaca'
            ]
            
            mascara_proveedores = proveedores.str.contains('|'.join(lista_proveedores), na=False, case=False)
            
            pagos_proveedores = sum([valores[i] for i, m in enumerate(mascara_proveedores) if m])
            # 🔥 TODO lo que NO es proveedor es gasto
            pagos_gastos = total_egresos - pagos_proveedores
        
        # Contar egresos
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        return pagos_proveedores, pagos_gastos, cantidad, total_egresos
    
    @staticmethod
    def procesar_estado_cuenta(df, saldo_inicial=0):
        """
        Procesa estado de cuenta bancario.
        FILTRA POR FECHA (solo el día 15).
        
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
        
        # 🔥 BUSCAR COLUMNA DE FECHA
        fecha_col = None
        for col in df.columns:
            col_str = str(col).lower().strip()
            if 'fecha' in col_str:
                fecha_col = col
                break
        
        # 🔥 FILTRAR POR FECHA (solo día 15 de junio 2026)
        if fecha_col:
            df = ProcesadorArchivos._filtrar_por_fecha(df, fecha_col, dia=15, mes=6, año=2026)
            if df.empty:
                return 0.0, 0.0, 0.0, saldo_inicial, 0.0, 0.0
        
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
        
        # 🔥 EXTRAER VALORES CON SOPORTE PARA FORMATO EUROPEO
        total_ingresos = 0.0
        total_egresos = 0.0
        
        if credito_col:
            try:
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
                        if num < 0:
                            valores.append(abs(num))
                        else:
                            valores.append(num)
                total_egresos = sum(valores)
            except:
                total_egresos = 0.0
        
        # Si no encontró valores, intentar buscar por posición
        if total_ingresos == 0 and total_egresos == 0:
            for col in df.columns:
                try:
                    valores = []
                    for val in df[col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num):
                            valores.append(num)
                    if len(valores) > 0:
                        if any(v < 0 for v in valores):
                            total_egresos = sum(abs(v) for v in valores if v < 0)
                        else:
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
        
        # Identificar ingresos identificados
        desc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'descripcion', 'concepto', 'detalle', 'observacion', 'referencia',
            'descripción', 'Descripción'
        )
        
        ingresos_id = 0.0
        ingresos_no_id = 0.0
        
        if credito_col and desc_col and total_ingresos > 0:
            try:
                descripciones = df[desc_col].astype(str).str.lower()
                mascara_id = descripciones.str.contains(
                    'cliente|factura|cobro|venta|pago|abono|recibo|deposito|transf recibida|pago recibido', 
                    na=False, case=False
                )
                if credito_col in df.columns:
                    valores_credito = []
                    for val in df[credito_col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num) and num > 0:
                            valores_credito.append(num)
                        else:
                            valores_credito.append(0.0)
                    ingresos_id = sum([valores_credito[i] for i, m in enumerate(mascara_id) if m])
                ingresos_no_id = total_ingresos - ingresos_id
            except:
                ingresos_id = total_ingresos * 0.7
                ingresos_no_id = total_ingresos * 0.3
        else:
            ingresos_id = total_ingresos * 0.7
            ingresos_no_id = total_ingresos * 0.3
        
        return ingresos_id, ingresos_no_id, total_egresos, saldo_final, total_ingresos, total_egresos
    
    # ===================== FUNCIONES NO MODIFICADAS =====================
    
    @staticmethod
    def procesar_recepciones(df):
        """
        Procesa archivo de recepciones.
        Busca "$ Neto + IVA" y extrae el total correcto (sin duplicar).
        
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
        idx_inicio = 0
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'compra' in row_str and 'proveedor' in row_str and 'f. recepción' in row_str:
                idx_inicio = idx + 1
                break
        
        if idx_inicio == 0:
            patrones = ['compra', 'proveedor', 'f. recepción']
            idx_inicio = ProcesadorArchivos._encontrar_fila_datos(df, patrones) + 1
        
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
        
        total_recepcion = 0.0
        
        # 🔥 BUSCAR LA COLUMNA "$ Neto + IVA" (con diferentes variantes)
        col_neto = None
        for col in df.columns:
            col_str = str(col).strip()
            # Probar diferentes variantes
            if ('$ Neto + IVA' in col_str or 
                'Neto + IVA' in col_str or 
                'neto + iva' in col_str.lower() or
                '$ Neto' in col_str or
                'Neto' in col_str):
                col_neto = col
                break
        
        # Si no encontró, buscar cualquier columna con "neto"
        if col_neto is None:
            for col in df.columns:
                col_str = str(col).lower().strip()
                if 'neto' in col_str:
                    col_neto = col
                    break
        
        # 🔥 Si encontró la columna, buscar el total
        if col_neto:
            # Buscar la fila "Total General:"
            for idx, row in df.iterrows():
                row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                if 'total general:' in row_str:
                    try:
                        valor = row[col_neto]
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num) and num > 0:
                            total_recepcion = float(num)
                            break
                    except:
                        pass
            
            # Si no encontró "Total General:", tomar el primer valor significativo
            if total_recepcion == 0:
                for val in df[col_neto]:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num) and num > 0:
                        total_recepcion = float(num)
                        break
        
        # Si no encontró ninguna columna con "neto", buscar la última columna numérica
        if total_recepcion == 0:
            for col in reversed(df.columns):
                try:
                    for val in df[col]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num) and num > 0:
                            total_recepcion = float(num)
                            break
                    if total_recepcion > 0:
                        break
                except:
                    pass
        
        # Calcular compras a crédito (60% de la recepción por defecto)
        compras_credito = total_recepcion * 0.6
        
        # Buscar columna de tipo para calcular compras a crédito más preciso
        tipo_col = ProcesadorArchivos._buscar_columna(
            df, 
            'tipo_compra', 'compra', 'tipo', 'forma_pago', 'condicion_pago',
            'pago', 'modalidad', 'metodo_pago'
        )
        
        if tipo_col and total_recepcion > 0:
            try:
                tipos = df[tipo_col].astype(str).str.lower()
                mascara_credito = tipos.str.contains('credito|crédito|cred|c/c|plazo|30|60|90|diferido', na=False, case=False)
                if col_neto:
                    valores = []
                    for val in df[col_neto]:
                        num = ProcesadorArchivos._convertir_numero_europeo(val)
                        if not pd.isna(num) and num > 0:
                            valores.append(num)
                        else:
                            valores.append(0.0)
                    compras_credito = sum([valores[i] for i, m in enumerate(mascara_credito) if m])
                else:
                    compras_credito = total_recepcion * 0.6
            except:
                compras_credito = total_recepcion * 0.6
        
        # Contar recepciones
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_recibo', 'recibo', 'factura'
        )
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        # Calcular promedio
        promedio = total_recepcion / cantidad if cantidad > 0 else 0.0
        
        return total_recepcion, compras_credito, cantidad, promedio
    
    @staticmethod
    def procesar_notas_credito(df):
        """
        Procesa notas de crédito.
        
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
    def procesar_costo_facturacion(df):
        """
        Procesa archivo de reporte de utilidad para extraer el costo de facturación.
        Busca "Total General:" y extrae el valor de la columna "Costo"
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            float: Costo total de facturación
        """
        if df is None or df.empty:
            return 0.0
        
        # Limpiar columnas
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 BUSCAR LA FILA "Total General:"
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'total general:' in row_str:
                # Buscar la columna que contiene el costo
                for col in df.columns:
                    try:
                        valor = row[col]
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        # El costo total debe ser un número grande (> 1000)
                        if not pd.isna(num) and num > 1000:
                            return float(num)
                    except:
                        pass
        
        return 0.0
    
    @staticmethod
    def extraer_saldo_reportado(df, tipo):
        """
        Extrae saldo reportado de archivos de verificación.
        
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
                valores = []
                for val in df[saldo_col]:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num):
                        valores.append(num)
                
                if len(valores) == 1:
                    return float(valores[0])
                else:
                    for val in reversed(valores):
                        if val > 0:
                            return float(val)
                    return float(valores[-1]) if valores else None
            except:
                return None
        
        return None
