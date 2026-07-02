import os
import sys
import glob
import json
import pandas as pd
from datetime import datetime

# Mapear el módulo de Streamlit para simular la ejecución sin Streamlit instalado (solo si se ejecuta desde consola)
if __name__ == '__main__':
    class StreamlitMock:
        def cache_data(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
        def error(self, msg):
            bot_print(f"[ST Mock Error] {msg}")
        class cache_data_clear_mock:
            def clear(self):
                pass
        cache_data = cache_data_clear_mock()

    sys.modules['streamlit'] = StreamlitMock()

# Importar funciones del motor de auditoría
from motor_auditoria import (
    ejecutar_auditoria_inteligente, 
    guardar_resultado_cierre, 
    calcular_kpis, 
    buscar_excepcion
)

# Definición de directorios locales
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "datos_servidor")
REPORT_PATH = os.path.join(BASE_DIR, "errores_cierre_diario.xlsx")

def bot_print(text):
    """
    Función de impresión segura que previene caídas por codificación de caracteres (UnicodeEncodeError)
    reemplazando los emojis por texto plano en consolas de Windows estándar.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        # Mapeo de reemplazo de emojis para mantener la legibilidad
        clean_text = str(text)
        replacements = {
            "🤖": "[BOT]",
            "✓": "[OK]",
            "❌": "[ERROR]",
            "⏳": "[PROCESANDO]",
            "💾": "[GUARDADO]",
            "⚠️": "[ALERTA]",
            "✅": "[EXITOSO]",
            "🔴": "[ROJO]",
            "🟡": "[AMARILLO]",
            "🟠": "[NARANJA]",
            "🟢": "[VERDE]"
        }
        for emoji, txt in replacements.items():
            clean_text = clean_text.replace(emoji, txt)
        try:
            print(clean_text)
        except UnicodeEncodeError:
            print(clean_text.encode('ascii', errors='replace').decode('ascii'))

def buscar_archivo_por_patron(patrones):
    """
    Busca archivos Excel en datos_servidor que coincidan con alguno de los patrones.
    """
    if not os.path.exists(INPUT_DIR):
        os.makedirs(INPUT_DIR)
        return None
        
    for patron in patrones:
        archivos = glob.glob(os.path.join(INPUT_DIR, patron))
        if archivos:
            return sorted(archivos, key=os.path.getmtime, reverse=True)[0]
    return None

def enviar_notificacion(kpis, fallas_activas):
    """
    Formatea y envía una notificación con el resumen del cierre y KPIs.
    Actualmente imprime en consola como Mock, pero incluye la estructura para Telegram/Email.
    """
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    mensaje = (
        "🤖 *BOT AUTÓNOMO DE AUDITORÍA - REPORTE DE BALANCE*\n"
        "==================================================\n"
        f"📅 Fecha/Hora Cierre: {ahora}\n"
        f"💵 Tasa Oficial BCV: {kpis['tasa_bcv']:.2f} VES/USD\n"
        "--------------------------------------------------\n"
        f"📊 Total Banco Procesado: {kpis['total_ves']:,.2f} Bs.\n"
        f"📊 Total Consolidado USD: ${kpis['total_usd']:,.2f}\n"
        "--------------------------------------------------\n"
        "🚨 *Alertas Activas Detectadas:*\n"
        f"🔴 Rojas (No en Sistema): {kpis['alertas_rojas']}\n"
        f"🟡 Amarillas (iPago en Tránsito): {kpis['alertas_amarillas']}\n"
        f"🟠 Naranjas (Diferencia Monto): {kpis['alertas_naranjas']}\n"
        f"⚠️ Total Discrepancias Activas: {kpis['total_alertas']}\n"
        "==================================================\n"
    )
    
    if fallas_activas:
        mensaje += "📋 *Detalle de Alertas Activas (Primeras 5):*\n"
        for idx, f in enumerate(fallas_activas[:5], 1):
            emoji = "🔴" if f['tipo'] == 'ROJA' else ("🟠" if f['tipo'] == 'NARANJA' else "🟡")
            monto = f['monto_banco'] if f['monto_banco'] > 0 else f['monto_sistema']
            mensaje += f"{idx}. {emoji} Ref: {f['referencia']} | {f['origen']} | Monto: {monto:.2f} | {f['causa']}\n"
        
        mensaje += "\n 📝 *Acción:* Se ha exportado el reporte físico de discrepancias a 'errores_cierre_diario.xlsx'.\n"
    else:
        mensaje += "✅ *¡Cierre Diario Exitoso!* Todas las transacciones cuadran perfectamente contra excepciones históricas.\n"
        
    bot_print("\n[BOT NOTIFICACIÓN]")
    bot_print(mensaje)
    bot_print("--------------------------------------------------")
    
    # -------------------------------------------------------------
    # Nota para producción: Integración API de Telegram (Opcional)
    # -------------------------------------------------------------
    # import requests
    # TELEGRAM_TOKEN = "INGRESE_AQUI_TELEGRAM_BOT_TOKEN"
    # TELEGRAM_CHAT_ID = "INGRESE_AQUI_CHAT_ID_GRUPO_ANALISTAS"
    # url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # try:
    #     requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"})
    # except Exception as e:
    #     print(f"Error al enviar notificación a Telegram: {e}")

def ejecutar_cierre_automatico():
    """
    Función principal del Bot que busca archivos locales, ejecuta la auditoría inteligente,
    aplica las excepciones guardadas en SQLite3, genera el reporte en Excel y guarda los resultados en BD.
    """
    bot_print(f"🤖 Inciando Bot de Auditoría en: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. Búsqueda automática de archivos Excel en la ruta datos_servidor
    file_banco = buscar_archivo_por_patron(["*Banesco*.xlsx", "*BNC*.xlsx", "*Banco*.xlsx", "*banco*.xlsx", "*estado_cuenta*.xlsx"])
    file_ipago = buscar_archivo_por_patron(["*iPago*.xlsx", "*ipago*.xlsx", "*egresos*.xlsx", "*Egresos*.xlsx"])
    file_cobranzas = buscar_archivo_por_patron(["*Cobranzas*.xlsx", "*cobranzas*.xlsx", "*ingresos*.xlsx"])
    file_facturacion = buscar_archivo_por_patron(["*Facturacion*.xlsx", "*facturacion*.xlsx", "*facturas*.xlsx"])
    
    # Validar que existan los archivos mínimos
    if not file_banco and not file_ipago:
        bot_print("❌ Error: No se encontraron los archivos mínimos necesarios en 'datos_servidor/' (Banco e iPago). Abortando cierre.")
        return False
        
    bot_print(f"✓ Archivo Banco localizado: {os.path.basename(file_banco) if file_banco else 'No encontrado'}")
    bot_print(f"✓ Archivo iPago localizado: {os.path.basename(file_ipago) if file_ipago else 'No encontrado'}")
    bot_print(f"✓ Archivo Cobranzas localizado: {os.path.basename(file_cobranzas) if file_cobranzas else 'No encontrado'}")
    bot_print(f"✓ Archivo Facturación localizado: {os.path.basename(file_facturacion) if file_facturacion else 'No encontrado'}")
    
    # 2. Ejecutar auditoría inteligente
    bot_print("⏳ Ejecutando análisis cruzado y verificando excepciones históricas en la BD...")
    hay_errores, fallas, df_consolidado = ejecutar_auditoria_inteligente(
        file_facturacion, file_cobranzas, file_ipago, file_banco
    )
    
    # Calcular KPIs
    kpis = calcular_kpis(df_consolidado, tasa_bcv=36.50)
    
    # Filtrar fallas que son verdaderamente ACTIVAS (sin auto-corregir)
    fallas_activas = [f for f in fallas if f['tipo'] in ['ROJA', 'AMARILLA', 'NARANJA']]
    
    # 3. Guardar el resultado en la BD para visualización pasiva en Streamlit
    bot_print("💾 Guardando reporte consolidado y alertas de última corrida en la BD...")
    guardar_resultado_cierre(hay_errores, fallas, df_consolidado, kpis)
    
    # 4. Manejo de Alertas Activas y reporte físico
    if hay_errores:
        bot_print(f"⚠️ Se detectaron {len(fallas_activas)} discrepancias activas. Generando reporte Excel...")
        try:
            with pd.ExcelWriter(REPORT_PATH, engine='openpyxl') as writer:
                df_fallas_activas = pd.DataFrame(fallas_activas)
                cols_fallas = ['tipo', 'referencia', 'fecha_banco', 'monto_banco', 'fecha_sistema', 'monto_sistema', 'origen', 'causa', 'accion']
                df_fallas_activas[cols_fallas].to_excel(writer, sheet_name='Discrepancias Activas', index=False)
                
                df_consolidado.to_excel(writer, sheet_name='Reporte Consolidado Completo', index=False)
            bot_print(f"✓ Reporte físico creado exitosamente en: {REPORT_PATH}")
        except Exception as e:
            bot_print(f"❌ Error al escribir el reporte físico Excel: {e}")
    else:
        bot_print("✅ Balance limpio de alertas activas. El cierre diario se completó sin discrepancias.")
        if os.path.exists(REPORT_PATH):
            try:
                os.remove(REPORT_PATH)
            except:
                pass
                
    # 5. Enviar notificación
    enviar_notificacion(kpis, fallas_activas)
    bot_print("🤖 Bot de Auditoría finalizó sus tareas con éxito.")
    return True

if __name__ == "__main__":
    ejecutar_cierre_automatico()
