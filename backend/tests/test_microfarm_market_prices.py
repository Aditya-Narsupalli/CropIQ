import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.endpoints.microfarm_main import get_market_prices


def test_get_market_prices_uses_selected_location_when_available():
    prices_data = pd.DataFrame(
        [
            {"crop": "Tomato", "price_per_quintal": 3200, "location": "Pune Market, Pune", "date": "2025-04-19"},
            {"crop": "Tomato", "price_per_quintal": 2800, "location": "Kolhapur APMC, Kolhapur", "date": "2025-04-19"},
        ]
    )

    result = get_market_prices(["tomato"], "Pune, Maharashtra", "Kolhapur", prices_data)

    assert len(result) == 1
    assert result[0]["location"] == "Pune Market, Pune"
    assert result[0]["price_per_quintal"] == 3200


def test_get_market_prices_does_not_return_unrelated_locations_when_no_match_exists():
    prices_data = pd.DataFrame(
        [
            {"crop": "Tomato", "price_per_quintal": 3200, "location": "Pune Market, Pune", "date": "2025-04-19"},
            {"crop": "Tomato", "price_per_quintal": 2800, "location": "Kolhapur APMC, Kolhapur", "date": "2025-04-19"},
        ]
    )

    result = get_market_prices(["tomato"], "Nashik, Maharashtra", "Nashik", prices_data)

    assert result == []
