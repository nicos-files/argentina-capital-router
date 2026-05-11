import time
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))
from agents.agent_definitions import analyst, sentiment, strategist, user_agent

def test_agent(agent, prompt, max_tokens=128):
    print(f"\n🧪 Probando agente: {agent.name}")
    start = time.time()
    try:
        response = agent.generate_reply(prompt, max_tokens=max_tokens)
        duration = time.time() - start
        print(f"✅ {agent.name} respondió en {duration:.2f} segundos.")
        print(f"🧠 Respuesta:\n{response}")
    except Exception as e:
        print(f"❌ Error en {agent.name}: {e}")

# Prompts de prueba
prompt = "¿Qué oportunidades de inversión hay hoy en el mercado argentino?"

# Test individual
test_agent(analyst, prompt)
test_agent(sentiment, prompt)
test_agent(strategist, prompt)
test_agent(user_agent, prompt)
