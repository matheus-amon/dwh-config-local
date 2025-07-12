from datetime import datetime
from typing import Dict, List, Literal

import requests
from loguru import logger


def get_quotes(
    start_date: datetime,
    end_date: datetime = datetime.today(),
    currencies: List[str] = ["USD", "EUR"],
    top: int = 100,
    format: Literal["json", "xml"] = "json",
) -> List[Dict]:
    """Retrieves currency exchange rate quotations from the Central Bank of Brazil (BCB).

    This function queries the BCB's Olinda PTAX API to fetch daily exchange rates
    for a specified list of currencies within a given date range. It automatically
    handles pagination to retrieve all available records.

    In case of an API error for a specific currency, the error will be logged,
    and the function will proceed to the next currency.

    Args:
        start_date: The start date for the quotation period.
        end_date: The end date for the quotation period. Defaults to the current date.
        currencies: A list of currency codes (e.g., "USD", "EUR") to fetch.
        top: The maximum number of records to retrieve per API call, used for pagination.
        format: The desired format for the API response, either "json" or "xml".

    Returns:
        A list of dictionaries, where each dictionary contains the details of a
        single currency quotation. The list may be partial if errors occur
        during fetching.
    """
    start_date = start_date.strftime("%d-%m-%Y")
    end_date = end_date.strftime("%d-%m-%Y")
    api_url = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"

    params = (
        "moeda=@moeda,"
        "dataInicial=@dataInicial,"
        "dataFinalCotacao=@dataFinalCotacao"
    )

    endpoint = f"CotacaoMoedaPeriodo({params})"

    all_quotes: List = []
    for currency in currencies:
        skip = 0
        while True:
            try:
                query = (
                    f"?@moeda='{currency}'"
                    f"&@dataInicial='{start_date}'"
                    f"&@dataFinalCotacao='{end_date}'"
                    f"&$top={top}"
                    f"&$skip={skip}"
                    f"&$format={format}"
                )
                response = requests.get(api_url + endpoint + query)
                data = response.json()
                quotes = data.get("value", [])
                if not quotes:
                    break
                all_quotes.extend(quotes)
                if len(quotes) < top:
                    break
                skip += top
            except requests.RequestException as e:
                logger.error(f"Request failed for {currency}: {e}")
                break
            except KeyError:
                logger.error(
                    f"Unexpected response format for {currency}: {data}"
                )
                break
            except Exception as e:
                logger.error(f"Error getting quotes for {currency}: {e}")
                break
    return all_quotes


if __name__ == "__main__":
    start_date = datetime(2025, 7, 1)
    end_date = datetime(2025, 7, 11)
    all_quotes = get_quotes(start_date, end_date)
    for quote in all_quotes:
        logger.info(quote)
