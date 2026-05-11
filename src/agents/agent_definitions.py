import os
from dotenv import load_dotenv
from src.agents.sentiment_agent import SentimentAgent
from src.agents.strategy_agent import StrategyAgent
from src.agents.user_agent import UserAgent

load_dotenv()

# 🧠 Agente de sentimiento
sentiment_agent = SentimentAgent(
    relevance_model=os.getenv("RELEVANCE_MODEL", "gpt-4o"),
    sentiment_model=os.getenv("SENTIMENT_MODEL", "gpt-4o")
)

# 📈 Agente estratega (ahora con OpenAI también)
strategy_llm_agent = StrategyAgent(
    model=os.getenv("STRATEGY_MODEL", "gpt-4o")
)

# 🧑‍💼 Agente usuario (presentación, sin LLM)
user_agent = UserAgent(name="UserAgent")
