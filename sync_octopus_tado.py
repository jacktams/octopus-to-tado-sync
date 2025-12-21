import argparse
import asyncio
import requests
from datetime import datetime
from requests.auth import HTTPBasicAuth
from playwright.async_api import async_playwright
from PyTado.interface import Tado


def get_gas_tariff(api_key, account_number):
    """
    Retrieves the current gas unit rate from the Octopus Energy API.
    Returns a dict with unit_rate (pence per kWh), valid_from, and valid_to dates.
    """
    # Get account details to find the active gas tariff
    account_url = f"https://api.octopus.energy/v1/accounts/{account_number}/"
    response = requests.get(account_url, auth=HTTPBasicAuth(api_key, ""))

    if response.status_code != 200:
        print(f"Failed to retrieve account data. Status code: {response.status_code}")
        return None

    account_data = response.json()

    # Find the active gas agreement
    for property_data in account_data.get("properties", []):
        for meter_point in property_data.get("gas_meter_points", []):
            for agreement in meter_point.get("agreements", []):
                # Check if agreement is current (no end date or end date in future)
                valid_to = agreement.get("valid_to")
                valid_from = agreement.get("valid_from")
                if valid_to is None or valid_to > datetime.now().isoformat():
                    tariff_code = agreement.get("tariff_code")
                    if tariff_code:
                        # Extract product code from tariff code (e.g., "G-1R-VAR-22-11-01-A" -> "VAR-22-11-01")
                        # Tariff format: G-1R-{PRODUCT_CODE}-{REGION}
                        parts = tariff_code.split("-")
                        if len(parts) >= 3:
                            # Product code is everything between G-1R- and the region letter at the end
                            product_code = "-".join(parts[2:-1])

                            # Get the unit rates for this tariff
                            rates_url = f"https://api.octopus.energy/v1/products/{product_code}/gas-tariffs/{tariff_code}/standard-unit-rates/"
                            rates_response = requests.get(rates_url)

                            if rates_response.status_code == 200:
                                rates_data = rates_response.json()
                                if rates_data.get("results"):
                                    # Get the most recent/current rate
                                    current_rate = rates_data["results"][0]
                                    unit_rate = current_rate.get("value_inc_vat")
                                    rate_valid_from = current_rate.get("valid_from")
                                    rate_valid_to = current_rate.get("valid_to")
                                    print(f"Current gas unit rate: {unit_rate}p/kWh")
                                    return {
                                        "unit_rate": unit_rate,
                                        "valid_from": rate_valid_from,
                                        "valid_to": rate_valid_to,
                                    }
                            else:
                                print(f"Failed to retrieve tariff rates. Status code: {rates_response.status_code}")

    print("No active gas tariff found")
    return None


def get_meter_reading_total_consumption(api_key, mprn, gas_serial_number):
    """
    Retrieves total gas consumption from the Octopus Energy API for the given gas meter point and serial number.
    """
    period_from = datetime(2000, 1, 1, 0, 0, 0)
    url = f"https://api.octopus.energy/v1/gas-meter-points/{mprn}/meters/{gas_serial_number}/consumption/?group_by=quarter&period_from={period_from.isoformat()}Z"
    total_consumption = 0.0

    while url:
        response = requests.get(url, auth=HTTPBasicAuth(api_key, ""))

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
    return total_consumption + 1678


async def browser_login(url, username, password):

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True
        )  # Set to True if you don't want a browser window
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(url)

        # Click the "Submit" button before login
        await page.wait_for_selector('text="Submit"', timeout=5000)
        await page.click('text="Submit"')

        # Wait for the login form to appear
        await page.wait_for_selector('input[name="loginId"]')

        # Replace with actual selectors for your site
        await page.fill('input[id="loginId"]', username)
        await page.fill('input[name="password"]', password)

        await page.click('button.c-btn--primary:has-text("Sign in")')

        # Optionally take a screenshot
        await page.screenshot(path="screenshot.png")

        await page.wait_for_selector(
            ".text-center.message-screen.b-bubble-screen__spaced", timeout=10000
        )

        # Take a screenshot (optional)
        await page.screenshot(path="after-message.png")
        await browser.close()


def tado_login(username, password):
    tado = Tado(token_file_path="/tmp/tado_refresh_token")

    status = tado.device_activation_status()

    if status == "PENDING":
        url = tado.device_verification_url()

        asyncio.run(browser_login(url, username, password))

        tado.device_activation()

        status = tado.device_activation_status()

    if status == "COMPLETED":
        print("Login successful")
    else:
        print(f"Login status is {status}")

    return tado


def send_reading_to_tado(tado, reading):
    """
    Sends the total consumption reading to Tado using its Energy IQ feature.
    """
    result = tado.set_eiq_meter_readings(reading=int(reading))
    print(result)


def set_tado_gas_tariff(tado, tariff_info):
    """
    Sets the gas tariff in Tado Energy IQ using dates from Octopus API.
    tariff_info: Dict with unit_rate, valid_from, and valid_to from get_gas_tariff()
    """
    if tariff_info is None:
        print("No tariff to set")
        return

    unit_rate_pence = tariff_info["unit_rate"]
    valid_to = tariff_info["valid_to"]

    # Convert pence to pounds
    unit_rate_pounds = unit_rate_pence / 100

    # Use today as the start date for the current tariff
    from_date = datetime.now().strftime("%Y-%m-%d")
    # If valid_to is None (open-ended tariff), use a far future date
    if valid_to:
        to_date = datetime.fromisoformat(valid_to.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    else:
        to_date = "2099-12-31"

    result = tado.set_eiq_tariff(
        from_date=from_date,
        to_date=to_date,
        tariff=unit_rate_pounds,
        unit="kWh",
        is_period=True,
    )
    print(f"Set gas tariff to {unit_rate_pence}p/kWh (£{unit_rate_pounds}/kWh) from {from_date} to {to_date}: {result}")


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
    parser.add_argument(
        "--octopus-account-number",
        required=True,
        help="Octopus account number (e.g., A-1234ABCD)",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Login to Tado
    tado = tado_login(args.tado_email, args.tado_password)

    # Get total consumption from Octopus Energy API
    consumption = get_meter_reading_total_consumption(
        args.octopus_api_key, args.mprn, args.gas_serial_number
    )

    # Send the total consumption to Tado
    send_reading_to_tado(tado, consumption)

    # Get current gas tariff from Octopus Energy API
    tariff_info = get_gas_tariff(args.octopus_api_key, args.octopus_account_number)

    # Set the gas tariff in Tado
    set_tado_gas_tariff(tado, tariff_info)
