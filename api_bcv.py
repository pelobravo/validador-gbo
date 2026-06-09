from bcv_api import BCV

def obtener_tasa_bcv():

    try:

        bcv = BCV()

        tasas = bcv.get_currencies(
            verify=False
        )

        print("Tasas obtenidas:", tasas)

        if "USD" in tasas:
            return float(tasas["USD"])

        return None

    except Exception as e:

        print("ERROR BCV:", str(e))

        return None