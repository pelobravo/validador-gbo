# api_bcv.py
import requests
import json
from datetime import datetime
from config import TASA_BCV_POR_DEFECTO

def obtener_tasa_bcv():
    """
    Obtiene la tasa de cambio del BCV
    """
    # Placeholder - En producción, conectar con API real del BCV
    # Por ahora retorna la tasa por defecto de config
    return TASA_BCV_POR_DEFECTO

def obtener_tasa_paralelo():
    """Obtiene la tasa paralelo"""
    # Placeholder
    return TASA_BCV_POR_DEFECTO

def convertir_moneda(monto, tasa=None):
    """Convierte un monto usando la tasa especificada"""
    if tasa is None:
        tasa = obtener_tasa_bcv()
    return monto * tasa