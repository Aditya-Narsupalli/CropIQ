import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.endpoints.microfarm_main import get_market_prices


class MarketPricesLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_recommendations_use_live_market_prices_for_selected_location(self):
        async def fake_market_prices(crop=None, location=None):
            return [
                {
                    "crop": crop,
                    "price_per_quintal": 3300,
                    "location": f"{location or 'Unknown'} Mandi, {location or 'Unknown'}",
                    "date": "2025-04-19",
                }
            ]

        with patch("app.api.endpoints.microfarm_main.get_market_prices_from_market_endpoint", side_effect=fake_market_prices):
            result = await get_market_prices(["wheat"], "Kolhapur", "Kolhapur", None)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["location"], "Kolhapur Mandi, Kolhapur")
        self.assertEqual(result[0]["price_per_quintal"], 3300)


if __name__ == "__main__":
    unittest.main()
