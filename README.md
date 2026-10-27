#### 8. Run the Development Server (Daphne ASGI)
To ensure WebSockets and real-time streaming work correctly, run the application using **Daphne**:
```bash
daphne -b 127.0.0.1 -p 8000 marketmind.asgi:application
```
*(Or alternatively, `python manage.py runserver` for standard HTTP development).*
Open your browser and navigate to:
```
http://127.0.0.1:8000
```
---
## ⚡ Performance & Engineering Optimizations
1. **Lazy-Loaded Model Singletons**:
   Heavy machine learning models (`ProsusAI/finbert`, `sentence-transformers`) are wrapped in lazy singleton wrappers. They load on-demand rather than during Django/Daphne startup, cutting server boot time from 30+ seconds to instant.
2. **MD5 State Hashing for Vector Retrieval**:
   Rather than rebuilding the FAISS index on every chat message, the assistant hashes the user's holdings and latest prices. If the hash matches the cache, vector re-computation is skipped, maintaining query latency under 300ms.
3. **Optimized Scraping Cadence**:
   The data collector tracks the last synchronization timestamp for each ticker, bypassing redundant requests if updated within the last 5 minutes.
4. **Non-Blocking ASGI Event Broadcast**:
   Alert notifications are processed asynchronously and broadcast via Redis Channel layers, preventing user-facing HTTP requests from being blocked by alert computations.
---
## 🧪 Verification & Testing
Verify that your analytical pipeline and RAG co-pilot are operational:
```bash
# Run unit and integration tests
python manage.py test market
# Run diagnostic verification on RAG assistant and Groq LLM integration
python test_assistant.py
```
---
## 🛡️ License
This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
---
## 👤 Author & Acknowledgments
* **Developer**: [G Chethan Gowda](https://github.com/chethan2903)
* **Project**: [FinSight-AI (MarketMind)](https://github.com/chethan2903/FinSight-AI)
* **Built With**: Python, Django, Daphne, Hugging Face, FAISS, and Groq.
