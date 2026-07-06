import os
import datetime
import django
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "marketmind.settings")
django.setup()

from django.contrib.auth.models import User
from market.models import Stock, Portfolio, PortfolioHolding, AlertRule
from market.utils.data_collector import collect_stock_price, collect_news
from market.utils.sentiment_engine import batch_analyze_stock
from market.utils.prediction_engine import get_technical_indicators, generate_prediction
from market.utils.explainer import generate_insight_report


def populate_initial_data():
    print("====================================================")
    print("   MarketMind AI Initial Data Populate Script   ")
    print("====================================================")

    # 1. Verify or create admin user
    user = User.objects.filter(username="admin").first()
    if not user:
        print("[+] Creating admin superuser...")
        user = User.objects.create_superuser("admin", "admin@example.com", "admin123")
    else:
        print("[*] Admin user exists.")

    # 2. Get or create primary portfolio
    portfolio, _ = Portfolio.objects.get_or_create(
        user=user, defaults={"name": "Primary Portfolio"}
    )
    print(f"[*] Portfolio initialized: '{portfolio.name}'")

    # 3. Define default watchlists with investment details
    tickers = [
        ("INFY.NS", "Infosys Limited", 20, 1420.0),
        ("AAPL", "Apple Inc.", 10, 175.5),
        ("MSFT", "Microsoft Corporation", 5, 385.0),
        ("RELIANCE.NS", "Reliance Industries Limited", 15, 2750.0),
    ]

    print("[+] Syncing price history, news headlines, and calculating AI insights...")
    for ticker, name, qty, buy_price in tickers:
        print(f"\n---> Syncing stock: {ticker} ({name})")
        
        # Get or create stock metadata
        stock, _ = Stock.objects.get_or_create(
            ticker=ticker, defaults={"name": name, "exchange": "UNKNOWN", "sector": "UNKNOWN"}
        )

        # Download live prices and headlines
        try:
            collect_stock_price(ticker)
            new_news = collect_news(ticker, name)
            print(f"    - Updated latest price. Scraped {len(new_news)} headlines.")
        except Exception as e:
            print(f"    - Error syncing live data: {e}")
            continue

        # Add to portfolio holdings
        holding, created = PortfolioHolding.objects.get_or_create(
            portfolio=portfolio,
            stock=stock,
            defaults={
                "quantity": qty,
                "buy_price": buy_price,
                "buy_date": timezone.now().date() - datetime.timedelta(days=10),
            },
        )
        if created:
            print(f"    - Added holding: {qty} shares bought at INR {buy_price}")

        # Setup standard alert rule
        AlertRule.objects.get_or_create(
            user=user,
            stock=stock,
            alert_type="PRICE_MOVE",
            defaults={"threshold_value": 3.0},
        )

        # Run sentiment analysis
        try:
            avg_sent, signal, count = batch_analyze_stock(stock)
            print(f"    - Calculated sentiment (24h avg): {avg_sent:.2f}. Signal: {signal}")
        except Exception as e:
            print(f"    - Sentiment scoring error: {e}")
            avg_sent = 0.0

        # Calculate technical indicators
        try:
            indicators = get_technical_indicators(ticker)
            # Run prediction LLaMA/Rules engine
            generate_prediction(stock, avg_sent, indicators)
            # Run SHAP explainer
            generate_insight_report(stock)
            print("    - Formulated AI trend predictions and SHAP factor attribution.")
        except Exception as e:
            print(f"    - Indicators/Prediction error: {e}")

    print("\n====================================================")
    print("Database populated successfully with stock news & holdings!")
    print("====================================================")


if __name__ == "__main__":
    populate_initial_data()
