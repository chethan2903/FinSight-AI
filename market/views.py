import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
import yfinance as yf

from market.models import (
    Stock,
    StockPrice,
    NewsArticle,
    SentimentScore,
    MarketSignal,
    Portfolio,
    PortfolioHolding,
    AlertRule,
    AlertNotification,
)
from market.utils.data_collector import collect_stock_price, collect_news
from market.utils.sentiment_engine import batch_analyze_stock
from market.utils.prediction_engine import get_technical_indicators, generate_prediction
from market.utils.explainer import generate_insight_report
from market.utils.rag_assistant import answer_question


@login_required
def dashboard(request):
    """Render main dashboard with general market stats, latest signals, and unread notifications."""
    # Ensure user has a portfolio
    portfolio, _ = Portfolio.objects.get_or_create(user=request.user, defaults={"name": "Primary Portfolio"})

    # Fetch user's holdings
    holdings = PortfolioHolding.objects.filter(portfolio=portfolio)
    holding_stocks = [h.stock for h in holdings]

    # Prepopulate database with default stocks if empty (to give a premium first-impression)
    default_tickers = ["AAPL", "MSFT", "GOOGL", "INFY.NS"]
    if Stock.objects.count() == 0:
        for ticker in default_tickers:
            try:
                # Add default stocks
                collect_stock_price(ticker)
                # Scrap news
                collect_news(ticker, ticker)
            except Exception:
                pass

    # Fetch all stocks in system
    all_stocks = Stock.objects.all()

    # Get latest signals and prices for dashboard display
    stocks_summary = []
    for stock in all_stocks:
        latest_price = StockPrice.objects.filter(stock=stock).order_by("-timestamp").first()
        latest_signal = MarketSignal.objects.filter(stock=stock).order_by("-created_at").first()

        stocks_summary.append(
            {
                "stock": stock,
                "price": latest_price.close_price if latest_price else None,
                "volume": latest_price.volume if latest_price else None,
                "signal": latest_signal.signal if latest_signal else "WATCH",
                "confidence": latest_signal.confidence if latest_signal else 0.5,
                "trend": latest_signal.price_trend if latest_signal else "SIDEWAYS",
                "is_held": stock in holding_stocks,
            }
        )

    # Fetch unread notifications
    unread_notifications = AlertNotification.objects.filter(
        rule__user=request.user, is_read=False
    ).order_by("-triggered_at")[:10]

    context = {
        "stocks_summary": stocks_summary,
        "unread_notifications": unread_notifications,
        "portfolio": portfolio,
        "holdings_count": holdings.count(),
    }
    return render(request, "dashboard.html", context)


@login_required
def stock_detail(request, ticker):
    """Render comprehensive details for a stock, including Plotly charts, sentiment breakdown, and SHAP factors."""
    ticker = ticker.strip().upper()
    try:
        stock = Stock.objects.get(ticker=ticker)
    except Stock.DoesNotExist:
        # Validate ticker using yfinance
        yt = yf.Ticker(ticker)
        try:
            hist = yt.history(period="1d")
            if hist.empty:
                messages.error(request, f"Ticker {ticker} not found on Yahoo Finance.")
                return redirect("dashboard")
        except Exception:
            messages.error(request, f"Could not validate ticker {ticker}.")
            return redirect("dashboard")

        # Fetch metadata
        name = ticker
        exchange = "UNKNOWN"
        sector = "UNKNOWN"
        try:
            info = yt.info
            name = info.get("longName") or info.get("shortName") or ticker
            exchange = info.get("exchange") or "UNKNOWN"
            sector = info.get("sector") or "UNKNOWN"
        except Exception:
            pass

        # Create stock in DB
        stock = Stock.objects.create(
            ticker=ticker, name=name, exchange=exchange, sector=sector
        )
        
        # Initial data sync
        try:
            collect_stock_price(ticker)
            collect_news(ticker, name)
        except Exception:
            pass

    # Trigger fresh data fetch if last price is older than 15 mins (or doesn't exist)
    latest_price = StockPrice.objects.filter(stock=stock).order_by("-timestamp").first()
    if not latest_price or (timezone.now() - latest_price.timestamp).total_seconds() > 900:
        try:
            collect_stock_price(ticker)
            collect_news(ticker, stock.name)
            latest_price = StockPrice.objects.filter(stock=stock).order_by("-timestamp").first()
        except Exception as e:
            messages.warning(request, f"Could not refresh live data: {e}")


    # Ensure sentiment scores exist and signals are updated
    avg_score, signal, count = batch_analyze_stock(stock)
    indicators = get_technical_indicators(ticker)
    generate_prediction(stock, avg_score, indicators)
    shap_factors = generate_insight_report(stock)

    latest_signal = MarketSignal.objects.filter(stock=stock).order_by("-created_at").first()

    # Historical prices for Plotly chart (limit to last 50 data points)
    historical_prices = StockPrice.objects.filter(stock=stock).order_by("timestamp")[:50]
    price_chart_data = {
        "timestamps": [p.timestamp.strftime("%Y-%m-%d %H:%M") for p in historical_prices],
        "prices": [p.close_price for p in historical_prices],
        "volumes": [p.volume for p in historical_prices],
    }

    # News sentiment breakdown
    recent_news = NewsArticle.objects.filter(stock=stock).order_by("-published_at")[:10]
    news_list = []
    for item in recent_news:
        sentiment = SentimentScore.objects.filter(article=item).first()
        news_list.append({"article": item, "sentiment": sentiment})

    # Prepare Context
    context = {
        "stock": stock,
        "price_data": latest_price,
        "signal": latest_signal,
        "indicators": indicators,
        "shap_factors": shap_factors,
        "news_list": news_list,
        "price_chart_json": json.dumps(price_chart_data),
    }
    return render(request, "stock_detail.html", context)


@login_required
def portfolio_dashboard(request):
    """Detailed holdings breakdown, totals, performance, and weighted sentiment aggregates."""
    portfolio, _ = Portfolio.objects.get_or_create(user=request.user, defaults={"name": "Primary Portfolio"})
    holdings = PortfolioHolding.objects.filter(portfolio=portfolio)

    holdings_summary = []
    total_invested = 0.0
    total_current = 0.0
    weighted_sentiment_sum = 0.0

    for h in holdings:
        # Get latest price
        latest_price_obj = StockPrice.objects.filter(stock=h.stock).order_by("-timestamp").first()
        current_price = latest_price_obj.close_price if latest_price_obj else h.buy_price

        # Calculations
        cost_basis = h.quantity * h.buy_price
        current_value = h.quantity * current_price
        gain_loss = current_value - cost_basis
        gain_loss_pct = (gain_loss / cost_basis) * 100.0 if cost_basis != 0 else 0.0

        # Accumulators
        total_invested += cost_basis
        total_current += current_value

        # Latest Signal and Sentiment
        latest_signal = MarketSignal.objects.filter(stock=h.stock).order_by("-created_at").first()
        recent_sent = SentimentScore.objects.filter(article__stock=h.stock).order_by("-analyzed_at").first()
        sent_score = recent_sent.ensemble_score if recent_sent else 0.0

        weighted_sentiment_sum += sent_score * current_value

        holdings_summary.append(
            {
                "holding": h,
                "current_price": current_price,
                "current_value": current_value,
                "gain_loss": gain_loss,
                "gain_loss_pct": gain_loss_pct,
                "signal": latest_signal,
                "sentiment_score": sent_score,
            }
        )

    # Aggregates calculations
    total_gain_loss = total_current - total_invested
    total_gain_loss_pct = (total_gain_loss / total_invested) * 100.0 if total_invested != 0 else 0.0

    portfolio_sentiment = (
        weighted_sentiment_sum / total_current if total_current > 0 else 0.0
    )

    # Determine aggregated outlook label
    if portfolio_sentiment >= 0.35:
        portfolio_outlook = "BULLISH"
    elif portfolio_sentiment <= -0.35:
        portfolio_outlook = "BEARISH"
    else:
        portfolio_outlook = "NEUTRAL"

    context = {
        "portfolio": portfolio,
        "holdings": holdings_summary,
        "total_invested": total_invested,
        "total_current": total_current,
        "total_gain_loss": total_gain_loss,
        "total_gain_loss_pct": total_gain_loss_pct,
        "portfolio_sentiment": portfolio_sentiment,
        "portfolio_outlook": portfolio_outlook,
        "stocks": Stock.objects.all(),
    }
    return render(request, "portfolio.html", context)


@login_required
def add_holding(request):
    """Add a new stock holding to the portfolio. Checks yfinance for ticker validity."""
    if request.method == "POST":
        ticker = request.POST.get("ticker", "").strip().upper()
        quantity_str = request.POST.get("quantity", "0")
        buy_price_str = request.POST.get("buy_price", "0")
        buy_date = request.POST.get("buy_date")

        if not ticker or not buy_date:
            messages.error(request, "Please enter all fields.")
            return redirect("portfolio_dashboard")

        try:
            quantity = float(quantity_str)
            buy_price = float(buy_price_str)
        except ValueError:
            messages.error(request, "Invalid numeric values for quantity or buy price.")
            return redirect("portfolio_dashboard")

        # Validate ticker using yfinance
        yt = yf.Ticker(ticker)
        try:
            # Attempt to retrieve info dictionary or history to check validity
            hist = yt.history(period="1d")
            if hist.empty:
                messages.error(request, f"Ticker {ticker} not found on Yahoo Finance.")
                return redirect("portfolio_dashboard")
        except Exception:
            messages.error(request, f"Could not validate ticker {ticker}.")
            return redirect("portfolio_dashboard")

        # Fetch metadata
        name = ticker
        exchange = "UNKNOWN"
        sector = "UNKNOWN"
        try:
            info = yt.info
            name = info.get("longName") or info.get("shortName") or ticker
            exchange = info.get("exchange") or "UNKNOWN"
            sector = info.get("sector") or "UNKNOWN"
        except Exception:
            pass

        # Create/Get Stock
        stock, created = Stock.objects.get_or_create(
            ticker=ticker, defaults={"name": name, "exchange": exchange, "sector": sector}
        )

        # Collect initial price and news
        try:
            collect_stock_price(ticker)
            collect_news(ticker, name)
        except Exception:
            pass

        # Add holding
        portfolio, _ = Portfolio.objects.get_or_create(user=request.user, defaults={"name": "Primary Portfolio"})
        PortfolioHolding.objects.create(
            portfolio=portfolio,
            stock=stock,
            quantity=quantity,
            buy_price=buy_price,
            buy_date=buy_date,
        )

        messages.success(request, f"Holding {ticker} added successfully!")

    return redirect("portfolio_dashboard")


@login_required
def remove_holding(request, holding_id):
    """Delete a specific stock holding from the portfolio."""
    holding = get_object_or_404(PortfolioHolding, id=holding_id, portfolio__user=request.user)
    ticker = holding.stock.ticker
    holding.delete()
    messages.success(request, f"Removed {ticker} holding.")
    return redirect("portfolio_dashboard")


@login_required
def assistant_chat(request):
    """RAG-powered interactive financial chat assistant views."""
    if request.method == "POST":
        if request.content_type and "application/json" in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST
        question = data.get("question", "").strip()
        if not question:
            return JsonResponse({"error": "Empty question"}, status=400)

        try:
            answer = answer_question(request.user, question)
            return JsonResponse({"answer": answer})
        except Exception as e:
            return JsonResponse({"error": f"Error running RAG chatbot: {e}"}, status=500)

    # Render template
    return render(request, "assistant.html")


@login_required
def alerts_config(request):
    """Display active alert rules and previous notifications."""
    rules = AlertRule.objects.filter(user=request.user)
    notifications = AlertNotification.objects.filter(rule__user=request.user).order_by("-triggered_at")[:30]
    stocks = Stock.objects.all()

    context = {
        "rules": rules,
        "notifications": notifications,
        "stocks": stocks,
        "alert_types": [
            ("SENTIMENT_DROP", "Sentiment Score Drop"),
            ("PRICE_MOVE", "Price Movement %"),
            ("VOLUME_SPIKE", "Volume Spikes (x average)"),
            ("SIGNAL_CHANGE", "Market Signal Shift"),
        ],
    }
    return render(request, "alerts.html", context)


@login_required
def create_alert(request):
    """Create a new user-defined alert monitoring threshold."""
    if request.method == "POST":
        stock_id = request.POST.get("stock")
        alert_type = request.POST.get("alert_type")
        threshold_val_str = request.POST.get("threshold_value", "0")

        if not stock_id or not alert_type:
            messages.error(request, "Missing fields for alert creation.")
            return redirect("alerts_config")

        try:
            threshold_value = float(threshold_val_str)
        except ValueError:
            messages.error(request, "Threshold value must be a number.")
            return redirect("alerts_config")

        stock = get_object_or_404(Stock, id=stock_id)

        # Create Rule
        AlertRule.objects.create(
            user=request.user,
            stock=stock,
            alert_type=alert_type,
            threshold_value=threshold_value,
        )
        messages.success(
            request, f"Alert rule for {stock.ticker} created successfully!"
        )

    return redirect("alerts_config")


@login_required
def delete_alert(request, alert_id):
    """Remove a active alert monitoring threshold rule."""
    rule = get_object_or_404(AlertRule, id=alert_id, user=request.user)
    ticker = rule.stock.ticker
    rule.delete()
    messages.success(request, f"Deleted alert rule for {ticker}.")
    return redirect("alerts_config")


@login_required
def mark_notifications_read(request):
    """Mark all triggered alert notifications for user as read."""
    AlertNotification.objects.filter(rule__user=request.user, is_read=False).update(is_read=True)
    messages.success(request, "All notifications marked as read.")
    return redirect("alerts_config")
