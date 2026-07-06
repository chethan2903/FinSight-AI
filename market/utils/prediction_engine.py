import os
import json
import logging
import pandas as pd
import yfinance as yf
from django.utils import timezone
from groq import Groq
from market.models import Stock, StockPrice, NewsArticle, MarketSignal

logger = logging.getLogger(__name__)

# Initialize Groq client if key is present
api_key = os.getenv("GROQ_API_KEY")
if api_key:
    try:
        groq_client = Groq(api_key=api_key)
    except Exception as e:
        logger.error(f"Failed to initialize Groq client: {e}")
        groq_client = None
else:
    logger.warning("GROQ_API_KEY is not configured. Falling back to rules-based insights.")
    groq_client = None


def get_technical_indicators(ticker):
    """Fetch 60-day historical data and calculate MA-7, MA-21, RSI-14, price change %, and volume trend."""
    try:
        yt = yf.Ticker(ticker)
        df = yt.history(period="60d")
        if df.empty or len(df) < 5:
            # Try loading existing StockPrice history if yfinance fails
            prices = StockPrice.objects.filter(stock__ticker=ticker).order_by("timestamp")
            if prices.exists():
                data = {
                    "Close": [p.close_price for p in prices],
                    "Volume": [p.volume for p in prices],
                }
                df = pd.DataFrame(data)
            else:
                return {
                    "ma7": 0.0,
                    "ma21": 0.0,
                    "rsi": 50.0,
                    "price_change_pct": 0.0,
                    "volume_ratio": 1.0,
                    "current_price": 0.0,
                }

        # Current Price
        current_price = float(df["Close"].iloc[-1])

        # Moving Averages
        df["MA7"] = df["Close"].rolling(window=min(7, len(df))).mean()
        df["MA21"] = df["Close"].rolling(window=min(21, len(df))).mean()

        ma7 = float(df["MA7"].iloc[-1]) if not pd.isna(df["MA7"].iloc[-1]) else current_price
        ma21 = float(df["MA21"].iloc[-1]) if not pd.isna(df["MA21"].iloc[-1]) else current_price

        # RSI (14 days)
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(window=min(14, len(df) - 1)).mean()
        avg_loss = loss.rolling(window=min(14, len(df) - 1)).mean()

        last_loss = avg_loss.iloc[-1] if len(avg_loss) > 0 else 0
        last_gain = avg_gain.iloc[-1] if len(avg_gain) > 0 else 0

        if pd.isna(last_loss) or pd.isna(last_gain) or last_loss == 0:
            rsi = 50.0
        else:
            rs = last_gain / last_loss
            rsi = float(100.0 - (100.0 / (1.0 + rs)))

        # 7-day price change
        idx_7 = max(0, len(df) - 7)
        price_7_days_ago = float(df["Close"].iloc[idx_7])
        price_change_pct = (
            ((current_price - price_7_days_ago) / price_7_days_ago) * 100.0
            if price_7_days_ago != 0
            else 0.0
        )

        # Volume Trend
        # average last 7 days vs previous 7 days
        avg_vol_7 = df["Volume"].iloc[-7:].mean()
        avg_vol_prev_7 = df["Volume"].iloc[-14:-7].mean()
        if pd.isna(avg_vol_prev_7) or avg_vol_prev_7 == 0:
            volume_ratio = 1.0
        else:
            volume_ratio = float(avg_vol_7 / avg_vol_prev_7)

        return {
            "ma7": ma7,
            "ma21": ma21,
            "rsi": rsi,
            "price_change_pct": price_change_pct,
            "volume_ratio": volume_ratio,
            "current_price": current_price,
        }

    except Exception as e:
        logger.error(f"Error calculating technical indicators for {ticker}: {e}")
        return {
            "ma7": 0.0,
            "ma21": 0.0,
            "rsi": 50.0,
            "price_change_pct": 0.0,
            "volume_ratio": 1.0,
            "current_price": 0.0,
        }


def generate_prediction(stock_obj, sentiment_score, indicators):
    """Run LLM prediction using Groq client, falling back to rule-based prediction if unavailable."""
    headlines = NewsArticle.objects.filter(stock=stock_obj).order_by("-published_at")[:5]
    headline_summary = (
        "; ".join([h.title for h in headlines])
        if headlines.exists()
        else "No recent news available"
    )

    outlook = "NEUTRAL"
    key_factors = []
    risk_factors = []
    confidence = "MEDIUM"
    reasoning = ""

    # Try calling Groq LLaMA model if client and key are configured
    if groq_client:
        prompt = f"""You are a senior financial analyst. Analyze this stock:
Company: {stock_obj.name} ({stock_obj.ticker})
Current Price: ₹{indicators['current_price']}
7-day price change: {indicators['price_change_pct']:.2f}%
RSI (14): {indicators['rsi']:.2f}
7-day MA: {indicators['ma7']:.2f} | 21-day MA: {indicators['ma21']:.2f}
Volume trend: {indicators['volume_ratio']:.2f}x average volume
News sentiment score (24h): {sentiment_score:.2f} (scale -1 to +1)
Recent headline themes: {headline_summary}

Based on this data, provide:
1. SHORT-TERM OUTLOOK (1-7 days): BULLISH/BEARISH/NEUTRAL
2. KEY FACTORS: 3 bullet points explaining why
3. RISK FACTORS: 2 main risks
4. CONFIDENCE: LOW/MEDIUM/HIGH

Respond in JSON format only:
{{
  "outlook": "BULLISH/BEARISH/NEUTRAL",
  "key_factors": ["...", "...", "..."],
  "risk_factors": ["...", "..."],
  "confidence": "LOW/MEDIUM/HIGH",
  "reasoning": "one paragraph summary"
}}"""

        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model="llama-3.1-8b-instant",
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            result_json = json.loads(chat_completion.choices[0].message.content)
            outlook = result_json.get("outlook", "NEUTRAL").upper()
            key_factors = result_json.get("key_factors", [])
            risk_factors = result_json.get("risk_factors", [])
            confidence = result_json.get("confidence", "MEDIUM").upper()
            reasoning = result_json.get("reasoning", "")
        except Exception as e:
            logger.error(f"Groq API call failed: {e}. Falling back to rule-based prediction.")
            groq_client_failed = True
        else:
            groq_client_failed = False
    else:
        groq_client_failed = True

    # Rule-based fallback if Groq failed or key is missing
    if groq_client_failed:
        # Determine outlook based on sentiment and RSI
        if sentiment_score >= 0.25 and indicators["rsi"] < 70:
            outlook = "BULLISH"
        elif sentiment_score <= -0.25 and indicators["rsi"] > 30:
            outlook = "BEARISH"
        else:
            outlook = "NEUTRAL"

        # Generate key factors
        key_factors = [
            f"Sentiment is currently {sentiment_score:.2f} indicating a {'positive' if sentiment_score > 0 else 'negative' if sentiment_score < 0 else 'stable'} tone.",
            f"RSI (14) stands at {indicators['rsi']:.1f}, which is in the {'overbought' if indicators['rsi'] > 70 else 'oversold' if indicators['rsi'] < 30 else 'neutral'} zone.",
            f"Short term MA-7 is ₹{indicators['ma7']:.2f} vs medium term MA-21 of ₹{indicators['ma21']:.2f}.",
        ]

        # Generate risk factors
        risk_factors = [
            "Volatility could spike due to unexpected macroeconomic indicators.",
            "Short-term price action might deviate from underlying technical indicators.",
        ]

        # Determine confidence
        confidence = "HIGH" if abs(sentiment_score) > 0.5 else "MEDIUM"

        # Generate reasoning
        reasoning = (
            f"The stock exhibits a {outlook.lower()} outlook. Sentiment analysis indicates "
            f"general market sentiment is {sentiment_score:.2f}. Technical parameters are supportive, with "
            f"an RSI of {indicators['rsi']:.1f} and volume ratio of {indicators['volume_ratio']:.2f}x. "
            f"Investors should keep a watch on key moving averages."
        )

    # Map outlook to signal (BUY/SELL/HOLD/WATCH)
    signal_map = {"BULLISH": "BUY", "BEARISH": "SELL", "NEUTRAL": "HOLD"}
    signal_val = signal_map.get(outlook, "WATCH")

    confidence_map = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3}
    confidence_val = confidence_map.get(confidence, 0.5)

    price_trend = "SIDEWAYS"
    if indicators["ma7"] > indicators["ma21"] * 1.01:
        price_trend = "UPWARD"
    elif indicators["ma7"] < indicators["ma21"] * 0.99:
        price_trend = "DOWNWARD"

    # SHAP factors will be computed in explainer.py and saved. Initialize with empty dict first.
    # Create MarketSignal in database
    signal_obj = MarketSignal.objects.create(
        stock=stock_obj,
        signal=signal_val,
        confidence=confidence_val,
        sentiment_score=sentiment_score,
        price_trend=price_trend,
        reasoning=reasoning,
        shap_factors={},
    )

    return {
        "id": signal_obj.id,
        "signal": signal_val,
        "confidence": confidence_val,
        "sentiment_score": sentiment_score,
        "price_trend": price_trend,
        "reasoning": reasoning,
        "key_factors": key_factors,
        "risk_factors": risk_factors,
        "created_at": signal_obj.created_at,
    }
