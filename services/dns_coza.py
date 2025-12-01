# services/dns_coza.py
import os
import logging
import requests
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# domains.co.za API
API_KEY = os.getenv("DOMAINS_COZA_API_KEY")
CLIENT_ID = os.getenv("DOMAINS_COZA_CLIENT_ID")
SANDBOX = os.getenv("DOMAINS_COZA_SANDBOX", "false").lower() == "true"

BASE_URL = (
    "https://sandbox-api.domains.co.za/v1/"
    if SANDBOX
    else "https://api.domains.co.za/v1/"
)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _request(method, endpoint, data=None):
    url = urljoin(BASE_URL, endpoint)
    try:
        response = requests.request(method, url, headers=HEADERS, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        err = response.json().get("error", {}).get("message", str(e))
        logger.error(f"domains.co.za API error ({endpoint}): {err}")
        raise Exception(f"API Error: {err}")
    except Exception as e:
        logger.error(f"Request failed: {e}")
        raise


def check_domain_availability(domain):
    """Check if .co.za domain is available"""
    if not domain.endswith(".co.za"):
        raise ValueError("Only .co.za domains supported")

    result = _request("GET", f"domains/check?domain={domain}")
    return {
        "available": result["available"],
        "premium": result.get("premium", False),
        "price": result.get("price", None),  # ZAR/year
    }


def register_domain(domain, registrant_data):
    """
    Register a .co.za domain
    registrant_data must include:
      - name, email, phone, address, city, province, postal_code, country (ZA)
      - id_number (SA ID or passport for .co.za)
    Note: .co.za has strict registrant requirements per ZADNA.
    """
    if not domain.endswith(".co.za"):
        raise ValueError("Only .co.za domains supported")

    payload = {
        "domain": domain,
        "period": 1,
        "registrant": {
            "name": registrant_data["name"],
            "email": registrant_data["email"],
            "phone": registrant_data["phone"],
            "address": registrant_data["address"],
            "city": registrant_data["city"],
            "province": registrant_data["province"],
            "postal_code": registrant_data["postal_code"],
            "country": registrant_data.get("country", "ZA"),
            "id_number": registrant_data["id_number"],  # Required for .co.za
        },
        "admin": registrant_data,
        "tech": {
            "name": os.getenv("TECH_NAME", "Hosting Manager"),
            "email": os.getenv("TECH_EMAIL", "tech@yourhosting.co.za"),
        },
        "billing": registrant_data,
    }

    logger.info(f":Registering {domain} via domains.co.za...")
    result = _request("POST", "domains/register", data=payload)

    return {
        "domain": result["domain"],
        "status": result["status"],  # "pending", "active"
        "expiry": result.get("expiry_date"),
        "invoice_id": result.get("invoice_id"),
        "success": result["status"] in ["active", "pending"],
    }


def set_dns_records(domain, records):
    """
    Set DNS records for a domain
    records = [
        {"type": "A", "name": "@", "content": "192.0.2.1", "ttl": 300},
        {"type": "CNAME", "name": "www", "content": "@", "ttl": 300},
        {"type": "TXT", "name": "_acme-challenge", "content": "xyz", "ttl": 300}
    ]
    """
    payload = {"records": records}
    result = _request("PUT", f"dns/{domain}", data=payload)
    return result.get("success", False)


def get_dns_records(domain):
    """Get current DNS records"""
    result = _request("GET", f"dns/{domain}")
    return result.get("records", [])


def get_domain_info(domain):
    """Get domain registration & status info"""
    result = _request("GET", f"domains/{domain}")
    return result
