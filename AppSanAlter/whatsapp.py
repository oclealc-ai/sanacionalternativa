import random
import requests
from config import WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_URL

def enviar_codigo_whatsapp(telefono):
    
    #print("TOKEN:", WHATSAPP_TOKEN)
    #print("PHONE_ID:", WHATSAPP_PHONE_ID)
    #print("URL:", WHATSAPP_URL)

    codigo = str(random.randint(100000, 999999))

    data = {
        "messaging_product": "whatsapp",
        "to": f"52{telefono}",
        "type": "text",
        "text": {"body": f"Tu código de verificación es: {codigo}"}
    }

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    response = requests.post(WHATSAPP_URL, headers=headers, json=data)

    #print("RESPUESTA WHATSAPP:", response.status_code, response.text)

    if response.status_code != 200:
        print("Error:", response.text)
        return None

    return codigo
