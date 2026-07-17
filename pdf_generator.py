# pdf_generator.py - Generador de Reporte PDF Ejecutivo para Validador Motor de Auditoría
import io
from datetime import datetime
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Configurar backend no interactivo
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY

# ============================================================
# FORMATEADORES DE NÚMEROS
# ============================================================
def formato_venezolano_pdf(valor):
    """
    Formatea un número al estilo venezolano: 1.234.567,89
    """
    if valor is None or pd.isna(valor) or valor == "":
        return ""
    try:
        val_float = float(valor)
        signo = "-" if val_float < 0 else ""
        abs_val = abs(val_float)
        partes = f"{abs_val:.2f}".split('.')
        entera = partes[0]
        decimal = partes[1]
        
        # Añadir puntos de millar
        resultado_entera = ""
        for idx, digito in enumerate(reversed(entera)):
            if idx > 0 and idx % 3 == 0:
                resultado_entera = "." + resultado_entera
            resultado_entera = digito + resultado_entera
            
        return f"{signo}{resultado_entera},{decimal}"
    except:
        return str(valor)

def formato_abreviado_pdf(valor):
    """
    Formatea un número de forma abreviada (ej. 18.5k o 1.2M)
    """
    if valor is None or pd.isna(valor) or valor == "":
        return "0"
    try:
        val_float = float(valor)
        signo = "-" if val_float < 0 else ""
        abs_val = abs(val_float)
        if abs_val >= 1_000_000:
            return f"{signo}{abs_val / 1_000_000:.1f}M"
        elif abs_val >= 1_000:
            return f"{signo}{abs_val / 1_000:.1f}k"
        return f"{signo}{abs_val:.0f}"
    except:
        return str(valor)

# ============================================================
# GENERADOR DEL GRÁFICO MATPLOTLIB
# ============================================================
def generar_grafico_barras_egresos(df_egresos_resumen, total_egresos):
    """
    Genera un gráfico de barras horizontales estilizado y lo devuelve como BytesIO.
    """
    if df_egresos_resumen is None or df_egresos_resumen.empty or total_egresos <= 0:
        # Retornar una imagen en blanco/placeholder si no hay datos
        fig, ax = plt.subplots(figsize=(5, 1.8))
        ax.text(0.5, 0.5, "Sin datos de egresos disponibles", 
                va='center', ha='center', fontsize=10, color='gray')
        ax.axis('off')
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png', dpi=300, transparent=True)
        img_buf.seek(0)
        plt.close(fig)
        return img_buf

    # Limpiar y copiar los datos para el gráfico
    df_chart = df_egresos_resumen.copy()
    
    # Asegurar que las columnas sean las correctas
    col_tipo = 'Tipo de Egreso'
    col_monto = 'Monto (Bs.)'
    
    # Agrupar si hay más de 5 categorías para no saturar el gráfico
    top_n = 5
    if len(df_chart) > top_n:
        top_data = df_chart.head(top_n).copy()
        otros_monto = df_chart.iloc[top_n:][col_monto].sum()
        otros_porc = (otros_monto / total_egresos * 100)
        
        otros_df = pd.DataFrame([{
            col_tipo: 'Otros',
            col_monto: otros_monto,
            'Porcentaje': otros_porc
        }])
        df_chart = pd.concat([top_data, otros_df], ignore_index=True)
    else:
        df_chart['Porcentaje'] = (df_chart[col_monto] / total_egresos * 100)

    # Invertir orden para que la categoría mayor quede arriba en el gráfico horizontal
    df_chart = df_chart.iloc[::-1].reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(5.5, 1.8))

    # Colores en gradiente de azul (estilo premium)
    colors = ['#5dade2', '#3498db', '#2980b9', '#1f618d', '#1a5276', '#113f67']
    # Ajustar cantidad de colores a las categorías
    colors = colors[-len(df_chart):]

    # Dibujar las barras
    bars = ax.barh(df_chart[col_tipo], df_chart['Porcentaje'], color=colors, height=0.55, edgecolor='none')

    # Configurar límites y remover bordes (spines)
    ax.set_xlim(0, max(df_chart['Porcentaje'].max() * 1.25, 10))
    for spine in ['top', 'right', 'bottom', 'left']:
        ax.spines[spine].set_visible(False)

    # Ocultar ticks y líneas del eje X
    ax.xaxis.set_visible(False)
    ax.tick_params(axis='y', length=0, labelsize=7.5, colors='#2c3e50')

    # Añadir las etiquetas con el porcentaje y el monto abreviado
    for bar, (_, row) in zip(bars, df_chart.iterrows()):
        width = bar.get_width()
        monto_val = float(row[col_monto])
        monto_str = formato_abreviado_pdf(monto_val)
        label_text = f"{width:.1f}% ({monto_str})"
        ax.text(width + 1, bar.get_y() + bar.get_height()/2, label_text, 
                va='center', ha='left', fontsize=7.5, color='#2c3e50', fontweight='semibold')

    plt.tight_layout()
    img_buf = io.BytesIO()
    plt.savefig(img_buf, format='png', dpi=300, transparent=True)
    img_buf.seek(0)
    plt.close(fig)
    return img_buf

# ============================================================
# FUNCIÓN PRINCIPAL DE GENERACIÓN DE PDF
# ============================================================
def generar_pdf_reporte(fecha_procesar, empresa_activa, capital_neto, activos_operativos, pasivos_operativos,
                        bancos_cierre, cx_c_cierre, inventario_cierre, cx_p_cierre, transito_cierre,
                        ratio_liquidez, prueba_acida, df_cxp_detalle=None, df_egresos_resumen=None,
                        total_egresos_general=0.0):
    """
    Genera un reporte PDF con diseño ejecutivo de doble columna.
    """
    output = io.BytesIO()
    
    # Crear documento con márgenes de 0.5 pulgadas (36 pt)
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    # Ancho imprimible total = 595.27 - 72 = 523.27 pt
    ancho_columna = 250
    ancho_separador = 23
    
    styles = getSampleStyleSheet()
    
    # Crear estilos de texto personalizados
    style_normal = ParagraphStyle('Norm', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor('#2c3e50'))
    style_normal_bold = ParagraphStyle('NormB', parent=style_normal, fontName='Helvetica-Bold')
    style_normal_right = ParagraphStyle('NormR', parent=style_normal, alignment=TA_RIGHT)
    style_normal_right_bold = ParagraphStyle('NormRB', parent=style_normal_bold, alignment=TA_RIGHT)
    
    style_title = ParagraphStyle('TitleCustom', fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#0a1628'))
    style_subtitle = ParagraphStyle('SubTitleCustom', fontName='Helvetica-Oblique', fontSize=10, leading=13, textColor=colors.HexColor('#4a5568'))
    
    style_meta_label = ParagraphStyle('MetaLabel', fontName='Helvetica', fontSize=8, leading=10, alignment=TA_RIGHT, textColor=colors.HexColor('#4a5568'))
    style_meta_val = ParagraphStyle('MetaVal', fontName='Helvetica-Bold', fontSize=8, leading=10, alignment=TA_RIGHT, textColor=colors.HexColor('#0a1628'))
    
    style_section_header = ParagraphStyle('SecHeader', fontName='Helvetica-Bold', fontSize=10, leading=12, textColor=colors.HexColor('#0a1628'))
    
    style_card_title = ParagraphStyle('CardTitle', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#1f618d'))
    style_card_formula = ParagraphStyle('CardForm', fontName='Helvetica-Oblique', fontSize=6.5, leading=8, textColor=colors.HexColor('#7f8c8d'))
    
    story = []
    
    # ============================================================
    # 1. ENCABEZADO DEL REPORTE
    # ============================================================
    fecha_str = fecha_procesar.strftime('%d/%m/%Y') if isinstance(fecha_procesar, (datetime, pd.Timestamp)) else str(fecha_procesar)
    
    # Tabla de encabezado (2 columnas)
    header_data = [
        [
            Paragraph("Reporte de Trazabilidad y Capital de Trabajo", style_title),
            Paragraph(f"<b>Fecha:</b> {fecha_str}", style_meta_val)
        ],
        [
            Paragraph("Cuadro de Mando Ejecutivo de Liquidez y Flujo de Caja", style_subtitle),
            Paragraph("<b>Frecuencia:</b> Diaria", style_meta_val)
        ],
        [
            Paragraph(f"<b>Empresa:</b> {empresa_activa}", ParagraphStyle('EmpCustom', parent=style_subtitle, fontName='Helvetica-Bold', fontSize=9)),
            Paragraph("", style_meta_label)
        ]
    ]
    
    header_table = Table(header_data, colWidths=[360, 163])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    
    story.append(header_table)
    story.append(Spacer(1, 4))
    
    # Línea horizontal divisoria
    line_table = Table([[""]], colWidths=[523], rowHeights=[2])
    line_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#0a1628')),
        ('TOPPADDING', (0,0), (0,0), 0),
        ('BOTTOMPADDING', (0,0), (0,0), 0),
        ('LEFTPADDING', (0,0), (0,0), 0),
        ('RIGHTPADDING', (0,0), (0,0), 0),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 10))
    
    # ============================================================
    # 2. CONSTRUCCIÓN DE COLUMNA IZQUIERDA
    # ============================================================
    col_izq_flowables = []
    
    # --- TARJETA: CAPITAL DE TRABAJO NETO ---
    color_capital_bg = '#e8f8f5' if capital_neto >= 0 else '#fde8e8'
    color_capital_border = '#117a65' if capital_neto >= 0 else '#9b1c1c'
    color_capital_text = '#117a65' if capital_neto >= 0 else '#9b1c1c'
    
    style_card_amount = ParagraphStyle(
        'CardAmount', 
        fontName='Helvetica-Bold', 
        fontSize=20, 
        leading=24, 
        textColor=colors.HexColor(color_capital_text)
    )
    
    formula_text = f"Fórmula: Activo Corriente (Bs. {formato_venezolano_pdf(activos_operativos)}) - Pasivo Corriente (Bs. {formato_venezolano_pdf(pasivos_operativos)})"
    
    card_data = [
        [Paragraph("CAPITAL DE TRABAJO NETO", style_card_title)],
        [Paragraph(f"Bs. {formato_venezolano_pdf(capital_neto)}", style_card_amount)],
        [Paragraph(formula_text, style_card_formula)]
    ]
    
    card_table = Table(card_data, colWidths=[ancho_columna - 10])
    card_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(color_capital_bg)),
        ('LINEBEFORE', (0,0), (0,-1), 4, colors.HexColor(color_capital_border)),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    
    col_izq_flowables.append(card_table)
    col_izq_flowables.append(Spacer(1, 10))
    
    # --- SECCIÓN 1: ESTRUCTURA DE CAPITAL ---
    col_izq_flowables.append(Paragraph("1. ESTRUCTURA DE CAPITAL DE TRABAJO", style_section_header))
    col_izq_flowables.append(Spacer(1, 4))
    
    # Construcción de la tabla de estructura
    estruc_table_data = [
        # Encabezado Activos
        [Paragraph("<b>CONCEPTO / CUENTA</b>", ParagraphStyle('H1', parent=style_normal_bold, textColor=colors.white)),
         Paragraph("<b>MONTO (Bs.)</b>", ParagraphStyle('H2', parent=style_normal_right_bold, textColor=colors.white)),
         Paragraph("<b>SUBTOTAL</b>", ParagraphStyle('H3', parent=style_normal_right_bold, textColor=colors.white))],
        
        [Paragraph("ACTIVOS CORRIENTES", style_normal_bold), "", ""],
        [Paragraph("Saldos Bancarios (Caja y Bancos)", style_normal), Paragraph(formato_venezolano_pdf(bancos_cierre), style_normal_right), ""],
        [Paragraph("Cuentas por Cobrar (Clientes)", style_normal), Paragraph(formato_venezolano_pdf(cx_c_cierre), style_normal_right), ""],
        [Paragraph("Inventario Total (Valorizado)", style_normal), Paragraph(formato_venezolano_pdf(inventario_cierre), style_normal_right), ""],
        [Paragraph("<font color='#1e7e34'><b>Total Activos</b></font>", style_normal_bold), "", Paragraph(f"<font color='#1e7e34'><b>{formato_venezolano_pdf(activos_operativos)}</b></font>", style_normal_right_bold)],
        
        # Espaciador
        ["", "", ""],
        
        # Encabezado Pasivos
        [Paragraph("PASIVOS CORRIENTES", style_normal_bold), "", ""],
        [Paragraph("Cuentas por Pagar (Proveedores)", style_normal), Paragraph(formato_venezolano_pdf(cx_p_cierre), style_normal_right), ""],
        [Paragraph("Préstamos / TC (Monto TB)", style_normal), Paragraph(formato_venezolano_pdf(transito_cierre), style_normal_right), ""],
        [Paragraph("<font color='#d97706'><b>Total Pasivos</b></font>", style_normal_bold), "", Paragraph(f"<font color='#d97706'><b>{formato_venezolano_pdf(pasivos_operativos)}</b></font>", style_normal_right_bold)],
        
        # Espaciador
        ["", "", ""],
        
        # Capital Neto
        [Paragraph(f"<font color='{color_capital_text}'><b>CAPITAL DE TRABAJO NETO</b></font>", style_normal_bold), "", Paragraph(f"<font color='{color_capital_text}'><b>{formato_venezolano_pdf(capital_neto)}</b></font>", style_normal_right_bold)]
    ]
    
    # Ancho de columnas: concepto=130pt, monto=60pt, subtotal=60pt
    estruc_table = Table(estruc_table_data, colWidths=[130, 60, 60], rowHeights=[16, 12, 12, 12, 12, 13, 6, 12, 12, 12, 13, 6, 15])
    estruc_table.setStyle(TableStyle([
        # Fila de cabecera de la tabla
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0a1628')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ('TOPPADDING', (0,0), (-1,-1), 1),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#e2e8f0')),
        
        # Estilo para ACTIVOS CORRIENTES
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#f0f7ff')),
        # Estilo para Total Activos
        ('BACKGROUND', (0,5), (-1,5), colors.HexColor('#e8f5e9')),
        ('TEXTCOLOR', (2,5), (2,5), colors.HexColor('#1e7e34')),
        
        # Fila de separación vacía 1
        ('BACKGROUND', (0,6), (-1,6), colors.white),
        ('SPAN', (0,6), (-1,6)),
        ('LINEBELOW', (0,6), (-1,6), 0, colors.white),
        ('LINEABOVE', (0,6), (-1,6), 0, colors.white),
        
        # Estilo para PASIVOS CORRIENTES
        ('BACKGROUND', (0,7), (-1,7), colors.HexColor('#fff5f5')),
        # Estilo para Total Pasivos
        ('BACKGROUND', (0,10), (-1,10), colors.HexColor('#fff3e0')),
        ('TEXTCOLOR', (2,10), (2,10), colors.HexColor('#d97706')),
        
        # Fila de separación vacía 2
        ('BACKGROUND', (0,11), (-1,11), colors.white),
        ('SPAN', (0,11), (-1,11)),
        ('LINEBELOW', (0,11), (-1,11), 0, colors.white),
        ('LINEABOVE', (0,11), (-1,11), 0, colors.white),
        
        # Estilo para Capital de Trabajo Neto
        ('BACKGROUND', (0,12), (-1,12), colors.HexColor(color_capital_bg)),
        ('TEXTCOLOR', (2,12), (2,12), colors.HexColor(color_capital_text)),
    ]))
    
    col_izq_flowables.append(estruc_table)
    col_izq_flowables.append(Spacer(1, 10))
    
    # --- ANÁLISIS DE LIQUIDEZ ---
    color_liq = '#27ae60' if ratio_liquidez >= 1.5 else ('#f39c12' if ratio_liquidez >= 1.0 else '#c0392b')
    status_liq = 'Saludable' if ratio_liquidez >= 1.5 else ('Ajustado' if ratio_liquidez >= 1.0 else 'Crítico')
    
    color_acd = '#27ae60' if prueba_acida >= 1.0 else ('#f39c12' if prueba_acida >= 0.7 else '#c0392b')
    status_acd = 'Buena' if prueba_acida >= 1.0 else ('Atención' if prueba_acida >= 0.7 else 'Crítica')
    
    if ratio_liquidez >= 1.5 and prueba_acida >= 0.7:
        analisis_nota = "* El capital de trabajo neto es positivo y los ratios indican una excelente capacidad de pago. Salud financiera óptima."
    elif ratio_liquidez >= 1.0 and prueba_acida < 0.7:
        analisis_nota = "* Liquidez corriente aceptable, pero alta dependencia del inventario (prueba ácida baja). Se recomienda acelerar cobros."
    elif ratio_liquidez < 1.0:
        analisis_nota = "* Alerta: Capital de trabajo neto negativo. Los pasivos corrientes superan activos corrientes. Riesgo de liquidez alto."
    else:
        analisis_nota = "* Los ratios de liquidez se encuentran en niveles estables y dentro de los rangos de control normales."
        
    liq_data = [
        [Paragraph("<b>ANÁLISIS DE LIQUIDEZ</b>", ParagraphStyle('LiqT', parent=style_section_header, fontSize=9, textColor=colors.HexColor('#0a1628'))), ""],
        [Paragraph("Ratio de Liquidez Corriente:", style_normal), 
         Paragraph(f"<b>{ratio_liquidez:.2f}</b> <font color='{color_liq}'>({status_liq})</font>", style_normal_right)],
        [Paragraph("Prueba Ácida (Sin Inventario):", style_normal), 
         Paragraph(f"<b>{prueba_acida:.2f}</b> <font color='{color_acd}'>({status_acd})</font>", style_normal_right)],
        [Paragraph(analisis_nota, ParagraphStyle('LiqN', parent=style_normal, fontSize=7, leading=9, textColor=colors.HexColor('#4a5568'))), ""]
    ]
    
    liq_table = Table(liq_data, colWidths=[150, 100])
    liq_table.setStyle(TableStyle([
        ('SPAN', (0,0), (1,0)),
        ('SPAN', (0,3), (1,3)),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('LINEBEFORE', (0,0), (0,-1), 4, colors.HexColor('#3498db')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    
    col_izq_flowables.append(liq_table)
    
    # ============================================================
    # 3. CONSTRUCCIÓN DE COLUMNA DERECHA
    # ============================================================
    col_der_flowables = []
    
    # --- SECCIÓN 2: CUENTAS POR PAGAR ---
    col_der_flowables.append(Paragraph("2. DETALLE DE CUENTAS POR PAGAR", style_section_header))
    col_der_flowables.append(Spacer(1, 4))
    
    cxp_table_rows = [
        [Paragraph("<b>PROVEEDOR / ACREEDOR</b>", ParagraphStyle('H1cxp', parent=style_normal_bold, textColor=colors.white)),
         Paragraph("<b>VENCE</b>", ParagraphStyle('H2cxp', parent=style_normal_bold, textColor=colors.white, alignment=TA_CENTER)),
         Paragraph("<b>ESTADO</b>", ParagraphStyle('H3cxp', parent=style_normal_bold, textColor=colors.white, alignment=TA_CENTER)),
         Paragraph("<b>MONTO (Bs.)</b>", ParagraphStyle('H4cxp', parent=style_normal_right_bold, textColor=colors.white))]
    ]
    
    # Obtener el día de referencia
    ref_date = fecha_procesar.date() if isinstance(fecha_procesar, datetime) else (fecha_procesar if hasattr(fecha_procesar, 'date') else datetime.now().date())
    
    tstyle_cxp_badges = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0a1628')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#e2e8f0')),
    ]
    
    total_cxp_sum = 0.0
    
    if df_cxp_detalle is not None and not df_cxp_detalle.empty:
        # Filtrar filas de TOTAL si existen
        df_cxp_data = df_cxp_detalle[~df_cxp_detalle['Proveedor / Acreedor'].str.contains('TOTAL', case=False, na=True)].copy()
        
        # Limitar a top 5 proveedores y agrupar el resto en "Otros"
        top_cxp_n = 5
        if len(df_cxp_data) > top_cxp_n:
            top_cxp = df_cxp_data.head(top_cxp_n).copy()
            otros_cxp_monto = df_cxp_data.iloc[top_cxp_n:]['Monto (Bs.)'].sum()
            
            # Crear fila Otros
            otros_row = pd.DataFrame([{
                'Proveedor / Acreedor': 'Otros Proveedores',
                'Documento': '',
                'Monto (Bs.)': otros_cxp_monto,
                'Fecha': ''
            }])
            df_cxp_draw = pd.concat([top_cxp, otros_row], ignore_index=True)
        else:
            df_cxp_draw = df_cxp_data.copy()
            
        total_cxp_sum = df_cxp_data['Monto (Bs.)'].sum()
        
        for idx, (_, row) in enumerate(df_cxp_draw.iterrows()):
            prov = str(row['Proveedor / Acreedor'])
            monto_val = float(row['Monto (Bs.)'])
            fecha_venc = str(row['Fecha'])
            
            # Truncar nombre proveedor largo
            if len(prov) > 23:
                prov = prov[:21] + "..."
                
            estado_str = "Vigente"
            vence_lbl = "No disp."
            
            # Calcular estado dinámicamente si hay fecha
            if fecha_venc and fecha_venc not in ['nan', 'None', 'No disponible', '']:
                vence_lbl = fecha_venc
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
                    try:
                        v_date = datetime.strptime(fecha_venc, fmt).date()
                        if v_date < ref_date:
                            estado_str = "Vencido"
                        break
                    except:
                        continue
                        
            # Si es la fila de "Otros", no poner fecha ni estado
            if prov == "Otros Proveedores":
                vence_lbl = "-"
                estado_str = "-"
                
            # Asignar estilo de badge para estado
            if estado_str == "Vigente":
                estado_p = Paragraph("<font color='#1b5e20'><b>Vigente</b></font>", ParagraphStyle('B1', parent=style_normal, alignment=TA_CENTER, fontSize=7.5))
                # Dibujar badge verde
                tstyle_cxp_badges.append(('BACKGROUND', (2, idx+1), (2, idx+1), colors.HexColor('#e8f5e9')))
            elif estado_str == "Vencido":
                estado_p = Paragraph("<font color='#b71c1c'><b>Vencido</b></font>", ParagraphStyle('B2', parent=style_normal, alignment=TA_CENTER, fontSize=7.5))
                # Dibujar badge rojo
                tstyle_cxp_badges.append(('BACKGROUND', (2, idx+1), (2, idx+1), colors.HexColor('#ffebee')))
            else:
                estado_p = Paragraph("-", ParagraphStyle('B3', parent=style_normal, alignment=TA_CENTER))
                
            cxp_table_rows.append([
                Paragraph(prov, style_normal),
                Paragraph(vence_lbl, ParagraphStyle('VenceL', parent=style_normal, alignment=TA_CENTER)),
                estado_p,
                Paragraph(formato_venezolano_pdf(monto_val), style_normal_right)
            ])
    else:
        # Fila placeholder
        cxp_table_rows.append([
            Paragraph("No hay cuentas por pagar registradas", style_normal), "", "", ""
        ])
        tstyle_cxp_badges.append(('SPAN', (0,1), (-1,1)))
        total_cxp_sum = cx_p_cierre
        
    # Añadir Fila de Total
    cxp_table_rows.append([
        Paragraph("<font color='white'><b>TOTAL CUENTAS POR PAGAR</b></font>", style_normal_bold),
        "", "",
        Paragraph(f"<font color='white'><b>{formato_venezolano_pdf(total_cxp_sum)}</b></font>", style_normal_right_bold)
    ])
    
    tot_row_idx = len(cxp_table_rows) - 1
    tstyle_cxp_badges.extend([
        ('SPAN', (0, tot_row_idx), (2, tot_row_idx)),
        ('BACKGROUND', (0, tot_row_idx), (-1, tot_row_idx), colors.HexColor('#0a1628')),
        ('TEXTCOLOR', (0, tot_row_idx), (-1, tot_row_idx), colors.white)
    ])
    
    # Tabla con anchos fijos: proveedor=110, vence=50, estado=45, monto=45 (total 250pt)
    cxp_table = Table(cxp_table_rows, colWidths=[110, 50, 45, 45])
    cxp_table.setStyle(TableStyle(tstyle_cxp_badges))
    
    col_der_flowables.append(cxp_table)
    col_der_flowables.append(Spacer(1, 10))
    
    # --- SECCIÓN 3: EGRESOS POR TIPO ---
    col_der_flowables.append(Paragraph("3. RESUMEN DE EGRESOS POR TIPO", style_section_header))
    col_der_flowables.append(Spacer(1, 4))
    
    egr_table_rows = [
        [Paragraph("<b>TIPO DE EGRESO</b>", ParagraphStyle('H1egr', parent=style_normal_bold, textColor=colors.white)),
         Paragraph("<b>MONTO (Bs.)</b>", ParagraphStyle('H2egr', parent=style_normal_right_bold, textColor=colors.white)),
         Paragraph("<b>%</b>", ParagraphStyle('H3egr', parent=style_normal_right_bold, textColor=colors.white))]
    ]
    
    tstyle_egr = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0a1628')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#e2e8f0')),
    ]
    
    if df_egresos_resumen is not None and not df_egresos_resumen.empty:
        # Filtrar filas de TOTAL
        df_egr_data = df_egresos_resumen[~df_egresos_resumen['Tipo de Egreso'].str.contains('TOTAL', case=False, na=True)].copy()
        
        for idx, (_, row) in enumerate(df_egr_data.iterrows()):
            tipo_e = str(row['Tipo de Egreso'])
            monto_val = float(row['Monto (Bs.)'])
            porc = float(row['Porcentaje']) if 'Porcentaje' in row else (monto_val / total_egresos_general * 100 if total_egresos_general > 0 else 0)
            
            if len(tipo_e) > 30:
                tipo_e = tipo_e[:27] + "..."
                
            egr_table_rows.append([
                Paragraph(tipo_e, style_normal),
                Paragraph(formato_venezolano_pdf(monto_val), style_normal_right),
                Paragraph(f"{porc:.1f}%", style_normal_right)
            ])
    else:
        egr_table_rows.append([
            Paragraph("No hay egresos registrados", style_normal), "", ""
        ])
        tstyle_egr.append(('SPAN', (0,1), (-1,1)))
        
    # Fila total
    egr_table_rows.append([
        Paragraph("<font color='white'><b>TOTAL EGRESOS</b></font>", style_normal_bold),
        Paragraph(f"<font color='white'><b>{formato_venezolano_pdf(total_egresos_general)}</b></font>", style_normal_right_bold),
        Paragraph("<font color='white'><b>100,0%</b></font>", style_normal_right_bold)
    ])
    
    tot_row_egr = len(egr_table_rows) - 1
    tstyle_egr.extend([
        ('BACKGROUND', (0, tot_row_egr), (-1, tot_row_egr), colors.HexColor('#0a1628')),
        ('TEXTCOLOR', (0, tot_row_egr), (-1, tot_row_egr), colors.white)
    ])
    
    # Tabla con anchos fijos: tipo=140, monto=75, porc=35 (total 250pt)
    egr_table = Table(egr_table_rows, colWidths=[145, 70, 35])
    egr_table.setStyle(TableStyle(tstyle_egr))
    
    col_der_flowables.append(egr_table)
    col_der_flowables.append(Spacer(1, 10))
    
    # --- GRÁFICO DE EGRESOS ---
    col_der_flowables.append(Paragraph("<b>Distribución Visual de Egresos:</b>", ParagraphStyle('VisT', parent=style_normal_bold, fontSize=8, textColor=colors.HexColor('#4a5568'))))
    col_der_flowables.append(Spacer(1, 2))
    
    # Generar y añadir el gráfico como Image
    try:
        img_buf = generar_grafico_barras_egresos(df_egresos_resumen, total_egresos_general)
        grafico_flowable = Image(img_buf, width=250, height=82)
        col_der_flowables.append(grafico_flowable)
    except Exception as e:
        col_der_flowables.append(Paragraph(f"Error cargando gráfico: {str(e)}", style_normal))

    # ============================================================
    # 4. ENSAMBLAJE DE LA TABLA DE DOS COLUMNAS PRINCIPAL
    # ============================================================
    # Columna 1 (izquierda), Columna 2 (separador), Columna 3 (derecha)
    main_layout_data = [
        [col_izq_flowables, "", col_der_flowables]
    ]
    
    main_layout_table = Table(main_layout_data, colWidths=[ancho_columna, ancho_separador, ancho_columna])
    main_layout_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    
    story.append(main_layout_table)
    
    # Pie de página informativo
    story.append(Spacer(1, 8))
    pie_line_table = Table([[""]], colWidths=[523], rowHeights=[0.5])
    pie_line_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0,0), (0,0), 0),
        ('BOTTOMPADDING', (0,0), (0,0), 0),
        ('LEFTPADDING', (0,0), (0,0), 0),
        ('RIGHTPADDING', (0,0), (0,0), 0),
    ]))
    story.append(pie_line_table)
    story.append(Spacer(1, 2))
    
    style_footer = ParagraphStyle('Footer', parent=style_normal, fontSize=6.5, alignment=TA_CENTER, textColor=colors.HexColor('#94a3b8'))
    story.append(Paragraph(f"Validador de Trazabilidad Diaria - Grupo Bodeguita Oriente | Reporte generado el {datetime.now().strftime('%d/%m/%Y %I:%M %p')}", style_footer))
    
    # Construir documento
    doc.build(story)
    
    output.seek(0)
    return output
