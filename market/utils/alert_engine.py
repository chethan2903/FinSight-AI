import logging
import datetime
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from market.models import (
    AlertRule,
    AlertNotification,
    StockPrice,
    SentimentScore,
    MarketSignal,
)
from market.utils.prediction_engine import get_technical_indicators

logger = logging.getLogger(__name__)


def check_alerts(user):
    """Evaluate active alert rules for a user, create notifications, and broadcast via WebSockets."""
    active_rules = AlertRule.objects.filter(user=user, is_active=True)
    channel_layer = get_channel_layer()
    group_name = f"user_{user.id}_alerts"

    notifications_count = 0

    for rule in active_rules:
        triggered = False
        message = ""
        severity = "medium"

        # 1. Fetch parameters
        latest_price_obj = StockPrice.objects.filter(stock=rule.stock).order_by("-timestamp").first()
        if not latest_price_obj:
            continue

        # 2. Evaluate alert types
        if rule.alert_type == "SENTIMENT_DROP":
            # Check latest average sentiment score
            recent_scores = SentimentScore.objects.filter(article__stock=rule.stock).order_by(
                "-analyzed_at"
            )[:3]
            if recent_scores.exists():
                avg_sent = sum(s.ensemble_score for s in recent_scores) / len(recent_scores)
                # Trigger if sentiment is below threshold (e.g. threshold_value = -0.2)
                if avg_sent <= rule.threshold_value:
                    triggered = True
                    message = (
                        f"Sentiment drop alert! {rule.stock.ticker} sentiment score is at "
                        f"{avg_sent:.2f}, below threshold of {rule.threshold_value:.2f}."
                    )
                    severity = "high"

        elif rule.alert_type == "PRICE_MOVE":
            # Check price move % in last hour or since last price point
            prev_prices = StockPrice.objects.filter(stock=rule.stock).order_by("-timestamp")[1:6]
            if prev_prices.exists():
                old_price = prev_prices[0].close_price
                current_price = latest_price_obj.close_price
                price_diff_pct = (
                    abs(current_price - old_price) / old_price * 100.0 if old_price != 0 else 0.0
                )
                if price_diff_pct >= rule.threshold_value:
                    triggered = True
                    direction = "up" if current_price > old_price else "down"
                    message = (
                        f"Price move alert! {rule.stock.ticker} moved {direction} by "
                        f"{price_diff_pct:.2f}%, exceeding threshold of {rule.threshold_value:.2f}%."
                    )
                    severity = "high" if price_diff_pct > 5.0 else "medium"

        elif rule.alert_type == "VOLUME_SPIKE":
            # Check if volume is threshold_value times (e.g. 2x) the 7-day average
            indicators = get_technical_indicators(rule.stock.ticker)
            vol_ratio = indicators.get("volume_ratio", 1.0)
            if vol_ratio >= rule.threshold_value:
                triggered = True
                message = (
                    f"Volume spike alert! {rule.stock.ticker} volume is {vol_ratio:.2f}x "
                    f"its 7-day average, exceeding threshold of {rule.threshold_value:.2f}x."
                )
                severity = "medium"

        elif rule.alert_type == "SIGNAL_CHANGE":
            # Check if signal has changed between the two most recent records
            recent_signals = MarketSignal.objects.filter(stock=rule.stock).order_by("-created_at")[:2]
            if len(recent_signals) == 2:
                latest_sig = recent_signals[0].signal
                prev_sig = recent_signals[1].signal
                # If signal changed, check if it fits BUY<->SELL transition (or any transition if threshold is 1)
                # Typically threshold_value can be 1.0 to check for BUY/SELL flip
                if latest_sig != prev_sig:
                    if (
                        (latest_sig == "BUY" and prev_sig == "SELL")
                        or (latest_sig == "SELL" and prev_sig == "BUY")
                        or rule.threshold_value == 0.0
                    ):
                        triggered = True
                        message = (
                            f"Signal change alert! {rule.stock.ticker} signal changed "
                            f"from {prev_sig} to {latest_sig}."
                        )
                        severity = "high"

        # 3. Handle triggered events
        if triggered:
            # Create AlertNotification
            AlertNotification.objects.create(rule=rule, message=message)
            notifications_count += 1

            # Dispatch WebSocket message via Channel Group
            if channel_layer:
                try:
                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        {
                            "type": "send_alert",
                            "data": {
                                "type": "alert",
                                "stock": rule.stock.ticker,
                                "message": message,
                                "severity": severity,
                                "timestamp": timezone.now().strftime("%H:%M:%S"),
                            },
                        },
                    )
                except Exception as e:
                    logger.error(f"Failed to send alert via WebSocket group {group_name}: {e}")

    return notifications_count
