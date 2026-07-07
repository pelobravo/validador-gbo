# crear_bd.py
import sqlite3
import os

def crear_base_datos():
    # Obtener la ruta donde está app.py
    ruta_app = os.path.dirname(os.path.abspath(__file__))
    ruta_db = os.path.join(ruta_app, 'saldos_diarios.db')
    
    print(f"📂 Creando base de datos en: {ruta_db}")
    
    try:
        conn = sqlite3.connect(ruta_db)
        cursor = conn.cursor()
        
        # Crear tabla saldos_diarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saldos_diarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                empresa TEXT,
                inventario REAL,
                cx_c REAL,
                bancos REAL,
                cx_p REAL,
                transito REAL,
                capital REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Crear tabla inconsistencias
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS inconsistencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                cuenta TEXT,
                valor_calculado REAL,
                valor_reportado REAL,
                diferencia REAL,
                descripcion TEXT,
                empresa TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Crear tabla ajustes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ajustes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                empresa TEXT,
                cuenta TEXT,
                monto REAL,
                justificacion TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Crear tabla tasa_bcv
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasa_bcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT UNIQUE,
                tasa REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
        print(f"✅ Base de datos creada exitosamente en: {ruta_db}")
        print("📊 Tablas creadas: saldos_diarios, inconsistencias, ajustes, tasa_bcv")
        return True
        
    except Exception as e:
        print(f"❌ Error al crear la base de datos: {e}")
        return False

if __name__ == "__main__":
    crear_base_datos()
