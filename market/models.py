from django.db import models
from django.contrib.auth.models import User


class Stock(models.Model):
    ticker = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=255)
    sector = models.CharField(max_length=100, blank=True, null=True)
    exchange = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.ticker})"


class StockPrice(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name="prices")
    open_price = models.FloatField()
    high_price = models.FloatField()
    low_price = models.FloatField()
    close_price = models.FloatField()
    volume = models.BigIntegerField()
    timestamp = models.DateTimeField()

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.stock.ticker} - Close: {self.close_price} at {self.timestamp}"


class NewsArticle(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name="articles")
    title = models.TextField()
    url = models.URLField(max_length=1000)
    source = models.CharField(max_length=100)
    published_at = models.DateTimeField()
    raw_text = models.TextField()

    class Meta:
        ordering = ["-published_at"]
        constraints = [
            models.UniqueConstraint(fields=["stock", "title"], name="unique_stock_news_title")
        ]

    def __str__(self):
        return f"{self.stock.ticker} News: {self.title[:50]}"


class SentimentScore(models.Model):
    article = models.OneToOneField(NewsArticle, on_delete=models.CASCADE, related_name="sentiment")
    finbert_label = models.CharField(max_length=20)
    finbert_score = models.FloatField()  # average or confidence score
    roberta_label = models.CharField(max_length=20)
    roberta_score = models.FloatField()
    ensemble_label = models.CharField(max_length=20)
    ensemble_score = models.FloatField()  # Range: -1.0 to +1.0
    analyzed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.article.stock.ticker} - Label: {self.ensemble_label} ({self.ensemble_score:.2f})"


class MarketSignal(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name="signals")
    signal = models.CharField(max_length=20)  # BUY, SELL, HOLD, WATCH
    confidence = models.FloatField()  # 0.0 to 1.0
    sentiment_score = models.FloatField()
    price_trend = models.CharField(max_length=20)  # UPWARD, DOWNWARD, SIDEWAYS
    reasoning = models.TextField()
    shap_factors = models.JSONField(default=dict)  # JSON representation of factors
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.stock.ticker} Signal: {self.signal} at {self.created_at}"


class Portfolio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="portfolios")
    name = models.CharField(max_length=100, default="My Portfolio")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s Portfolio: {self.name}"


class PortfolioHolding(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name="holdings")
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    quantity = models.FloatField()
    buy_price = models.FloatField()
    buy_date = models.DateField()

    def __str__(self):
        return f"{self.portfolio.user.username} - {self.stock.ticker}: {self.quantity} shares"


class AlertRule(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="alert_rules")
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=50)  # SENTIMENT_DROP, PRICE_MOVE, VOLUME_SPIKE, SIGNAL_CHANGE
    threshold_value = models.FloatField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.stock.ticker} {self.alert_type} Alert"


class AlertNotification(models.Model):
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="notifications")
    message = models.TextField()
    triggered_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-triggered_at"]

    def __str__(self):
        return f"Alert: {self.message[:50]} at {self.triggered_at}"
