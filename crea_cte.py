import argparse
import re
import quopri

from app import app
from modelos import db, Cliente


def limpiar_nombre(nombre_raw):
    if not nombre_raw:
        return None
    nombre = re.sub(r"\s+", " ", nombre_raw).strip()
    return nombre or None


def limpiar_telefono(valor):
    if not valor:
        return None

    texto = str(valor).strip()
    texto = texto.replace(" ", "")
    texto = texto.replace("-", "")
    texto = texto.replace("(", "").replace(")", "")
    texto = texto.replace("+", "")
    texto = re.sub(r"[^0-9]", "", texto)

    if not texto:
        return None

    # Guardar solo los 10 dígitos del teléfono móvil mexicano.
    # Si por error el texto trae dos números pegados, tomamos solo la parte útil.
    if len(texto) == 10:
        return texto
    if len(texto) == 11 and texto.startswith("1"):
        return texto[1:]
    if len(texto) == 12 and texto.startswith("52"):
        return texto[2:]
    if len(texto) >= 13 and texto.startswith("521"):
        return texto[3:][:10]

    # Caso de concatenación de dos números: por ejemplo 81202106705218116135190
    # Tomamos solo los primeros 10 dígitos del bloque y descartamos el resto.
    if len(texto) > 10:
        return texto[:10]

    return None

def extraer_registros_desde_texto(texto_raw):
    # Decodificar el texto si viene con Quoted-Printable
    try:
        texto_decodificado = quopri.decodestring(texto_raw.encode('utf-8')).decode('utf-8', errors='ignore')
    except Exception:
        texto_decodificado = texto_raw

    registros = []

    for linea in texto_decodificado.splitlines():
        linea = linea.strip()
        if not linea:
            continue

        # Regex para capturar:
        # Group 1: Teléfono (secuencia de dígitos, espacios, guiones o paréntesis) al inicio de la línea
        # Group 2: Nombre (el resto del texto en la línea separado por espacio o tabulador)
        match = re.match(r'^([\d\s\-\+\(\)]+)\s+[\t\s]*(.+)$', linea)
        
        if match:
            telefono_raw = match.group(1)
            nombre_raw = match.group(2)
        else:
            # Caso inverso: si el Nombre viene primero y el Teléfono al final
            match_inverso = re.match(r'^(.+?)[\t\s]+([\d\s\-\+\(\)]+)$', linea)
            if match_inverso:
                nombre_raw = match_inverso.group(1)
                telefono_raw = match_inverso.group(2)
            else:
                continue

        telefono = limpiar_telefono(telefono_raw)
        nombre = limpiar_nombre(nombre_raw)

        if telefono and nombre:
            registros.append({
                "nombre": nombre,
                "telefono": telefono,
            })

    return registros


def procesar_agenda(texto_raw):
    registros = extraer_registros_desde_texto(texto_raw)

    print("=" * 80)
    print(f"{'NOMBRE':<35} | {'TELÉFONO':<20}")
    print("=" * 80)
    for reg in registros:
        tel_str = reg['telefono'] if reg['telefono'] else 'Sin teléfono'
        print(f"{reg['nombre']:<35} | {tel_str:<20}")
    print("=" * 80)
    print(f"Total de registros procesados: {len(registros)}\n")

    return registros


def crear_clientes_desde_texto(texto_raw):
    registros = extraer_registros_desde_texto(texto_raw)
    creados = []

    with app.app_context():
        for reg in registros:
            telefono = reg["telefono"]
            nombre = reg["nombre"]

            if len(str(telefono or '')) != 10:
                continue

            existe = db.session.query(Cliente.idCliente).filter_by(telefono=telefono).first()
            if existe:
                continue

            correo = "importado@citanet.local"

            cliente = Cliente(
                nombreCliente=nombre,
                telefono=telefono,
                correo=correo,
                correoValido=False,
            )
            db.session.add(cliente)
            creados.append(cliente)

        db.session.commit()

    return creados


def leer_y_procesar(ruta_archivo):
    with open(ruta_archivo, 'r', encoding='utf-8', errors='ignore') as file:
        contenido = file.read()

    return procesar_agenda(contenido)


def crear_clientes_desde_archivo(ruta_archivo):
    with open(ruta_archivo, 'r', encoding='utf-8', errors='ignore') as file:
        contenido = file.read()

    clientes = crear_clientes_desde_texto(contenido)
    print(f"Clientes creados en la tabla cliente: {len(clientes)}")
    return clientes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parsea contactos y crea registros en la tabla cliente.")
    parser.add_argument("ruta", nargs="?", default=r"C:\Users\Ovidio\Downloads\contacts.txt", help="Ruta del archivo txt con nombres y teléfonos.")
    args = parser.parse_args()

    crear_clientes_desde_archivo(args.ruta)
