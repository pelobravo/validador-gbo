# logger.py
import logging
import os
from datetime import datetime
from config import RUTA_LOGS, LOG_NIVEL, LOG_FORMATO

class Logger:
    """Clase para manejar el logging del sistema"""
    
    _instances = {}
    
    def __new__(cls, name='validador'):
        if name not in cls._instances:
            cls._instances[name] = super(Logger, cls).__new__(cls)
            cls._instances[name]._inicializar(name)
        return cls._instances[name]
    
    def _inicializar(self, name):
        # Asegurar que la carpeta de logs existe
        os.makedirs(RUTA_LOGS, exist_ok=True)
        
        self.logger = logging.getLogger(name)
        nivel = getattr(logging, LOG_NIVEL.upper(), logging.INFO)
        self.logger.setLevel(nivel)
        
        # Crear archivo de log por día
        log_file = os.path.join(RUTA_LOGS, f"{datetime.now().strftime('%Y%m%d')}.log")
        
        # File handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(nivel)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(nivel)
        
        # Formatter
        formatter = logging.Formatter(LOG_FORMATO)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def info(self, mensaje):
        self.logger.info(mensaje)
    
    def warning(self, mensaje):
        self.logger.warning(mensaje)
    
    def error(self, mensaje):
        self.logger.error(mensaje)
    
    def debug(self, mensaje):
        self.logger.debug(mensaje)
    
    def log_procesamiento(self, tipo_archivo, registros, estado, error=None):
        """Registra el procesamiento de un archivo"""
        mensaje = f"Archivo: {tipo_archivo} | Registros: {registros} | Estado: {estado}"
        if error:
            mensaje += f" | Error: {error}"
        
        if estado == 'ERROR':
            self.error(mensaje)
        elif estado == 'WARNING':
            self.warning(mensaje)
        else:
            self.info(mensaje)