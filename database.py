# database.py
import os
import sqlite3
import pandas as pd
from datetime import datetime
from config import RUTA_BASE_DATOS


class Database:
    """Clase para manejar la base de datos SQLite"""
    
    def __init__(self):
        # Crear carpeta de base de datos si no existe
        if not os.path.exists(RUTA_BASE_DATOS):
            os.makedirs(RUTA_BASE_DATOS, exist_ok=True)
        self.db_path = os.path.join(RUTA_BASE_DATOS, 'conciliacion.db')
        self._inicializar_tablas()
    
    def _inicializar_tablas(self):
        """Crea las tablas necesarias si no existen"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Verificar si la columna 'empresa' existe en saldos_diarios para migrar si es necesario
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='saldos_diarios'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(saldos_diarios)")
            cols = [row[1] for row in cursor.fetchall()]
            if 'empresa' not in cols:
                # Tabla antigua detectada, la eliminamos para recrearla con soporte multi-empresa
                cursor.execute("DROP TABLE saldos_diarios")
        
        # Verificar si la columna 'inv_monto' existe en ajustes_diarios para migrar si es necesario
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ajustes_diarios'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(ajustes_diarios)")
            cols_aj = [row[1] for row in cursor.fetchall()]
            if 'inv_monto' not in cols_aj:
                # Tabla antigua detectada, la eliminamos para recrearla con la nueva estructura
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
        
        # Tabla de tasas BCV (nueva)
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
    
    def guardar_saldos(self, fecha, saldos, empresa='General'):
        """Guarda los saldos de un día específico para una empresa dada"""
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
    
    def obtener_saldos(self, fecha, empresa='General'):
        """Obtiene los saldos de una fecha específica para una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE fecha = ? AND empresa = ?",
            conn, params=[fecha, empresa]
        )
        conn.close()
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    
    def obtener_ultimo_saldo(self, empresa='General'):
        """Obtiene el último saldo registrado para una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE empresa = ? ORDER BY fecha DESC LIMIT 1",
            conn, params=[empresa]
        )
        conn.close()
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    
    def guardar_inconsistencia(self, fecha, cuenta, calc, reportado, diferencia, descripcion, empresa='General'):
        """Guarda una inconsistencia detectada para una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO inconsistencias 
            (fecha, empresa, cuenta, valor_calculado, valor_reportado, diferencia, descripcion)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (fecha, empresa, cuenta, calc, reportado, diferencia, descripcion))
        conn.commit()
        conn.close()
    
    def guardar_auditoria_archivo(self, fecha_proceso, nombre_archivo, tipo_archivo, 
                                   registros, estado, error=None, usuario=None, empresa='General'):
        """Registra la auditoría de un archivo cargado para una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO auditoria_archivos 
            (fecha_proceso, empresa, nombre_archivo, tipo_archivo, registros, estado, error, usuario)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (fecha_proceso, empresa, nombre_archivo, tipo_archivo, registros, estado, error, usuario))
        conn.commit()
        conn.close()
    
    def obtener_historial_saldos(self, limite=30, empresa='General'):
        """Obtiene el historial de saldos de los últimos N días para una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE empresa = ? ORDER BY fecha DESC LIMIT ?",
            conn, params=[empresa, limite]
        )
        conn.close()
        return df
    
    def obtener_inconsistencias(self, fecha=None, empresa='General'):
        """Obtiene las inconsistencias registradas para una empresa dada"""
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

    def obtener_historial_por_fechas(self, desde, hasta, empresa='General'):
        """Obtiene el historial de saldos entre dos fechas para una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE empresa = ? AND fecha >= ? AND fecha <= ? ORDER BY fecha ASC",
            conn, params=[empresa, desde, hasta]
        )
        conn.close()
        return df

    def obtener_historial_saldos_completo(self, limite=30, empresa='General'):
        """Obtiene el historial completo de saldos de una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE empresa = ? ORDER BY fecha DESC LIMIT ?",
            conn, params=[empresa, limite]
        )
        conn.close()
        return df

    def guardar_ajustes(self, fecha, ajustes, empresa='General'):
        """Guarda los ajustes diarios aplicados a las cuentas para una empresa dada"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        inv = ajustes.get('inventario', {'monto': 0.0, 'justificacion': ''})
        cxc = ajustes.get('cx_c', {'monto': 0.0, 'justificacion': ''})
        cxp = ajustes.get('cx_p', {'monto': 0.0, 'justificacion': ''})
        transito = ajustes.get('transito', {'monto': 0.0, 'justificacion': ''})
        
        cursor.execute('''
            INSERT OR REPLACE INTO ajustes_diarios 
            (fecha, empresa, inv_monto, inv_just, cxc_monto, cxc_just, cxp_monto, cxp_just, transito_monto, transito_just)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            fecha,
            empresa,
            inv.get('monto', 0.0),
            inv.get('justificacion', ''),
            cxc.get('monto', 0.0),
            cxc.get('justificacion', ''),
            cxp.get('monto', 0.0),
            cxp.get('justificacion', ''),
            transito.get('monto', 0.0),
            transito.get('justificacion', '')
        ))
        conn.commit()
        conn.close()

    def obtener_ajustes(self, fecha, empresa='General'):
        """Obtiene los ajustes diarios aplicados para una fecha y empresa dada"""
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
