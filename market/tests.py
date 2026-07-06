from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
import datetime
from unittest.mock import patch, MagicMock

from market.models import (
    Stock,
    StockPrice,
    NewsArticle,
    SentimentScore,
    MarketSignal,
    Portfolio,
    PortfolioHolding,
    AlertRule,
)
from market.utils.sentiment_engine import analyze_article
from market.utils.explainer import generate_insight_report


class MarketModelTest(TestCase):

    def setUp(self):
        # Create standard test data
        self.stock = Stock.objects.create(
            ticker="AAPL", name="Apple Inc.", sector="Technology", exchange="NASDAQ"
        )
        self.price = StockPrice.objects.create(
            stock=self.stock,
            open_price=150.0,
            high_price=155.0,
            low_price=149.0,
            close_price=152.5,
            volume=5000000,
            timestamp=timezone.now(),
        )

    def test_stock_creation(self):
        self.assertEqual(self.stock.ticker, "AAPL")
        self.assertEqual(str(self.stock), "Apple Inc. (AAPL)")

    def test_stock_price_creation(self):
        self.assertEqual(self.price.stock, self.stock)
        self.assertEqual(self.price.close_price, 152.5)


class MarketViewsTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.username = "testuser"
        self.password = "securepass123"
        self.user = User.objects.create_user(
            username=self.username, password=self.password
        )
        self.stock = Stock.objects.create(
            ticker="AAPL", name="Apple Inc.", sector="Technology", exchange="NASDAQ"
        )
        self.portfolio = Portfolio.objects.create(
            user=self.user, name="Primary Portfolio"
        )

    def test_dashboard_redirects_for_anonymous_user(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_dashboard_authenticated(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard.html")

    def test_portfolio_dashboard_authenticated(self):
        self.client.login(username=self.username, password=self.password)
        # Add holding
        PortfolioHolding.objects.create(
            portfolio=self.portfolio,
            stock=self.stock,
            quantity=10,
            buy_price=140.0,
            buy_date=timezone.now().date(),
        )
        response = self.client.get(reverse("portfolio_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portfolio.html")
        self.assertContains(response, "AAPL")
        self.assertContains(response, "140.00")

    def test_assistant_chat_page(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("assistant_chat"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "assistant.html")

    def test_alerts_config_view(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.get(reverse("alerts_config"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "alerts.html")


class MarketUtilsTest(TestCase):

    def setUp(self):
        self.stock = Stock.objects.create(
            ticker="INFY.NS", name="Infosys Limited", sector="Technology"
        )

    def test_analyze_article_fallback(self):
        # Testing fallback rules-based sentiment analysis
        result = analyze_article("Infosys announces high profits and revenue growth")
        self.assertEqual(result["ensemble_label"], "positive")
        self.assertGreater(result["ensemble_score"], 0.0)

    @patch("market.utils.prediction_engine.yf.Ticker")
    def test_generate_insight_report(self, mock_ticker):
        # Mocking yfinance history output for indicators calculation
        mock_instance = MagicMock()
        mock_ticker.return_value = mock_instance
        
        # Build fake history DataFrame
        import pandas as pd
        fake_dates = pd.date_range(start="2026-05-01", periods=30)
        fake_df = pd.DataFrame(
            {"Close": [100.0 + i for i in range(30)], "Volume": [1000 * i for i in range(30)]},
            index=fake_dates
        )
        mock_instance.history.return_value = fake_df

        # Create StockPrice and MarketSignal to feed the explainer
        StockPrice.objects.create(
            stock=self.stock,
            open_price=125.0,
            high_price=132.0,
            low_price=124.0,
            close_price=130.0,
            volume=50000,
            timestamp=timezone.now()
        )
        MarketSignal.objects.create(
            stock=self.stock,
            signal="BUY",
            confidence=0.8,
            sentiment_score=0.4,
            price_trend="UPWARD",
            reasoning="supportive trends"
        )

        factors = generate_insight_report(self.stock)
        self.assertEqual(len(factors), 4)
        # Check SHAP weights sum to approximately 1.0
        total_w = sum(f["weight"] for f in factors)
        self.assertAlmostEqual(total_w, 1.0, places=1)
