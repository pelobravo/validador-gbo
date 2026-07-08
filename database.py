# database.py
import os
import sqlite3
import pandas as pd
from datetime import datetime
from config import RUTA_BASE_DATOS

# Intentar importar Supabase (si está instalado)
try:
    from supabase import create_client, Client
    SUPPABASE_AVAILABLE = True
except ImportError:
    SUPPABASE_AVAILABLE = False
    print("⚠️ Supabase no está instalado. Usando solo SQLite local.")


class Database:
    """Clase para manejar la base de datos (Supabase + SQLite como respaldo)"""
    
    def __init__(self):
        # ============================================================
        # 1. CONFIGURACIÓN DE SUPABASE (NUBE)
        # ============================================================
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        
        self.use_supabase = False
        self.client = None
        
        if SUPPABASE_AVAILABLE and self.supabase_url and self.supabase_key:
            try:
                self.client: Client = create_client(self.supabase_url, self.supabase_key)
                self.use_supabase = True
                print("✅ Conectado a Supabase (nube)")
            except Exception as e:
                print(f"⚠️ Error al conectar con Supabase: {e}. Usando SQLite local.")
                self.use_supabase = False
        
        # ============================================================
        # 2. CONFIGURACIÓN DE SQLITE LOCAL (SIEMPRE ACTIVO COMO RESPALDO)
        # ============================================================
        if not os.path.exists(RUTA_BASE_DATOS):
            os.makedirs(RUTA_BASE_DATOS, exist_ok=True)
        self.db_path = os.path.join(RUTA_BASE_DATOS, 'conciliacion.db')
        self._inicializar_tablas()
        
        if not self.use_supabase:
            print("⚠️ Usando SQLite local (sin persistencia en la nube)")
    
    # ============================================================
    # 3. INICIALIZACIÓN DE TABLAS SQLITE
    # ============================================================
    def _inicializar_tablas(self):
        """Crea las tablas necesarias si no existen en SQLite"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Verificar si la columna 'empresa' existe en saldos_diarios para migrar si es necesario
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='saldos_diarios'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(saldos_diarios)")
            cols = [row[1] for row in cursor.fetchall()]
            if 'empresa' not in cols:
                cursor.execute("DROP TABLE saldos_diarios")
        
        # Verificar si la columna 'inv_monto' existe en ajustes_diarios
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ajustes_diarios'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(ajustes_diarios)")
            cols_aj = [row[1] for row in cursor.fetchall()]
            if 'inv_monto' not in cols_aj:
                cursor.execute("DROP TABLE ajustes_diarios")
        
        # Tabla de saldos diarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saldos_diarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha DATE NOT NULL,
                empresa TEXT NOT NULL DEFAULT 'General',
                inventario REAL DEFAULT 0,
                cx_c REAL DEFAULT 0,
                bancos REAL DEFAULT 0,
                cx_p REAL DEFAULT 0,
                transito REAL DEFAULT 0,
                capital REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(fecha, empresa)
            )
        ''')
        
        # Tabla de movimientos procesados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movimientos_diarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha DATE NOT NULL,
                empresa TEXT NOT NULL DEFAULT 'General',
                tipo_movimiento TEXT NOT NULL,
                concepto TEXT,
                monto REAL DEFAULT 0,
                referencia TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de inconsistencias detectadas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inconsistencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha DATE NOT NULL,
                empresa TEXT NOT NULL DEFAULT 'General',
                cuenta TEXT NOT NULL,
                valor_calculado REAL,
                valor_reportado REAL,
                diferencia REAL,
                descripcion TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de auditoría de archivos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS auditoria_archivos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_proceso DATE NOT NULL,
                empresa TEXT NOT NULL DEFAULT 'General',
                nombre_archivo TEXT NOT NULL,
                tipo_archivo TEXT NOT NULL,
                registros INTEGER,
                estado TEXT,
                error TEXT,
                usuario TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id TEXT PRIMARY KEY,
                nombre TEXT,
                email TEXT,
                rol TEXT,
                password TEXT,
                activo INTEGER DEFAULT 1,
                ultimo_acceso TIMESTAMP
            )
        ''')
        
        # Tabla de tasas BCV
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasas_bcv (
                fecha DATE PRIMARY KEY,
                tasa REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de ajustes diarios por empresa
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ajustes_diarios (
                fecha DATE NOT NULL,
                empresa TEXT NOT NULL,
                inv_monto REAL DEFAULT 0,
                inv_just TEXT,
                cxc_monto REAL DEFAULT 0,
                cxc_just TEXT,
                cxp_monto REAL DEFAULT 0,
                cxp_just TEXT,
                transito_monto REAL DEFAULT 0,
                transito_just TEXT,
                PRIMARY KEY (fecha, empresa)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    # ============================================================
    # 4. FUNCIÓN AUXILIAR: SINCRONIZAR SUPABASE CON SQLITE
    # ============================================================
    def _sincronizar_supabase_sqlite(self, tabla, data, empresa='General'):
        """
        Guarda los datos en Supabase si está disponible,
        y siempre guarda en SQLite como respaldo.
        """
        # Siempre guardar en SQLite (respaldo local)
        return True
        
        # (Opcional) Si se desea, se puede implementar sincronización bidireccional
        # entre SQLite y Supabase para tener respaldo local y nube.
    
    # ============================================================
    # 5. MÉTODOS PRINCIPALES (CON SUPABASE + SQLITE)
    # ============================================================
    
    def guardar_saldos(self, fecha, saldos, empresa='General'):
        """Guarda los saldos en Supabase (si está disponible) y en SQLite local."""
        exito_sqlite = False
        exito_supabase = False
        
        # --- 1. Guardar en SQLite (siempre) ---
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO saldos_diarios 
                (fecha, empresa, inventario, cx_c, bancos, cx_p, transito, capital)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                fecha,
                empresa,
                saldos.get('inventario', 0),
                saldos.get('cx_c', 0),
                saldos.get('bancos', 0),
                saldos.get('cx_p', 0),
                saldos.get('transito', 0),
                saldos.get('capital', 0)
            ))
            conn.commit()
            conn.close()
            exito_sqlite = True
            print(f"✅ Saldos guardados en SQLite para {fecha} - {empresa}")
        except Exception as e:
            print(f"❌ Error guardando en SQLite: {e}")
        
        # --- 2. Guardar en Supabase (si está disponible) ---
        if self.use_supabase and self.client:
            try:
                data = {
                    "fecha": fecha,
                    "empresa": empresa,
                    "inventario": float(saldos.get('inventario', 0)),
                    "cx_c": float(saldos.get('cx_c', 0)),
                    "bancos": float(saldos.get('bancos', 0)),
                    "cx_p": float(saldos.get('cx_p', 0)),
                    "transito": float(saldos.get('transito', 0)),
                    "capital": float(saldos.get('capital', 0))
                }
                result = self.client.table('saldos_diarios').upsert(data).execute()
                exito_supabase = True
                print(f"✅ Saldos guardados en Supabase para {fecha} - {empresa}")
            except Exception as e:
                print(f"❌ Error guardando en Supabase: {e}")
        
        # --- 3. Retornar éxito si al menos uno funcionó ---
        return exito_sqlite or exito_supabase
    
    def obtener_ultimo_saldo(self, empresa='General'):
        """Obtiene el último saldo guardado (prioriza Supabase, fallback a SQLite)"""
        
        # --- 1. Intentar desde Supabase (si está disponible) ---
        if self.use_supabase and self.client:
            try:
                result = self.client.table('saldos_diarios')\
                    .select('*')\
                    .eq('empresa', empresa)\
                    .order('fecha', desc=True)\
                    .limit(1)\
                    .execute()
                
                if result.data:
                    row = result.data[0]
                    return {
                        'fecha': row['fecha'],
                        'inventario': row['inventario'],
                        'cx_c': row['cx_c'],
                        'bancos': row['bancos'],
                        'cx_p': row['cx_p'],
                        'transito': row['transito'],
                        'capital': row['capital']
                    }
            except Exception as e:
                print(f"⚠️ Error en Supabase (obtener_ultimo_saldo): {e}")
                # Fallback a SQLite
        
        # --- 2. Fallback a SQLite local ---
        try:
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql_query(
                "SELECT * FROM saldos_diarios WHERE empresa = ? ORDER BY fecha DESC LIMIT 1",
                conn, params=[empresa]
            )
            conn.close()
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception as e:
            print(f"❌ Error en SQLite (obtener_ultimo_saldo): {e}")
        
        return None
    
    def obtener_saldos(self, fecha, empresa='General'):
        """Obtiene los saldos de una fecha específica (prioriza Supabase)"""
        
        # --- 1. Intentar desde Supabase ---
        if self.use_supabase and self.client:
            try:
                result = self.client.table('saldos_diarios')\
                    .select('*')\
                    .eq('fecha', fecha)\
                    .eq('empresa', empresa)\
                    .limit(1)\
                    .execute()
                
                if result.data:
                    return result.data[0]
            except Exception as e:
                print(f"⚠️ Error en Supabase (obtener_saldos): {e}")
        
        # --- 2. Fallback a SQLite ---
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE fecha = ? AND empresa = ?",
            conn, params=[fecha, empresa]
        )
        conn.close()
        if not df.empty:
            return df.iloc[0].to_dict()
        return None
    
    def obtener_historial_por_fechas(self, desde, hasta, empresa='General'):
        """Obtiene el historial entre dos fechas (prioriza Supabase)"""
        
        # --- 1. Intentar desde Supabase ---
        if self.use_supabase and self.client:
            try:
                result = self.client.table('saldos_diarios')\
                    .select('*')\
                    .eq('empresa', empresa)\
                    .gte('fecha', desde)\
                    .lte('fecha', hasta)\
                    .order('fecha', desc=True)\
                    .execute()
                
                if result.data:
                    df = pd.DataFrame(result.data)
                    df['fecha'] = pd.to_datetime(df['fecha']).dt.strftime('%Y-%m-%d')
                    return df
            except Exception as e:
                print(f"⚠️ Error en Supabase (obtener_historial_por_fechas): {e}")
        
        # --- 2. Fallback a SQLite ---
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE empresa = ? AND fecha >= ? AND fecha <= ? ORDER BY fecha ASC",
            conn, params=[empresa, desde, hasta]
        )
        conn.close()
        return df
    
    def obtener_historial_saldos_completo(self, limite=30, empresa='General'):
        """Obtiene el historial completo de una empresa (prioriza Supabase)"""
        
        # --- 1. Intentar desde Supabase ---
        if self.use_supabase and self.client:
            try:
                result = self.client.table('saldos_diarios')\
                    .select('*')\
                    .eq('empresa', empresa)\
                    .order('fecha', desc=True)\
                    .limit(limite)\
                    .execute()
                
                if result.data:
                    df = pd.DataFrame(result.data)
                    df['fecha'] = pd.to_datetime(df['fecha']).dt.strftime('%Y-%m-%d')
                    return df
            except Exception as e:
                print(f"⚠️ Error en Supabase (obtener_historial_saldos_completo): {e}")
        
        # --- 2. Fallback a SQLite ---
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE empresa = ? ORDER BY fecha DESC LIMIT ?",
            conn, params=[empresa, limite]
        )
        conn.close()
        return df
    
    def guardar_inconsistencia(self, fecha, cuenta, calc, reportado, diferencia, descripcion, empresa='General'):
        """Guarda una inconsistencia en Supabase y SQLite"""
        
        # --- 1. Guardar en SQLite (siempre) ---
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO inconsistencias 
                (fecha, empresa, cuenta, valor_calculado, valor_reportado, diferencia, descripcion)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (fecha, empresa, cuenta, calc, reportado, diferencia, descripcion))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Error guardando inconsistencia en SQLite: {e}")
        
        # --- 2. Guardar en Supabase (si está disponible) ---
        if self.use_supabase and self.client:
            try:
                data = {
                    "fecha": fecha,
                    "empresa": empresa,
                    "cuenta": cuenta,
                    "valor_calculado": float(calc),
                    "valor_reportado": float(reportado),
                    "diferencia": float(diferencia),
                    "descripcion": descripcion
                }
                self.client.table('inconsistencias').insert(data).execute()
                print(f"✅ Inconsistencia guardada en Supabase")
            except Exception as e:
                print(f"❌ Error guardando inconsistencia en Supabase: {e}")
    
    def guardar_ajustes(self, fecha, ajustes, empresa='General'):
        """Guarda los ajustes en Supabase y SQLite"""
        
        inv = ajustes.get('inventario', {'monto': 0.0, 'justificacion': ''})
        cxc = ajustes.get('cx_c', {'monto': 0.0, 'justificacion': ''})
        cxp = ajustes.get('cx_p', {'monto': 0.0, 'justificacion': ''})
        transito = ajustes.get('transito', {'monto': 0.0, 'justificacion': ''})
        
        # --- 1. Guardar en SQLite (siempre) ---
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO ajustes_diarios 
                (fecha, empresa, inv_monto, inv_just, cxc_monto, cxc_just, cxp_monto, cxp_just, transito_monto, transito_just)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                fecha, empresa,
                inv.get('monto', 0.0), inv.get('justificacion', ''),
                cxc.get('monto', 0.0), cxc.get('justificacion', ''),
                cxp.get('monto', 0.0), cxp.get('justificacion', ''),
                transito.get('monto', 0.0), transito.get('justificacion', '')
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Error guardando ajustes en SQLite: {e}")
        
        # --- 2. Guardar en Supabase (si está disponible) ---
        if self.use_supabase and self.client:
            try:
                # Eliminar ajustes anteriores para esta fecha/empresa
                self.client.table('ajustes')\
                    .delete()\
                    .eq('fecha', fecha)\
                    .eq('empresa', empresa)\
                    .execute()
                
                # Insertar nuevos ajustes
                for cuenta, data in [('inventario', inv), ('cx_c', cxc), ('cx_p', cxp), ('transito', transito)]:
                    if data['monto'] != 0 or data['justificacion']:
                        self.client.table('ajustes').insert({
                            "fecha": fecha,
                            "empresa": empresa,
                            "cuenta": cuenta,
                            "monto": data['monto'],
                            "justificacion": data['justificacion']
                        }).execute()
                print(f"✅ Ajustes guardados en Supabase")
            except Exception as e:
                print(f"❌ Error guardando ajustes en Supabase: {e}")
    
    def obtener_ajustes(self, fecha, empresa='General'):
        """Obtiene los ajustes (prioriza Supabase, fallback a SQLite)"""
        
        # --- 1. Intentar desde Supabase ---
        if self.use_supabase and self.client:
            try:
                result = self.client.table('ajustes')\
                    .select('*')\
                    .eq('fecha', fecha)\
                    .eq('empresa', empresa)\
                    .execute()
                
                if result.data:
                    ajustes = {}
                    for row in result.data:
                        ajustes[row['cuenta']] = {
                            'monto': row['monto'],
                            'justificacion': row['justificacion']
                        }
                    # Asegurar que todas las cuentas existan
                    for cuenta in ['inventario', 'cx_c', 'cx_p', 'transito']:
                        if cuenta not in ajustes:
                            ajustes[cuenta] = {'monto': 0.0, 'justificacion': ''}
                    return ajustes
            except Exception as e:
                print(f"⚠️ Error en Supabase (obtener_ajustes): {e}")
        
        # --- 2. Fallback a SQLite ---
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT inv_monto, inv_just, cxc_monto, cxc_just, cxp_monto, cxp_just, transito_monto, transito_just
            FROM ajustes_diarios
            WHERE fecha = ? AND empresa = ?
        ''', (fecha, empresa))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'inventario': {'monto': row[0], 'justificacion': row[1]},
                'cx_c': {'monto': row[2], 'justificacion': row[3]},
                'cx_p': {'monto': row[4], 'justificacion': row[5]},
                'transito': {'monto': row[6], 'justificacion': row[7]}
            }
        else:
            return {
                'inventario': {'monto': 0.0, 'justificacion': ''},
                'cx_c': {'monto': 0.0, 'justificacion': ''},
                'cx_p': {'monto': 0.0, 'justificacion': ''},
                'transito': {'monto': 0.0, 'justificacion': ''}
            }
    
    # ============================================================
    # 6. OTROS MÉTODOS (MANTENIDOS SIN CAMBIOS)
    # ============================================================
    
    def guardar_auditoria_archivo(self, fecha_proceso, nombre_archivo, tipo_archivo, 
                                   registros, estado, error=None, usuario=None, empresa='General'):
        """Registra la auditoría de un archivo cargado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO auditoria_archivos 
            (fecha_proceso, empresa, nombre_archivo, tipo_archivo, registros, estado, error, usuario)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (fecha_proceso, empresa, nombre_archivo, tipo_archivo, registros, estado, error, usuario))
        conn.commit()
        conn.close()
    
    def obtener_inconsistencias(self, fecha=None, empresa='General'):
        """Obtiene las inconsistencias registradas"""
        conn = sqlite3.connect(self.db_path)
        if fecha:
            df = pd.read_sql_query(
                "SELECT * FROM inconsistencias WHERE fecha = ? AND empresa = ? ORDER BY created_at DESC",
                conn, params=[fecha, empresa]
            )
        else:
            df = pd.read_sql_query(
                "SELECT * FROM inconsistencias WHERE empresa = ? ORDER BY created_at DESC LIMIT 100",
                conn, params=[empresa]
            )
        conn.close()
        return df
    
    def guardar_tasa_bcv(self, fecha, tasa):
        """Guarda la tasa BCV para una fecha específica"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO tasas_bcv
            (fecha, tasa)
            VALUES (?, ?)
        """, (fecha, tasa))
        conn.commit()
        conn.close()
    
    def obtener_tasa_bcv(self, fecha):
        """Obtiene la tasa BCV para una fecha específica"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tasa
            FROM tasas_bcv
            WHERE fecha = ?
        """, (fecha,))
        resultado = cursor.fetchone()
        conn.close()
        if resultado:
            return float(resultado[0])
        return None

    def limpiar_saldos(self, empresa=None):
        """Limpia los saldos de la base de datos, opcionalmente filtrados por empresa"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if empresa:
            cursor.execute("DELETE FROM saldos_diarios WHERE empresa = ?", (empresa,))
            cursor.execute("DELETE FROM ajustes_diarios WHERE empresa = ?", (empresa,))
            cursor.execute("DELETE FROM inconsistencias WHERE empresa = ?", (empresa,))
            cursor.execute("DELETE FROM auditoria_archivos WHERE empresa = ?", (empresa,))
        else:
            cursor.execute("DELETE FROM saldos_diarios")
            cursor.execute("DELETE FROM ajustes_diarios")
            cursor.execute("DELETE FROM inconsistencias")
            cursor.execute("DELETE FROM auditoria_archivos")
        conn.commit()
        conn.close()

    def obtener_historial_saldos(self, limite=30, empresa='General'):
        """Obtiene el historial de saldos de los últimos N días (fallback)"""
        return self.obtener_historial_saldos_completo(limite, empresa)
