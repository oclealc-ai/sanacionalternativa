from app                    import app, db
from modelos                import Cita, CitaCliente, Cliente, Empresa, EmpresaPlan, Usuario, FilaEspera
from routes.citas_cliente   import avisar_fila_espera
from constantes             import const
from correo                 import enviar_correo_base
from sqlalchemy             import or_, and_
from datetime               import datetime, timedelta
from whatsapp               import enviar_whatsapp
from firebase_admin         import messaging

import logging
import sys

logger = logging.getLogger(__name__)

logger_venv = logging.getLogger("venv")

formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

for log_obj in [logger, logger_venv]:
    if not log_obj.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        log_obj.addHandler(handler)
        log_obj.setLevel(logging.INFO)
        log_obj.propagate = False

from itsdangerous import URLSafeSerializer


def generar_url_segura(id_cita_cliente_ids):
    s = URLSafeSerializer(app.config["SECRET_KEY"])
    token = s.dumps({'idCitaCliente': list(id_cita_cliente_ids)})
    return f"https://www.citanet.com.mx/confirmacion-directa/{token}"


def plan_x_vencer():
    """ funcion para enviar a las empresas un aviso de que su plan esta por vencer """
    with app.app_context():
        with app.test_request_context(): 
            logger.error("--- Ejecutando plan_x_vencer ---")
            
            hoy = datetime.now().date()
            # El rango inicia mañana y termina en 5 días
            manana = hoy + timedelta(days=1)
            fecha_limite = hoy + timedelta(days=5)
            
            try:
                # 1. Buscar los planes activos/demo que venzan dentro de los próximos 5 días
                planes_por_vencer = EmpresaPlan.query.filter(
                    EmpresaPlan.estatusPlan.in_(['activa', 'demo']),
                    EmpresaPlan.fechaVencimiento >= manana,
                    EmpresaPlan.fechaVencimiento <= fecha_limite
                ).all()
                
                for plan in planes_por_vencer:
                    # Obtenemos la empresa ligada a este plan
                    empresa = plan.empresa
                    
                    if empresa and empresa.telefono:
                        telefono_empresa = empresa.telefono
                        fecha_formateada = plan.fechaVencimiento.strftime('%d/%m/%Y')
                        
                        # Calculamos cuántos días le quedan exactamente
                        dias_restantes = (plan.fechaVencimiento - hoy).days
                        
                        # Estructuramos el mensaje dinámico según los días que le queden
                        cuerpo_mensaje = f"*Recordatorio de Citanet*\n\n"
                        cuerpo_mensaje += f"Estimado equipo de *{empresa.razonSocial}*,\n"
                        cuerpo_mensaje += f"Le recordamos que su plan actual (*{plan.estatusPlan}*) está próximo a vencer el día *{fecha_formateada}* (quedan *{dias_restantes}* días).\n\n"
                        cuerpo_mensaje += f"Para evitar interrupciones en su agenda y servicios, le sugerimos realizar la renovación correspondiente."
                        
                        try:
                            # Se envía al teléfono de la empresa usando su propio idEmpresa
                            telefono_empresa = "8110646050"
                            empresa_id = empresa.idEmpresa
                            empresa_id = 1
                            enviar_whatsapp(telefono_empresa, cuerpo_mensaje, empresa_id)
                            logger.info(f"✅ Aviso de vencimiento ({dias_restantes} días restantes) enviado a {empresa.razonSocial}")
                        except Exception as wa_e:
                            logger.error(f"⚠️ falló WhatsApp de vencimiento para {empresa.razonSocial}: {wa_e}")
                            
                        # -------------------------------------------------------------
                        # ENVÍO DE CORREO ELECTRÓNICO PROFESIONAL
                        # -------------------------------------------------------------
                        if empresa.correoContacto:
                            try:
                                asunto_correo = f"Recordatorio de Renovación: Su plan Citanet vence en {dias_restantes} días"
                                
                                # Cuerpo en formato HTML limpio y profesional
                                cuerpo_html = f"""
                                <html>
                                <body style="font-family: 'Segoe UI', Arial, sans-serif; color: #333333; line-height: 1.6; background-color: #f8fafc; padding: 20px;">
                                    <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                                        <div style="background-color: #0f172a; padding: 25px; text-align: center;">
                                            <h2 style="color: #5bbfa6; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">CITANET</h2>
                                        </div>
                                        <div style="padding: 30px;">
                                            <p style="margin-top: 0; font-size: 16px;">Estimado equipo de <strong>{empresa.razonSocial}</strong>,</p>
                                            <p style="font-size: 15px;">Le saludamos cordialmente de parte del equipo de Citanet para informarle que su plan actual de servicios (<strong>{plan.estatusPlan.upper()}</strong>) está próximo a expirar.</p>
                                            
                                            <div style="background-color: #f1f5f9; border-left: 4px solid #5bbfa6; padding: 15px; margin: 20px 0; border-radius: 0 4px 4px 0;">
                                                <table style="width: 100%; border-collapse: collapse;">
                                                    <tr>
                                                        <td style="padding: 4px 0; font-size: 14px; color: #64748b; font-weight: bold; width: 40%;">Fecha de Vencimiento:</td>
                                                        <td style="padding: 4px 0; font-size: 14px; color: #0f172a; font-weight: bold;">{fecha_formateada}</td>
                                                    </tr>
                                                    <tr>
                                                        <td style="padding: 4px 0; font-size: 14px; color: #64748b; font-weight: bold;">Tiempo Restante:</td>
                                                        <td style="padding: 4px 0; font-size: 14px; color: #ef4444; font-weight: bold;">{dias_restantes} días</td>
                                                    </tr>
                                                </table>
                                            </div>
                                            
                                            <p style="font-size: 15px;">Para asegurar la continuidad operativa de su negocio, mantener el acceso ininterrumpido a su agenda y seguir ofreciendo un servicio óptimo a sus clientes, le sugerimos gestionar la renovación de su suscripción a la brevedad.</p>
                                            <p style="font-size: 15px; margin-bottom: 0;">Si requiere asistencia con su proceso de pago o desea evaluar un cambio de plan, nuestro equipo de soporte se encuentra a su entera disposición.</p>
                                        </div>
                                        <div style="background-color: #f8fafc; padding: 20px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8;">
                                            Atentamente,<br>
                                            <strong>Equipo de Operaciones Citanet</strong><br>
                                            <span style="display: inline-block; margin-top: 5px;">Este es un mensaje automático de control del sistema.</span>
                                        </div>
                                    </div>
                                </body>
                                </html>
                                """
                                destino=empresa.correoContacto
                                #destino="oclealc@gmail.com"
                                enviar_correo_base(
                                    destino,
                                    asunto_correo,
                                    cuerpo_html,
                                    es_html=True)
                                logger.info(f"📧 Correo de vencimiento enviado a {empresa.correoContacto}")
                                
                            except Exception as email_e:
                                logger.error(f"⚠️ falló el envío de correo para {empresa.razonSocial}: {email_e}")
                            
            except Exception as e:
                logger.error(f"💥 Error general en la base de datos (plan_x_vencer): {e}")


def enviar_citas_diarias(horario="am"):
    """ funcion para enviar a los terapeutas sus citas del dia siguiente """
    with app.app_context():
        with app.test_request_context(): 
            logger.error("--- Ejecutando enviar_citas_diarias ---")

            hoy = datetime.now().date()
            
            # Evaluamos el horario para calcular los días a sumar
            if horario == "am":
                # Si es en la mañana, buscamos las citas de HOY mismo
                dias_a_sumar = 0
            else:
                # Si es en la tarde/noche (pm), buscamos las del DÍA SIGUIENTE
                dias_a_sumar = 1
                
            fecha_objetivo = hoy + timedelta(days=dias_a_sumar)
            
            try:
                # 1. Buscar empresas con idEstatus igual a 1
                empresas = Empresa.query.filter_by(idEstatus=1).all()
                
                for empresa in empresas:
                    # Buscar el último plan registrado (más reciente) de esta empresa
                    ultimo_plan = EmpresaPlan.query.filter(
                        EmpresaPlan.idEmpresa == empresa.idEmpresa,
                        EmpresaPlan.estatusPlan.in_(['activa', 'demo']),
                        EmpresaPlan.fechaInicio <= hoy,
                        EmpresaPlan.fechaVencimiento >= hoy
                    ).order_by(EmpresaPlan.idEmpresaPlan.desc()).first()
                    
                    # Si no cuenta con plan que cumpla las condiciones, pasamos a la siguiente empresa
                    if not ultimo_plan:
                        continue
                        
                    # 2. Buscar usuarios de tipo staff de esta empresa con teléfono capturado
                    staff_usuarios = Usuario.query.filter(
                        Usuario.idEmpresa == empresa.idEmpresa,
                        Usuario.tipoUsuario == 'staff',
                        Usuario.telefono != None,
                        Usuario.telefono != ""
                    ).all()
                    
                    for terapeuta in staff_usuarios:
                        # 3. Buscar las citas de mañana asignadas a este usuario (staff) en esta empresa
                        citas_manana = Cita.query.join(CitaCliente).filter(
                            Cita.idEmpresa == empresa.idEmpresa,
                            Cita.idUsuario == terapeuta.idUsuario,
                            Cita.fechaCita == fecha_objetivo,
                            CitaCliente.idEstatus.in_([const.RESERVADA, const.CONFIRMADA])
                        ).distinct().all()
                        
                        # Si el terapeuta tiene citas asignadas, armamos el desglose detallado
                        if citas_manana:
                            fecha_formateada = fecha_objetivo.strftime('%d/%m/%Y')
                            
                            cuerpo_mensaje = f"*Hola {terapeuta.nombreUsuario}!*\n"
                            cuerpo_mensaje += f"Aquí tienes tu agenda para el dia *{fecha_formateada}*:\n\n"
                            
                            # Iteramos sobre cada cita para concatenar sus datos
                            for cita in citas_manana:
                                hora_formateada = cita.horaCita.strftime('%H:%M') if hasattr(cita.horaCita, 'strftime') else str(cita.horaCita)
                                reservas = [r for r in cita.reservas if r.idEstatus in (const.RESERVADA, const.CONFIRMADA)]
                                nombre_cliente = ', '.join(dict.fromkeys(r.nombre_asistente for r in reservas)) or "Sin asignar"
                                nombre_estatus = ', '.join(dict.fromkeys(r.estatus.nombre for r in reservas if r.estatus)) or "N/A"
                                
                                cuerpo_mensaje += f"⏰ *Hora:* {hora_formateada}\n"
                                cuerpo_mensaje += f"👤 *Cliente:* {nombre_cliente}\n"
                                cuerpo_mensaje += f"📌 *Estatus:* {nombre_estatus}\n"
                                cuerpo_mensaje += f"---------------------------\n"
                            
                            telefono_terapeuta = terapeuta.telefono
                            #telefono_terapeuta = '8110646050'  # Solo para pruebas, comentar esta línea en producción
                            
                            try:
                                # Se envía desde el teléfono de su propia empresa
                                empresa = empresa.idEmpresa
                                #empresa = 1  # Solo para pruebas, comentar esta línea en producción
                                enviar_whatsapp(telefono_terapeuta, cuerpo_mensaje, empresa)
                                logger.info(f"✅ Mensaje enviado a {terapeuta.nombreUsuario} (Empresa: {empresa.idEmpresa})")
                            except Exception as wa_e:
                                logger.error(f"⚠️ falló WhatsApp para el terapeuta {telefono_terapeuta}: {wa_e}")
            
            except Exception as e:
                logger.error(f"💥 Error general en la base de datos: {e}")


def enviar_mensaje_reservados():
    """Envía recordatorios a clientes con citas en estatus RESERVADA"""
    with app.app_context():
        with app.test_request_context(): 
            logger.error("--- Ejecutando enviar_mensaje_reservados ---")
            hoy = datetime.now().date()
            limite = hoy + timedelta(days=3)
            
            try:
                reservas_pendientes = CitaCliente.query.join(Cita).filter(
                    CitaCliente.idEstatus == const.RESERVADA,
                    Cita.fechaCita >= hoy,
                    Cita.fechaCita <= limite,
                    or_(
                        CitaCliente.ultimoRecordatorio == None,
                        CitaCliente.ultimoRecordatorio < hoy
                    )
                ).all()
                
                if not reservas_pendientes:
                    logger.error("No hay reservas pendientes para los próximos 3 días.")
                    return

                pendientes_por_cliente_cita = {}
                for reserva in reservas_pendientes:
                    key = (reserva.idCita, reserva.idCliente)
                    pendientes_por_cliente_cita.setdefault(key, []).append(reserva)

                for (id_cita, id_cliente), reservas in pendientes_por_cliente_cita.items():
                    cita = Cita.query.get(id_cita)
                    if not cita:
                        continue
                    cliente = db.session.get(Cliente, id_cliente)
                    if not cliente or not cliente.correo:
                        logger.error(f"Cita {id_cita}: Cliente no encontrado o sin correo.")
                        continue

                    nombre_empresa = cita.empresa.razonSocial if cita.empresa else "CitaNet"
                    destino = cliente.correo
                    asunto = f"Recordatorio de Cita: {cita.fechaCita.strftime('%d/%m/%Y')}"
                    empresa_dir = cita.empresa.googleMapsUrl if cita.empresa and cita.empresa.googleMapsUrl else "Ver en sucursal"
                    url_confirmacion = generar_url_segura([r.idCitaCliente for r in reservas])
                    lugares = []
                    for reserva in reservas:
                        nombre = (reserva.para or '').strip() or cliente.nombreCliente.strip()
                        if nombre.lower() not in {k.lower() for k in lugares}:
                            lugares.append(nombre)

                    lista_lugares = ", ".join(f"{x}" for x in lugares)
                    etiqueta_lugares = f"\n👤 *Para:* {lista_lugares}\n" if len(lugares) > 1 else ""
                    if len(lugares) == 1 and lugares[0].strip() != cliente.nombreCliente.strip():
                        etiqueta_lugares = f"\n👤 *Para:* {lugares[0]}\n"

                    cuerpo = f"""
                            <html>
                                <body style="font-family: sans-serif; color: #333; line-height: 1.6;">
                                    <div style="max-width: 600px; margin: auto; border: 1px solid #eee; padding: 20px; border-radius: 10px;">
                                        <h2 style="color: #2c3e50;">Hola {cliente.nombreCliente},</h2>
                                        <p>Te recordamos que tienes una cita <strong>pendiente de confirmar</strong> en <strong>{nombre_empresa}</strong>:</p>
                                        
                                        <div style="background-color: #f9f9f9; padding: 15px; border-radius: 8px; margin: 20px 0;">
                                            <p style="margin: 5px 0;"><strong>Fecha:</strong> {cita.fechaCita.strftime('%d/%m/%Y')}</p>
                                            <p style="margin: 5px 0;"><strong>Hora:</strong> {cita.horaCita.strftime('%H:%M')}</p>
                                            {f"<p style='margin: 5px 0;'><strong>Para:</strong> {lista_lugares}</p>" if lista_lugares else ''}
                                        </div>
                                        
                                        <p>Por favor, confirma tu asistencia haciendo clic en el siguiente botón:</p>
                                        <a href="{url_confirmacion}" 
                                        style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                                        Confirmar mi Cita
                                        </a>

                                        <hr style="border: 0; border-top: 1px solid #eee;">
                                        <p>Saludos,<br><strong>Equipo {nombre_empresa}</strong></p>
                                    </div>
                                </body>
                            </html>
                            """

                    try:
                        enviar_correo_base(destino, asunto, cuerpo, es_html=True)

                        cuerpo_mensaje = (
                            f"¡Hola *{cliente.nombreCliente}*! 👋\n\n"
                            f"Te recordamos tu cita reservada en *{nombre_empresa}*:\n"
                            f"📅 *Fecha:* {cita.fechaCita.strftime('%d/%m/%Y')}\n"
                            f"⏰ *Hora:* {cita.horaCita.strftime('%H:%M')}\n"
                            f"{etiqueta_lugares}\n"
                            f"✅ *Confirma tu asistencia aquí:* \n"
                            f"{url_confirmacion}\n\n"
                            f"📍 *Ubicación:* {empresa_dir}\n\n"
                            f"_Por favor, llega 10 minutos antes._\n"
                            f"¡Te esperamos! 😊"
                        )

                        telefono_cliente = cliente.telefono
                        if telefono_cliente:
                            try:
                                enviar_whatsapp(telefono_cliente, cuerpo_mensaje, cita.idEmpresa)
                            except Exception as wa_e:
                                logger.error(f"⚠️ Correo enviado, pero falló WhatsApp para {destino}: {wa_e}")

                        for reserva in reservas:
                            reserva.ultimoRecordatorio = hoy
                        db.session.commit()
                        logger.error(f"✅ Recordatorio enviado con éxito a {cliente.nombreCliente}")
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"❌ Error al enviar a {destino}: {e}")
                        
            except Exception as e:
                logger.error(f"💥 Error general en la base de datos: {e}")

def enviar_citas_fila_espera():
    with app.app_context():
        with app.test_request_context():
            logger.error("--- Ejecutando enviar_citas_fila_espera ---")

            hoy    = datetime.now().date()
            limite = hoy + timedelta(days=15)

            try:
                # Verificar que hay registros activos en fila antes de buscar citas
                hay_fila = FilaEspera.query.filter_by(activo=True).first()
                if not hay_fila:
                    #logger.error("No hay clientes en fila de espera activos. Nada que hacer.")
                    return

                ahora = datetime.now()
                hoy = ahora.date()
                hora_actual = ahora.time()

                citas_disponibles = Cita.query.filter(
                    Cita.idEstatus == const.DISPONIBLE,
                    or_(
                        and_(
                            Cita.fechaCita > hoy,
                            Cita.fechaCita <= limite
                        ),
                        and_(
                            Cita.fechaCita == hoy,
                            Cita.horaCita > hora_actual
                        )
                    )
                ).order_by(Cita.idEmpresa, Cita.idUsuario, Cita.fechaCita, Cita.horaCita).all()

                if not citas_disponibles:
                    #logger.error("No hay citas disponibles en los próximos 15 días.")
                    return

                #logger.error(f"Procesando {len(citas_disponibles)} citas disponibles...")
                total_avisos = 0

                for cita in citas_disponibles:
                    try:
                        aviso = avisar_fila_espera(cita)
                        if aviso:
                            total_avisos += 1
                    except Exception as e:
                        logger.error(f"Error procesando cita {cita.idCita}: {e}")
                        continue

                logger.error(f"✅ enviar_citas_fila_espera completado. Avisos enviados: {total_avisos}")

            except Exception as e:
                logger.error(f"💥 Error general en enviar_citas_fila_espera: {e}")




def enviar_recordatorio_proximas_horas():
    """
    Envía un aviso a los clientes cuya cita de HOY está dentro de las próximas 2 horas.
    La lógica se basa en CitaCliente, para que cada cliente reciba un solo aviso por
    cita y se acumulen varios nombres en el mismo mensaje cuando haya más de un lugar.
    """
    with app.app_context():
        with app.test_request_context():
            logger.error("--- Ejecutando enviar_recordatorio_proximas_horas ---")

            ahora = datetime.now()
            hoy = ahora.date()
            hora_actual = ahora.time()

            limite_dt = ahora + timedelta(hours=2)
            if limite_dt.date() != hoy:
                hora_limite = datetime.max.time()
            else:
                hora_limite = limite_dt.time()

            try:
                reservas_proximas = CitaCliente.query.join(Cita).filter(
                    Cita.fechaCita == hoy,
                    Cita.horaCita >= hora_actual,
                    Cita.horaCita <= hora_limite,
                    CitaCliente.idEstatus.in_([const.RESERVADA, const.CONFIRMADA]),
                    or_(
                        CitaCliente.avisoProximoEnviado == None,
                        CitaCliente.avisoProximoEnviado == False
                    )
                ).all()

                if not reservas_proximas:
                    return

                total_avisos = 0
                reservas_por_cliente_cita = {}
                for reserva in reservas_proximas:
                    key = (reserva.idCita, reserva.idCliente)
                    reservas_por_cliente_cita.setdefault(key, []).append(reserva)

                for (id_cita, id_cliente), reservas in reservas_por_cliente_cita.items():
                    try:
                        cita = Cita.query.get(id_cita)
                        cliente = db.session.get(Cliente, id_cliente)
                        empresa = db.session.get(Empresa, cita.idEmpresa) if cita else None

                        if not cita or not cliente or not cliente.telefono:
                            logger.error(f"Cita {id_cita}: cliente sin teléfono o cita no encontrada, se omite.")
                            continue

                        nombre_empresa = empresa.razonSocial if empresa else "CitaNet"
                        hora_formateada = cita.horaCita.strftime('%H:%M')
                        lugares = []
                        for reserva in reservas:
                            nombre = (reserva.para or '').strip() or cliente.nombreCliente.strip()
                            if nombre not in lugares:
                                lugares.append(nombre)
                        nombres_lugares = ", ".join(lugares)
                        linea_para = f"👤 *Para:* {nombres_lugares}\n" if nombres_lugares and nombres_lugares != cliente.nombreCliente.strip() else ""
                        empresa_dir = empresa.googleMapsUrl if empresa and empresa.googleMapsUrl else None
                        linea_ubicacion = f"📍 *Ubicación:* {empresa_dir}\n" if empresa_dir else ""

                        cuerpo_mensaje = (
                            f"¡Hola *{cliente.nombreCliente}*! 👋\n\n"
                            f"Te recordamos que tu cita en *{nombre_empresa}* es *hoy a las {hora_formateada}*, "
                            f"en menos de 2 horas.\n"
                            f"{linea_para}"
                            f"{linea_ubicacion}\n"
                            f"¡Te esperamos! 😊"
                        )

                        enviar_whatsapp(cliente.telefono, cuerpo_mensaje, cita.idEmpresa)

                        for reserva in reservas:
                            reserva.avisoProximoEnviado = True
                        db.session.commit()
                        total_avisos += 1
                        logger.info(f"✅ Recordatorio de próxima cita enviado a {cliente.nombreCliente} (Cita {cita.idCita})")
                    except Exception as wa_e:
                        db.session.rollback()
                        logger.error(f"⚠️ Falló el aviso para la cita {id_cita}: {wa_e}")
                        continue

                logger.error(f"✅ enviar_recordatorio_proximas_horas completado. Avisos enviados: {total_avisos}")

            except Exception as e:
                logger.error(f"💥 Error general en enviar_recordatorio_proximas_horas: {e}")


def enviar_recordatorio_push(token_cliente, titulo, mensaje):
    """
    Envía una notificación push directa a la barra superior del móvil del cliente.
    Recibe el token Push guardado en la base de datos, el título y el cuerpo del mensaje.
    """
    if not token_cliente:
        return False
        
    # Estructura visual de la notificación
    notification = messaging.Notification(
        title=titulo,
        body=mensaje
    )
    
    # Construcción del mensaje uniendo el diseño con el token del teléfono destino
    message = messaging.Message(
        notification=notification,
        token=token_cliente
    )
    
    try:
        # Se envía a los servidores de Firebase para que lo empujen de inmediato
        response = messaging.send(message)
        logger.info("Notificación enviada con éxito, ID de respuesta:", response)
        return True
    except Exception as e:
        logger.info("Error enviando push a Firebase:", e)
        return False



def vencer_citas_pasadas(dias_atras=30):
    """
    Pasa a "Vencida" las citas que ya pasaron de horario sin clientes activos.
    Las que aún tienen clientes en Reservada/Confirmada no se tocan (quedan "pendientes de cerrar").
    dias_atras=None revisa todo el histórico (limpieza única).
    """
    from routes.ver_citas import cerrar_citas_vencidas
    with app.app_context():
        vencidas = cerrar_citas_vencidas(dias_atras=dias_atras)
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} citas vencidas: {vencidas}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python avisos.py [reservados | diarias | planxvencer | filaespera | proximas | vencidas]")
        sys.exit(1)

    accion = sys.argv[1].lower()

    if accion == "reservados":
        enviar_mensaje_reservados()
    elif accion == "diarias":
        # 1. Leemos el tercer parámetro (posición 2). Si no viene nada, por defecto es 'am'
        horario = sys.argv[2].lower() if len(sys.argv) > 2 else "am"
        
        # 2. Se lo pasamos a tu función existente
        enviar_citas_diarias(horario)
    elif accion == "planxvencer":
        plan_x_vencer()
    elif accion == "filaespera":
        enviar_citas_fila_espera()
    elif accion == "proximas":
        enviar_recordatorio_proximas_horas()
    elif accion == "vencidas":
        # Opcional: días hacia atrás a revisar (default 30) o --todas para todo el histórico
        arg = sys.argv[2].lower() if len(sys.argv) > 2 else "30"
        vencer_citas_pasadas(None if arg == "--todas" else int(arg))
    else:
        print(f"Error: La acción '{accion}' no existe.")