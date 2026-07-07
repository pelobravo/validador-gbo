# procesadores.py - Versión flexible con búsqueda inteligente de columnas
# y soporte para archivos del Analista 3 (reportes SAP)
# con conversión de números en formato europeo (coma decimal)

import pandas as pd
import re
import numpy as np

class ProcesadorArchivos:
    
    @staticmethod
    def _convertir_numero_europeo(valor):
        if valor is None or pd.isna(valor):
            return np.nan

        if isinstance(valor, (int, float)):
            return float(valor)

        valor_str = str(valor).strip()

        if not valor_str:
            return np.nan

        valor_str = (
            valor_str.replace('$', '')
            .replace('Bs.', '')
            .replace(' ', '')
            .strip()
        )

        try:
            # FORMATO AMERICANO
            # 409,856.24
            if ',' in valor_str and '.' in valor_str:
                if valor_str.rfind('.') > valor_str.rfind(','):
                    valor_limpio = valor_str.replace(',', '')
                    return float(valor_limpio)
                else:
                    valor_limpio = valor_str.replace('.', '').replace(',', '.')
                    return float(valor_limpio)

            # FORMATO EUROPEO
            # 154.930,00
            elif ',' in valor_str:
                valor_limpio = valor_str.replace('.', '').replace(',', '.')
                return float(valor_limpio)

            # FORMATO NORMAL
            else:
                return float(valor_str)

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
        
        columnas_lower = {col.lower().strip(): col for col in df.columns}
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            if nombre_lower in columnas_lower:
                return columnas_lower[nombre_lower]
        
        for nombre in nombres_posibles:
            nombre_lower = nombre.lower().strip()
            for col_lower, col_original in columnas_lower.items():
                if nombre_lower in col_lower or col_lower in nombre_lower:
                    return col_original
        
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
            
            mascara = []
            for f in fechas:
                if pd.notna(f) and f.day == dia and f.month == mes and f.year == año:
                    mascara.append(True)
                else:
                    mascara.append(False)
            
            return df[mascara].copy()
        except Exception as e:
            return df
    
    # ===================== FACTURACIÓN =====================
    
    @staticmethod
    def procesar_facturacion(df):
        """
        Procesa archivo de facturación (ranking de ventas).
        Busca la fila "Totales:" y extrae el valor de la columna P (índice 15)
        El valor correcto es 15.288,18
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (facturacion_total, costo_total, cantidad_facturas, promedio_factura)
        """
        if df is None or df.empty:
            return 0.0, 0.0, 0, 0.0

        try:
            for _, row in df.iterrows():
                texto = str(row.iloc[0]).lower()
                if "totales" in texto:
                    valor = row.iloc[15]
                    facturacion = ProcesadorArchivos._convertir_numero_europeo(valor)
                    return (
                        float(facturacion),
                        0.0,
                        1,
                        float(facturacion)
                    )
        except Exception as e:
            print(f"Error en procesar_facturacion: {e}")

        return 0.0, 0.0, 0, 0.0
    
    # ===================== COBRANZAS =====================
    
    @staticmethod
    def procesar_cobranzas(df):
        if df is None or df.empty:
            return 0.0, 0, 0.0

        df = ProcesadorArchivos._limpiar_columnas(df)

        # Buscar la fila Total General
        for idx, row in df.iterrows():
            row_str = ' '.join(
                [str(x) for x in row.values if pd.notna(x)]
            ).lower()

            if 'total general' in row_str:
                # Tomar el MAYOR valor numérico de esa fila
                mayor = 0.0

                for valor in row.values:
                    try:
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num):
                            if float(num) > mayor:
                                mayor = float(num)
                    except:
                        pass

                if mayor > 0:
                    return mayor, 1, mayor

        return 0.0, 0, 0.0
    
    # ===================== EGRESOS - CORREGIDO =====================
    
    @staticmethod
    def procesar_egresos(df):
        """
        Procesa archivo de egresos iPago.
        Filtra SOLO "PROVEEDORES DE MERCANCIA" de la columna "Tipo de Pago" (columna D)
        y suma los montos de la columna "Monto USD" (columna H).
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            tuple: (pagos_proveedores, pagos_gastos, total_egresos, df_proveedores)
                - pagos_proveedores: Suma de montos USD donde Tipo de Pago = "PROVEEDORES DE MERCANCIA"
                - pagos_gastos: Suma de montos USD donde Tipo de Pago != "PROVEEDORES DE MERCANCIA"
                - total_egresos: Suma de todos los egresos en USD
                - df_proveedores: DataFrame con los proveedores de mercancía filtrados
        """
        pagos_proveedores = 0.0
        pagos_gastos = 0.0
        df_proveedores = pd.DataFrame()
        
        if df is None or df.empty:
            return pagos_proveedores, pagos_gastos, 0.0, df_proveedores

        df = ProcesadorArchivos._limpiar_columnas(df)
        
        try:
            # ============================================================
            # 🔥 COLUMNA D (Tipo de Pago) - índice 3
            # ============================================================
            col_tipo_pago = None
            
            # Buscar por nombre exacto primero
            for col in df.columns:
                col_lower = str(col).strip().lower()
                if col_lower == 'tipo de pago' or col_lower == 'tipo_pago' or col_lower == 'tipodepago':
                    col_tipo_pago = col
                    break
            
            # Si no se encuentra, buscar por nombre parcial
            if col_tipo_pago is None:
                for col in df.columns:
                    col_lower = str(col).strip().lower()
                    if 'tipo' in col_lower and 'pago' in col_lower:
                        col_tipo_pago = col
                        break
            
            # Si aún no se encuentra, usar índice 3 (columna D)
            if col_tipo_pago is None and len(df.columns) >= 4:
                col_tipo_pago = df.columns[3]
            
            # ============================================================
            # 🔥 COLUMNA H (Monto USD) - índice 7
            # ============================================================
            col_monto_usd = None
            
            # Buscar por nombre exacto primero
            for col in df.columns:
                col_lower = str(col).strip().lower()
                if col_lower == 'monto usd' or col_lower == 'monto_usd' or col_lower == 'montousd':
                    col_monto_usd = col
                    break
            
            # Si no se encuentra, buscar por nombre parcial
            if col_monto_usd is None:
                for col in df.columns:
                    col_lower = str(col).strip().lower()
                    if 'usd' in col_lower or 'monto' in col_lower:
                        col_monto_usd = col
                        break
            
            # Si aún no se encuentra, usar índice 7 (columna H)
            if col_monto_usd is None and len(df.columns) >= 8:
                col_monto_usd = df.columns[7]
            
            # Si no se encuentra ninguna columna, retornar
            if col_tipo_pago is None or col_monto_usd is None:
                print(f"⚠️ No se encontraron columnas: Tipo de Pago={col_tipo_pago}, Monto USD={col_monto_usd}")
                return pagos_proveedores, pagos_gastos, 0.0, df_proveedores
            
            # ============================================================
            # 🔥 PROCESAR CADA FILA
            # ============================================================
            
            # Crear una copia del DataFrame para el filtro de proveedores
            df_filtrado = df.copy()
            
            # Convertir la columna de tipo de pago a string para filtrar y normalizar acentos
            df_filtrado['_tipo_pago_str'] = df_filtrado[col_tipo_pago].astype(str).str.upper().str.strip()
            df_filtrado['_tipo_pago_str'] = df_filtrado['_tipo_pago_str'].str.replace('Á', 'A').str.replace('É', 'E').str.replace('Í', 'I').str.replace('Ó', 'O').str.replace('Ú', 'U')
            
            # Filtrar SOLO PROVEEDORES DE MERCANCIA
            mascara_proveedores = (
                df_filtrado['_tipo_pago_str'].str.contains('PROVEEDORES DE MERCANCIA', case=False, na=False) |
                df_filtrado['_tipo_pago_str'].str.contains('PROVEEDOR DE MERCANCIA', case=False, na=False)
            )
            
            # Guardar los proveedores filtrados
            df_proveedores = df_filtrado[mascara_proveedores].copy()
            
            # ============================================================
            # 🔥 SUMAR MONTOS
            # ============================================================
            
            # Recorrer todas las filas
            for idx, row in df.iterrows():
                # Obtener el monto en USD
                monto = ProcesadorArchivos._convertir_numero_europeo(row[col_monto_usd])
                if pd.isna(monto) or monto == 0:
                    continue
                
                # Obtener el tipo de pago y normalizar acentos
                tipo_pago = str(row[col_tipo_pago]).upper().strip() if pd.notna(row[col_tipo_pago]) else ''
                tipo_pago_norm = tipo_pago.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')
                
                # Clasificar
                if 'PROVEEDORES DE MERCANCIA' in tipo_pago_norm or 'PROVEEDOR DE MERCANCIA' in tipo_pago_norm:
                    pagos_proveedores += monto
                else:
                    pagos_gastos += monto
            
            # Total de egresos en USD
            total_egresos = pagos_proveedores + pagos_gastos
            
            # Eliminar columna temporal
            if '_tipo_pago_str' in df_filtrado.columns:
                df_filtrado.drop('_tipo_pago_str', axis=1, inplace=True)
            
            # También eliminar la columna temporal de df_proveedores si existe
            if '_tipo_pago_str' in df_proveedores.columns:
                df_proveedores.drop('_tipo_pago_str', axis=1, inplace=True)
            
            # ============================================================
            # 🔥 DEPURACIÓN
            # ============================================================
            print(f"✅ Columnas encontradas: Tipo de Pago='{col_tipo_pago}', Monto USD='{col_monto_usd}'")
            print(f"✅ Proveedores de Mercancía: {len(df_proveedores)} registros, Total: {pagos_proveedores}")
            print(f"✅ Otros Gastos: {len(df) - len(df_proveedores)} registros, Total: {pagos_gastos}")
            
            return pagos_proveedores, pagos_gastos, total_egresos, df_proveedores
            
        except Exception as e:
            print(f"❌ Error al procesar egresos: {str(e)}")
            import traceback
            traceback.print_exc()
            return 0.0, 0.0, 0.0, pd.DataFrame()
    
    # ===================== ESTADO DE CUENTA =====================
    
    @staticmethod
    def procesar_estado_cuenta(df, saldo_inicial=0):
        """
        Procesa estado de cuenta bancario.
        Lee valores del archivo ESTADO DE CUENTA.xlsx
        
        Args:
            df: DataFrame de pandas
            saldo_inicial: Saldo inicial del día (float)
        
        Returns:
            tuple: (saldo_inicial, ingresos_id, ingresos_no_id, ingresos_no_id, total_egresos, saldo_final, total_ingresos, total_egresos)
        """
        if df is None or df.empty:
            return saldo_inicial, 0.0, 0.0, 0.0, saldo_inicial, 0.0, 0.0
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # --- DETECCION DE FORMATO RESUMEN DE SALDOS (BODEGUITA) ---
        is_resumen_saldos = False
        for idx, row in df.iterrows():
            row_str = ' '.join([str(val) for val in row.values if pd.notna(val)]).lower()
            if 'total consolidado' in row_str or 'resumen de saldos' in row_str:
                is_resumen_saldos = True
                break

        if is_resumen_saldos:
            saldo_final_encontrado = 0.0
            ingresos_encontrados = 0.0
            egresos_encontrados = 0.0
            
            for idx, row in df.iterrows():
                row_str = ' '.join([str(val) for val in row.values if pd.notna(val)]).lower()
                nums = []
                for col in df.columns:
                    val = row[col]
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if num is not None and not pd.isna(num):
                        nums.append(float(num))
                
                if 'total consolidado' in row_str:
                    if len(nums) >= 2:
                        saldo_final_encontrado = nums[1]
                    elif len(nums) == 1:
                        saldo_final_encontrado = nums[0]
                elif 'total ingresos archivos' in row_str or ('ingresos' in row_str and 'total' in row_str):
                    if len(nums) >= 2:
                        ingresos_encontrados = nums[1]
                    elif len(nums) == 1:
                        ingresos_encontrados = nums[0]
                elif 'total egresos ipago' in row_str or ('egresos' in row_str and 'total' in row_str):
                    if len(nums) >= 2:
                        egresos_encontrados = nums[1]
                    elif len(nums) == 1:
                        egresos_encontrados = nums[0]
                        
            # Calcular saldo inicial para mantener coherencia contable
            saldo_inicial_calc = saldo_final_encontrado - ingresos_encontrados + egresos_encontrados
            
            return (
                saldo_inicial_calc,     # saldo_inicial
                ingresos_encontrados,   # ingresos_id
                0.0,                    # ingresos_no_id
                egresos_encontrados,    # total_egresos
                saldo_final_encontrado, # saldo_final
                ingresos_encontrados,   # total_ingresos
                egresos_encontrados     # total_egresos (como total_egresos_banco)
            )

        # --- FORMATO ESTADO DE CUENTA TRADICIONAL ---
        saldo_inicial_encontrado = None
        ingresos_encontrados = None
        egresos_encontrados = None
        saldo_final_encontrado = None
        
        for idx, row in df.iterrows():
            row_values = []
            for col in df.columns:
                if pd.notna(row[col]):
                    row_values.append(str(row[col]).strip())
            row_str = ' '.join(row_values).lower()
            
            if 'saldo inicial' in row_str:
                for col in df.columns:
                    try:
                        num = ProcesadorArchivos._convertir_numero_europeo(row[col])
                        if not pd.isna(num) and num > 0:
                            saldo_inicial_encontrado = float(num)
                            break
                    except:
                        pass
            elif 'ingresos' in row_str:
                for col in df.columns:
                    try:
                        num = ProcesadorArchivos._convertir_numero_europeo(row[col])
                        if not pd.isna(num) and num > 0:
                            ingresos_encontrados = float(num)
                            break
                    except:
                        pass
            elif 'egresos' in row_str:
                for col in df.columns:
                    try:
                        num = ProcesadorArchivos._convertir_numero_europeo(row[col])
                        if not pd.isna(num) and num > 0:
                            egresos_encontrados = float(num)
                            break
                    except:
                        pass
            elif 'saldo final' in row_str:
                for col in df.columns:
                    try:
                        num = ProcesadorArchivos._convertir_numero_europeo(row[col])
                        if not pd.isna(num):
                            saldo_final_encontrado = float(num)
                            break
                    except:
                        pass
        
        saldo_inicial = saldo_inicial_encontrado if saldo_inicial_encontrado is not None else saldo_inicial
        total_ingresos = ingresos_encontrados if ingresos_encontrados is not None else 0.0
        total_egresos = egresos_encontrados if egresos_encontrados is not None else 0.0
        saldo_final = (
            saldo_final_encontrado
            if saldo_final_encontrado is not None
            else (saldo_inicial + total_ingresos - total_egresos)
        )
        
        ingresos_id = total_ingresos
        ingresos_no_id = 0.0
        
        return (
            saldo_inicial,
            ingresos_id,
            ingresos_no_id,
            total_egresos,
            saldo_final,
            total_ingresos,
            total_egresos
        )
    
    # ===================== OBTENER TOTAL EGRESOS IPAGO =====================
    
    @staticmethod
    def obtener_total_egresos_ipago(df):
        """
        Obtiene el total de egresos iPago desde el archivo.
        Busca la columna "Monto USD" (columna H)
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            float: Total de egresos iPago
        """
        if df is None or df.empty:
            return 0.0
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        monto_col = None
        
        for col in df.columns:
            if str(col).strip().lower() == "monto usd":
                monto_col = col
                break
        
        if monto_col is None:
            if len(df.columns) >= 8:
                monto_col = df.columns[7]
        
        if monto_col is None:
            return 0.0
        
        total = 0.0
        
        for val in df[monto_col]:
            num = ProcesadorArchivos._convertir_numero_europeo(val)
            if not pd.isna(num):
                total += float(num)
        
        return total
    
    # ===================== RECEPCIONES =====================
    
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
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        idx_inicio = 0
        for idx, row in df.iterrows():
            row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
            if 'compra' in row_str and 'proveedor' in row_str and 'recep' in row_str:
                idx_inicio = idx + 1
                break
        
        if idx_inicio == 0:
            patrones = ['compra', 'proveedor', 'recep']
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
        
        col_neto = None
        # 1. Buscar primero la columna preferencial: Neto + IVA (normalizando para ser inmunes a formatos)
        for col in df.columns:
            col_str = str(col).strip()
            clean_col = re.sub(r'[^a-z0-9]', '', col_str.lower())
            if 'neto' in clean_col and 'iva' in clean_col:
                col_neto = col
                break
        
        # 2. Si no se encuentra, buscar la columna Neto simple (sin IVA)
        if col_neto is None:
            for col in df.columns:
                col_str = str(col).strip()
                clean_col = re.sub(r'[^a-z0-9]', '', col_str.lower())
                if 'neto' in clean_col and 'iva' not in clean_col:
                    col_neto = col
                    break
        
        if col_neto:
            for idx, row in df.iterrows():
                row_str = ' '.join([str(x) for x in row.values if pd.notna(x)]).lower()
                if 'total general' in row_str or 'total' in row_str:
                    try:
                        valor = row[col_neto]
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num) and num > 0:
                            total_recepcion = float(num)
                            break
                    except:
                        pass
            
            if total_recepcion == 0:
                for val in df[col_neto]:
                    num = ProcesadorArchivos._convertir_numero_europeo(val)
                    if not pd.isna(num) and num > 0:
                        total_recepcion = float(num)
                        break
        
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
        
        compras_credito = total_recepcion * 0.6
        
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
        
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_recibo', 'recibo', 'factura'
        )
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        promedio = total_recepcion / cantidad if cantidad > 0 else 0.0
        
        return total_recepcion, compras_credito, cantidad, promedio
    
    # ===================== NOTAS DE CRÉDITO =====================
    
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
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        monto_col = ProcesadorArchivos._buscar_columna(
            df, 
            'monto', 'valor', 'total', 'credito', 'importe', 'amount',
            'nota_credito', 'monto_nota', 'abono'
        )
        
        doc_col = ProcesadorArchivos._buscar_columna(
            df, 
            'documento', 'comprobante', 'doc', 'id', 'nro_nota', 'nota'
        )
        
        total = ProcesadorArchivos._extraer_valor(df, 'monto', 'valor', 'total', 'credito')
        if total == 0 and monto_col:
            try:
                total = ProcesadorArchivos._extraer_valor(df, monto_col)
            except:
                total = 0.0
        
        cantidad = df[doc_col].nunique() if doc_col else len(df)
        
        promedio = total / cantidad if cantidad > 0 else 0.0
        
        return total, cantidad, promedio
    
    # ===================== COSTO DE FACTURACIÓN - CORREGIDO =====================
    
    @staticmethod
    def procesar_costo_facturacion(df):
        """
        Procesa archivo de reporte de utilidad para extraer el costo de facturación.
        Busca "Total General:" y extrae el valor de la columna E (índice 4)
        
        Estructura esperada del archivo:
        - Columna E: Costo (con valores como 1.417,00)
        - Fila que contiene "Total General:" en la primera columna
        
        Args:
            df: DataFrame de pandas
        
        Returns:
            float: Costo total de facturación (ej: 1.417,00)
        """
        if df is None or df.empty:
            return 0.0
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # 🔥 Buscar la fila que contiene "Total General" o "Total General:"
        for idx, row in df.iterrows():
            # Convertir la primera columna a string para buscar
            primera_col = str(row.iloc[0]) if len(row) > 0 else ""
            
            # Buscar "Total General" en la primera columna
            if 'total general' in primera_col.lower() or 'total general:' in primera_col.lower():
                # 🔥 Extraer el valor de la columna E (índice 4)
                try:
                    if len(row) > 4:
                        valor = row.iloc[4]
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num) and num > 0:
                            return float(num)
                except Exception as e:
                    print(f"Error al extraer valor de columna E: {e}")
                
                # Si falla la columna E, intentar buscar en cualquier columna numérica
                for col in df.columns:
                    try:
                        valor = row[col]
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num) and num > 100:
                            return float(num)
                    except:
                        pass
        
        # 🔥 Si no se encuentra "Total General", buscar "Total" en la primera columna
        for idx, row in df.iterrows():
            primera_col = str(row.iloc[0]) if len(row) > 0 else ""
            
            if 'total' in primera_col.lower():
                try:
                    if len(row) > 4:
                        valor = row.iloc[4]
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num) and num > 0:
                            return float(num)
                except:
                    pass
        
        return 0.0
    
    # ===================== 🔥 EXTRAER SALDO REPORTADO (MEJORADO - POR COLUMNA ESPECÍFICA) =====================
    
    @staticmethod
    def extraer_saldo_reportado(df, tipo):
        """
        Extrae saldo reportado de archivos de verificación.
        Busca específicamente en las columnas correctas según el tipo.
        
        CxC: Columna I (Saldo Pendt.) - Total Compañia = 417.932,23
        CxP: Columna C (Saldo Pendt.) - Total Compañia = 670.115,79
        
        Args:
            df: DataFrame de pandas
            tipo: Tipo de saldo ('cxc', 'cxp', 'inventario', 'bancos')
        
        Returns:
            float: Saldo reportado, o None si no se encuentra
        """
        if df is None or df.empty:
            return None
        
        df = ProcesadorArchivos._limpiar_columnas(df)
        
        # ============================================================
        # 🔥 CxC: Buscar en columna I (índice 8) o columna "Saldo Pendt."
        # ============================================================
        if tipo == 'cxc':
            # Buscar la fila con "Total Compañia"
            for idx, row in df.iterrows():
                texto_fila = ' '.join(
                    [str(x) for x in row.values if pd.notna(x)]
                ).lower()
                
                if 'total compañia' in texto_fila or 'total compania' in texto_fila or 'total compañía' in texto_fila:
                    # Intentar por índice de columna (columna I = índice 8)
                    try:
                        if len(row) > 8:
                            valor = row.iloc[8]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                return float(num)
                    except:
                        pass
                    
                    # Si falla, buscar en la columna "Saldo Pendt."
                    saldo_col = ProcesadorArchivos._buscar_columna(df, 'saldo pendt', 'saldo pendiente', 'saldo')
                    if saldo_col:
                        try:
                            valor = row[saldo_col]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                return float(num)
                        except:
                            pass
                    
                    # Último recurso: tomar el número más grande de la fila
                    numeros = []
                    for valor in row.values:
                        try:
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                numeros.append(float(num))
                        except:
                            pass
                    if numeros:
                        return max(numeros)
        
        # ============================================================
        # 🔥 CxP: Buscar en columna C (índice 2) o columna "Saldo Pendt."
        # ============================================================
        if tipo == 'cxp':
            # Buscar la fila con "Total Compañia"
            for idx, row in df.iterrows():
                texto_fila = ' '.join(
                    [str(x) for x in row.values if pd.notna(x)]
                ).lower()
                
                if 'total compañia' in texto_fila or 'total compania' in texto_fila or 'total compañía' in texto_fila:
                    # Intentar por índice de columna (columna C = índice 2)
                    try:
                        if len(row) > 2:
                            valor = row.iloc[2]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                return float(num)
                    except:
                        pass
                    
                    # Si falla, buscar en la columna "Saldo Pendt."
                    saldo_col = ProcesadorArchivos._buscar_columna(df, 'saldo pendt', 'saldo pendiente', 'saldo')
                    if saldo_col:
                        try:
                            valor = row[saldo_col]
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                return float(num)
                        except:
                            pass
                    
                    # Último recurso: tomar el número más grande de la fila
                    numeros = []
                    for valor in row.values:
                        try:
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                numeros.append(float(num))
                        except:
                            pass
                    if numeros:
                        return max(numeros)
        
        # ============================================================
        # 🔥 Inventario: Buscar "Totales:"
        # ============================================================
        if tipo == 'inventario':
            for idx, row in df.iterrows():
                texto_fila = ' '.join(
                    [str(x) for x in row.values if pd.notna(x)]
                ).lower()

                if 'totales:' in texto_fila or 'total' in texto_fila:
                    numeros = []
                    for valor in row.values:
                        try:
                            num = ProcesadorArchivos._convertir_numero_europeo(valor)
                            if not pd.isna(num) and num > 0:
                                numeros.append(float(num))
                        except:
                            pass

                    if numeros:
                        return max(numeros)
        
        # ============================================================
        # 🔥 Bancos (si se usa)
        # ============================================================
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
                    if valores:
                        return float(valores[-1])
                except:
                    pass
        
        # ============================================================
        # 🔥 Fallback: buscar en cualquier columna
        # ============================================================
        for idx, row in df.iterrows():
            texto_fila = ' '.join(
                [str(x) for x in row.values if pd.notna(x)]
            ).lower()
            
            if 'total compañia' in texto_fila or 'total compania' in texto_fila:
                numeros = []
                for valor in row.values:
                    try:
                        num = ProcesadorArchivos._convertir_numero_europeo(valor)
                        if not pd.isna(num) and num > 0:
                            numeros.append(float(num))
                    except:
                        pass
                
                if numeros:
                    return max(numeros)
        
        return None

    @staticmethod
    def cargar_detalle_inventario(df):
        """
        Carga el inventario a nivel de producto, extrayendo columnas normalizadas:
        Producto (código), Descrip_Clean (descripción), Cantidad, Precio/Unidad, Total(*)
        
        Args:
            df: DataFrame de pandas cargado del archivo de inventario
            
        Returns:
            DataFrame: DataFrame normalizado o None si ocurre un error
        """
        if df is None or df.empty:
            return None
            
        try:
            df = df.copy()
            
            # Buscar la fila de cabecera que contenga 'producto' y 'cantidad'
            header_idx = None
            for idx, row in df.iterrows():
                row_str = [str(x).lower().strip() for x in row.values]
                if 'producto' in row_str and 'cantidad' in row_str:
                    header_idx = idx
                    break
                    
            if header_idx is None:
                # Intento secundario: buscar 'producto' en cualquier columna de las primeras 20 filas
                for idx in range(min(20, len(df))):
                    row_str = [str(x).lower().strip() for x in df.iloc[idx].values]
                    if any('producto' in x for x in row_str):
                        header_idx = idx
                        break
                        
            if header_idx is None:
                return None
                
            # Hacer únicas las columnas para evitar errores de pandas
            raw_cols = df.iloc[header_idx].values
            cols = []
            seen = {}
            for i, x in enumerate(raw_cols):
                name = str(x).strip() if pd.notna(x) else f'col_{i}'
                if name in seen:
                    seen[name] += 1
                    cols.append(f"{name}_{seen[name]}")
                else:
                    seen[name] = 0
                    cols.append(name)
                    
            df_clean = df.iloc[header_idx+1:].reset_index(drop=True)
            df_clean.columns = cols
            
            # Limpiar filas donde 'Producto' es nulo o contiene palabras totales
            df_clean = df_clean.dropna(subset=['Producto'])
            df_clean = df_clean[~df_clean['Producto'].astype(str).str.lower().str.contains('total')]
            
            # Normalizar código de producto (quitar ceros a la izquierda y espacios)
            df_clean['Producto'] = df_clean['Producto'].astype(str).str.strip().str.replace(r'^0+', '', regex=True)
            
            # Buscar columnas correspondientes
            price_col = None
            total_col = None
            desc_col = None
            qty_col = None
            
            for col in df_clean.columns:
                col_lower = col.lower()
                if 'precio' in col_lower or 'precio/unidad' in col_lower:
                    price_col = col
                elif 'total' in col_lower:
                    total_col = col
                elif 'descrip' in col_lower:
                    desc_col = col
                elif 'cantidad' in col_lower:
                    qty_col = col
                    
            if not qty_col:
                qty_col = 'Cantidad'
            if not price_col:
                price_col = 'Precio/Unidad'
            if not total_col:
                total_col = 'Total(*)'
            if not desc_col:
                desc_col = 'Descripci\xf3n'
                
            # Procesar datos numéricos
            df_clean['Cantidad'] = df_clean[qty_col].apply(ProcesadorArchivos._convertir_numero_europeo).fillna(0.0)
            df_clean['Precio/Unidad'] = df_clean[price_col].apply(ProcesadorArchivos._convertir_numero_europeo).fillna(0.0)
            df_clean['Total(*)'] = df_clean[total_col].apply(ProcesadorArchivos._convertir_numero_europeo).fillna(0.0)
            
            # Encontrar el nombre real de la descripción en el df
            real_desc_col = None
            for c in df_clean.columns:
                if 'desc' in c.lower():
                    real_desc_col = c
                    break
            if real_desc_col:
                df_clean['Descrip_Clean'] = df_clean[real_desc_col].astype(str).str.strip()
            else:
                df_clean['Descrip_Clean'] = 'Producto ' + df_clean['Producto']
                
            return df_clean[['Producto', 'Cantidad', 'Precio/Unidad', 'Total(*)', 'Descrip_Clean']]
        except Exception as e:
            print(f"Error al cargar detalle de inventario: {e}")
            return None

    @staticmethod
    def cargar_detalle_utilidad(df):
        """
        Carga el reporte de utilidad (rentabilidad por producto) a nivel de producto,
        agrupando por código de producto.
        
        Args:
            df: DataFrame de pandas del reporte de utilidad
            
        Returns:
            DataFrame: DataFrame consolidado por producto con columnas Cod_Producto, Cantidad (vendida), Costo_Total (vendido)
        """
        if df is None or df.empty:
            return None
            
        try:
            df = df.copy()
            
            # Buscar fila de cabecera
            header_idx = None
            for idx, row in df.iterrows():
                row_str = [str(x).lower().strip() for x in row.values]
                if 'producto' in row_str and ('ganancia' in ''.join(row_str) or 'costo' in row_str):
                    header_idx = idx
                    break
                    
            if header_idx is None:
                # Intento secundario: buscar 'producto' en las primeras 20 filas
                for idx in range(min(20, len(df))):
                    row_str = [str(x).lower().strip() for x in df.iloc[idx].values]
                    if any('producto' in x for x in row_str):
                        header_idx = idx
                        break
                        
            if header_idx is None:
                return None
                
            # Hacer únicas las columnas
            raw_cols = df.iloc[header_idx].values
            cols = []
            seen = {}
            for i, x in enumerate(raw_cols):
                name = str(x).strip() if pd.notna(x) else f'col_{i}'
                if name in seen:
                    seen[name] += 1
                    cols.append(f"{name}_{seen[name]}")
                else:
                    seen[name] = 0
                    cols.append(name)
                    
            df_clean = df.iloc[header_idx+1:].reset_index(drop=True)
            df_clean.columns = cols
            
            df_clean = df_clean.dropna(subset=['Producto'])
            df_clean = df_clean[~df_clean['Producto'].astype(str).str.lower().str.contains('total')]
            
            # Función para parsear código de producto
            def parse_prod_code(val):
                val_str = str(val).strip()
                if '-' in val_str:
                    return val_str.split('-')[0].strip().lstrip('0')
                return val_str.lstrip('0')
                
            df_clean['Cod_Producto'] = df_clean['Producto'].apply(parse_prod_code)
            
            qty_col = None
            for c in df_clean.columns:
                if c.lower().strip() == 'cantidad':
                    qty_col = c
                    break
            if not qty_col:
                qty_col = 'Cantidad'
                
            df_clean['Cantidad_Clean'] = df_clean[qty_col].apply(ProcesadorArchivos._convertir_numero_europeo).fillna(0.0)
            
            # Buscar el Costo Total (segunda columna de Costo o columna Costo_1)
            cost_col = 'Costo_1' if 'Costo_1' in df_clean.columns else 'Costo'
            df_clean['Costo_Total'] = df_clean[cost_col].apply(ProcesadorArchivos._convertir_numero_europeo).fillna(0.0)
            
            # Agrupar
            df_grouped = df_clean.groupby('Cod_Producto').agg({
                'Cantidad_Clean': 'sum',
                'Costo_Total': 'sum',
                'Producto': 'first'
            }).reset_index()
            
            df_grouped.columns = ['Cod_Producto', 'Cantidad', 'Costo_Total', 'Producto_Original']
            return df_grouped
        except Exception as e:
            print(f"Error al cargar detalle de utilidad: {e}")
            return None
