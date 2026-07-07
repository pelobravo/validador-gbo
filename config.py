# config.py
# CONFIGURACIÓN DEL SISTEMA DE CONCILIACIÓN
# GRUPO BODEGUITA ORIENTE
# ==========================================

import os

# =============================================
# 1. RUTAS DEL SISTEMA (Auto-detecta el entorno)
# =============================================

# 🔥 OBTENER LA CARPETA DONDE ESTÁ ESTE ARCHIVO
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🔥 USAR RUTAS RELATIVAS (funciona en cualquier entorno)
RUTA_BASE = BASE_DIR

# Subcarpetas (se crearán automáticamente)
RUTA_ARCHIVOS = os.path.join(RUTA_BASE, "01_ARCHIVOS_SUBIDOS")
RUTA_BASE_DATOS = os.path.join(RUTA_BASE, "02_BASE_DATOS")
RUTA_LOGS = os.path.join(RUTA_BASE, "03_LOG_AUDITORIA")
RUTA_PLANTILLAS = os.path.join(RUTA_BASE, "04_PLANTILLAS")
RUTA_REPORTES = os.path.join(RUTA_BASE, "05_REPORTES")
RUTA_DOCS = os.path.join(RUTA_BASE, "06_DOCUMENTACION")

# =============================================
# 2. USUARIOS DEL SISTEMA (CON EMPRESA ASIGNADA)
# =============================================

USUARIOS = {
    "analista1": {
        "nombre": "Marian Guaipo",
        "email": "marianguaipo@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123",
        "empresa": "Bodeguita Monagas"  # 🔥 NUEVO
    },
    "analista2": {
        "nombre": "Francia Mota",
        "email": "franciamota@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123",
        "empresa": "Bodeguita Nororiental"  # 🔥 NUEVO
    },
    "analista3": {
        "nombre": "Carmen Villahermosa",
        "email": "carmenvillahermosa@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123",
        "empresa": "Bodeguita Guayana"  # 🔥 NUEVO
    },
    "analista4": {
        "nombre": "Aura Galán",
        "email": "auragalan@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123",
        "empresa": "Bodeguita Anzoátegui"  # 🔥 NUEVO
    },
    "analista5": {
        "nombre": "Ismariely Gómez",
        "email": "ismarielygomez@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123",
        "empresa": "Nexo Comercial Oriente"  # 🔥 SU EMPRESA CORRECTA
    },
    "analista6": {
        "nombre": "Mayerlin Rondón",
        "email": "mayerlinrondon@grupobodeguita.com",
        "rol": "analista",
        "password": "cambiar123",
        "empresa": "Auditora Principal"  # 🔥 NUEVO
    },
    "supervisor1": {
        "nombre": "Mayerlin Rondón",
        "email": "mayerlinrondon@grupobodeguita.com",
        "rol": "supervisor",
        "password": "cambiar123",
        "empresa": "📊 Dashboard General"  # 🔥 NUEVO
    },
    "auditor1": {
        "nombre": "Gabriel Palomo",
        "email": "gabrielpalomo@grupobodeguita.com",
        "rol": "auditor",
        "password": "cambiar123",
        "empresa": "📊 Dashboard General"  # 🔥 NUEVO
    },
    "admin": {
        "nombre": "Administrador",
        "email": "carlos.marcano@grupobodeguita.com",
        "rol": "admin",
        "password": "admin123",
        "empresa": "📊 Dashboard General"  # 🔥 NUEVO
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

def get_empresa_usuario(usuario_id):
    """Obtiene la empresa asignada a un usuario"""
    
    if usuario_id in USUARIOS:
        return USUARIOS[usuario_id].get("empresa", "General")
    return "General"

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
        print(f"📂 Carpeta validada/creada: {carpeta}")
    
    print("✅ Carpetas validadas/creadas correctamente")
    print(f"📁 Ruta base: {RUTA_BASE}")
    print(f"👥 Usuarios cargados: {len(USUARIOS)}")

# Si ejecutan este archivo directamente, validar carpetas
if __name__ == "__main__":
    validar_carpetas()
