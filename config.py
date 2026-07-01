# config.py
# CONFIGURACIÓN DEL SISTEMA DE CONCILIACIÓN
# GRUPO BODEGUITA ORIENTE
# ==========================================

import os

# =============================================
# 1. RUTAS DEL SISTEMA (Ajustar según su servidor)
# =============================================

# Windows (usar esta)
RUTA_BASE = r"C:\CONCILIACION_GBO"

# Linux/Mac (descomentar y comentar la de Windows)
# RUTA_BASE = "/home/usuario/CONCILIACION_GBO"

# Subcarpetas
RUTA_ARCHIVOS = os.path.join(RUTA_BASE, "01_ARCHIVOS_SUBIDOS")
RUTA_BASE_DATOS = os.path.join(RUTA_BASE, "02_BASE_DATOS")
RUTA_LOGS = os.path.join(RUTA_BASE, "03_LOG_AUDITORIA")
RUTA_PLANTILLAS = os.path.join(RUTA_BASE, "04_PLANTILLAS")
RUTA_REPORTES = os.path.join(RUTA_BASE, "05_REPORTES")
RUTA_DOCS = os.path.join(RUTA_BASE, "06_DOCUMENTACION")

# =============================================
# 2. USUARIOS DEL SISTEMA (Tarea 4)
# =============================================

USUARIOS = {
    "analista1": {
        "nombre": "Marian Guaipo",
        "email": "marianguaipo@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123"  # CAMBIAR en primera ejecución
    },
    "analista2": {
        "nombre": "Francia Mota",
        "email": "franciamota@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123"
    },
    "analista3": {
        "nombre": "Carmen Villahermosa",
        "email": "carmenvillahermosa@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123"
    },
    "analista4": {
        "nombre": "Aura Galán",
        "email": "auragalan@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123"
    },
    "analista5": {
        "nombre": "Ismariely Gómez",
        "email": "ismarielygomez@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123"
    },
    "analista6": {
        "nombre": "Mayerlin Rondón",
        "email": "mayerlinrondon@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123"
    },
    "supervisor1": {
        "nombre": "Mayerlin Rondón",
        "email": "mayerlinrondon@grupobodeguita.com",
        "rol": "supervisor",
        "password": "cambiar123"
    },
    "auditor1": {
        "nombre": "Gabriel Palomo",
        "email": "gabrielpalomo@grupobodeguita.com",
        "rol": "auditor",
        "password": "cambiar123"
    },
    "admin": {
        "nombre": "Administrador",
        "email": "carlos.marcano@grupobodeguita.com",
        "rol": "admin",
        "password": "admin123"  # CAMBIAR después de la primera ejecución
    }
}

# =============================================
# 3. DEFINICIÓN DE ROLES Y PERMISOS
# =============================================

PERMISOS = {
    "analista": [
        "subir_archivos",
        "procesar_dia",
        "ver_historico"
    ],
    "supervisor": [
        "subir_archivos",
        "procesar_dia",
        "ver_historico",
        "aprobar_conciliacion",
        "ver_logs"
    ],
    "auditor": [
        "ver_historico",
        "ver_logs",
        "exportar_reportes"
    ],
    "admin": [
        "subir_archivos",
        "procesar_dia",
        "ver_historico",
        "aprobar_conciliacion",
        "ver_logs",
        "exportar_reportes",
        "gestionar_usuarios",
        "modificar_configuracion"
    ]
}

# =============================================
# 4. CONFIGURACIÓN DE RESPALDOS
# =============================================

BACKUP_HORA = "23:00"
BACKUP_DIAS_RETENCION = 90  # Días que se guardan los backups

# =============================================
# 5. NOTIFICACIONES
# =============================================

CORREO_ERRORES = "auditoria@grupobodeguita.com"
CORREO_SOPORTE = "soporte@grupobodeguita.com"

# =============================================
# 6. TASA DE CAMBIO
# =============================================

TASA_BCV_POR_DEFECTO = 544.5794

# =============================================
# 7. UMBRALES DE ALERTA
# =============================================

ALERTA_DIFERENCIA_MAXIMA = 100000  # Bs (alerta si diferencia > 100.000)
ALERTA_INVENTARIO_MINIMO = 7       # Días (alerta si inventario < 7 días)

# =============================================
# 8. CONFIGURACIÓN DE LOGS
# =============================================

LOG_NIVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FORMATO = "%(asctime)s | %(levelname)s | %(message)s"

# =============================================
# 9. FUNCIÓN PARA VERIFICAR PERMISOS
# =============================================

def tiene_permiso(usuario_id, accion):
    """Verifica si un usuario tiene permiso para realizar una acción"""
    
    if usuario_id not in USUARIOS:
        return False
    
    rol = USUARIOS[usuario_id]["rol"]
    
    if rol == "admin":
        return True
    
    return accion in PERMISOS.get(rol, [])

def get_usuario_info(usuario_id):
    """Obtiene la información de un usuario"""
    
    if usuario_id in USUARIOS:
        return USUARIOS[usuario_id]
    return None

# =============================================
# 10. VALIDAR QUE LAS CARPETAS EXISTAN
# =============================================

def validar_carpetas():
    """Crea las carpetas si no existen"""
    
    carpetas = [
        RUTA_ARCHIVOS,
        RUTA_BASE_DATOS,
        os.path.join(RUTA_BASE_DATOS, "backup"),
        RUTA_LOGS,
        RUTA_PLANTILLAS,
        RUTA_REPORTES,
        RUTA_DOCS
    ]
    
    for carpeta in carpetas:
        os.makedirs(carpeta, exist_ok=True)
    
    print("✅ Carpetas validadas/creadas correctamente")

# Si ejecutan este archivo directamente, validar carpetas
if __name__ == "__main__":
    validar_carpetas()
    print(f"📁 Ruta base: {RUTA_BASE}")
    print(f"👥 Usuarios cargados: {len(USUARIOS)}")
