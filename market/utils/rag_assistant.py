import os
import datetime
import logging
from django.utils import timezone
from groq import Groq
from market.models import NewsArticle, MarketSignal, PortfolioHolding, StockPrice

logger = logging.getLogger(__name__)

# Try to load ML models at module level
try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer

    embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
except Exception as e:
    logger.warning(
        f"Failed to initialize sentence-transformers or faiss: {e}. Falling back to keyword RAG."
    )
    embedding_model = None
    faiss = None
    np = None

# Initialize Groq client
api_key = os.getenv("GROQ_API_KEY")
if api_key:
    try:
        groq_client = Groq(api_key=api_key)
    except Exception as e:
        logger.error(f"Failed to initialize Groq client: {e}")
        groq_client = None
else:
    groq_client = None


def build_portfolio_index(user):
    """Retrieve portfolio news, signals, holdings, combine them, embed and build FAISS index."""
    chunks = []

    # 1. Fetch user's holdings and performance context
    holdings = PortfolioHolding.objects.filter(portfolio__user=user)
    for h in holdings:
        ticker = h.stock.ticker
        name = h.stock.name
        qty = h.quantity
        buy_price = h.buy_price

        # Get latest price
        latest_price_obj = StockPrice.objects.filter(stock=h.stock).order_by("-timestamp").first()
        current_price = latest_price_obj.close_price if latest_price_obj else buy_price
        total_cost = qty * buy_price
        current_val = qty * current_price
        pnl = current_val - total_cost
        pnl_pct = (pnl / total_cost) * 100.0 if total_cost != 0 else 0.0

        holding_text = (
            f"Portfolio Holding: The investor holds {qty:.2f} shares of {name} ({ticker}) "
            f"bought at a price of ₹{buy_price:.2f} per share on {h.buy_date}. "
            f"The current market price is ₹{current_price:.2f}. "
            f"The total investment is ₹{total_cost:.2f}, current value is ₹{current_val:.2f}, "
            f"with a profit/loss of ₹{pnl:.2f} ({pnl_pct:+.2f}%)."
        )
        chunks.append(holding_text)

    # 2. Fetch recent NewsArticles (last 7 days) for portfolio stocks
    cutoff = timezone.now() - datetime.timedelta(days=7)
    news = NewsArticle.objects.filter(
        stock__portfolioholding__portfolio__user=user, published_at__gte=cutoff
    ).distinct()

    for item in news:
        news_text = (
            f"News Article for {item.stock.name} ({item.stock.ticker}) "
            f"published by {item.source} on {item.published_at.date()}: "
            f"Title: {item.title}. Content Summary: {item.raw_text}"
        )
        chunks.append(news_text)

    # 3. Fetch recent MarketSignals (last 7 days)
    signals = MarketSignal.objects.filter(
        stock__portfolioholding__portfolio__user=user, created_at__gte=cutoff
    ).distinct()

    for sig in signals:
        sig_text = (
            f"Market Signal for {sig.stock.name} ({sig.stock.ticker}) "
            f"generated on {sig.created_at.date()}: "
            f"Recommended Signal: {sig.signal} with confidence {sig.confidence * 100:.1f}%. "
            f"Price trend: {sig.price_trend}. Analytical reasoning: {sig.reasoning}."
        )
        chunks.append(sig_text)

    # Handlers for empty portfolio / no data scenarios
    if not chunks:
        chunks.append(
            "Portfolio Context: The investor portfolio currently has no active holdings or "
            "no recent news/signals available in the system database."
        )

    # If FAISS and SentenceTransformer are successfully loaded
    if embedding_model and faiss and np:
        try:
            embeddings = embedding_model.encode(chunks, show_progress_bar=False)
            embeddings = np.array(embeddings).astype("float32")

            # FAISS IndexFlatL2
            dimension = embeddings.shape[1]
            index = faiss.IndexFlatL2(dimension)
            index.add(embeddings)
            return index, chunks
        except Exception as e:
            logger.error(f"Error building FAISS index: {e}")

    # Fallback return when libraries are missing or indexing fails
    return None, chunks


def answer_question(user, question):
    """Retrieve relevant portfolio context using FAISS (or keyword matching) and query LLM."""
    index, chunks = build_portfolio_index(user)
    retrieved_chunks = []

    # If FAISS index is active
    if index and embedding_model and np:
        try:
            q_emb = embedding_model.encode([question], show_progress_bar=False)
            q_emb = np.array(q_emb).astype("float32")

            # Query top 5 chunks
            k = min(5, len(chunks))
            distances, indices = index.search(q_emb, k)

            for idx in indices[0]:
                if idx != -1 and idx < len(chunks):
                    retrieved_chunks.append(chunks[idx])
        except Exception as e:
            logger.error(f"FAISS search failed: {e}")

    # Fallback keyword-based search if FAISS failed or is unavailable
    if not retrieved_chunks:
        # Match keywords between question and chunks
        q_words = set(question.lower().split())
        scored_chunks = []
        for chunk in chunks:
            match_score = sum(1 for w in q_words if w in chunk.lower())
            scored_chunks.append((match_score, chunk))
        # Sort by match score descending
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        retrieved_chunks = [item[1] for item in scored_chunks[:5]]

    context_str = "\n\n".join(retrieved_chunks)

    # Groq API LLM assistant call
    if groq_client:
        prompt = f"""You are a personal financial assistant for this investor.
Answer their question using ONLY the information below.
If the information is not available, say so clearly.
Never make up prices, news, or predictions.

PORTFOLIO CONTEXT:
{context_str}

USER QUESTION: {question}

Answer in 2-3 clear sentences. Be specific with numbers."""

        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0.1,
            )
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Groq API assistant call failed: {e}")

    # Rule-based response fallback if Groq API fails or is not configured
    # Attempt to extract context matching key terms in the question
    question_lower = question.lower()
    answer_parts = []

    # Fetch holdings data from database directly for precise calculations
    try:
        from market.models import Portfolio, PortfolioHolding, StockPrice, NewsArticle, MarketSignal
        portfolio = Portfolio.objects.filter(user=user).first()
        holdings = PortfolioHolding.objects.filter(portfolio=portfolio) if portfolio else []
    except Exception:
        holdings = []

    # 1. Check for Portfolio Holdings List query
    if any(w in question_lower for w in ["holding", "portfolio", "stock", "share", "asset", "own", "hold"]):
        if holdings:
            lines = []
            for h in holdings:
                latest_p = StockPrice.objects.filter(stock=h.stock).order_by("-timestamp").first()
                curr_price = latest_p.close_price if latest_p else h.buy_price
                val = h.quantity * curr_price
                lines.append(f"{h.stock.ticker} ({h.quantity:.0f} shares, valued at ₹{val:.2f})")
            answer_parts.append("Your current holdings: " + ", ".join(lines) + ".")
        else:
            answer_parts.append("You do not have any active assets in your portfolio holdings.")

    # 2. Check for P&L or value keywords
    if any(w in question_lower for w in ["p&l", "profit", "gain", "loss", "performance", "value", "worth", "return"]):
        if holdings:
            tot_cost = 0.0
            tot_val = 0.0
            for h in holdings:
                latest_p = StockPrice.objects.filter(stock=h.stock).order_by("-timestamp").first()
                curr_price = latest_p.close_price if latest_p else h.buy_price
                tot_cost += h.quantity * h.buy_price
                tot_val += h.quantity * curr_price
            pnl = tot_val - tot_cost
            pnl_pct = (pnl / tot_cost * 100.0) if tot_cost > 0 else 0.0
            answer_parts.append(
                f"Your total portfolio is currently valued at ₹{tot_val:.2f} (invested: ₹{tot_cost:.2f}), "
                f"yielding a profit/loss of ₹{pnl:+.2f} ({pnl_pct:+.2f}%)."
            )
        else:
            answer_parts.append("No portfolio assets found to calculate performance metrics.")

    # 3. Check for news query
    if any(w in question_lower for w in ["news", "headline", "happen", "article"]):
        # Look for a specific stock ticker in question
        matched_stock = None
        for h in holdings:
            ticker_base = h.stock.ticker.split(".")[0].lower()
            if ticker_base in question_lower or h.stock.ticker.lower() in question_lower:
                matched_stock = h.stock
                break
        
        if matched_stock:
            articles = NewsArticle.objects.filter(stock=matched_stock).order_by("-published_at")[:2]
            if articles.exists():
                lines = [f"'{a.title}' ({a.source})" for a in articles]
                answer_parts.append(f"Recent headlines for {matched_stock.ticker}: " + " | ".join(lines))
            else:
                answer_parts.append(f"No recent news articles found in the database for {matched_stock.ticker}.")
        else:
            # General news (top 3 articles overall)
            articles = NewsArticle.objects.filter(stock__portfolioholding__portfolio__user=user).order_by("-published_at")[:2]
            if articles.exists():
                lines = [f"'{a.title}' ({a.stock.ticker})" for a in articles]
                answer_parts.append("Latest headlines in your portfolio: " + " | ".join(lines))
            else:
                answer_parts.append("No portfolio stock news articles are available in the database.")

    # 4. Check for signals / predictions
    if any(w in question_lower for w in ["signal", "outlook", "trend", "buy", "sell", "recommend"]):
        lines = []
        for h in holdings:
            sig = MarketSignal.objects.filter(stock=h.stock).order_by("-created_at").first()
            if sig:
                lines.append(f"{h.stock.ticker}: {sig.signal} (confidence {sig.confidence * 100:.0f}%, trend {sig.price_trend})")
        if lines:
            answer_parts.append("Latest AI signals: " + ", ".join(lines) + ".")
        else:
            answer_parts.append("No market recommendations generated for your holdings yet.")

    # 5. Default fallback if no keyword matches
    if not answer_parts:
        best_match = retrieved_chunks[0] if retrieved_chunks else "No relevant context found."
        # Strip rupee symbol just in case stdout encoding issues occur elsewhere
        best_match_safe = best_match.replace("₹", "INR")
        answer_parts.append(f"Here is what I found matching your query: {best_match_safe}")

    # Return safe ASCII string representation to handle windows cmd print safely
    return " ".join(answer_parts)[:400]
