import logging
from market.models import Stock, StockPrice, MarketSignal, SentimentScore
from market.utils.prediction_engine import get_technical_indicators

logger = logging.getLogger(__name__)


def generate_insight_report(stock_obj):
    """Calculate SHAP-style contributions for key factors, normalize, update MarketSignal, and return list."""
    # 1. Fetch latest prices and sentiment
    latest_price = StockPrice.objects.filter(stock=stock_obj).order_by("-timestamp").first()
    latest_signal = MarketSignal.objects.filter(stock=stock_obj).order_by("-created_at").first()

    # Get average sentiment of last 5 articles
    recent_sentiment_scores = SentimentScore.objects.filter(article__stock=stock_obj).order_by(
        "-analyzed_at"
    )[:5]
    if recent_sentiment_scores.exists():
        avg_sentiment = sum(s.ensemble_score for s in recent_sentiment_scores) / len(
            recent_sentiment_scores
        )
    else:
        avg_sentiment = 0.0

    # 2. Get technical indicators
    indicators = get_technical_indicators(stock_obj.ticker)
    rsi = indicators.get("rsi", 50.0)
    change_pct = indicators.get("price_change_pct", 0.0)
    volume_ratio = indicators.get("volume_ratio", 1.0)

    # 3. Compute raw SHAP-style weights
    raw_sentiment_w = abs(avg_sentiment) * 0.4
    raw_momentum_w = abs(change_pct / 10.0) * 0.3
    raw_volume_w = abs(volume_ratio - 1.0) * 0.2
    raw_rsi_w = abs(rsi - 50.0) / 50.0 * 0.1

    # Avoid zero weights sum division error
    total_raw = raw_sentiment_w + raw_momentum_w + raw_volume_w + raw_rsi_w
    if total_raw == 0:
        raw_sentiment_w = 0.4
        raw_momentum_w = 0.3
        raw_volume_w = 0.2
        raw_rsi_w = 0.1
        total_raw = 1.0

    # Normalize weights to sum to 1.0
    sentiment_weight = round(raw_sentiment_w / total_raw, 2)
    momentum_weight = round(raw_momentum_w / total_raw, 2)
    volume_weight = round(raw_volume_w / total_raw, 2)
    rsi_weight = round(1.0 - (sentiment_weight + momentum_weight + volume_weight), 2)

    # Compile factors details
    factors = [
        {
            "factor": "News Sentiment",
            "weight": sentiment_weight,
            "direction": "positive" if avg_sentiment >= 0 else "negative",
        },
        {
            "factor": "Price Momentum",
            "weight": momentum_weight,
            "direction": "positive" if change_pct >= 0 else "negative",
        },
        {
            "factor": "Volume Expansion",
            "weight": volume_weight,
            "direction": "positive" if volume_ratio >= 1.0 else "negative",
        },
        {
            "factor": "RSI Indicator",
            "weight": rsi_weight,
            "direction": "positive" if rsi >= 50 else "negative",
        },
    ]

    # Sort factors by magnitude of impact
    factors.sort(key=lambda x: x["weight"], reverse=True)

    # 4. Save to MarketSignal if it exists
    if latest_signal:
        latest_signal.shap_factors = factors
        latest_signal.save()
        logger.info(f"Updated SHAP factors on MarketSignal id {latest_signal.id} for {stock_obj.ticker}")

    return factors
