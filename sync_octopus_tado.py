import argparse
import requests
from requests.auth import HTTPBasicAuth
from PyTado.interface import Tado


def get_meter_reading_total_consumption(api_key, mprn, gas_serial_number):
    """
    Retrieves total gas consumption from the Octopus Energy API for the given gas meter point and serial number.
    """
    url = f"https://api.octopus.energy/v1/gas-meter-points/{mprn}/meters/{gas_serial_number}/consumption/"
    total_consumption = 2420

    while url:
        response = requests.get(
            url + "?group_by=quarter", auth=HTTPBasicAuth(api_key, "")
        )

        if response.status_code == 200:
            meter_readings = response.json()
            total_consumption += sum(
                interval["consumption"] for interval in meter_readings["results"]
            )
            url = meter_readings.get("next", "")
        else:
            print(
                f"Failed to retrieve data. Status code: {response.status_code}, Message: {response.text}"
            )
            break

    print(f"Total consumption is {total_consumption}")
    return total_consumption

def uploadAllTarrifs(api_key, tarrif, fullTarrif):
    url = f"https://api.octopus.energy/v1/products/{tarrif}/gas-tariffs/{fullTarrif}/standard-unit-rates/"

    while url:
        response = requests.get(
                url , auth=HTTPBasicAuth(api_key, "")
            )
        
        if response.status_code == 200:
            meter_readings = response.json()
            
            for result in meter_readings['results']:
                
                
                send_tarrif_to_tado(args.tado_email, args.tado_password, result)
                
            url = meter_readings.get("next", "")


def send_reading_to_tado(username, password, reading):
    """
    Sends the total consumption reading to Tado using its Energy IQ feature.
    """
    tado = Tado(username, password)
    result = tado.set_eiq_meter_readings(reading=int(reading))
    print(result)

def send_tarrif_to_tado(username, password, tarrif):
    """
    Sends the tarrif information to Tado using its Energy IQ feature.
    """
    tado = Tado(username, password)
    
    value = tarrif["value_inc_vat"] / 100
    valid_from = tarrif["valid_from"][:-10]
    valid_to = tarrif["valid_to"][:-10]
    
    result = tado.set_eiq_tariff(from_date=valid_from, to_date=valid_to, tariff=value, is_period=True, unit="kWh")
    print(result)


def parse_args():
    """
    Parses command-line arguments for Tado and Octopus API credentials and meter details.
    """
    parser = argparse.ArgumentParser(
        description="Tado and Octopus API Interaction Script"
    )

    # Tado API arguments
    parser.add_argument("--tado-email", required=True, help="Tado account email")
    parser.add_argument("--tado-password", required=True, help="Tado account password")

    # Octopus API arguments
    parser.add_argument(
        "--mprn",
        required=True,
        help="MPRN (Meter Point Reference Number) for the gas meter",
    )
    parser.add_argument(
        "--gas-serial-number", required=True, help="Gas meter serial number"
    )
    parser.add_argument("--octopus-api-key", required=True, help="Octopus API key")
    parser.add_argument("--tarrif", required=True, help="tarrif details")
    parser.add_argument("--fulltarrif", required=True, help="full tarrif details")

    return parser.parse_args()

def getCurrentTarrif(api_key, tarrif, fullTarrif):
    url = f"https://api.octopus.energy/v1/products/{tarrif}/gas-tariffs/{fullTarrif}/standard-unit-rates/"

    response = requests.get(
            url + "?group_by=quarter", auth=HTTPBasicAuth(api_key, "")
        )

    if response.status_code == 200:
        meter_readings = response.json()
        result = meter_readings["results"][0]
        print(f"Result is {result}")
        return result



if __name__ == "__main__":
    args = parse_args()

    # Get total consumption from Octopus Energy API
    consumption = get_meter_reading_total_consumption(
        args.octopus_api_key, args.mprn, args.gas_serial_number
    )
    
    # Send the total consumption to Tado
    send_reading_to_tado(args.tado_email, args.tado_password, consumption)

    #uploadAllTarrifs(args.octopus_api_key, args.tarrif, args.fulltarrif)

    tarrif = getCurrentTarrif(args.octopus_api_key, args.tarrif, args.fulltarrif)

    # Send the tarrif to Tado
    send_tarrif_to_tado(args.tado_email, args.tado_password, tarrif)
