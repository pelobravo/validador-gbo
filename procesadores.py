# procesadores.py
import pandas as pd
import numpy as np

class ProcesadorArchivos:
    """Clase para procesar los diferentes tipos de archivos"""
    
    @staticmethod
    def procesar_facturacion(df):
        """Procesa archivo de facturación"""
        try:
            if 'monto_factura' in df.columns:
                total_facturacion = df['monto_factura'].sum()
            else:
                total_facturacion = df.iloc[:, 2].sum()
            
            if 'costo_venta' in df.columns:
                total_costo = df['costo_venta'].sum()
            else:
                total_costo = 0
            
            registros = len(df)
            return total_facturacion, total_costo, registros, None
        except Exception as e:
            return 0, 0, 0, str(e)
    
    @staticmethod
    def procesar_cobranzas(df):
        """Procesa archivo de cobranzas"""
        try:
            if 'monto_cobranza' in df.columns:
                total_cobranzas = df['monto_cobranza'].sum()
            else:
                total_cobranzas = df.iloc[:, 2].sum()
            
            registros = len(df)
            return total_cobranzas, registros, None
        except Exception as e:
            return 0, 0, str(e)
    
    @staticmethod
    def procesar_recepciones(df):
        """Procesa archivo de recepciones"""
        try:
            if 'monto_recepcion' in df.columns:
                total_recepcion = df['monto_recepcion'].sum()
                
                if 'tipo_compra' in df.columns:
                    compras_credito = df[df['tipo_compra'].str.lower() == 'credito']['monto_recepcion'].sum()
                else:
                    compras_credito = total_recepcion  # Asumir todo a crédito
            else:
                total_recepcion = df.iloc[:, 2].sum()
                compras_credito = total_recepcion
            
            registros = len(df)
            return total_recepcion, compras_credito, registros, None
        except Exception as e:
            return 0, 0, 0, str(e)
    
    @staticmethod
    def procesar_egresos(df):
        """Procesa archivo de egresos"""
        try:
            pagos_proveedores = 0
            pagos_gastos = 0
            
            if 'tipo' in df.columns:
                pagos_proveedores = df[df['tipo'].str.lower() == 'proveedor']['monto'].sum()
                pagos_gastos = df[df['tipo'].str.lower() == 'gasto']['monto'].sum()
            else:
                pagos_proveedores = df.iloc[:, 2].sum()
            
            registros = len(df)
            return pagos_proveedores, pagos_gastos, registros, None
        except Exception as e:
            return 0, 0, 0, str(e)
    
    @staticmethod
    def procesar_estado_cuenta(df, saldo_inicial):
        """Procesa archivo de estado de cuenta"""
        try:
            if 'ingreso' in df.columns:
                ingresos = df['ingreso'].sum()
                egresos = df['egreso'].sum()
                
                if 'saldo_final' in df.columns:
                    saldo_final = df['saldo_final'].iloc[-1]
                else:
                    saldo_final = saldo_inicial + ingresos - egresos
            else:
                ingresos = 0
                egresos = 0
                saldo_final = saldo_inicial
            
            # Por ahora, todos los ingresos son identificados
            ingresos_identificados = ingresos
            ingresos_no_identificados = 0
            
            registros = len(df)
            return ingresos_identificados, ingresos_no_identificados, egresos, saldo_final, registros, None
        except Exception as e:
            return 0, 0, 0, 0, 0, str(e)
    
    @staticmethod
    def procesar_notas_credito(df):
        """Procesa archivo de notas de crédito"""
        try:
            if 'monto_nota' in df.columns:
                total_notas = df['monto_nota'].sum()
            else:
                total_notas = df.iloc[:, 2].sum() if len(df.columns) > 2 else 0
            
            registros = len(df)
            return total_notas, registros, None
        except Exception as e:
            return 0, 0, str(e)
    
    @staticmethod
    def extraer_saldo_reportado(df, tipo_reporte):
        """Extrae el saldo final de un archivo de reporte (CxC, CxP, Inventario)"""
        try:
            if tipo_reporte in ['cxc', 'cxp']:
                # Buscar "Total Compañía" en las últimas filas
                for i in range(len(df)-10, len(df)):
                    fila = df.iloc[i, :].astype(str)
                    if 'Total Compañía' in ' '.join(fila.values) or 'Total Compania' in ' '.join(fila.values):
                        for col in df.columns:
                            try:
                                val = pd.to_numeric(df.iloc[i, col], errors='coerce')
                                if pd.notna(val) and val > 0:
                                    return val
                            except:
                                pass
            
            elif tipo_reporte == 'inventario':
                for i in range(len(df)-5, len(df)):
                    fila = df.iloc[i, :].astype(str)
                    if 'Total' in ' '.join(fila.values) and 'Producto' not in ' '.join(fila.values):
                        for col in df.columns:
                            try:
                                val = pd.to_numeric(df.iloc[i, col], errors='coerce')
                                if pd.notna(val) and val > 0:
                                    return val
                            except:
                                pass
            
            return None
        except Exception as e:
            return None
    
    @staticmethod
    def calcular_saldos_finales(saldos_iniciales, movimientos):
        """Calcula los saldos finales aplicando las fórmulas"""
        
        inventario = (saldos_iniciales['inventario'] + 
                      movimientos['recepcion_total'] - 
                      movimientos['costo_facturacion'])
        
        cx_c = (saldos_iniciales['cx_c'] + 
                movimientos['facturacion'] - 
                movimientos['cobranzas'] - 
                movimientos['notas_credito'])
        
        bancos = (saldos_iniciales['bancos'] + 
                  movimientos['ingresos_totales'] - 
                  movimientos['pagos_proveedores'] - 
                  movimientos['pagos_gastos'])
        
        cx_p = (saldos_iniciales['cx_p'] + 
                movimientos['compras_credito'] - 
                movimientos['pagos_proveedores'])
        
        transito = saldos_iniciales['transito'] + movimientos['ingresos_no_identificados']
        
        capital = (inventario + cx_c + bancos) - (cx_p + transito)
        
        return {
            'inventario': inventario,
            'cx_c': cx_c,
            'bancos': bancos,
            'cx_p': cx_p,
            'transito': transito,
            'capital': capital
        }