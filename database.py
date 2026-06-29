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
        
        # Tabla de saldos diarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saldos_diarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha DATE NOT NULL,
                inventario REAL DEFAULT 0,
                cx_c REAL DEFAULT 0,
                bancos REAL DEFAULT 0,
                cx_p REAL DEFAULT 0,
                transito REAL DEFAULT 0,
                capital REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(fecha)
            )
        ''')
        
        # Tabla de movimientos procesados
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movimientos_diarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha DATE NOT NULL,
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
        
        conn.commit()
        conn.close()
    
    def guardar_saldos(self, fecha, saldos):
        """Guarda los saldos de un día específico"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO saldos_diarios 
            (fecha, inventario, cx_c, bancos, cx_p, transito, capital)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            fecha,
            saldos.get('inventario', 0),
            saldos.get('cx_c', 0),
            saldos.get('bancos', 0),
            saldos.get('cx_p', 0),
            saldos.get('transito', 0),
            saldos.get('capital', 0)
        ))
        conn.commit()
        conn.close()
    
    def obtener_saldos(self, fecha):
        """Obtiene los saldos de una fecha específica"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios WHERE fecha = ?",
            conn, params=[fecha]
        )
        conn.close()
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    
    def obtener_ultimo_saldo(self):
        """Obtiene el último saldo registrado"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios ORDER BY fecha DESC LIMIT 1",
            conn
        )
        conn.close()
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    
    def guardar_inconsistencia(self, fecha, cuenta, calc, reportado, diferencia, descripcion):
        """Guarda una inconsistencia detectada"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO inconsistencias 
            (fecha, cuenta, valor_calculado, valor_reportado, diferencia, descripcion)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (fecha, cuenta, calc, reportado, diferencia, descripcion))
        conn.commit()
        conn.close()
    
    def guardar_auditoria_archivo(self, fecha_proceso, nombre_archivo, tipo_archivo, 
                                   registros, estado, error=None, usuario=None):
        """Registra la auditoría de un archivo cargado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO auditoria_archivos 
            (fecha_proceso, nombre_archivo, tipo_archivo, registros, estado, error, usuario)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (fecha_proceso, nombre_archivo, tipo_archivo, registros, estado, error, usuario))
        conn.commit()
        conn.close()
    
    def obtener_historial_saldos(self, limite=30):
        """Obtiene el historial de saldos de los últimos N días"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT * FROM saldos_diarios ORDER BY fecha DESC LIMIT ?",
            conn, params=[limite]
        )
        conn.close()
        return df
    
    def obtener_historial_saldos_completo(self, limite=30):
        """Obtiene el historial de saldos con capital de los últimos N días
        
        Args:
            limite (int): Número de días a consultar (default 30)
        
        Returns:
            DataFrame: Historial de saldos incluyendo capital
        """
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            """SELECT 
                fecha, 
                inventario, 
                cx_c, 
                bancos, 
                cx_p, 
                transito, 
                capital,
                created_at
            FROM saldos_diarios 
            ORDER BY fecha DESC 
            LIMIT ?""",
            conn, params=[limite]
        )
        conn.close()
        return df
    
    def obtener_historial_capital(self, limite=30):
        """Obtiene solo el historial de capital de los últimos N días
        
        Args:
            limite (int): Número de días a consultar (default 30)
        
        Returns:
            DataFrame: Historial de capital
        """
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            "SELECT fecha, capital FROM saldos_diarios ORDER BY fecha DESC LIMIT ?",
            conn, params=[limite]
        )
        conn.close()
        return df
    
    # ============================================================
    # 🔥 NUEVO MÉTODO: OBTENER HISTORIAL POR RANGO DE FECHAS
    # ============================================================
    def obtener_historial_por_fechas(self, fecha_desde, fecha_hasta):
        """
        Obtiene el historial de saldos en un rango de fechas
        
        Args:
            fecha_desde (str): Fecha de inicio en formato YYYY-MM-DD
            fecha_hasta (str): Fecha de fin en formato YYYY-MM-DD
        
        Returns:
            DataFrame: Historial de saldos en el rango de fechas
        """
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(
            """SELECT 
                fecha, 
                inventario, 
                cx_c, 
                bancos, 
                cx_p, 
                transito, 
                capital,
                created_at
            FROM saldos_diarios 
            WHERE fecha BETWEEN ? AND ?
            ORDER BY fecha DESC""",
            conn, params=[fecha_desde, fecha_hasta]
        )
        conn.close()
        return df
    
    def obtener_inconsistencias(self, fecha=None):
        """Obtiene las inconsistencias registradas"""
        conn = sqlite3.connect(self.db_path)
        if fecha:
            df = pd.read_sql_query(
                "SELECT * FROM inconsistencias WHERE fecha = ? ORDER BY created_at DESC",
                conn, params=[fecha]
            )
        else:
            df = pd.read_sql_query(
                "SELECT * FROM inconsistencias ORDER BY created_at DESC LIMIT 100",
                conn
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
    
    def eliminar_saldo(self, fecha):
        """Elimina los saldos de una fecha específica"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "DELETE FROM saldos_diarios WHERE fecha = ?",
            (fecha,)
        )
        
        conn.commit()
        conn.close()
    
    def limpiar_saldos(self):
        """Elimina TODOS los saldos de la tabla saldos_diarios"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM saldos_diarios")
        
        conn.commit()
        conn.close()
