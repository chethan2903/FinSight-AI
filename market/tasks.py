import logging
from celery import shared_task
from django.contrib.auth.models import User
from market.models import PortfolioHolding, Stock
from market.utils.data_collector import collect_all_watchlist
from market.utils.sentiment_engine import batch_analyze_stock
from market.utils.prediction_engine import get_technical_indicators, generate_prediction
from market.utils.explainer import generate_insight_report
from market.utils.alert_engine import check_alerts

logger = logging.getLogger(__name__)


@shared_task
def run_market_update():
    """Celery background task running every 15 mins to sync stock prices, headlines, sentiments, predictions, and alerts."""
    logger.info("Executing scheduled market update task...")
    active_users = User.objects.filter(is_active=True)

    for user in active_users:
        try:
            # 1. Sync live stock price & scrape RSS feeds
            summary = collect_all_watchlist(user)
            logger.info(f"Live data update for {user.username}: {summary}")

            # 2. Update sentiment scores and signals for portfolio holdings
            holdings = PortfolioHolding.objects.filter(portfolio__user=user)
            for holding in holdings:
                stock_obj = holding.stock

                # Run sentiment pipeline on new articles
                avg_sentiment, signal, article_count = batch_analyze_stock(stock_obj)

                # Get technical indicators
                indicators = get_technical_indicators(stock_obj.ticker)

                # Generate trend prediction and save MarketSignal
                generate_prediction(stock_obj, avg_sentiment, indicators)

                # Run SHAP explainer
                generate_insight_report(stock_obj)

            # 3. Process active alert rules
            alerts_fired = check_alerts(user)
            logger.info(f"Alert evaluation complete for {user.username}. Fired: {alerts_fired}")

        except Exception as e:
            logger.error(f"Error executing update workflow for user {user.username}: {e}")

    return "Scheduled update executed successfully."
